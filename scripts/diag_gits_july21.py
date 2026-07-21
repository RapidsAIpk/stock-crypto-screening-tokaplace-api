"""Standalone diagnostic: GITS July 21 1h candle vs TradingView pre-market bar."""
from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.config import settings
from services.market_data import (
    MAX_CANDLES,
    MASSIVE_BASE_URL,
    POLYGON_LOOKBACK_BUFFER_MIN_BARS,
    POLYGON_LOOKBACK_BUFFER_RATIO,
    POLYGON_MAX_BASE_AGGREGATES,
    POLYGON_MIN_BASE_AGGREGATES,
    POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_MIN_SECONDS,
    POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_RATIO,
    _build_market_data_payload,
    _download_polygon_rows,
    _extract_polygon_results,
    _finalize_intraday_candles,
    _mark_unclosed_last_candle,
    _polygon_buffer_bars,
    _polygon_base_aggregate_seconds,
    _polygon_download_limit,
    _polygon_required_base_aggregates,
    _request_polygon_aggregate_page,
    _with_freshness_metadata,
    map_symbol_for_polygon,
    map_timeframe_for_polygon,
    normalize_polygon_rows,
    slice_recent,
    timeframe_seconds,
)
from services.stock_session import (
    apply_stock_session_policy,
    expected_session_policy_for_symbol,
)

ENV_PATH = BASE_DIR / ".env"
DB_PATH = BASE_DIR / "data" / "market_data_cache.db"
SYMBOL = "GITS"
TIMEFRAME = "1h"
NY = ZoneInfo("America/New_York")

# Backend export snapshot time from user report
EXPORT_TS = int(datetime(2026, 7, 21, 12, 10, 25, 802000, tzinfo=timezone.utc).timestamp())
DIAG_FROM_TS = int(datetime(2026, 7, 20, 18, 0, 0, tzinfo=timezone.utc).timestamp())
DIAG_TO_TS = EXPORT_TS
MINUTE_WINDOW_FROM_TS = int(datetime(2026, 7, 21, 7, 0, 0, tzinfo=timezone.utc).timestamp())

BACKEND_LATEST = {
    "time": 1784574000,
    "open": 2.14,
    "high": 2.22,
    "low": 2.02,
    "close": 2.10,
    "volume": 10255,
}
TV_SUSPECT = {
    "time_approx_utc": "2026-07-21 08:00:00",
    "open": 1.92,
    "high": 1.92,
    "low": 1.92,
    "close": 1.92,
}
BACKEND_TS_MS = BACKEND_LATEST["time"] * 1000
TV_TS_MS = int(datetime(2026, 7, 21, 8, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def api_key() -> str:
    key = (
        os.environ.get("MASSIVE_API_KEY")
        or os.environ.get("POLYGON_API_KEY")
        or str(settings.market_data_api_key or "").strip()
    )
    if not key:
        raise SystemExit("No MASSIVE_API_KEY / POLYGON_API_KEY found in env or settings")
    return key


def fmt_ts_ms(ts_ms: int) -> tuple[str, str]:
    utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    ny = utc.astimezone(NY)
    return utc.strftime("%Y-%m-%d %H:%M:%S"), ny.strftime("%Y-%m-%d %H:%M:%S %Z")


def print_bar_table(title: str, rows: list[dict], *, from_ms: int | None = None) -> None:
    print(f"\n=== {title} ===")
    print("| Raw t | UTC | New York | Open | High | Low | Close | Volume | Transactions |")
    print("|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        ts_ms = int(row["t"])
        if from_ms is not None and ts_ms < from_ms:
            continue
        utc_s, ny_s = fmt_ts_ms(ts_ms)
        txns = row.get("n", "")
        print(
            f"| {ts_ms} | {utc_s} | {ny_s} "
            f"| {row.get('o')} | {row.get('h')} | {row.get('l')} | {row.get('c')} "
            f"| {row.get('v')} | {txns} |"
        )


def print_candle_table(title: str, candles: list[dict]) -> None:
    print(f"\n=== {title} (last 10) ===")
    print("| Stage | Timestamp | UTC | OHLCV |")
    print("|---|---:|---|---|")
    for candle in candles[-10:]:
        ts_raw = candle.get("time", candle.get("t"))
        if ts_raw is None:
            continue
        ts = int(ts_raw)
        if ts > 10_000_000_000:
            ts = ts // 1000
        utc = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if "o" in candle:
            ohlcv = (
                f"O={candle['o']} H={candle['h']} L={candle['l']} "
                f"C={candle['c']} V={candle.get('v', 0)}"
            )
        else:
            ohlcv = (
                f"O={candle['open']} H={candle['high']} L={candle['low']} "
                f"C={candle['close']} V={candle.get('volume', 0)}"
            )
        if "is_closed" in candle:
            ohlcv += f" is_closed={candle['is_closed']}"
        print(f"| {title} | {ts} | {utc} | {ohlcv} |")


def production_limit(candles_limit: int = MAX_CANDLES) -> int:
    target_bars = candles_limit + _polygon_buffer_bars(candles_limit)
    return min(
        POLYGON_MAX_BASE_AGGREGATES,
        max(
            POLYGON_MIN_BASE_AGGREGATES,
            _polygon_required_base_aggregates(TIMEFRAME, target_bars),
        ),
    )


def production_window_seconds(base_limit: int) -> int:
    base_seconds = _polygon_base_aggregate_seconds(TIMEFRAME)
    window_seconds = max(base_seconds * base_limit, timeframe_seconds(TIMEFRAME))
    window_seconds = max(
        int(math.ceil(window_seconds * POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_RATIO)),
        window_seconds + POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_MIN_SECONDS,
    )
    return window_seconds


def massive_get(client: httpx.Client, path: str, params: dict) -> dict:
    query = dict(params)
    query["apiKey"] = api_key()
    response = client.get(path, params=query, timeout=60)
    print(f"GET {path} status={response.status_code}")
    payload = response.json()
    meta = {
        "status": payload.get("status"),
        "queryCount": payload.get("queryCount"),
        "resultsCount": payload.get("resultsCount"),
        "adjusted": payload.get("adjusted"),
        "request_id": payload.get("request_id"),
        "next_url": payload.get("next_url"),
        "error": payload.get("error"),
        "message": payload.get("message"),
    }
    print("  metadata:", json.dumps(meta, default=str))
    return payload


def aggregate_hour_from_minutes(minute_rows: list[dict], bucket_start_ms: int) -> dict:
    bucket_end_ms = bucket_start_ms + 3600 * 1000
    bucket_rows = [
        row
        for row in minute_rows
        if bucket_start_ms <= int(row["t"]) < bucket_end_ms
    ]
    bucket_rows.sort(key=lambda item: int(item["t"]))
    if not bucket_rows:
        return {
            "bucket_start_utc": datetime.fromtimestamp(bucket_start_ms / 1000, tz=timezone.utc).isoformat(),
            "bucket_end_utc": datetime.fromtimestamp(bucket_end_ms / 1000, tz=timezone.utc).isoformat(),
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
            "minute_count": 0,
        }
    return {
        "bucket_start_utc": datetime.fromtimestamp(bucket_start_ms / 1000, tz=timezone.utc).isoformat(),
        "bucket_end_utc": datetime.fromtimestamp(bucket_end_ms / 1000, tz=timezone.utc).isoformat(),
        "open": bucket_rows[0]["o"],
        "high": max(float(row["h"]) for row in bucket_rows),
        "low": min(float(row["l"]) for row in bucket_rows),
        "close": bucket_rows[-1]["c"],
        "volume": sum(float(row.get("v") or 0) for row in bucket_rows),
        "minute_count": len(bucket_rows),
    }


def inspect_cache(now: int) -> dict:
    result = {"found": False}
    if not DB_PATH.exists():
        return result
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT symbol, timeframe, payload, updated_at
            FROM market_data_cache
            WHERE symbol = ? AND timeframe = ?
            """,
            (SYMBOL, TIMEFRAME),
        ).fetchone()
        if not row:
            return result
        payload = json.loads(row["payload"])
        candles = payload.get("candles") or []
        latest = candles[-1] if candles else None
        interest = conn.execute(
            """
            SELECT last_requested_at, last_refreshed_at, next_refresh_at
            FROM market_data_interest
            WHERE symbol = ? AND timeframe = ?
            """,
            (SYMBOL, TIMEFRAME),
        ).fetchone()
        result = {
            "found": True,
            "cache_key": f"{SYMBOL}+{TIMEFRAME}",
            "updated_at": row["updated_at"],
            "updated_at_utc": datetime.fromtimestamp(row["updated_at"], tz=timezone.utc).isoformat(),
            "candle_count": len(candles),
            "latest_candle": latest,
            "next_refresh_at": payload.get("next_refresh_at"),
            "session_policy": payload.get("session_policy"),
            "interest": dict(interest) if interest else None,
            "cache_age_seconds": max(0, now - int(row["updated_at"])),
        }
        if latest and latest.get("time"):
            result["latest_candle_age_seconds"] = max(0, now - int(latest["time"]) - 3600)
        return result


async def replay_production_request(now_ms: int, candles_limit: int = MAX_CANDLES) -> dict:
    session_policy = expected_session_policy_for_symbol(SYMBOL, TIMEFRAME)
    download_limit = _polygon_download_limit(candles_limit, SYMBOL, TIMEFRAME, session_policy)
    target_bars = download_limit + _polygon_buffer_bars(download_limit)
    base_limit = production_limit(download_limit)
    window_seconds = production_window_seconds(base_limit)
    from_ms = max(0, now_ms - window_seconds * 1000)
    multiplier, timespan = map_timeframe_for_polygon(TIMEFRAME)
    provider_symbol = map_symbol_for_polygon(SYMBOL)

    print("\n=== PRODUCTION REQUEST REPLAY ===")
    print(f"provider_symbol={provider_symbol}")
    print(f"path=/v2/aggs/ticker/{provider_symbol}/range/{multiplier}/{timespan}/{from_ms}/{now_ms}")
    print(f"multiplier={multiplier} timespan={timespan}")
    print(f"from_ms={from_ms} ({datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).isoformat()})")
    print(f"to_ms={now_ms} ({datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat()})")
    print(f"adjusted=true sort=desc limit={base_limit}")
    print(f"download_limit={download_limit} target_bars={target_bars} session_policy={session_policy}")
    print(f"window_seconds={window_seconds} covers_july21={from_ms <= int(datetime(2026, 7, 21, tzinfo=timezone.utc).timestamp() * 1000)}")

    page = await _request_polygon_aggregate_page(SYMBOL, TIMEFRAME, now_ms, target_bars)
    rows = await _download_polygon_rows(SYMBOL, TIMEFRAME, download_limit)

    latest_raw_ms = max((int(r["t"]) for r in rows), default=None)
    return {
        "page_count": len(page),
        "rows_count": len(rows),
        "latest_raw_ms": latest_raw_ms,
        "rows": rows,
        "from_ms": from_ms,
        "to_ms": now_ms,
        "base_limit": base_limit,
        "download_limit": download_limit,
        "session_policy": session_policy,
    }


def pipeline_stages(rows: list[dict], candles_limit: int, session_policy: str | None, now: int) -> dict:
    extracted = list(rows)
    seen = set()
    deduped = []
    for row in extracted:
        ts = row.get("t")
        if ts is None or ts in seen:
            continue
        seen.add(ts)
        deduped.append(row)
    sorted_rows = sorted(deduped, key=lambda item: int(item["t"]))
    normalized = normalize_polygon_rows(sorted_rows)
    filtered = apply_stock_session_policy(normalized, SYMBOL, TIMEFRAME, session_policy)
    sliced = slice_recent(filtered, limit=candles_limit)
    payload = _build_market_data_payload(
        SYMBOL,
        sliced,
        TIMEFRAME,
        session_policy=session_policy,
    )
    marked = _mark_unclosed_last_candle(list(sliced), TIMEFRAME, now=now)
    return {
        "raw": sorted_rows,
        "extracted": extracted,
        "deduped": sorted(deduped, key=lambda item: int(item["t"])),
        "sorted": sorted_rows,
        "normalized": normalized,
        "filtered": filtered,
        "sliced": sliced,
        "payload_candles": payload.get("candles") or [],
        "marked": marked,
    }


def answer_hour_checks(rows: list[dict]) -> None:
    print("\n=== 1-HOUR RAW ANSWERS ===")
    july21 = [r for r in rows if datetime.fromtimestamp(int(r["t"]) / 1000, tz=timezone.utc).date().isoformat() == "2026-07-21"]
    ts_1784574000 = [r for r in rows if int(r["t"]) == BACKEND_TS_MS]
    ts_0800 = [r for r in rows if int(r["t"]) == TV_TS_MS]
    price_192 = [
        r for r in rows
        if float(r.get("o", -1)) == 1.92
        and float(r.get("h", -1)) == 1.92
        and float(r.get("l", -1)) == 1.92
        and float(r.get("c", -1)) == 1.92
    ]
    newest = max(rows, key=lambda item: int(item["t"])) if rows else None

    print(f"- Is 1784574000000 present? {bool(ts_1784574000)}")
    print(f"- Any July 21 1-hour bar present? {bool(july21)} (count={len(july21)})")
    print(f"- Bar at 08:00 UTC (ts={TV_TS_MS})? {bool(ts_0800)}")
    print(f"- Bar with OHLC all 1.92? {bool(price_192)}")
    if newest:
        utc, ny = fmt_ts_ms(int(newest["t"]))
        print(f"- Newest raw 1-hour timestamp: {newest['t']} ({utc} UTC / {ny})")
        print(
            f"  OHLCV: {newest.get('o')} / {newest.get('h')} / {newest.get('l')} / "
            f"{newest.get('c')} / {newest.get('v')}"
        )
    if ts_1784574000:
        row = ts_1784574000[0]
        exact = all(
            abs(float(row[k]) - float(BACKEND_LATEST[bc])) < 1e-9
            for k, bc in [("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")]
        )
        print(f"- Backend OHLCV matches Massive exactly for 1784574000? {exact}")


def answer_minute_checks(rows: list[dict]) -> None:
    print("\n=== 1-MINUTE RAW ANSWERS ===")
    price_192 = [
        r for r in rows
        if any(abs(float(r.get(k, -999)) - 1.92) < 1e-9 for k in ("o", "h", "l", "c"))
    ]
    around_0800 = [
        r for r in rows
        if TV_TS_MS <= int(r["t"]) < TV_TS_MS + 3600 * 1000
    ]
    low_vol = [r for r in rows if float(r.get("v") or 0) <= 5]
    one_txn = [r for r in rows if int(r.get("n") or 0) == 1]

    print(f"- Does Massive minute data contain price 1.92? {bool(price_192)} (matches={len(price_192)})")
    for row in price_192[:10]:
        utc, ny = fmt_ts_ms(int(row["t"]))
        print(
            f"  t={row['t']} utc={utc} ny={ny} "
            f"O={row.get('o')} H={row.get('h')} L={row.get('l')} C={row.get('c')} "
            f"V={row.get('v')} n={row.get('n')}"
        )
    print(f"- Minute bars in 08:00-09:00 UTC bucket: {len(around_0800)}")
    print(f"- Low-volume bars (v<=5): {len(low_vol)}")
    print(f"- One-transaction bars: {len(one_txn)}")


def incomplete_candle_audit(candles: list[dict], now: int) -> None:
    print("\n=== INCOMPLETE CANDLE AUDIT ===")
    if not candles:
        print("No candles to audit.")
        return
    tf_sec = timeframe_seconds(TIMEFRAME)
    for candle in candles[-5:]:
        ts = int(candle["time"])
        close_ts = ts + tf_sec
        is_closed = now >= close_ts
        retained = True
        print(
            f"bar={ts} ({datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()}) "
            f"expected_close={datetime.fromtimestamp(close_ts, tz=timezone.utc).isoformat()} "
            f"now={datetime.fromtimestamp(now, tz=timezone.utc).isoformat()} "
            f"is_closed={is_closed} retained={retained} "
            f"marked_is_closed={candle.get('is_closed', 'n/a')}"
        )


async def main() -> None:
    load_env()
    now = EXPORT_TS
    now_ms = now * 1000
    start_ms = DIAG_FROM_TS * 1000
    end_ms = DIAG_TO_TS * 1000
    minute_from_ms = MINUTE_WINDOW_FROM_TS * 1000

    print("=== GITS JULY 21 DIAGNOSTIC ===")
    print(f"symbol={SYMBOL} timeframe={TIMEFRAME}")
    print(f"export_ts={datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}")
    print(f"window_1h={datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()} -> "
          f"{datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).isoformat()}")
    print(f"session_policy={expected_session_policy_for_symbol(SYMBOL, TIMEFRAME)}")
    print(f"massive_base_url={MASSIVE_BASE_URL}")

    base_limit = production_limit(MAX_CANDLES)

    with httpx.Client(base_url=MASSIVE_BASE_URL, headers={"Accept": "application/json"}) as client:
        # Narrow asc request
        path_1h = f"/v2/aggs/ticker/{SYMBOL}/range/1/hour/{start_ms}/{end_ms}"
        payload_1h_asc = massive_get(
            client,
            path_1h,
            {"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        rows_1h_asc = payload_1h_asc.get("results") or []

        # Production-style desc request over same explicit window
        payload_1h_prod = massive_get(
            client,
            path_1h,
            {"adjusted": "true", "sort": "desc", "limit": base_limit},
        )
        rows_1h_prod = payload_1h_prod.get("results") or []

        print_bar_table("RAW 1-HOUR (asc, from 2026-07-20 18:00 UTC)", rows_1h_asc, from_ms=start_ms)
        answer_hour_checks(rows_1h_asc)

        path_1m = f"/v2/aggs/ticker/{SYMBOL}/range/1/minute/{minute_from_ms}/{end_ms}"
        payload_1m = massive_get(
            client,
            path_1m,
            {"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        rows_1m = payload_1m.get("results") or []
        print_bar_table("RAW 1-MINUTE (2026-07-21 07:00 through export)", rows_1m)
        answer_minute_checks(rows_1m)

        # Optional trades endpoint probe
        trades_path = f"/v3/trades/{SYMBOL}"
        trades_from = datetime(2026, 7, 21, 7, 55, 0, tzinfo=timezone.utc).isoformat()
        trades_to = datetime(2026, 7, 21, 8, 5, 0, tzinfo=timezone.utc).isoformat()
        trades_payload = massive_get(
            client,
            trades_path,
            {
                "timestamp.gte": trades_from,
                "timestamp.lt": trades_to,
                "order": "asc",
                "limit": 1000,
                "sort": "timestamp",
            },
        )
        trades = trades_payload.get("results") or []
        print(f"\n=== TRADES ENDPOINT (07:55-08:05 UTC) count={len(trades)} ===")
        for trade in trades[:20]:
            ts = trade.get("sip_timestamp") or trade.get("participant_timestamp") or trade.get("t")
            price = trade.get("price")
            size = trade.get("size")
            print(f"  trade ts={ts} price={price} size={size} conditions={trade.get('conditions')}")

    reconstructed = aggregate_hour_from_minutes(rows_1m, TV_TS_MS)
    print("\n=== RECONSTRUCTED 1-HOUR FROM MINUTES (08:00 UTC bucket) ===")
    print(json.dumps(reconstructed, indent=2))

    replay = await replay_production_request(now_ms, MAX_CANDLES)
    stages = pipeline_stages(
        replay["rows"],
        MAX_CANDLES,
        replay["session_policy"],
        now,
    )

    for name, candles in [
        ("1_raw_massive", stages["raw"]),
        ("2_extracted", stages["extracted"]),
        ("3_deduped", stages["deduped"]),
        ("4_sorted", stages["sorted"]),
        ("5_normalized", stages["normalized"]),
        ("6_session_filtered", stages["filtered"]),
        ("7_sliced", stages["sliced"]),
        ("8_payload_before_cache", stages["payload_candles"]),
        ("10_indicator_input", stages["marked"]),
    ]:
        print_candle_table(name, candles)

    cache = inspect_cache(now)
    print("\n=== CACHE AUDIT ===")
    print(json.dumps(cache, indent=2, default=str))
    if cache.get("found"):
        cached_candles = json.loads(
            sqlite3.connect(DB_PATH)
            .execute(
                "SELECT payload FROM market_data_cache WHERE symbol=? AND timeframe=?",
                (SYMBOL, TIMEFRAME),
            )
            .fetchone()[0]
        ).get("candles", [])
        print_candle_table("9_cache_after_refresh", cached_candles)

    incomplete_candle_audit(stages["payload_candles"], now)

    freshness = _with_freshness_metadata(
        stages["payload_candles"] and {"candles": stages["payload_candles"]} or {"candles": []},
        is_stale=False,
        market_data_source="fresh_cache",
        stale_age_seconds=cache.get("cache_age_seconds", 0) if cache.get("found") else 0,
    )
    print("\n=== FRESHNESS METADATA EXAMPLE ===")
    print(json.dumps({k: freshness[k] for k in ("is_stale", "stale_age_seconds", "market_data_source")}, indent=2))
    print("NOTE: stale_age_seconds is cache-write age, NOT latest-candle age.")

    print("\n=== DECISION TREE INPUT ===")
    print(f"Massive 1h July21 bars: {len([r for r in rows_1h_asc if int(r['t']) >= int(datetime(2026,7,21,tzinfo=timezone.utc).timestamp()*1000)])}")
    print(f"Massive 1m price 1.92 bars: {len([r for r in rows_1m if any(abs(float(r.get(k,-9))-1.92)<1e-9 for k in ('o','h','l','c'))])}")
    print(f"Session-filtered latest: {stages['filtered'][-1]['time'] if stages['filtered'] else None}")
    print(f"Payload latest: {stages['payload_candles'][-1]['time'] if stages['payload_candles'] else None}")


if __name__ == "__main__":
    asyncio.run(main())

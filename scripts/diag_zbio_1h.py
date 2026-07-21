"""One-off diagnostic: ZBIO 1h Massive aggregates vs backend case."""
from __future__ import annotations

import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.market_data import normalize_polygon_rows
from services.stock_session import apply_stock_session_policy, SESSION_POLICY_TRADINGVIEW_REGULAR

ENV_PATH = BASE_DIR / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    api_key = os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise SystemExit("No MASSIVE_API_KEY / POLYGON_API_KEY found")

    base = "https://api.massive.com"
    export_ts = int(datetime(2026, 7, 21, 9, 5, 5, 890000, tzinfo=timezone.utc).timestamp())
    to_ms = export_ts * 1000
    start_ms = int(datetime(2026, 7, 20, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)

    print("=== DIAGNOSTIC WINDOW ===")
    print(f"from: {datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat()}")
    print(f"to:   {datetime.fromtimestamp(to_ms / 1000, tz=timezone.utc).isoformat()}")
    print(f"endpoint: GET /v2/aggs/ticker/ZBIO/range/1/hour/{start_ms}/{to_ms}")
    print()

    url = f"{base}/v2/aggs/ticker/ZBIO/range/1/hour/{start_ms}/{to_ms}"
    response = httpx.get(
        url,
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key},
        timeout=60,
    )
    print(f"HTTP status: {response.status_code}")
    payload = response.json()
    print(
        "API status:",
        payload.get("status"),
        " resultsCount:",
        payload.get("resultsCount"),
        " queryCount:",
        payload.get("queryCount"),
    )
    rows = payload.get("results") or []
    print(f"rows returned: {len(rows)}")
    print()

    print("=== RAW MASSIVE BARS FROM 2026-07-20 18:00 UTC ===")
    print("| Raw timestamp | UTC datetime | New York datetime | Open | High | Low | Close | Volume |")
    print("|---:|---|---|---:|---:|---:|---:|---:|")
    for row in rows:
        timestamp_ms = int(row["t"])
        utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        ny = utc.astimezone(ZoneInfo("America/New_York"))
        print(
            f"| {timestamp_ms} | {utc.strftime('%Y-%m-%d %H:%M:%S')} "
            f"| {ny.strftime('%Y-%m-%d %H:%M:%S %Z')} "
            f"| {row['o']} | {row['h']} | {row['l']} | {row['c']} | {row['v']} |"
        )

    suspect_ms = 1784584800 * 1000
    match = [row for row in rows if int(row.get("t", 0)) == suspect_ms]
    print()
    print("=== TRADINGVIEW REGULAR SESSION FILTER (July 20 18:00+ UTC) ===")
    normalized = normalize_polygon_rows(rows)
    filtered = apply_stock_session_policy(
        normalized,
        "ZBIO",
        "1h",
        SESSION_POLICY_TRADINGVIEW_REGULAR,
    )
    print("| time | UTC datetime | OHLCV |")
    print("|---|---:|---|")
    for candle in filtered:
        utc = datetime.fromtimestamp(candle["time"], tz=timezone.utc)
        print(
            f"| {candle['time']} | {utc.strftime('%Y-%m-%d %H:%M:%S')} "
            f"| O={candle['open']} H={candle['high']} L={candle['low']} "
            f"C={candle['close']} V={candle['volume']} |"
        )
    if filtered:
        print(f"latest_regular_session_bar: {filtered[-1]['time']}")
    else:
        print("latest_regular_session_bar: none")
    print(f"found_in_massive: {bool(match)}")
    if match:
        row = match[0]
        print(
            f"raw row: t={row['t']} o={row['o']} h={row['h']} "
            f"l={row['l']} c={row['c']} v={row['v']}"
        )
        backend = {
            "open": 31.86,
            "high": 32.3436,
            "low": 31.30,
            "close": 31.30,
            "volume": 935,
        }
        normalized = {
            "open": row["o"],
            "high": row["h"],
            "low": row["l"],
            "close": row["c"],
            "volume": row["v"],
        }
        exact = all(abs(float(normalized[key]) - float(backend[key])) < 1e-9 for key in backend)
        print(f"backend OHLCV exact match: {exact}")

    normalized_limit = 73
    target_bars = normalized_limit + max(8, int(math.ceil(normalized_limit * 0.2)))
    base_limit = min(50000, max(64, target_bars * 60))
    window_seconds = max(60 * base_limit, 3600)
    window_seconds = max(
        int(math.ceil(window_seconds * 4.0)),
        window_seconds + 4 * 86400,
    )
    from_ms = max(0, to_ms - window_seconds * 1000)

    print()
    print("=== BACKEND-REPLICATED REQUEST (export time) ===")
    print(f"from_ms={from_ms} ({datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).isoformat()})")
    print(f"to_ms={to_ms} ({datetime.fromtimestamp(to_ms / 1000, tz=timezone.utc).isoformat()})")
    print(f"limit={base_limit} sort=desc")

    url2 = f"{base}/v2/aggs/ticker/ZBIO/range/1/hour/{from_ms}/{to_ms}"
    response2 = httpx.get(
        url2,
        params={"adjusted": "true", "sort": "desc", "limit": base_limit, "apiKey": api_key},
        timeout=60,
    )
    rows2 = response2.json().get("results") or []
    rows2_sorted = sorted(rows2, key=lambda item: int(item["t"]))
    last10 = rows2_sorted[-10:]

    print()
    print("=== LAST 10 BARS (backend-replicated window, normalized) ===")
    print("| time | UTC datetime | OHLCV |")
    print("|---|---:|---|")
    for row in last10:
        time_sec = int(int(row["t"]) / 1000)
        utc = datetime.fromtimestamp(time_sec, tz=timezone.utc)
        print(
            f"| {time_sec} | {utc.strftime('%Y-%m-%d %H:%M:%S')} "
            f"| O={row['o']} H={row['h']} L={row['l']} C={row['c']} V={row['v']} |"
        )

    suspect_in_rep = any(int(row["t"]) == suspect_ms for row in rows2)
    print(f"suspect 1784584800 in backend-replicated response: {suspect_in_rep}")


if __name__ == "__main__":
    main()

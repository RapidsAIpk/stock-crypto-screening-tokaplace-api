"""Trace AIR 1h candles from Massive through Trend Channel window=1 evaluation."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.market_data import (
    MAX_CANDLES,
    _download_polygon_rows,
    _finalize_intraday_candles,
    _mark_unclosed_last_candle,
    normalize_polygon_rows,
    request_polygon_candles,
    timeframe_seconds,
)
from services.stock_session import (
    apply_stock_session_policy,
    expected_session_policy_for_symbol,
)
from services.trend_channels import compute_trend_channel, evaluate_single_area

SYMBOL = "AIR"
TIMEFRAME = "1h"
NY = ZoneInfo("America/New_York")
DB_PATH = BASE_DIR / "data" / "market_data_cache.db"
ENV_PATH = BASE_DIR / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def fmt_candle(candle: dict, index: int | None = None) -> dict:
    ts = int(candle.get("time", 0))
    utc = datetime.fromtimestamp(ts, tz=timezone.utc)
    ny = utc.astimezone(NY)
    out = {
        "index": index,
        "time": ts,
        "utc": utc.strftime("%Y-%m-%d %H:%M:%S"),
        "new_york": ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
        "volume": candle.get("volume"),
        "is_closed": candle.get("is_closed", "not_set"),
    }
    return out


def print_stage(title: str, candle: dict | None, index: int | None = None) -> None:
    print(f"\n=== {title} ===")
    if candle is None:
        print("  (none)")
        return
    print(json.dumps(fmt_candle(candle, index), indent=2, default=str))


async def main() -> None:
    load_env()
    now = int(time.time())
    session_policy = expected_session_policy_for_symbol(SYMBOL, TIMEFRAME)

    print(f"AIR 1h pipeline trace at {datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}")
    print(f"session_policy={session_policy}")

    # 1. Raw provider rows
    rows = await _download_polygon_rows(SYMBOL, TIMEFRAME, MAX_CANDLES)
    raw_sorted = sorted(rows, key=lambda r: int(r.get("t") or 0))
    latest_raw = raw_sorted[-1] if raw_sorted else None

    # 2. Normalized
    normalized = normalize_polygon_rows(raw_sorted)
    latest_normalized = normalized[-1] if normalized else None

    # 3. Session filtered (before slice, full history)
    session_filtered = apply_stock_session_policy(
        normalized, SYMBOL, TIMEFRAME, session_policy
    )
    latest_session = session_filtered[-1] if session_filtered else None

    # 4. Production fetch path (finalize + payload marking)
    payload = await request_polygon_candles(SYMBOL, TIMEFRAME, candles_limit=MAX_CANDLES)
    cached_candles = (payload or {}).get("candles") or []
    latest_cached = cached_candles[-1] if cached_candles else None

    # 5. SQLite cache
    db_latest = None
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT payload, updated_at FROM market_data_cache WHERE symbol=? AND timeframe=?",
                (SYMBOL, TIMEFRAME),
            ).fetchone()
        if row:
            db_payload = json.loads(row[0])
            db_candles = db_payload.get("candles") or []
            db_latest = db_candles[-1] if db_candles else None
            print(f"\nSQLite cache updated_at={datetime.fromtimestamp(row[1], tz=timezone.utc).isoformat()}")

    # Indicator input = same as fetch payload candles
    indicator_candles = list(cached_candles)
    latest_indicator = indicator_candles[-1] if indicator_candles else None

    # 6. Trend channel + window=1 evaluation
    tc = compute_trend_channel(indicator_candles, length=8) if indicator_candles else None
    rule = {
        "area": "bottom_line",
        "action": "touched",
        "touch_type": "wick",
        "tolerance": 2,
        "window": 1,
        "confirmation": False,
    }
    evaluated_index = len(indicator_candles) - 1 if indicator_candles else None
    evaluated_candle = indicator_candles[-1] if indicator_candles else None

    # Forming status analysis
    tf_sec = timeframe_seconds(TIMEFRAME)
    if latest_indicator:
        last_time = int(latest_indicator["time"])
        would_be_forming = now < last_time + tf_sec
        print(f"\n=== FORMING STATUS ===")
        print(f"now={datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}")
        print(f"last_candle_open={datetime.fromtimestamp(last_time, tz=timezone.utc).isoformat()}")
        print(f"last_candle_close_expected={datetime.fromtimestamp(last_time + tf_sec, tz=timezone.utc).isoformat()}")
        print(f"is_closed_flag={latest_indicator.get('is_closed', 'not_set')}")
        print(f"would_be_forming_by_time={would_be_forming}")

    print_stage("1. Latest RAW Massive row", None)
    if latest_raw:
        print(json.dumps({
            "raw_t_ms": latest_raw.get("t"),
            "utc": datetime.fromtimestamp(int(latest_raw["t"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "new_york": datetime.fromtimestamp(int(latest_raw["t"]) / 1000, tz=timezone.utc).astimezone(NY).strftime("%Y-%m-%d %H:%M:%S %Z"),
            "open": latest_raw.get("o"),
            "high": latest_raw.get("h"),
            "low": latest_raw.get("l"),
            "close": latest_raw.get("c"),
            "volume": latest_raw.get("v"),
        }, indent=2))

    print_stage("2. Latest NORMALIZED candle", latest_normalized, len(normalized) - 1 if normalized else None)
    print_stage("3. Latest SESSION-FILTERED candle", latest_session, len(session_filtered) - 1 if session_filtered else None)
    print_stage("4. Latest CACHED/PRODUCTION candle", latest_cached, len(cached_candles) - 1 if cached_candles else None)
    print_stage("5. Latest SQLITE cache candle", db_latest, None)
    print_stage("6. Candle PASSED TO INDICATOR (handle_trend input)", latest_indicator, evaluated_index)

    if tc and evaluated_candle is not None:
        start_index = len(indicator_candles) - tc["length"]
        regression_index = evaluated_index - start_index
        print(f"\n=== 7. RULE EVALUATION (window=1) ===")
        print(f"function=evaluate_single_area in services/trend_channels.py")
        print(f"candle_index={evaluated_index}")
        print(f"tc.start_index={tc['start_index']} tc.length={tc['length']} regression_index={regression_index}")
        if 0 <= regression_index < tc["length"]:
            print(f"bottom_line_at_regression_index={tc['bottom'][regression_index]}")
        print(f"rule_passed={evaluate_single_area(indicator_candles, tc, rule)}")
        print_stage("Candle ACTUALLY EVALUATED", evaluated_candle, evaluated_index)

    print("\n=== PIPELINE FUNCTIONS ===")
    print("Massive fetch: _download_polygon_rows -> normalize_polygon_rows")
    print("Session filter: _finalize_intraday_candles -> apply_stock_session_policy")
    print("Forming mark: _build_market_data_payload -> _mark_unclosed_last_candle")
    print("Cache: store_snapshots (full payload replace)")
    print("Screener: fetch_live_data -> apply_indicators -> handle_trend(asset, candles, config)")
    print("Channel: compute_trend_channel(candles)")
    print("Rule window=1: evaluate_single_area -> candles[-window:] -> candle_index=len(candles)-1")


if __name__ == "__main__":
    asyncio.run(main())

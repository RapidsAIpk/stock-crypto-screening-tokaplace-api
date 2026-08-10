"""Trace IBTA 1day candles through the bearish Channel Confluence evaluation.

Reproduces the exact payload reported as a bug: Regression(upper, len=8) as
Source 1, LRC(upper, len=100, line_relation=close_above) as Source 2.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

ENV_PATH = BASE_DIR / ".env"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()

from services.market_data import fetch_live_data  # noqa: E402
from services.linear_regression_channel import compute_lrc_channel  # noqa: E402
from services.regression_channel_dw import compute_dw_regression_channel  # noqa: E402
from services import confluence as conf  # noqa: E402

SYMBOL = "IBTA"
TIMEFRAME = "1day"


def source_ns(id_, channel_type, selection, length, **extra):
    base = dict(
        id=id_,
        channel_type=channel_type,
        selection=selection,
        length=length,
        width_coeff=None,
        upper_dev=None,
        lower_dev=None,
        deviation=None,
        devlen=None,
        source=None,
        window_type=None,
        interval_step=None,
        line_relation="none",
        target_line=None,
        candles_since_close_min=None,
        candles_since_close_max=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


async def main() -> None:
    items = await fetch_live_data([SYMBOL], TIMEFRAME, candles_limit=400)
    if not items:
        print("No data returned for", SYMBOL)
        return

    asset = items[0]
    candles = asset.get("candles") or []
    completed = [c for c in candles if c.get("is_closed") is not False]

    print(f"total candles={len(candles)} completed={len(completed)}")
    print("last candle is_closed flag:", candles[-1].get("is_closed") if candles else None)

    regression_source = source_ns("trend-legacy-0", "regression", "upper", 8)
    lrc_source = source_ns(
        "lrc-legacy-1", "lrc", "upper", 100, line_relation="close_above",
    )

    config = SimpleNamespace(
        type="bearish",
        channels=["regression", "lrc"],
        sources=[regression_source, lrc_source],
        liquidity_sweep=False,
        lookback_candles=4,
        tolerance_pct=0.1,
        reclose_to_first_line=False,
    )

    regression_channel = compute_dw_regression_channel(completed, length=8, width_coeff=1.0)
    lrc_channel = compute_lrc_channel(completed, length=100, upper_dev=2.0, lower_dev=2.0, source="close")

    channels = {
        "trend-legacy-0": {"channel_type": "regression", "selection": "upper", "channel": regression_channel},
        "lrc-legacy-1": {"channel_type": "lrc", "selection": "upper", "channel": lrc_channel},
    }

    source_channels = conf._iter_channel_sources(channels, config)
    print("\n=== resolved source_channels ===")
    for s in source_channels:
        print(s["source_id"], s["channel_type"], s["selection"], "sub_filter=", s.get("sub_filter"))

    print("\n=== per-candle values (last 6 completed candles) ===")
    n = len(completed)
    for idx in range(max(0, n - 6), n):
        candle = completed[idx]
        ts = int(candle["time"])
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        reg_snap = conf._selection_snapshot(source_channels[0], completed, idx)
        lrc_snap = conf._selection_snapshot(source_channels[1], completed, idx)
        reg_upper = reg_snap["upper"] if reg_snap else None
        lrc_upper = lrc_snap["upper"] if lrc_snap else None
        reg_touch = conf._holds_resistance(completed, source_channels[0], idx, 0.1)
        lrc_touch = conf._holds_resistance(completed, source_channels[1], idx, 0.1)
        close_above_lrc = conf._close_above_selection(completed, source_channels[1], idx)

        print(json.dumps({
            "index": idx,
            "date": dt,
            "open": candle["open"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
            "regression_upper": reg_upper,
            "regression_resistance_touch": reg_touch,
            "lrc_upper": lrc_upper,
            "lrc_resistance_touch": lrc_touch,
            "lrc_close_above": close_above_lrc,
        }, indent=2, default=str))

    print("\n=== evaluate_confluence ===")
    evidence = {}
    result = conf.evaluate_confluence(completed, channels, config, evidence=evidence)
    print("matched:", result)
    print("evidence:", json.dumps(evidence, indent=2, default=str))

    if evidence.get("source_matches"):
        for match in evidence["source_matches"]:
            idx = match["candle_index"]
            candle = completed[idx]
            dt = datetime.fromtimestamp(int(candle["time"]), tz=timezone.utc).strftime("%Y-%m-%d")
            print(f"source_id={match['source_id']} matched at index={idx} date={dt} close={candle['close']}")

    print("\n=== sub-filter isolation check (LRC close_above, target=own selection) ===")
    sub_filter = source_channels[1].get("sub_filter")
    print("sub_filter payload:", sub_filter)
    streak_at_396 = conf._close_streak_ending_at(completed, source_channels[1], "close_above", 396)
    print("close_above streak ending AT the matched candle (index 396, Aug 4):", streak_at_396)
    streak_at_399 = conf._close_streak_ending_at(completed, source_channels[1], "close_above", 399)
    print("close_above streak ending at the latest candle (index 399, Aug 7), for comparison:", streak_at_399)
    passes_at_matched_candle = conf._source_sub_filter_passes(completed, source_channels[1], sub_filter, 396)
    print("sub_filter_passes anchored to matched candle 396 (new, correct):", passes_at_matched_candle)


if __name__ == "__main__":
    asyncio.run(main())

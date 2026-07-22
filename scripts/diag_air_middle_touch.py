"""Why does AIR pass trend middle_line touched window=1?"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from services.market_data import MAX_CANDLES, request_polygon_candles
from services.trend_channels import (
    _channel_last_signal_index,
    _candle_index_eligible_for_signal,
    compute_trend_channel,
    evaluate_single_area,
    evaluate_trend_channel_rules,
)
from services.utils import detect_touch

SYMBOL = "AIR"
NY = ZoneInfo("America/New_York")
CONFIG = {
    "length": 8,
    "show_last_channel": True,
    "wait_for_break": True,
    "areas": [
        {
            "breach_direction": "any",
            "action": "touched",
            "touch_type": "wick",
            "confirmation": False,
            "breach_type": "wick",
            "tolerance": None,
            "area": "middle_line",
            "window": 1,
        }
    ],
}
RULE = CONFIG["areas"][0]


async def main() -> None:
    payload = await request_polygon_candles(SYMBOL, "1h", MAX_CANDLES)
    candles = payload["candles"] or []
    tc = compute_trend_channel(
        candles,
        length=8,
        wait_for_break=True,
        show_last_channel=True,
    )
    if not tc:
        print("No channel")
        return

    last_i = len(candles) - 1
    candle = candles[last_i]
    ts = int(candle["time"])
    start = len(candles) - tc["length"]
    ri = last_i - start
    middle = float(tc["middle"][ri])

    print("=== AIR middle_line touched window=1 ===")
    print("now_utc:", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    print(
        "last_candle:",
        json.dumps(
            {
                "index": last_i,
                "time": ts,
                "utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "ny": datetime.fromtimestamp(ts, tz=timezone.utc)
                .astimezone(NY)
                .strftime("%Y-%m-%d %H:%M:%S %Z"),
                "ohlc": [candle["open"], candle["high"], candle["low"], candle["close"]],
                "is_closed": candle.get("is_closed", "not_set"),
            },
            indent=2,
        ),
    )
    print(
        "channel:",
        json.dumps(
            {
                "direction": tc["direction"],
                "broken": tc["broken"],
                "break_index": tc["break_index"],
                "break_direction": tc.get("break_direction"),
                "start_index": tc["start_index"],
                "length": tc["length"],
                "line_x1": tc.get("line_x1"),
                "line_x2": tc.get("line_x2"),
                "last_signal_index": _channel_last_signal_index(tc),
                "last_eligible": _candle_index_eligible_for_signal(tc, last_i),
            },
            indent=2,
        ),
    )
    print("middle_at_last:", middle)
    print("wick_touches_middle:", detect_touch(candle, middle, middle, RULE, direction=None))
    print("evaluate_single_area:", evaluate_single_area(candles, tc, RULE))
    print("evaluate_rules:", evaluate_trend_channel_rules(candles, tc, CONFIG))

    print("\nlast 8 bars vs middle:")
    for i in range(max(0, last_i - 7), last_i + 1):
        reg_i = i - start
        if reg_i < 0 or reg_i >= tc["length"]:
            continue
        mid = float(tc["middle"][reg_i])
        row = candles[i]
        t = int(row["time"])
        eligible = _candle_index_eligible_for_signal(tc, i)
        print(
            f"  i={i} {datetime.fromtimestamp(t, tz=timezone.utc).strftime('%m-%d %H:%M')} "
            f"L={row['low']} H={row['high']} mid={mid:.4f} "
            f"touch={detect_touch(row, mid, mid, RULE)} eligible={eligible}"
        )


if __name__ == "__main__":
    asyncio.run(main())

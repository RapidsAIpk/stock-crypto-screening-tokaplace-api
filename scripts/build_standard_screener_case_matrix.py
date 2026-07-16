from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path


RULES = {
    "rsi": {"length": 14, "location": "overbought", "direction": None, "window": 1, "tolerance_pct": 0, "confirmation": False},
    "aroon": {"length": 14, "level": "above_50", "direction": None, "window": 1, "extreme_level": 70, "tolerance_pct": 0, "confirmation": False},
    "macd": {"fast": 12, "slow": 26, "signal": 9, "rule": "above_zero", "tolerance_pct": 0},
    "ema": {"length": 9, "rule": "above", "tolerance_pct": 0},
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the 15 structural RSI/Aroon/MACD/EMA validation cases.")
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = []
    names = tuple(RULES)
    for size in range(1, len(names) + 1):
        for combination in itertools.combinations(names, size):
            case_id = "_and_".join(combination)
            cases.append({
                "id": case_id,
                "description": " AND ".join(item.upper() for item in combination),
                "fixture_id": args.fixture_id,
                "symbols": [item.upper() for item in args.symbols],
                "required": True,
                "asset_type": "stocks",
                "timeframe_mode": "single",
                "single_timeframe": "1day",
                "stock_sources": ["zoya"],
                "indicators": [{"name": name, "timeframe": "single", "config": RULES[name]} for name in combination],
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"suite_id": "standard_indicators", "cases": cases}, indent=2) + "\n", "utf-8")
    print(f"Wrote {len(cases)} cases: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.custom_indicator_matrix import BUILDERS, DEFAULT_FIXTURE_ID, DEFAULT_SYMBOLS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate minimal custom-indicator validation case suites for manual TradingView comparison.",
    )
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument(
        "--indicator",
        choices=tuple(BUILDERS),
        help="Generate one indicator suite only (default: all seven + aggregator)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BACKEND / "production_screener_validation" / "cases",
        help="Directory for per-indicator JSON files",
    )
    parser.add_argument(
        "--aggregate-output",
        type=Path,
        default=BACKEND / "production_screener_validation" / "cases" / "custom_indicators_minimal.json",
        help="Combined suite output path",
    )
    parser.add_argument("--skip-aggregate", action="store_true")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected = {args.indicator: BUILDERS[args.indicator]} if args.indicator else dict(BUILDERS)

    all_cases: list[dict] = []
    for key, (suite_id, builder) in selected.items():
        cases = builder(fixture_id=args.fixture_id, symbols=args.symbols)
        output_path = args.output_dir / f"{key}_filter_minimal.json"
        payload = {"suite_id": suite_id, "cases": cases}
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(cases)} cases -> {output_path}")
        all_cases.extend(cases)

    if not args.skip_aggregate and not args.indicator:
        aggregate = {"suite_id": "custom_indicators_minimal", "cases": all_cases}
        args.aggregate_output.parent.mkdir(parents=True, exist_ok=True)
        args.aggregate_output.write_text(json.dumps(aggregate, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(all_cases)} combined cases -> {args.aggregate_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

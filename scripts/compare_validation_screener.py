from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from validation.fixture_store import FixtureStore  # noqa: E402
from validation.screener.cases import ScreenerCaseSuite  # noqa: E402
from validation.screener.comparator import ScreenerComparator  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate backend screener decisions against frozen Twelve references."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--twelve-symbol")
    parser.add_argument("--massive-symbol")
    parser.add_argument("--rsi-length", type=int, default=14)
    parser.add_argument("--aroon-length", type=int, default=14)
    parser.add_argument("--macd-fast", type=int, default=12)
    parser.add_argument("--macd-slow", type=int, default=26)
    parser.add_argument("--macd-signal", type=int, default=9)
    parser.add_argument("--ema-length", type=int, default=9)
    parser.add_argument("--adjustment", default="splits")
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=BACKEND_DIR / "validation" / "fixtures",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    spec = ValidationSpec(
        symbol=args.symbol,
        twelve_symbol=args.twelve_symbol,
        massive_symbol=args.massive_symbol,
        adjustment=args.adjustment,
        indicators=IndicatorParameters(
            rsi_length=args.rsi_length,
            aroon_length=args.aroon_length,
            macd_fast=args.macd_fast,
            macd_slow=args.macd_slow,
            macd_signal=args.macd_signal,
            ema_length=args.ema_length,
        ),
    )
    output = ScreenerComparator(FixtureStore(args.fixtures_root)).compare(
        spec,
        ScreenerCaseSuite.from_json_file(args.cases),
    )
    print(f"Screener verdict: {output['report']['verdict']}")
    print(f"Earliest mismatch: {output['report']['earliest_mismatch_stage'] or 'none'}")
    print(f"Report: {output['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

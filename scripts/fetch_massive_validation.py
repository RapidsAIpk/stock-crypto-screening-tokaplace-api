from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from validation.alignment import CandleAlignmentAuditor  # noqa: E402
from validation.fixture_store import FixtureStore  # noqa: E402
from validation.massive.client import MassiveDataClient  # noqa: E402
from validation.massive.fetcher import MassiveCandleFetcher  # noqa: E402
from validation.massive.pipeline import MassiveValidationPipeline  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Freeze and audit Massive candles for June 1-30, 2026."
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--twelve-symbol")
    parser.add_argument("--massive-symbol")
    parser.add_argument("--rsi-length", type=int, default=14)
    parser.add_argument("--aroon-length", type=int, default=14)
    parser.add_argument("--macd-fast", type=int, default=12)
    parser.add_argument("--macd-slow", type=int, default=26)
    parser.add_argument("--macd-signal", type=int, default=9)
    parser.add_argument("--ema-length", type=int, default=9)
    parser.add_argument("--adjustment", default="splits")
    parser.add_argument("--absolute-tolerance", type=float, default=0.0)
    parser.add_argument("--relative-tolerance", type=float, default=0.0)
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=BACKEND_DIR / "validation" / "fixtures",
    )
    return parser


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    args = build_parser().parse_args()
    api_key = str(
        os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""
    ).strip()
    if not api_key:
        raise SystemExit("MASSIVE_API_KEY or POLYGON_API_KEY is required in backend/.env")

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
    store = FixtureStore(args.fixtures_root)
    client = MassiveDataClient(
        api_key,
        base_url=os.getenv("MARKET_DATA_API_BASE_URL", "https://api.massive.com"),
    )
    try:
        result = MassiveValidationPipeline(
            MassiveCandleFetcher(client),
            store,
            CandleAlignmentAuditor(
                store,
                absolute_tolerance=args.absolute_tolerance,
                relative_tolerance=args.relative_tolerance,
            ),
        ).freeze_and_audit(spec)
    finally:
        client.close()

    print(f"Frozen Massive validation run: {result['massive_run_path']}")
    print(f"Alignment status: {result['alignment']['status']}")
    print(f"Alignment report: {result['alignment_report_path']}")
    print("API requests used: 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

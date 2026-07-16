from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from validation.alignment import CandleAlignmentAuditor  # noqa: E402
from validation.comparison import IndicatorComparator  # noqa: E402
from validation.fixture_store import FixtureStore  # noqa: E402
from validation.indicators.pipeline import BackendIndicatorPipeline  # noqa: E402
from validation.massive.client import MassiveDataClient  # noqa: E402
from validation.massive.fetcher import MassiveCandleFetcher  # noqa: E402
from validation.massive.pipeline import MassiveValidationPipeline  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402
from validation.twelve.client import TwelveDataClient  # noqa: E402
from validation.twelve.pipeline import TwelveReferencePipeline  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full 30-minute validation pipeline: freeze Twelve Data, "
            "fetch Massive, align OHLCV, calculate backend indicators, and compare."
        )
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
        "--tolerances",
        type=Path,
        default=BACKEND_DIR / "validation" / "tolerances.example.json",
    )
    parser.add_argument(
        "--fixtures-root",
        type=Path,
        default=BACKEND_DIR / "validation" / "fixtures",
    )
    return parser


def spec_from_args(args: argparse.Namespace) -> ValidationSpec:
    return ValidationSpec(
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


def freeze_twelve_if_missing(spec: ValidationSpec, store: FixtureStore) -> Path:
    run_path = store.run_path(spec)
    if run_path.exists():
        store.verify_run(run_path)
        print(f"Twelve Data fixture exists: {run_path}")
        return run_path

    api_key = str(os.getenv("TWELVE_DATA_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("TWELVE_DATA_API_KEY is required in backend/.env")
    client = TwelveDataClient(api_key)
    try:
        run_path = TwelveReferencePipeline(client, store).freeze(spec)
    finally:
        client.close()
    print(f"Frozen Twelve Data fixture: {run_path}")
    return run_path


def freeze_massive_if_missing(
    spec: ValidationSpec,
    store: FixtureStore,
    twelve_path: Path,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> Path:
    run_path = store.massive_run_path(spec)
    alignment_path = store.results_path(spec) / "candle_alignment.json"
    if run_path.exists() and alignment_path.exists():
        store.verify_massive_run(run_path)
        print(f"Massive fixture exists: {run_path}")
        print(f"Candle alignment report exists: {alignment_path}")
        return run_path

    api_key = str(
        os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""
    ).strip()
    if not api_key:
        raise RuntimeError("MASSIVE_API_KEY or POLYGON_API_KEY is required in backend/.env")
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
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            ),
        ).freeze_and_audit(spec, twelve_path)
    finally:
        client.close()
    print(f"Frozen Massive fixture: {result['massive_run_path']}")
    print(f"Alignment status: {result['alignment']['status']}")
    print(f"Alignment report: {result['alignment_report_path']}")
    return Path(result["massive_run_path"])


def calculate_backend_if_missing(spec: ValidationSpec, store: FixtureStore, massive_path: Path) -> Path:
    result_path = store.results_path(spec) / "backend_indicators.json"
    if result_path.exists():
        print(f"Backend indicator result exists: {result_path}")
        return result_path
    output = BackendIndicatorPipeline(store).run(spec, massive_path)
    print(f"Backend indicator result: {output['result_path']}")
    for indicator, summary in output["result"]["summary"].items():
        print(f"{indicator}: {summary['status']} ({summary['rows']} rows)")
    return Path(output["result_path"])


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    args = build_parser().parse_args()
    spec = spec_from_args(args)
    store = FixtureStore(args.fixtures_root)

    print(f"Validation run_id: {spec.run_id}")
    print(f"Timeframe: {spec.timeframe}")

    twelve_path = freeze_twelve_if_missing(spec, store)
    massive_path = freeze_massive_if_missing(
        spec,
        store,
        twelve_path,
        absolute_tolerance=args.absolute_tolerance,
        relative_tolerance=args.relative_tolerance,
    )
    calculate_backend_if_missing(spec, store, massive_path)

    tolerances = {}
    if args.tolerances and args.tolerances.exists():
        tolerances = json.loads(args.tolerances.read_text("utf-8"))
        if not isinstance(tolerances, dict):
            raise RuntimeError("--tolerances must contain a JSON object")
    output = IndicatorComparator(store, tolerance_overrides=tolerances).compare(
        spec,
        twelve_path,
    )
    print(f"Indicator verdict: {output['report']['verdict']}")
    print(f"Earliest mismatch: {output['report']['earliest_mismatch_stage'] or 'none'}")
    print(f"Report: {output['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

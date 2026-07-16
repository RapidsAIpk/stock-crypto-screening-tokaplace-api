from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.comparison.production_reports import (  # noqa: E402
    write_production_case_report,
    write_production_suite_summary,
)
from production_screener_validation.contracts import CaseSuite  # noqa: E402
from production_screener_validation.fixture_store import FixtureStore  # noqa: E402
from production_screener_validation.production.evidence import evaluate_case_production  # noqa: E402
from production_screener_validation.production.runner import ProductionRunner  # noqa: E402


DEFAULT_CASES = BACKEND / "production_screener_validation" / "cases" / "custom_indicators_minimal.json"
DEFAULT_ROOT = BACKEND / "production_screener_validation" / "data"
DEFAULT_OUTPUT = BACKEND / "production_screener_validation" / "reports" / "custom"


async def _verify_production_alignment(case, store, evidence_result) -> None:
    runner = ProductionRunner(store)
    production = await runner.run_case(case)
    expected = set(evidence_result.get("passing_symbols") or [])
    actual = set(production.get("symbols") or [])
    if production.get("status") == "evaluated" and expected != actual:
        print(
            f"WARN  {case.case_id}: evidence={sorted(expected)} runner={sorted(actual)}",
            file=sys.stderr,
        )


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="Run custom-indicator cases using production screener only (no oracle).",
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", help="Run only one case ID")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--verify-runner",
        action="store_true",
        help="Cross-check evidence vs ProductionRunner and print warnings on mismatch",
    )
    args = parser.parse_args()

    store = FixtureStore(args.root)
    manifest = store.verify("stocks_daily_2026_06_30_v1")
    print(f"Fixture OK: {manifest['fixture_id']} ({len(manifest.get('symbols', []))} symbols)")

    loaded = CaseSuite.from_json_file(args.cases)
    cases = tuple(case for case in loaded.cases if not args.case or case.case_id == args.case)
    if not cases:
        raise SystemExit(f"case '{args.case}' was not found in {args.cases}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = args.output or (DEFAULT_OUTPUT / stamp)
    cases_dir = output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    print(f"Running {len(cases)} case(s) from {args.cases.name}")
    print(f"Output: {output_dir}\n")

    for case in cases:
        result = evaluate_case_production(case, store)
        result["case_id"] = case.case_id
        if args.verify_runner:
            await _verify_production_alignment(case, store, result)
        paths = write_production_case_report(cases_dir, case, result)
        results.append(result)
        passing = ", ".join(result.get("passing_symbols") or []) or "none"
        print(f"CASE  {case.case_id:40} pass=[{passing}]")
        print(f"       -> {paths['markdown'].name}")

    summary_paths = write_production_suite_summary(output_dir, loaded.suite_id, results)
    print(f"\nSummary: {summary_paths['markdown']}")
    print(f"Cases:   {cases_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

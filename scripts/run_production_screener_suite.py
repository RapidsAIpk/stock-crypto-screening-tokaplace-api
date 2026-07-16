from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.comparison.readable_reports import (  # noqa: E402
    write_case_report,
    write_suite_summary,
)
from production_screener_validation.contracts import CaseSuite  # noqa: E402
from production_screener_validation.pipeline import ValidationPipeline  # noqa: E402


DEFAULT_CASES = BACKEND / "production_screener_validation" / "cases" / "standard_combinations.example.json"
DEFAULT_ROOT = BACKEND / "production_screener_validation" / "data"
DEFAULT_OUTPUT = BACKEND / "production_screener_validation" / "reports" / "runs"


async def run() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run all screener filter combos offline: independent reference vs production, "
            "one readable report file per case."
        )
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Case suite JSON file")
    parser.add_argument("--case", help="Run only one case ID from the suite")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Fixture/golden data root")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: reports/runs/<timestamp>)",
    )
    args = parser.parse_args()

    loaded = CaseSuite.from_json_file(args.cases)
    cases = tuple(case for case in loaded.cases if not args.case or case.case_id == args.case)
    if not cases:
        raise SystemExit(f"case '{args.case}' was not found in {args.cases}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = args.output or (DEFAULT_OUTPUT / stamp)
    cases_dir = output_dir / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    pipeline = ValidationPipeline(args.root)
    results: list[dict] = []
    print(f"Running {len(cases)} case(s) from {args.cases.name}")
    print(f"Output: {output_dir}\n")

    for case in cases:
        result = await pipeline.compare_case_direct(case)
        paths = write_case_report(cases_dir, case, result)
        results.append(result)
        status = result["verdict"].upper()
        expected = ", ".join(result["expected_symbols"]) or "none"
        actual = ", ".join(result["actual_symbols"]) or "none"
        print(f"{status:6} {case.case_id:35} expected=[{expected}] production=[{actual}]")
        print(f"       -> {paths['markdown'].name}")

    summary_paths = write_suite_summary(output_dir, loaded.suite_id, results)
    passes = sum(1 for item in results if item["verdict"] == "pass")
    failures = len(results) - passes
    overall = "PASS" if failures == 0 else "FAIL"
    print(f"\nOverall: {overall} ({passes}/{len(results)} cases match)")
    print(f"Summary: {summary_paths['markdown']}")
    print(f"Cases:   {cases_dir}/")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))

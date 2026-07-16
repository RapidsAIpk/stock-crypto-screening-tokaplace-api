from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from validation.fixture_store import FixtureStore
from validation.screener.backend_runner import BackendFilterRunner
from validation.screener.cases import ScreenerCaseSuite
from validation.screener.oracle import ReferenceFilterOracle
from validation.spec import ValidationSpec


class ScreenerComparator:
    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    def compare(
        self,
        spec: ValidationSpec,
        suite: ScreenerCaseSuite,
        twelve_run_path: str | Path | None = None,
        massive_run_path: str | Path | None = None,
    ) -> dict[str, Any]:
        twelve_path = Path(twelve_run_path or self.store.run_path(spec))
        massive_path = Path(massive_run_path or self.store.massive_run_path(spec))
        self.store.verify_run(twelve_path)
        self.store.verify_massive_run(massive_path)
        indicator_report = json.loads(
            (self.store.results_path(spec) / "indicator_comparison.json").read_text("utf-8")
        )
        if indicator_report.get("run_id") != spec.run_id:
            raise ValueError("indicator comparison does not match the validation run ID")

        expected = ReferenceFilterOracle(spec, twelve_path).evaluate_suite(suite)
        actual = BackendFilterRunner(spec, str(massive_path)).evaluate_suite(suite)
        case_results: list[dict[str, Any]] = []
        for case in suite.cases:
            reference = expected["cases"][case.case_id]
            backend = actual["cases"][case.case_id]
            if reference["status"] != "evaluated":
                status = "reference_error"
            elif backend["status"] != "evaluated":
                status = "insufficient_data"
            else:
                status = (
                    "pass"
                    if reference["expected_pass"] == backend["actual_pass"]
                    and backend["actual_pass"] == backend["screener_included"]
                    else "fail"
                )
            case_results.append(
                {
                    "case_id": case.case_id,
                    "indicator": case.indicator,
                    "status": status,
                    "expected": reference,
                    "actual": backend,
                }
            )

        combined_results: list[dict[str, Any]] = []
        for combined in suite.combined:
            reference = expected["combined"][combined.case_id]
            backend = actual["combined"][combined.case_id]
            if reference["status"] != "evaluated":
                status = "reference_error"
            elif backend["status"] != "evaluated":
                status = "insufficient_data"
            else:
                status = (
                    "pass"
                    if reference["expected_included"] == backend["actual_included"]
                    else "fail"
                )
            combined_results.append(
                {
                    "case_id": combined.case_id,
                    "operator": combined.operator,
                    "status": status,
                    "expected": reference,
                    "actual": backend,
                }
            )

        indicator_verdict = indicator_report.get("verdict")
        if indicator_verdict != "pass":
            verdict = indicator_verdict
            earliest_stage = indicator_report.get("earliest_mismatch_stage") or "indicator_comparison"
        elif any(item["status"] == "reference_error" for item in case_results + combined_results):
            verdict = "reference_error"
            earliest_stage = "reference_filter_oracle"
        elif any(item["status"] == "insufficient_data" for item in case_results + combined_results):
            verdict = "insufficient_data"
            earliest_stage = "backend_filter"
        elif any(item["status"] == "fail" for item in case_results):
            verdict = "fail"
            earliest_stage = "rule_evaluation"
        elif any(item["status"] == "fail" for item in combined_results):
            verdict = "fail"
            earliest_stage = "screener_composition"
        else:
            verdict = "pass"
            earliest_stage = None

        report = {
            "run_id": spec.run_id,
            "verdict": verdict,
            "earliest_mismatch_stage": earliest_stage,
            "indicator_comparison_verdict": indicator_verdict,
            "single_indicator_cases": case_results,
            "combined_cases": combined_results,
        }
        report_path = self.store.write_result(
            spec,
            "screener_comparison.json",
            report,
        )
        return {"report_path": report_path, "report": report}

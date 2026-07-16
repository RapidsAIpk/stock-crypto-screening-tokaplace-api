from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .comparison.comparator import ScreenerComparator
from .comparison.reporting import write_reports
from .contracts import CaseSuite, ScreenerCase
from .fixture_store import FixtureStore, GoldenStore
from .production.runner import ProductionRunner
from .reference.oracle import ReferenceOracle


class ValidationPipeline:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.fixtures = FixtureStore(self.root)
        self.goldens = GoldenStore(self.root)
        self.oracle = ReferenceOracle(self.fixtures)
        self.production = ProductionRunner(self.fixtures)
        self.comparator = ScreenerComparator()

    def generate_candidate(self, case: ScreenerCase) -> tuple[str, Path]:
        reference = self._reference_for_case(case)
        return self.goldens.write_candidate(case, self.fixtures.verify(case.fixture_id), reference)

    def _reference_for_case(self, case: ScreenerCase) -> dict[str, Any]:
        if case.timeframe_mode == "single":
            return self.oracle.evaluate_case(case)
        gate_reference = self.oracle.evaluate_case(case, scope="primary")
        if gate_reference["status"] != "evaluated":
            return gate_reference
        entry_reference = self.oracle.evaluate_case(case, scope="secondary")
        allowed = set(gate_reference["expected_symbols"])
        entry_reference["expected_symbols"] = sorted(allowed.intersection(entry_reference["expected_symbols"]))
        entry_reference["gate_expected_symbols"] = gate_reference["expected_symbols"]
        entry_reference["gate_symbol_evidence"] = gate_reference["symbol_evidence"]
        return entry_reference

    async def compare_case_direct(self, case: ScreenerCase) -> dict[str, Any]:
        """Compare independent reference output with production without requiring golden approval."""
        reference = self._reference_for_case(case)
        production = await self.production.run_case(case)
        return asdict(self.comparator.compare(case, reference, production))

    async def validate_case(self, case: ScreenerCase) -> dict[str, Any]:
        reference = self._reference_for_case(case)
        if case.golden_id:
            try:
                golden = self.goldens.load_approved(case.golden_id)
            except FileNotFoundError as exc:
                result = self.comparator.compare(case, reference, None, reference_verdict="unapproved_reference", error=str(exc))
                return asdict(result)
        else:
            golden = self.goldens.find_approved(case)
            if golden is None:
                result = self.comparator.compare(case, reference, None, reference_verdict="unapproved_reference", error="case has no approved golden reference")
                return asdict(result)
        drift = self.goldens.verify(golden, case, self.fixtures.verify(case.fixture_id), reference)
        if drift:
            result = self.comparator.compare(case, reference, None, reference_verdict="reference_drift", error=drift)
            return asdict(result)
        production = await self.production.run_case(case)
        return asdict(self.comparator.compare(case, golden["reference"], production))

    async def validate_suite(self, suite: CaseSuite, output_dir: str | Path) -> dict[str, Any]:
        results = []
        for case in suite.cases:
            result = await self.validate_case(case)
            result["required"] = case.required
            results.append(result)
        paths = write_reports(output_dir, suite.suite_id, results)
        required_failures = [item for item in results if item["required"] and item["verdict"] != "pass"]
        return {"verdict": "pass" if not required_failures else "fail", "results": results, "paths": paths}

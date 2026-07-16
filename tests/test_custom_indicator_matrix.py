from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.contracts import CaseSuite  # noqa: E402
from scripts.custom_indicator_matrix import BUILDERS  # noqa: E402


class CustomIndicatorMatrixTests(unittest.TestCase):
    def test_builders_produce_unique_case_ids(self) -> None:
        fixture_id = "stocks_daily_2026_06_30_v1"
        symbols = ["AAPL", "AMD", "MSFT", "NVDA", "TSLA"]
        for key, (_suite_id, builder) in BUILDERS.items():
            cases = builder(fixture_id=fixture_id, symbols=symbols)
            ids = [item["id"] for item in cases]
            self.assertGreater(len(cases), 5, msg=key)
            self.assertEqual(len(ids), len(set(ids)), msg=f"duplicate ids in {key}")

    def test_aggregate_suite_loads(self) -> None:
        path = BACKEND / "production_screener_validation" / "cases" / "custom_indicators_minimal.json"
        if not path.exists():
            self.skipTest("run build_custom_indicator_filter_matrix.py first")
        suite = CaseSuite.from_json_file(path)
        self.assertEqual(len(suite.cases), 106)


if __name__ == "__main__":
    unittest.main()

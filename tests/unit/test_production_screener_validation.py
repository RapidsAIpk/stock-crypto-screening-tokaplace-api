from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.comparison.comparator import ScreenerComparator
from production_screener_validation.contracts import CaseSuite, IndicatorRule, ScreenerCase
from production_screener_validation.fixture_store import FixtureStore, GoldenStore
from production_screener_validation.pipeline import ValidationPipeline
from production_screener_validation.reference.oracle import ReferenceOracle
from production_screener_validation.reference.rule_engine import evaluate_custom
from production_screener_validation.reference.talib_engine import TALIB_VERSION, calculate


def candles(direction: int, count: int = 100) -> list[dict]:
    start = date(2025, 1, 1)
    rows = []
    for index in range(count):
        close = 100.0 + direction * index
        rows.append({
            "date": (start + timedelta(days=index)).isoformat(),
            "time": index,
            "open": close - direction * 0.4,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0 + index * (10 if direction > 0 else 1),
            "closed": True,
        })
    return rows


def standard_indicators(scope: str = "single") -> tuple[IndicatorRule, ...]:
    return (
        IndicatorRule("rsi", scope, {"length": 14, "location": "overbought", "direction": None, "window": 1, "tolerance_pct": 0, "confirmation": False}),
        IndicatorRule("aroon", scope, {"length": 14, "level": "above_50", "direction": None, "window": 1, "extreme_level": 70, "tolerance_pct": 0, "confirmation": False}),
        IndicatorRule("macd", scope, {"fast": 12, "slow": 26, "signal": 9, "rule": "above_zero", "tolerance_pct": 0}),
        IndicatorRule("ema", scope, {"length": 9, "rule": "above", "tolerance_pct": 0}),
    )


class ProductionScreenerValidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = FixtureStore(self.root)
        self.store.create(
            "tiny_stocks_v1",
            {
                "1day": {"UP": candles(1), "DOWN": candles(-1)},
                "1h": {"UP": candles(1), "DOWN": candles(-1)},
            },
            {
                "UP": {"name": "Up Corp", "exchange": "TEST", "asset_type": "stocks", "compliance_status": "compliant", "float_shares": 1_000_000, "shares_outstanding": 2_000_000},
                "DOWN": {"name": "Down Corp", "exchange": "TEST", "asset_type": "stocks", "compliance_status": "compliant", "float_shares": 3_000_000, "shares_outstanding": 4_000_000},
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def case(self, **overrides) -> ScreenerCase:
        values = {
            "case_id": "all_standard",
            "fixture_id": "tiny_stocks_v1",
            "symbols": ("UP", "DOWN"),
            "indicators": standard_indicators(),
        }
        values.update(overrides)
        return ScreenerCase(**values)

    def test_linreg_reference_supports_virtual_ohlc_and_all_position_actions(self):
        rows = [
            {"date": f"2025-01-0{index + 1}", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1, "closed": True}
            for index in range(3)
        ]

        scenarios = {
            "above": ([101, 101, 101], [103, 103, 103], [101, 101, 101], [102, 102, 102]),
            "below": ([99, 99, 99], [99, 99, 99], [97, 97, 97], [98, 98, 98]),
            "on": ([99, 99, 99], [102, 102, 102], [98, 98, 98], [101, 101, 101]),
            "piercing_from_below": ([101, 99, 101], [102, 102, 103], [98, 98, 100.5], [101, 101, 102]),
            "piercing_from_above": ([99, 101, 99], [102, 102, 100], [98, 98, 97], [99, 99, 98]),
        }

        for position, (bopen, bhigh, blow, bclose) in scenarios.items():
            values = {
                "line": np.array([100.0] * 3),
                "bopen": np.array(bopen, dtype=float),
                "bhigh": np.array(bhigh, dtype=float),
                "blow": np.array(blow, dtype=float),
                "bclose": np.array(bclose, dtype=float),
            }
            config = {
                "lr_length": 1,
                "signal_smoothing": 1,
                "price_position": position,
                "window": 2 if position.startswith("piercing_") else 3,
                "tolerance_pct": 0,
                "confirmation": False,
            }
            with self.subTest(position=position), patch(
                "production_screener_validation.reference.rule_engine.linear_regression_candles",
                return_value=values,
            ):
                result = evaluate_custom("linreg_candles", rows, {}, config)
                self.assertTrue(result["passed"])
                self.assertEqual(result["values"]["bclose"], float(bclose[result["signal_index"]]))

                younger_or_older = {**config, "window": config["window"] + 1}
                mismatch = evaluate_custom("linreg_candles", rows, {}, younger_or_older)
                self.assertFalse(mismatch["passed"])

    def test_linreg_reference_on_zero_tolerance_rejects_near_miss_and_ignores_forming_bar(self):
        rows = [
            {"date": "2025-01-01", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1, "closed": True},
            {"date": "2025-01-02", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1, "closed": True},
            {"date": "2025-01-03", "open": 99, "high": 102, "low": 98, "close": 101, "volume": 1, "is_closed": False},
        ]
        values = {
            "line": np.array([100.0, 100.0]),
            "bopen": np.array([99.0, 99.0]),
            "bhigh": np.array([99.9, 99.9]),
            "blow": np.array([98.0, 98.0]),
            "bclose": np.array([99.9, 99.9]),
        }
        config = {
            "lr_length": 1,
            "signal_smoothing": 1,
            "price_position": "on",
            "window": 2,
            "tolerance_pct": 0,
            "confirmation": False,
        }

        with patch(
            "production_screener_validation.reference.rule_engine.linear_regression_candles",
            return_value=values,
        ) as engine:
            result = evaluate_custom("linreg_candles", rows, {}, config)

        self.assertFalse(result["passed"])
        self.assertEqual(len(engine.call_args.args[0]), 2)

    def test_linreg_reference_price_position_any_or_null_does_not_apply_window(self):
        rows = [
            {"date": f"2025-01-0{index + 1}", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1, "closed": True}
            for index in range(3)
        ]
        values = {
            "line": np.array([100.0, 100.0, 100.0]),
            "bopen": np.array([101.0, 101.0, 101.0]),
            "bhigh": np.array([103.0, 103.0, 103.0]),
            "blow": np.array([101.0, 101.0, 101.0]),
            "bclose": np.array([102.0, 102.0, 102.0]),
        }

        for price_position in (None, "any"):
            config = {
                "lr_length": 1,
                "signal_smoothing": 1,
                "price_position": price_position,
                "close_location": "any",
                "window": 1,
                "tolerance_pct": 0,
                "confirmation": False,
            }
            with self.subTest(price_position=price_position), patch(
                "production_screener_validation.reference.rule_engine.linear_regression_candles",
                return_value=values,
            ):
                result = evaluate_custom("linreg_candles", rows, {}, config)

            self.assertTrue(result["passed"])
            self.assertEqual(result["signal_index"], 2)

    def test_linreg_reference_any_signal_unions_real_positions_and_respects_window(self):
        rows = [
            {"date": f"2025-01-0{index + 1}", "open": 200, "high": 201, "low": 199, "close": 200, "volume": 1, "closed": True}
            for index in range(3)
        ]
        values = {
            "line": np.array([100.0, 100.0, 100.0]),
            "bopen": np.array([98.0, 101.0, 101.0]),
            "bhigh": np.array([99.0, 103.0, 103.0]),
            "blow": np.array([97.0, 101.0, 101.0]),
            "bclose": np.array([98.0, 102.0, 102.0]),
        }
        config = {
            "lr_length": 1,
            "signal_smoothing": 1,
            "price_position": "any_signal",
            "close_location": "any",
            "window": 1,
            "tolerance_pct": 0,
            "confirmation": False,
        }

        with patch(
            "production_screener_validation.reference.rule_engine.linear_regression_candles",
            return_value=values,
        ):
            too_young = evaluate_custom("linreg_candles", rows, {}, config)
            exact = evaluate_custom("linreg_candles", rows, {}, {**config, "window": 2})

        self.assertFalse(too_young["passed"])
        self.assertTrue(exact["passed"])
        self.assertEqual(exact["signal_index"], 2)

    def approve(self, pipeline: ValidationPipeline, case: ScreenerCase) -> str:
        candidate, _ = pipeline.generate_candidate(case)
        golden_id, _ = pipeline.goldens.approve(candidate, "unit-test")
        return golden_id

    def test_talib_standard_adapter_produces_finite_latest_values(self):
        source = candles(1)
        configs = {
            "rsi": {"length": 14},
            "aroon": {"length": 14},
            "macd": {"fast": 12, "slow": 26, "signal": 9},
            "ema": {"length": 9},
        }
        for name, config in configs.items():
            output = calculate(name, source, config)
            self.assertTrue(all(float(series[-1]) == float(series[-1]) for series in output.values()), name)
        self.assertEqual(TALIB_VERSION, "0.6.8")

    def test_reference_oracle_selects_only_the_uptrend(self):
        reference = ReferenceOracle(self.store).evaluate_case(self.case())
        self.assertEqual(reference["status"], "evaluated")
        self.assertEqual(reference["expected_symbols"], ["UP"])
        self.assertTrue(all(rule["passed"] for rule in reference["symbol_evidence"]["UP"]["rules"]))

    async def test_approved_reference_matches_real_production_single_scan(self):
        pipeline = ValidationPipeline(self.root)
        case = self.case()
        self.approve(pipeline, case)
        result = await pipeline.validate_case(case)
        self.assertEqual(result["verdict"], "pass", result)
        self.assertEqual(result["expected_symbols"], ["UP"])
        self.assertEqual(result["actual_symbols"], ["UP"])

    async def test_unapproved_case_fails_closed_without_running_production(self):
        result = await ValidationPipeline(self.root).validate_case(self.case())
        self.assertEqual(result["verdict"], "unapproved_reference")
        self.assertEqual(result["actual_symbols"], [])

    async def test_reference_drift_is_detected_before_production(self):
        pipeline = ValidationPipeline(self.root)
        case = self.case()
        golden_id = self.approve(pipeline, case)
        path = self.root / "golden" / "approved" / f"{golden_id}.json"
        payload = json.loads(path.read_text("utf-8"))
        payload["reference"]["expected_symbols"] = ["DOWN"]
        path.write_text(json.dumps(payload), "utf-8")
        result = await pipeline.validate_case(case)
        self.assertEqual(result["verdict"], "reference_drift")

    def test_comparator_reports_false_positive_and_false_negative(self):
        case = self.case()
        reference = ReferenceOracle(self.store).evaluate_case(case)
        result = ScreenerComparator().compare(case, reference, {"status": "evaluated", "symbols": ["DOWN"], "results": []})
        self.assertEqual(result.verdict, "fail")
        self.assertEqual(result.missing_symbols, ["UP"])
        self.assertEqual(result.unexpected_symbols, ["DOWN"])

    async def test_gate_entry_runs_real_production_session_path(self):
        case = self.case(
            case_id="gate_entry",
            timeframe_mode="gate_entry",
            single_timeframe=None,
            gate_timeframe="1day",
            entry_timeframe="1h",
            indicators=(
                IndicatorRule("rsi", "primary", {"length": 14, "location": "overbought", "direction": None, "window": 1, "tolerance_pct": 0, "confirmation": False}),
                IndicatorRule("ema", "secondary", {"length": 9, "rule": "above", "tolerance_pct": 0}),
            ),
        )
        pipeline = ValidationPipeline(self.root)
        self.approve(pipeline, case)
        result = await pipeline.validate_case(case)
        self.assertEqual(result["verdict"], "pass", result)
        self.assertEqual(result["actual_symbols"], ["UP"])

    def test_fixture_checksum_mutation_is_rejected(self):
        path = self.root / "fixtures" / "tiny_stocks_v1" / "candles" / "1day" / "UP.json"
        path.write_text("[]", "utf-8")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.store.verify("tiny_stocks_v1")

    def test_reference_package_has_no_production_service_imports(self):
        reference_dir = BACKEND / "production_screener_validation" / "reference"
        violations = []
        for path in reference_dir.glob("*.py"):
            tree = ast.parse(path.read_text("utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    violations.extend(alias.name for alias in node.names if alias.name == "services" or alias.name.startswith("services."))
                if isinstance(node, ast.ImportFrom) and node.module and (node.module == "services" or node.module.startswith("services.")):
                    violations.append(node.module)
        self.assertEqual(violations, [])

    def test_suite_rejects_duplicate_ids(self):
        path = self.root / "cases.json"
        base = {
            "id": "same", "fixture_id": "tiny_stocks_v1", "symbols": ["UP"],
            "indicators": [{"name": "ema", "timeframe": "single", "config": {"length": 9, "rule": "above", "tolerance_pct": 0}}],
        }
        path.write_text(json.dumps({"suite_id": "bad", "cases": [base, base]}), "utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            CaseSuite.from_json_file(path)

    def test_contract_rejects_unknown_rule_and_incomplete_config(self):
        with self.assertRaisesRegex(ValueError, "unknown rsi.location"):
            IndicatorRule("rsi", "single", {"length": 14, "location": "cheap", "direction": None, "window": 1, "tolerance_pct": 0, "confirmation": False})
        with self.assertRaisesRegex(ValueError, "missing explicit fields"):
            IndicatorRule("ema", "single", {"length": 9, "rule": "above"})

    def test_fixture_rejects_incomplete_candles(self):
        rows = candles(1)
        rows[-1]["closed"] = False
        with self.assertRaisesRegex(ValueError, "incomplete candle"):
            self.store.create("bad_fixture", {"1day": {"UP": rows}}, {"UP": {}})

    def test_reference_with_insufficient_data_cannot_be_approved(self):
        case = self.case(
            case_id="too_long",
            indicators=(IndicatorRule("macd", "single", {"fast": 100, "slow": 200, "signal": 50, "rule": "above_zero", "tolerance_pct": 0}),),
        )
        pipeline = ValidationPipeline(self.root)
        candidate, _ = pipeline.generate_candidate(case)
        with self.assertRaisesRegex(ValueError, "fully evaluated"):
            pipeline.goldens.approve(candidate, "unit-test")

    def test_golden_approval_accepts_readable_case_id(self):
        pipeline = ValidationPipeline(self.root)
        case = self.case(case_id="readable_rsi_macd", indicators=standard_indicators()[:3])
        candidate_id, _ = pipeline.generate_candidate(case)
        self.assertEqual(pipeline.goldens.resolve_candidate_id("readable_rsi_macd"), candidate_id)
        golden_id, path = pipeline.goldens.approve("readable_rsi_macd", "unit-test")
        self.assertTrue(path.is_file())
        self.assertTrue(golden_id.startswith("readable_rsi_macd-"))

    def test_golden_store_lists_candidates_for_cli_errors(self):
        pipeline = ValidationPipeline(self.root)
        pipeline.generate_candidate(self.case(case_id="listed_case"))
        candidates = pipeline.goldens.list_candidates()
        self.assertEqual(candidates[0]["case_id"], "listed_case")
        with self.assertRaisesRegex(FileNotFoundError, "missing_case"):
            pipeline.goldens.resolve_candidate_id("missing_case")

    def test_all_fifteen_standard_combinations_are_structurally_valid(self):
        import itertools
        rules = standard_indicators()
        cases = []
        for size in range(1, 5):
            for combination in itertools.combinations(rules, size):
                cases.append(self.case(case_id="_".join(item.name for item in combination), indicators=combination))
        self.assertEqual(len(cases), 15)
        self.assertEqual(len({case.checksum for case in cases}), 15)

    def test_all_custom_indicator_families_are_evaluable_offline(self):
        configurations = {
            "wavetrend": {"channel_length": 10, "average_length": 21, "signal_length": 4, "zone": "any", "direction": None, "window": 1, "tolerance_pct": 0, "confirmation": False},
            "linreg_candles": {"lr_length": 11, "signal_smoothing": 7, "price_position": "above", "close_location": "bullish", "window": 1, "tolerance_pct": 0, "confirmation": False},
            "lrc": {"length": 50, "upper_dev": 2, "lower_dev": 2, "lines": ["middle"], "action": "touched", "touch_type": "both", "window": 3, "tolerance_pct": 1, "r_mode": "ignore", "r_min": 0, "r_max": 1, "confirmation": False},
            "regression": {"length": 50, "width_coeff": 1, "window_type": "continuous", "interval_step": 1, "lines": ["middle"], "action": "touched", "touch_type": "both", "window": 3, "tolerance_pct": 1, "confirmation": False},
            "trend": {"length": 20, "areas": [{"area": "middle_line", "action": "touched", "window": 3, "tolerance_pct": 2}], "wait_for_break": True, "show_last_channel": True},
            "volume": {"length": 20, "multiplier": 1.1, "tolerance_pct": 0},
            "relative_volume": {"length": 20, "min_ratio": 1.0, "tolerance_pct": 0},
            "current_volume": {"min_value": 1, "max_value": 1_000_000, "tolerance_pct": 0},
            "float": {"min_value": 1, "max_value": 10_000_000, "tolerance_pct": 0},
            "shares_outstanding": {"min_value": 1, "max_value": 10_000_000, "tolerance_pct": 0},
            "volatility": {"length": 20, "min_pct": 0, "max_pct": 100, "tolerance_pct": 0},
        }
        oracle = ReferenceOracle(self.store)
        for name, config in configurations.items():
            case = self.case(case_id=f"custom_{name}", indicators=(IndicatorRule(name, "single", config),))
            result = oracle.evaluate_case(case)
            self.assertEqual(result["status"], "evaluated", (name, result))

    def test_report_files_are_generated_for_automation_and_review(self):
        from production_screener_validation.comparison.reporting import write_reports
        result = ScreenerComparator().compare(
            self.case(),
            ReferenceOracle(self.store).evaluate_case(self.case()),
            {"status": "evaluated", "symbols": ["UP"], "results": []},
        )
        paths = write_reports(self.root / "reports", "tiny", [{**vars(result), "required": True}])
        self.assertEqual(set(paths), {"json", "markdown", "csv"})
        self.assertTrue(all(path.is_file() for path in paths.values()))


if __name__ == "__main__":
    unittest.main()

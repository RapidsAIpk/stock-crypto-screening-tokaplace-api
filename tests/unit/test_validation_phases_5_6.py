from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import aroon_oscillator, ema, indicators, macd, rsi  # noqa: E402
from validation.comparison import IndicatorComparator  # noqa: E402
from validation.fixture_store import FixtureStore  # noqa: E402
from validation.indicators.pipeline import BackendIndicatorPipeline  # noqa: E402
from validation.massive.client import MassiveDataClient  # noqa: E402
from validation.massive.fetcher import MassiveCandleFetcher  # noqa: E402
from validation.massive.pipeline import MassiveValidationPipeline  # noqa: E402
from validation.screener.cases import ScreenerCaseSuite  # noqa: E402
from validation.screener.comparator import ScreenerComparator  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402
from backend.tests.unit.test_validation_phases_3_4 import (  # noqa: E402
    FakeMassiveTransport,
    daily_rows,
    make_twelve_response,
    massive_payload,
)


def short_spec(**overrides):
    values = {
        "symbol": "BTC/USD",
        "indicators": IndicatorParameters(
            rsi_length=2,
            aroon_length=2,
            macd_fast=2,
            macd_slow=3,
            macd_signal=2,
            ema_length=2,
        ),
    }
    values.update(overrides)
    return ValidationSpec(**values)


def exact_reference_payloads(spec: ValidationSpec, *, omit_ema=False):
    twelve_rows, _ = daily_rows()
    candles = [
        {
            "date": row["datetime"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in twelve_rows
    ]
    parameters = spec.indicators

    rsi_values = rsi.compute_rsi_series(candles, length=parameters.rsi_length)
    rsi_offset = len(candles) - len(rsi_values)
    rsi_rows = [
        {"datetime": candles[index + rsi_offset]["date"], "rsi": str(float(value))}
        for index, value in enumerate(rsi_values)
    ]

    aroon_values = aroon_oscillator.compute_aroon_oscillator(
        candles,
        length=parameters.aroon_length,
    )
    aroon_offset = len(candles) - len(aroon_values)
    aroon_rows = []
    for index, value in enumerate(aroon_values):
        oscillator = float(value)
        aroon_rows.append(
            {
                "datetime": candles[index + aroon_offset]["date"],
                "aroon_up": str(max(oscillator, 0.0)),
                "aroon_down": str(max(-oscillator, 0.0)),
            }
        )

    macd_values = macd.compute_macd(
        candles,
        fast=parameters.macd_fast,
        slow=parameters.macd_slow,
        signal=parameters.macd_signal,
    )
    macd_rows = [
        {
            "datetime": candle["date"],
            "macd": str(float(macd_values["macd"][index])),
            "macd_signal": str(float(macd_values["signal"][index])),
            "macd_hist": str(float(macd_values["hist"][index])),
        }
        for index, candle in enumerate(candles)
    ]

    ema_values = ema.compute_ema(
        np.array([candle["close"] for candle in candles], dtype=float),
        parameters.ema_length,
    )
    ema_rows = [
        ({"datetime": candle["date"]} if omit_ema else {"datetime": candle["date"], "ema": str(float(ema_values[index]))})
        for index, candle in enumerate(candles)
    ]
    candle_payload = {
        "meta": {"symbol": "BTC/USD", "interval": "30min"},
        "values": twelve_rows,
        "status": "ok",
    }
    return candle_payload, {
        "rsi": {"values": rsi_rows, "status": "ok"},
        "aroon": {"values": aroon_rows, "status": "ok"},
        "macd": {"values": macd_rows, "status": "ok"},
        "ema": {"values": ema_rows, "status": "ok"},
    }


def standard_suite(*, confirmation=False, rsi_length=2):
    return ScreenerCaseSuite.from_payload(
        {
            "cases": [
                {
                    "id": "rsi_case",
                    "indicator": "rsi",
                    "config": {
                        "length": rsi_length,
                        "location": "overbought",
                        "window": 1,
                        "confirmation": confirmation,
                        **({"confirmation_type": "bullish"} if confirmation else {}),
                    },
                },
                {
                    "id": "aroon_case",
                    "indicator": "aroon",
                    "config": {
                        "length": 2,
                        "level": "above_50",
                        "window": 1,
                        "confirmation": False,
                    },
                },
                {
                    "id": "macd_case",
                    "indicator": "macd",
                    "config": {
                        "fast": 2,
                        "slow": 3,
                        "signal": 2,
                        "rule": "above_zero",
                    },
                },
                {
                    "id": "ema_case",
                    "indicator": "ema",
                    "config": {"length": 2, "rule": "above"},
                },
            ],
            "combined": [
                {
                    "id": "all_four",
                    "operator": "all",
                    "case_ids": ["rsi_case", "aroon_case", "macd_case", "ema_case"],
                },
                {
                    "id": "any_four",
                    "operator": "any",
                    "case_ids": ["rsi_case", "aroon_case", "macd_case", "ema_case"],
                },
            ],
        }
    )


class PhaseFiveSixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _prepare(
        self,
        *,
        spec: ValidationSpec | None = None,
        massive=None,
        omit_ema=False,
    ):
        spec = spec or short_spec()
        store = FixtureStore(self.root)
        candle_payload, indicator_payloads = exact_reference_payloads(
            spec,
            omit_ema=omit_ema,
        )
        twelve_path = store.freeze_twelve_run(
            spec,
            make_twelve_response("time_series", candle_payload),
            {
                name: make_twelve_response(name, payload)
                for name, payload in indicator_payloads.items()
            },
        )
        transport = FakeMassiveTransport(massive or massive_payload())
        phase_three = MassiveValidationPipeline(
            MassiveCandleFetcher(MassiveDataClient("test-key", request_get=transport)),
            store,
        ).freeze_and_audit(spec, twelve_path)
        BackendIndicatorPipeline(store).run(spec, phase_three["massive_run_path"])
        return spec, store, twelve_path, phase_three["massive_run_path"]

    def test_phase_five_passes_exact_component_values(self) -> None:
        spec, store, twelve_path, _ = self._prepare()
        output = IndicatorComparator(store).compare(spec, twelve_path)

        report = output["report"]
        self.assertEqual(report["verdict"], "pass")
        self.assertIsNone(report["earliest_mismatch_stage"])
        self.assertIsNone(report["first_divergence"])
        self.assertEqual(
            {summary["verdict"] for summary in report["summary"].values()},
            {"pass"},
        )
        self.assertTrue(all(row["status"] == "pass" for row in report["rows"]))

    def test_phase_five_reports_first_numeric_failure(self) -> None:
        spec, store, twelve_path, _ = self._prepare()
        backend_path = store.results_path(spec) / "backend_indicators.json"
        backend = json.loads(backend_path.read_text("utf-8"))
        target = next(row for row in backend["rows"] if row["indicator"] == "rsi")
        target["backend_value"] += 5
        backend_path.write_text(json.dumps(backend), encoding="utf-8")

        report = IndicatorComparator(store).compare(spec, twelve_path)["report"]
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["earliest_mismatch_stage"], "indicator_comparison")
        self.assertEqual(report["first_divergence"]["indicator"], "rsi")

    def test_phase_five_accepts_report_time_tolerance_override(self) -> None:
        spec, store, twelve_path, _ = self._prepare()
        backend_path = store.results_path(spec) / "backend_indicators.json"
        backend = json.loads(backend_path.read_text("utf-8"))
        target = next(row for row in backend["rows"] if row["indicator"] == "rsi")
        target["backend_value"] += 0.5
        backend_path.write_text(json.dumps(backend), encoding="utf-8")

        report = IndicatorComparator(
            store,
            tolerance_overrides={"rsi": 0.5},
        ).compare(spec, twelve_path)["report"]
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["tolerance_overrides"], {"rsi": 0.5})

        rerun = IndicatorComparator(
            store,
            tolerance_overrides={"rsi": 0.1},
        ).compare(spec, twelve_path)["report"]
        self.assertEqual(rerun["verdict"], "fail")
        self.assertEqual(rerun["tolerance_overrides"], {"rsi": 0.1})

    def test_phase_five_inherits_candle_input_mismatch(self) -> None:
        payload = massive_payload()
        payload["results"][25]["c"] += 3
        spec, store, twelve_path, _ = self._prepare(massive=payload)

        report = IndicatorComparator(store).compare(spec, twelve_path)["report"]
        self.assertEqual(report["verdict"], "inconclusive_input_mismatch")
        self.assertEqual(report["earliest_mismatch_stage"], "candle_alignment")

    def test_phase_five_reports_reference_error(self) -> None:
        spec, store, twelve_path, _ = self._prepare(omit_ema=True)

        report = IndicatorComparator(store).compare(spec, twelve_path)["report"]
        self.assertEqual(report["verdict"], "reference_error")
        self.assertEqual(report["summary"]["ema"]["verdict"], "reference_error")

    def test_phase_six_passes_single_combined_and_confirmation_cases(self) -> None:
        spec, store, twelve_path, massive_path = self._prepare()
        IndicatorComparator(store).compare(spec, twelve_path)

        report = ScreenerComparator(store).compare(
            spec,
            standard_suite(confirmation=True),
            twelve_path,
            massive_path,
        )["report"]
        self.assertEqual(report["verdict"], "pass")
        self.assertTrue(all(case["status"] == "pass" for case in report["single_indicator_cases"]))
        self.assertTrue(all(case["status"] == "pass" for case in report["combined_cases"]))
        rsi_case = next(
            case for case in report["single_indicator_cases"] if case["indicator"] == "rsi"
        )
        self.assertTrue(rsi_case["expected"]["confirmation_pass"])
        self.assertTrue(rsi_case["actual"]["confirmation_pass"])

    def test_phase_six_reports_backend_rule_mismatch(self) -> None:
        spec, store, twelve_path, massive_path = self._prepare()
        IndicatorComparator(store).compare(spec, twelve_path)
        with patch.dict(
            indicators.INDICATOR_REGISTRY,
            {"ema": lambda asset, candles, config: (False, None)},
        ):
            report = ScreenerComparator(store).compare(
                spec,
                standard_suite(),
                twelve_path,
                massive_path,
            )["report"]

        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["earliest_mismatch_stage"], "rule_evaluation")
        ema_case = next(
            case for case in report["single_indicator_cases"] if case["indicator"] == "ema"
        )
        self.assertEqual(ema_case["status"], "fail")

    def test_phase_six_rejects_case_period_mismatch(self) -> None:
        spec, store, twelve_path, massive_path = self._prepare()
        IndicatorComparator(store).compare(spec, twelve_path)

        report = ScreenerComparator(store).compare(
            spec,
            standard_suite(rsi_length=3),
            twelve_path,
            massive_path,
        )["report"]
        self.assertEqual(report["verdict"], "reference_error")
        self.assertEqual(report["earliest_mismatch_stage"], "reference_filter_oracle")

    def test_case_suite_requires_all_four_indicators_and_combined_case(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing indicators"):
            ScreenerCaseSuite.from_payload(
                {
                    "cases": [
                        {"id": "only_rsi", "indicator": "rsi", "config": {}},
                    ],
                    "combined": [],
                }
            )

    def test_case_suite_rejects_unknown_rule(self) -> None:
        payload = {
            "cases": [
                {"id": "rsi", "indicator": "rsi", "config": {}},
                {
                    "id": "aroon",
                    "indicator": "aroon",
                    "config": {"level": "above_50"},
                },
                {
                    "id": "macd",
                    "indicator": "macd",
                    "config": {"rule": "not_a_rule"},
                },
                {"id": "ema", "indicator": "ema", "config": {"rule": "above"}},
            ],
            "combined": [
                {
                    "id": "combined",
                    "operator": "all",
                    "case_ids": ["rsi", "aroon", "macd", "ema"],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "unsupported rule"):
            ScreenerCaseSuite.from_payload(payload)


if __name__ == "__main__":
    unittest.main()

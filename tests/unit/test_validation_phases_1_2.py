from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from validation.fixture_store import FixtureIntegrityError, FixtureStore  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402
from validation.twelve.client import (  # noqa: E402
    TwelveDataClient,
    TwelveDataError,
)
from validation.twelve.pipeline import TwelveReferencePipeline  # noqa: E402


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        # Deliberately non-canonical: the fixture must retain these exact bytes.
        self.content = json.dumps(payload, separators=(", ", ": ")).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class FakeTwelveTransport:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, Any], timeout: float) -> FakeHTTPResponse:
        endpoint = url.rstrip("/").rsplit("/", 1)[-1]
        self.calls.append({"endpoint": endpoint, "params": dict(params), "timeout": timeout})
        return FakeHTTPResponse(self.payloads[endpoint])


def reference_payloads() -> dict[str, dict[str, Any]]:
    common_meta = {
        "symbol": "BTC/USD",
        "interval": "30min",
        "exchange_timezone": "UTC",
    }
    return {
        "time_series": {
            "meta": common_meta,
            "values": [
                {
                    "datetime": "2026-06-02",
                    "open": "100.0",
                    "high": "103.0",
                    "low": "99.0",
                    "close": "102.0",
                    "volume": "10",
                },
                {
                    "datetime": "2026-06-21",
                    "open": "102.0",
                    "high": "106.0",
                    "low": "101.0",
                    "close": "105.0",
                    "volume": "12",
                },
            ],
            "status": "ok",
        },
        "rsi": {
            "meta": {**common_meta, "indicator": {"time_period": 14}},
            "values": [
                {"datetime": "2026-06-02", "rsi": "48.1"},
                {"datetime": "2026-06-21", "rsi": "51.7"},
            ],
            "status": "ok",
        },
        "aroon": {
            "meta": {**common_meta, "indicator": {"time_period": 14}},
            "values": [
                {"datetime": "2026-06-02", "aroon_up": "50", "aroon_down": "20"},
                {"datetime": "2026-06-21", "aroon_up": "70", "aroon_down": "10"},
            ],
            "status": "ok",
        },
        "macd": {
            "meta": {
                **common_meta,
                "indicator": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
            },
            "values": [
                {
                    "datetime": "2026-06-02",
                    "macd": "1.2",
                    "macd_signal": "1.0",
                    "macd_hist": "0.2",
                },
                {
                    "datetime": "2026-06-21",
                    "macd": "1.4",
                    "macd_signal": "1.1",
                    "macd_hist": "0.3",
                },
            ],
            "status": "ok",
        },
        "ema": {
            "meta": {**common_meta, "indicator": {"time_period": 9}},
            "values": [
                {"datetime": "2026-06-02", "ema": "101.2"},
                {"datetime": "2026-06-21", "ema": "102.0"},
            ],
            "status": "ok",
        },
    }


def june_spec(**overrides: Any) -> ValidationSpec:
    values: dict[str, Any] = {
        "symbol": "BTC/USD",
    }
    values.update(overrides)
    return ValidationSpec(**values)


class ValidationSpecTests(unittest.TestCase):
    def test_builds_deterministic_contract_and_fixed_split(self) -> None:
        first = june_spec()
        second = june_spec()

        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(first.training_start, date(2026, 6, 1))
        self.assertEqual(first.training_end, date(2026, 6, 20))
        self.assertEqual(first.validation_start, date(2026, 6, 21))
        self.assertEqual(first.validation_end, date(2026, 6, 30))
        self.assertEqual(first.timeframe, "30min")
        self.assertEqual(first.twelve_symbol, "BTC/USD")
        self.assertEqual(first.contract_dict()["comparison_end"], "2026-06-30")
        self.assertEqual(first.contract_dict()["data_split"]["training_days"], 20)
        self.assertEqual(first.contract_dict()["data_split"]["validation_days"], 10)

    def test_run_id_changes_with_indicator_parameters(self) -> None:
        baseline = june_spec()
        changed = june_spec(indicators=IndicatorParameters(ema_length=20))
        self.assertNotEqual(baseline.run_id, changed.run_id)

    def test_rejects_dates_outside_fixed_june_range_and_non_30_minute_timeframe(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed to 2026-06-01"):
            june_spec(comparison_end="2026-06-29")
        with self.assertRaisesRegex(ValueError, "only supports"):
            june_spec(timeframe="1h")

    def test_rejects_invalid_indicator_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "macd_fast"):
            IndicatorParameters(macd_fast=26, macd_slow=12)
        with self.assertRaisesRegex(ValueError, "tolerances"):
            june_spec(tolerance={"rsi": -0.1})


class TwelveDataClientTests(unittest.TestCase):
    def test_api_key_is_sent_but_not_retained_in_public_request_params(self) -> None:
        transport = FakeTwelveTransport(reference_payloads())
        client = TwelveDataClient("secret-key", request_get=transport)
        response = client.get("rsi", {"symbol": "BTC/USD"})

        self.assertEqual(transport.calls[0]["params"]["apikey"], "secret-key")
        self.assertNotIn("apikey", response.request_params)
        self.assertEqual(response.body, FakeHTTPResponse(reference_payloads()["rsi"]).content)

    def test_api_error_is_explicit(self) -> None:
        transport = FakeTwelveTransport(
            {"rsi": {"status": "error", "code": 429, "message": "limit reached"}}
        )
        client = TwelveDataClient("secret-key", request_get=transport)
        with self.assertRaisesRegex(TwelveDataError, "limit reached"):
            client.get("rsi", {})


class TwelveReferencePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.payloads = reference_payloads()
        self.transport = FakeTwelveTransport(self.payloads)
        self.client = TwelveDataClient("test-key", request_get=self.transport)
        self.store = FixtureStore(self.root)
        self.pipeline = TwelveReferencePipeline(self.client, self.store)
        self.spec = june_spec()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_freezes_four_independent_bundles_with_only_five_requests(self) -> None:
        run_path = self.pipeline.freeze(self.spec)

        self.assertEqual(
            [call["endpoint"] for call in self.transport.calls],
            ["time_series", "rsi", "aroon", "macd", "ema"],
        )
        for call in self.transport.calls:
            params = call["params"]
            self.assertEqual(params["interval"], "30min")
            self.assertEqual(params["start_date"], "2026-06-01")
            self.assertEqual(params["end_date"], "2026-06-30")
            self.assertEqual(params["timezone"], "UTC")

        expected_candle_bytes = FakeHTTPResponse(self.payloads["time_series"]).content
        for indicator in ("rsi", "aroon", "macd", "ema"):
            bundle = run_path / indicator
            self.assertTrue((bundle / "reference.csv").is_file())
            self.assertEqual((bundle / "candles.raw.json").read_bytes(), expected_candle_bytes)
            self.assertEqual(
                (bundle / "indicator.raw.json").read_bytes(),
                FakeHTTPResponse(self.payloads[indicator]).content,
            )
        self.store.verify_run(run_path)

        manifest_text = (run_path / "run_manifest.json").read_text("utf-8")
        self.assertNotIn("test-key", manifest_text)
        manifest = json.loads(manifest_text)
        self.assertEqual(manifest["run_id"], self.spec.run_id)
        self.assertEqual(set(manifest["bundles"]), {"rsi", "aroon", "macd", "ema"})

    def test_existing_run_fails_before_spending_more_api_requests(self) -> None:
        self.pipeline.freeze(self.spec)
        calls_after_first_run = len(self.transport.calls)

        with self.assertRaisesRegex(FileExistsError, "cannot be overwritten"):
            self.pipeline.freeze(self.spec)
        self.assertEqual(len(self.transport.calls), calls_after_first_run)

    def test_checksum_verification_detects_tampering(self) -> None:
        run_path = self.pipeline.freeze(self.spec)
        with (run_path / "rsi" / "indicator.raw.json").open("ab") as handle:
            handle.write(b"tampered")

        with self.assertRaisesRegex(FixtureIntegrityError, "checksum mismatch"):
            self.store.verify_run(run_path)

    def test_invalid_indicator_schema_is_not_frozen(self) -> None:
        del self.payloads["aroon"]["values"][0]["aroon_down"]

        with self.assertRaisesRegex(TwelveDataError, "aroon_down"):
            self.pipeline.freeze(self.spec)
        self.assertFalse(self.store.run_path(self.spec).exists())

    def test_non_numeric_reference_value_is_not_frozen(self) -> None:
        self.payloads["ema"]["values"][0]["ema"] = "not-a-number"

        with self.assertRaisesRegex(TwelveDataError, "non-numeric field 'ema'"):
            self.pipeline.freeze(self.spec)
        self.assertFalse(self.store.run_path(self.spec).exists())

    def test_duplicate_or_out_of_range_timestamps_are_rejected(self) -> None:
        self.payloads["rsi"]["values"][1]["datetime"] = "2026-06-02"
        with self.assertRaisesRegex(TwelveDataError, "duplicate datetime"):
            self.pipeline.freeze(self.spec)
        self.assertFalse(self.store.run_path(self.spec).exists())

        self.payloads = reference_payloads()
        self.payloads["rsi"]["values"][0]["datetime"] = "2026-05-31"
        self.transport.payloads = self.payloads
        with self.assertRaisesRegex(TwelveDataError, "outside the comparison range"):
            self.pipeline.freeze(self.spec)
        self.assertFalse(self.store.run_path(self.spec).exists())


if __name__ == "__main__":
    unittest.main()

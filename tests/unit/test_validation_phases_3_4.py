from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from validation.alignment import CandleAlignmentAuditor  # noqa: E402
from validation.fixture_store import FixtureIntegrityError, FixtureStore  # noqa: E402
from validation.indicators.pipeline import BackendIndicatorPipeline  # noqa: E402
from validation.massive.client import (  # noqa: E402
    MassiveDataClient,
    MassiveDataError,
    MassiveResponse,
)
from validation.massive.fetcher import MassiveCandleFetcher  # noqa: E402
from validation.massive.pipeline import MassiveValidationPipeline  # noqa: E402
from validation.spec import IndicatorParameters, ValidationSpec  # noqa: E402
from validation.twelve.client import TwelveResponse  # noqa: E402


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.content = json.dumps(payload, separators=(", ", ": ")).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class FakeMassiveTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, Any], timeout: float) -> FakeHTTPResponse:
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        return FakeHTTPResponse(self.payload)


def daily_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    twelve_rows: list[dict[str, Any]] = []
    massive_rows: list[dict[str, Any]] = []
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    for offset in range(30):
        timestamp = start + timedelta(days=offset)
        open_value = 100.0 + offset
        high_value = open_value + 2.0
        low_value = open_value - 1.0
        close_value = open_value + 1.0
        volume = 1000.0 + offset
        twelve_rows.append(
            {
                "datetime": timestamp.date().isoformat(),
                "open": str(open_value),
                "high": str(high_value),
                "low": str(low_value),
                "close": str(close_value),
                "volume": str(volume),
            }
        )
        massive_rows.append(
            {
                "t": int(timestamp.timestamp() * 1000),
                "o": open_value,
                "h": high_value,
                "l": low_value,
                "c": close_value,
                "v": volume,
            }
        )
    return twelve_rows, massive_rows


def massive_payload(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    _, default_rows = daily_rows()
    selected = default_rows if rows is None else rows
    return {
        "ticker": "X:BTCUSD",
        "adjusted": True,
        "queryCount": len(selected),
        "resultsCount": len(selected),
        "results": selected,
        "status": "OK",
        "request_id": "test-request",
    }


def make_twelve_response(endpoint: str, payload: dict[str, Any]) -> TwelveResponse:
    body = json.dumps(payload, separators=(", ", ": ")).encode("utf-8")
    return TwelveResponse(
        endpoint=endpoint,
        request_params={"symbol": "BTC/USD", "interval": "30min"},
        body=body,
        payload=payload,
        fetched_at="2026-07-01T00:00:00+00:00",
    )


def freeze_twelve(store: FixtureStore, spec: ValidationSpec) -> Path:
    twelve_candles, _ = daily_rows()
    candle_payload = {
        "meta": {"symbol": "BTC/USD", "interval": "30min"},
        "values": twelve_candles,
        "status": "ok",
    }
    indicator_payloads = {
        "rsi": {
            "values": [{"datetime": row["datetime"], "rsi": "50"} for row in twelve_candles],
            "status": "ok",
        },
        "aroon": {
            "values": [
                {"datetime": row["datetime"], "aroon_up": "60", "aroon_down": "20"}
                for row in twelve_candles
            ],
            "status": "ok",
        },
        "macd": {
            "values": [
                {
                    "datetime": row["datetime"],
                    "macd": "1",
                    "macd_signal": "0.8",
                    "macd_hist": "0.2",
                }
                for row in twelve_candles
            ],
            "status": "ok",
        },
        "ema": {
            "values": [{"datetime": row["datetime"], "ema": row["close"]} for row in twelve_candles],
            "status": "ok",
        },
    }
    return store.freeze_twelve_run(
        spec,
        make_twelve_response("time_series", candle_payload),
        {
            name: make_twelve_response(name, payload)
            for name, payload in indicator_payloads.items()
        },
    )


class MassiveFetcherTests(unittest.TestCase):
    def test_fetches_fixed_range_maps_crypto_and_marks_split(self) -> None:
        transport = FakeMassiveTransport(massive_payload())
        client = MassiveDataClient("secret", request_get=transport)
        response, candles = MassiveCandleFetcher(client).fetch(ValidationSpec(symbol="BTC/USD"))

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertTrue(
            call["url"].endswith(
                "/v2/aggs/ticker/X:BTCUSD/range/30/minute/2026-06-01/2026-06-30"
            )
        )
        self.assertEqual(call["params"]["sort"], "asc")
        self.assertIs(call["params"]["adjusted"], True)
        self.assertEqual(call["params"]["apiKey"], "secret")
        self.assertNotIn("apiKey", response.request_params)
        self.assertEqual([row["segment"] for row in candles].count("training"), 20)
        self.assertEqual([row["segment"] for row in candles].count("validation"), 10)

    def test_rejects_duplicate_timestamp_and_adjustment_mismatch(self) -> None:
        _, rows = daily_rows()
        rows[1]["t"] = rows[0]["t"]
        client = MassiveDataClient(
            "secret",
            request_get=FakeMassiveTransport(massive_payload(rows)),
        )
        with self.assertRaisesRegex(MassiveDataError, "duplicate timestamp"):
            MassiveCandleFetcher(client).fetch(ValidationSpec(symbol="BTC/USD"))

        payload = massive_payload()
        payload["adjusted"] = False
        client = MassiveDataClient(
            "secret",
            request_get=FakeMassiveTransport(payload),
        )
        with self.assertRaisesRegex(MassiveDataError, "does not match"):
            MassiveCandleFetcher(client).fetch(ValidationSpec(symbol="BTC/USD"))


class PhaseThreeFourPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = FixtureStore(self.root)
        self.spec = ValidationSpec(symbol="BTC/USD")
        self.twelve_path = freeze_twelve(self.store, self.spec)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _freeze_massive(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        transport = FakeMassiveTransport(payload or massive_payload())
        client = MassiveDataClient("test-key", request_get=transport)
        result = MassiveValidationPipeline(
            MassiveCandleFetcher(client),
            self.store,
        ).freeze_and_audit(self.spec, self.twelve_path)
        result["transport"] = transport
        return result

    def test_phase_three_freezes_one_request_and_aligned_report(self) -> None:
        output = self._freeze_massive()

        self.assertEqual(len(output["transport"].calls), 1)
        self.assertEqual(output["alignment"]["status"], "aligned")
        self.assertEqual(output["alignment"]["summary"]["validation_overlap_rows"], 10)
        massive_path = output["massive_run_path"]
        self.store.verify_massive_run(massive_path)
        self.assertTrue((massive_path / "candles.raw.json").is_file())
        csv_text = (massive_path / "candles.csv").read_text("utf-8")
        self.assertIn("training", csv_text)
        self.assertIn("validation", csv_text)
        self.assertNotIn("test-key", (massive_path / "run_manifest.json").read_text("utf-8"))

    def test_existing_massive_run_fails_before_another_request(self) -> None:
        output = self._freeze_massive()
        transport = output["transport"]
        calls_after_first_run = len(transport.calls)
        pipeline = MassiveValidationPipeline(
            MassiveCandleFetcher(MassiveDataClient("test-key", request_get=transport)),
            self.store,
        )

        with self.assertRaisesRegex(FileExistsError, "cannot be overwritten"):
            pipeline.freeze_and_audit(self.spec, self.twelve_path)
        self.assertEqual(len(transport.calls), calls_after_first_run)

    def test_massive_checksum_verification_detects_tampering(self) -> None:
        massive_path = self._freeze_massive()["massive_run_path"]
        with (massive_path / "candles.raw.json").open("ab") as handle:
            handle.write(b"tampered")

        with self.assertRaisesRegex(FixtureIntegrityError, "checksum mismatch"):
            self.store.verify_massive_run(massive_path)

    def test_alignment_marks_provider_value_difference_inconclusive(self) -> None:
        payload = massive_payload()
        payload["results"][25]["c"] += 5
        output = self._freeze_massive(payload)

        self.assertEqual(output["alignment"]["status"], "inconclusive_input_mismatch")
        mismatches = [
            row for row in output["alignment"]["rows"] if row["status"] == "value_mismatch"
        ]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["date"], "2026-06-26")
        self.assertFalse(mismatches[0]["fields"]["close"]["matches"])

    def test_alignment_marks_missing_validation_candle_inconclusive(self) -> None:
        _, rows = daily_rows()
        del rows[24]
        output = self._freeze_massive(massive_payload(rows))

        self.assertEqual(output["alignment"]["status"], "inconclusive_input_mismatch")
        missing = [row for row in output["alignment"]["rows"] if row["status"] == "missing_massive"]
        self.assertEqual([row["date"] for row in missing], ["2026-06-25"])

    def test_phase_four_uses_existing_indicators_and_flags_default_macd_history(self) -> None:
        phase_three = self._freeze_massive()
        output = BackendIndicatorPipeline(self.store).run(
            self.spec,
            phase_three["massive_run_path"],
        )

        result = output["result"]
        self.assertEqual(result["summary"]["rsi"]["status"], "calculated")
        self.assertEqual(result["summary"]["aroon"]["status"], "calculated")
        self.assertEqual(result["summary"]["ema"]["status"], "calculated")
        self.assertEqual(result["summary"]["macd"]["status"], "insufficient_data")
        macd_rows = [row for row in result["rows"] if row["indicator"] == "macd"]
        self.assertEqual({row["component"] for row in macd_rows}, {"macd", "macd_signal", "macd_hist"})
        self.assertTrue(all(row["available_candles"] == 30 for row in macd_rows))
        calculated = [row for row in result["rows"] if row["status"] == "calculated"]
        self.assertTrue(calculated)
        self.assertTrue(all("2026-06-21" <= row["timestamp"][:10] <= "2026-06-30" for row in calculated))

    def test_phase_four_calculates_all_macd_components_with_short_test_periods(self) -> None:
        custom_spec = ValidationSpec(
            symbol="BTC/USD",
            indicators=IndicatorParameters(
                rsi_length=2,
                aroon_length=2,
                macd_fast=2,
                macd_slow=3,
                macd_signal=2,
                ema_length=2,
            ),
        )
        custom_store = FixtureStore(self.root / "custom")
        twelve_path = freeze_twelve(custom_store, custom_spec)
        transport = FakeMassiveTransport(massive_payload())
        client = MassiveDataClient("test-key", request_get=transport)
        phase_three = MassiveValidationPipeline(
            MassiveCandleFetcher(client),
            custom_store,
        ).freeze_and_audit(custom_spec, twelve_path)

        result = BackendIndicatorPipeline(custom_store).run(
            custom_spec,
            phase_three["massive_run_path"],
        )["result"]
        self.assertEqual(result["summary"]["macd"], {"status": "calculated", "rows": 30})
        for indicator in ("rsi", "aroon", "macd", "ema"):
            self.assertEqual(result["summary"][indicator]["status"], "calculated")


if __name__ == "__main__":
    unittest.main()

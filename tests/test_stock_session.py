"""Tests for TradingView-compatible stock intraday session filtering."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from core.config import settings
from services import market_data
from services.stock_session import (
    SESSION_POLICY_PROVIDER_DEFAULT,
    SESSION_POLICY_TRADINGVIEW_REGULAR,
    apply_stock_session_policy,
    filter_tradingview_regular_candles,
    is_payload_session_compatible,
    is_tradingview_regular_session_bar,
)


def _candle(unix_seconds: int, close: float = 100.0) -> dict:
    return {
        "time": unix_seconds,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }


class TradingViewRegularSessionBarTests(unittest.TestCase):
    def test_july_20_zbio_regular_last_hour_is_kept(self):
        # 2026-07-20 19:00 UTC = 15:00 EDT (regular)
        self.assertTrue(is_tradingview_regular_session_bar(1784574000))

    def test_july_20_zbio_after_hours_bars_are_rejected(self):
        # 2026-07-20 20:00 UTC = 16:00 EDT (after-hours open)
        self.assertFalse(is_tradingview_regular_session_bar(1784577600))
        # 2026-07-20 22:00 UTC = 18:00 EDT (after-hours)
        self.assertFalse(is_tradingview_regular_session_bar(1784584800))

    def test_premarket_bar_start_is_rejected(self):
        # 2026-07-20 12:00 UTC = 08:00 EDT
        self.assertFalse(is_tradingview_regular_session_bar(1784548800))

    def test_regular_midday_bar_is_kept(self):
        # 2026-07-20 14:00 UTC = 10:00 EDT
        self.assertTrue(is_tradingview_regular_session_bar(1784556000))


class ZbioJuly20FilterTests(unittest.TestCase):
    def test_massive_zbio_sequence_matches_tradingview_cutoff(self):
        candles = [
            _candle(1784570400, 31.265),
            _candle(1784574000, 30.68),
            _candle(1784577600, 32.2),
            _candle(1784584800, 31.3),
        ]
        filtered = filter_tradingview_regular_candles(candles, "1h")

        self.assertEqual([item["time"] for item in filtered], [1784570400, 1784574000])
        self.assertEqual(filtered[-1]["close"], 30.68)
        self.assertEqual(filtered[-1]["time"], 1784574000)

    def test_crypto_symbols_are_not_filtered(self):
        candles = [
            _candle(1784577600, 1.0),
            _candle(1784584800, 2.0),
        ]
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            result = apply_stock_session_policy(candles, "BTC-USD", "1h")
        self.assertEqual(result, candles)


class SessionPolicyCacheCompatibilityTests(unittest.TestCase):
    def test_legacy_cache_without_policy_is_incompatible_with_tradingview_regular(self):
        payload = {
            "symbol": "ZBIO",
            "candles_provider": "massive",
            "candles": [_candle(1784584800)],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertFalse(is_payload_session_compatible(payload, "ZBIO", "1h"))

    def test_tagged_cache_matches_expected_policy(self):
        payload = {
            "symbol": "ZBIO",
            "candles_provider": "massive",
            "session_policy": SESSION_POLICY_TRADINGVIEW_REGULAR,
            "candles": [_candle(1784574000)],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertTrue(is_payload_session_compatible(payload, "ZBIO", "1h"))

    def test_provider_default_policy_matches_legacy_cache(self):
        payload = {
            "symbol": "ZBIO",
            "candles_provider": "massive",
            "candles": [_candle(1784584800)],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_PROVIDER_DEFAULT):
            self.assertTrue(is_payload_session_compatible(payload, "ZBIO", "1h"))


class RequestPolygonCandlesSessionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_polygon_candles_applies_tradingview_regular_filter(self):
        rows = [
            {"t": 1784574000000, "o": 31.26, "h": 31.43, "l": 30.38, "c": 30.68, "v": 100.0},
            {"t": 1784577600000, "o": 30.7, "h": 32.2, "l": 30.7, "c": 32.2, "v": 100.0},
            {"t": 1784584800000, "o": 31.86, "h": 32.3436, "l": 31.3, "c": 31.3, "v": 935.0},
        ]

        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR), patch.object(
            market_data.integration_runtime,
            "is_enabled",
            return_value=True,
        ), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="test-key",
        ), patch.object(
            market_data,
            "_download_polygon_rows",
            AsyncMock(return_value=rows),
        ) as download_mock:
            payload = await market_data.request_polygon_candles("ZBIO", "1h", candles_limit=1)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["session_policy"], SESSION_POLICY_TRADINGVIEW_REGULAR)
        self.assertEqual(len(payload["candles"]), 1)
        self.assertEqual(payload["candles"][-1]["time"], 1784574000)
        self.assertEqual(download_mock.await_args.args[2], 3)

    async def test_request_polygon_candles_keeps_provider_default_behavior(self):
        rows = [
            {"t": 1784584800000, "o": 31.86, "h": 32.3436, "l": 31.3, "c": 31.3, "v": 935.0},
        ]

        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_PROVIDER_DEFAULT), patch.object(
            market_data.integration_runtime,
            "is_enabled",
            return_value=True,
        ), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="test-key",
        ), patch.object(
            market_data,
            "_download_polygon_rows",
            AsyncMock(return_value=rows),
        ) as download_mock:
            payload = await market_data.request_polygon_candles("ZBIO", "1h", candles_limit=1)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["session_policy"], SESSION_POLICY_PROVIDER_DEFAULT)
        self.assertEqual(payload["candles"][-1]["time"], 1784584800)
        self.assertEqual(download_mock.await_args.args[2], 1)


if __name__ == "__main__":
    unittest.main()

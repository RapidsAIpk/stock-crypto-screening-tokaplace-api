"""Focused tests for the unified timeframe pipeline: one parser used by every
stage (provider mapping, duration, aggregation source selection, closure,
freshness, refresh scheduling), a real-bucket-end closure/freshness
resolver (not a fixed start+timeframe_seconds guess), cache/version
isolation for session-anchored candles, and graceful validation of
malformed provider data and unsupported timeframes.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from core.config import settings
from services import market_data
from services.stock_session import (
    SESSION_POLICY_PROVIDER_DEFAULT,
    SESSION_POLICY_TRADINGVIEW_REGULAR,
    US_EASTERN,
)


def _et(year, month, day, hour, minute):
    return int(datetime(year, month, day, hour, minute, tzinfo=US_EASTERN).timestamp())


def _utc(year, month, day, hour=0, minute=0):
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp())


# =========================================================
# 1. UNIFIED PARSER
# =========================================================

class UnifiedTimeframeParserTests(unittest.TestCase):
    def test_required_timeframe_list_all_parse(self):
        expected = {
            "1m": (1, "m"),
            "3m": (3, "m"),
            "5m": (5, "m"),
            "15m": (15, "m"),
            "30m": (30, "m"),
            "45m": (45, "m"),
            "1h": (1, "h"),
            "2h": (2, "h"),
            "4h": (4, "h"),
            "1D": (1, "d"),
            "1W": (1, "w"),
            "1M": (1, "mo"),
        }
        for tf, parsed in expected.items():
            with self.subTest(timeframe=tf):
                self.assertEqual(market_data.parse_timeframe_spec(tf), parsed)

    def test_lowercase_m_is_minute_uppercase_m_is_month(self):
        self.assertEqual(market_data.parse_timeframe_spec("1m"), (1, "m"))
        self.assertEqual(market_data.parse_timeframe_spec("1M"), (1, "mo"))
        self.assertEqual(market_data.parse_timeframe_spec("3m"), (3, "m"))
        self.assertEqual(market_data.parse_timeframe_spec("3M"), (3, "mo"))

    def test_future_arbitrary_minute_hour_day_week_month_values_parse(self):
        for tf, expected in [
            ("7m", (7, "m")), ("11h", (11, "h")), ("6d", (6, "d")),
            ("2w", (2, "w")), ("5mo", (5, "mo")), ("2 hours", (2, "h")),
            ("3Months", (3, "mo")), ("1week", (1, "w")),
        ]:
            with self.subTest(timeframe=tf):
                self.assertEqual(market_data.parse_timeframe_spec(tf), expected)

    def test_malformed_timeframes_are_rejected_not_defaulted(self):
        for tf in ["banana", "", None, "0m", "-1h", "m5", "1", 42]:
            with self.subTest(timeframe=tf):
                self.assertIsNone(market_data.parse_timeframe_spec(tf))

    def test_validate_timeframe_raises_clear_error_for_unsupported_input(self):
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            market_data.validate_timeframe("banana")

    def test_canonicalize_timeframe_merges_equivalent_spellings(self):
        self.assertEqual(market_data.canonicalize_timeframe("1D"), "1day")
        self.assertEqual(market_data.canonicalize_timeframe("1d"), "1day")
        self.assertEqual(market_data.canonicalize_timeframe("1day"), "1day")
        self.assertEqual(market_data.canonicalize_timeframe("1M"), "1mo")
        self.assertEqual(market_data.canonicalize_timeframe("1mo"), "1mo")
        self.assertEqual(market_data.canonicalize_timeframe("1W"), "1w")
        self.assertEqual(market_data.canonicalize_timeframe("1w"), "1w")

    def test_map_timeframe_for_polygon_uses_the_same_parsed_representation(self):
        self.assertEqual(market_data.map_timeframe_for_polygon("1M"), (1, "month"))
        self.assertEqual(market_data.map_timeframe_for_polygon("1m"), (1, "minute"))
        self.assertEqual(market_data.map_timeframe_for_polygon("2h"), (2, "hour"))
        with self.assertRaises(ValueError):
            market_data.map_timeframe_for_polygon("garbage")

    def test_map_timeframe_for_binance_gracefully_returns_none_for_garbage(self):
        # Binance mapping must not raise for unparseable OR merely
        # unsupported-by-Binance timeframes - both are legitimate "no
        # mapping" outcomes, not a validation failure.
        self.assertIsNone(market_data.map_timeframe_for_binance("garbage"))
        self.assertIsNone(market_data.map_timeframe_for_binance("45m"))
        self.assertEqual(market_data.map_timeframe_for_binance("1h"), "1h")


# =========================================================
# 2. UNIVERSAL BUCKET-CLOSE RESOLVER
# =========================================================

class TimeframeBucketCloseUnixTests(unittest.TestCase):
    def test_crypto_intraday_uses_fixed_duration_not_session_anchoring(self):
        start = _utc(2026, 7, 20, 15, 45)  # arbitrary time, no RTH relevance for crypto
        close = market_data.timeframe_bucket_close_unix(start, "1h", symbol="BTC-USD")
        self.assertEqual(close, start + 3600)

    def test_stock_intraday_provider_default_policy_uses_fixed_duration(self):
        start = _utc(2026, 7, 20, 15, 45)
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_PROVIDER_DEFAULT):
            close = market_data.timeframe_bucket_close_unix(start, "1h", symbol="AAPL")
        self.assertEqual(close, start + 3600)

    def test_stock_intraday_rth_policy_caps_final_bucket_at_session_close(self):
        from services.stock_session import US_EASTERN

        start = int(datetime(2026, 7, 20, 15, 30, tzinfo=US_EASTERN).timestamp())
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            close = market_data.timeframe_bucket_close_unix(start, "1h", symbol="AAPL")
        expected_close = int(datetime(2026, 7, 20, 16, 0, tzinfo=US_EASTERN).timestamp())
        self.assertEqual(close, expected_close)
        self.assertNotEqual(close, start + 3600)

    def test_native_daily_candle_is_already_closed(self):
        start = _utc(2026, 7, 20)
        close = market_data.timeframe_bucket_close_unix(
            start, "1day", symbol="AAPL", candles_provider="massive",
        )
        self.assertEqual(close, start)

    def test_weekly_close_is_the_real_iso_week_boundary_not_seven_fixed_days(self):
        # Bucket "starts" mid-week (Wednesday) - the close must still be the
        # NEXT Monday (real ISO week boundary), not start+7*86400.
        start = _utc(2026, 7, 22)  # Wednesday
        close = market_data.timeframe_bucket_close_unix(start, "1w", symbol="AAPL")
        self.assertEqual(close, _utc(2026, 7, 27))  # following Monday
        self.assertNotEqual(close, start + 7 * 86400)

    def test_monthly_close_respects_a_short_28_day_february(self):
        start = _utc(2026, 2, 1)
        close = market_data.timeframe_bucket_close_unix(start, "1mo", symbol="AAPL")
        self.assertEqual(close, _utc(2026, 3, 1))
        self.assertNotEqual(close, start + 30 * 86400)  # fixed-30-day would be wrong (28-day Feb)

    def test_monthly_close_respects_a_long_31_day_january(self):
        start = _utc(2026, 1, 1)
        close = market_data.timeframe_bucket_close_unix(start, "1mo", symbol="AAPL")
        self.assertEqual(close, _utc(2026, 2, 1))
        self.assertNotEqual(close, start + 30 * 86400)  # fixed-30-day would be wrong (31-day Jan)

    def test_unsupported_timeframe_raises(self):
        with self.assertRaises(ValueError):
            market_data.timeframe_bucket_close_unix(0, "garbage", symbol="AAPL")


class ForminVsCompletedCandleTests(unittest.TestCase):
    def test_monthly_candle_is_still_forming_on_january_31st(self):
        """A fixed 30-day duration would mark a January candle closed a day
        early (Jan has 31 days); the real calendar boundary must not.
        """
        candles = [{"time": _utc(2026, 1, 1), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        with patch.object(market_data.time, "time", return_value=_utc(2026, 1, 31)):
            payload = market_data._build_market_data_payload("AAPL", candles, "1mo")
        self.assertIs(payload["candles"][-1]["is_closed"], False)

    def test_monthly_candle_closes_once_february_begins(self):
        candles = [{"time": _utc(2026, 1, 1), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        with patch.object(market_data.time, "time", return_value=_utc(2026, 2, 1)):
            payload = market_data._build_market_data_payload("AAPL", candles, "1mo")
        self.assertNotIn("is_closed", payload["candles"][-1])

    def test_weekly_candle_is_forming_until_the_following_monday(self):
        candles = [{"time": _utc(2026, 7, 20), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        with patch.object(market_data.time, "time", return_value=_utc(2026, 7, 26)):
            payload = market_data._build_market_data_payload("AAPL", candles, "1w")
        self.assertIs(payload["candles"][-1]["is_closed"], False)

    def test_crypto_hourly_candle_completed_vs_forming(self):
        candles = [{"time": 1_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        with patch.object(market_data.time, "time", return_value=1_000_000 + 3599):
            forming = market_data._build_market_data_payload("BTC-USD", candles, "1h")
        with patch.object(market_data.time, "time", return_value=1_000_000 + 3600):
            closed = market_data._build_market_data_payload("BTC-USD", candles, "1h")
        self.assertIs(forming["candles"][-1]["is_closed"], False)
        self.assertNotIn("is_closed", closed["candles"][-1])


# =========================================================
# 3. CACHE / ALIGNMENT-VERSION ISOLATION
# =========================================================

class CandleAlignmentVersionCacheTests(unittest.TestCase):
    def test_build_market_data_payload_tags_the_current_alignment_version(self):
        candles = [{"time": 1_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
        payload = market_data._build_market_data_payload("BTC-USD", candles, "1h")
        self.assertEqual(payload["candle_alignment_version"], market_data.CANDLE_ALIGNMENT_VERSION)

    def test_session_anchored_symbol_rejects_a_payload_missing_the_version_tag(self):
        legacy_payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candles": [{"time": 1_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
            # no candle_alignment_version - built before this fix existed
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertFalse(market_data.is_payload_compatible_for_fetch(legacy_payload, "AAPL", "1h"))

    def test_session_anchored_symbol_accepts_a_payload_with_matching_version(self):
        payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candle_alignment_version": market_data.CANDLE_ALIGNMENT_VERSION,
            # A genuinely session-anchored 1h bucket start (09:30 ET) -
            # compatibility requires both the version tag AND a boundary-
            # correct timestamp.
            "candles": [{"time": _et(2026, 7, 20, 9, 30), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertTrue(market_data.is_payload_compatible_for_fetch(payload, "AAPL", "1h"))

    def test_session_anchored_symbol_rejects_misaligned_timestamps_even_with_matching_version(self):
        # The regression this guards against: a payload tagged with the
        # current version but whose candle times were built by a buggy
        # aggregator (e.g. copied from an unaligned provider row) must still
        # be rejected - the version tag alone is not sufficient proof.
        payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candle_alignment_version": market_data.CANDLE_ALIGNMENT_VERSION,
            "candles": [
                {"time": _et(2026, 7, 20, 9, 42), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            ],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertFalse(market_data.is_payload_compatible_for_fetch(payload, "AAPL", "1h"))

    def test_non_session_anchored_payload_is_unaffected_by_missing_version(self):
        # Crypto and calendar (1day) payloads never go through session
        # anchoring, so a missing version tag must not invalidate them - the
        # version check is scoped to exactly the affected blast radius.
        crypto_payload = {
            "symbol": "BTC-USD",
            "candles_provider": "massive",
            "candles": [{"time": 1_000_000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        }
        self.assertTrue(market_data.is_payload_compatible_for_fetch(crypto_payload, "BTC-USD", "1h"))

        daily_payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candles": [{"time": _utc(2026, 7, 20), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertTrue(
                market_data.is_payload_compatible_for_fetch(daily_payload, "AAPL", "1day")
            )


# =========================================================
# 4. GRACEFUL VALIDATION OF MALFORMED PROVIDER DATA
# =========================================================

class MalformedProviderDataValidationTests(unittest.TestCase):
    def test_normalize_polygon_rows_rejects_low_greater_than_open(self):
        rows = [
            {"t": 1000, "o": 5.0, "h": 6.0, "l": 5.5, "c": 5.2, "v": 10},  # low > open: invalid
            {"t": 2000, "o": 2.0, "h": 2.5, "l": 1.5, "c": 2.2, "v": 10},  # valid
        ]
        candles = market_data.normalize_polygon_rows(rows)
        self.assertEqual([c["time"] for c in candles], [2])

    def test_normalize_polygon_rows_rejects_high_less_than_close(self):
        rows = [
            {"t": 1000, "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.5, "v": 10},  # high < close: invalid
        ]
        self.assertEqual(market_data.normalize_polygon_rows(rows), [])

    def test_normalize_polygon_rows_sorts_and_dedupes_out_of_order_duplicate_rows(self):
        rows = [
            {"t": 3000, "o": 3.0, "h": 3.5, "l": 2.5, "c": 3.2, "v": 10},
            {"t": 1000, "o": 1.0, "h": 1.5, "l": 0.5, "c": 1.2, "v": 10},
            {"t": 3000, "o": 3.0, "h": 3.9, "l": 2.5, "c": 3.8, "v": 20},  # duplicate time, last wins
        ]
        candles = market_data.normalize_polygon_rows(rows)
        self.assertEqual([c["time"] for c in candles], [1, 3])
        self.assertEqual(candles[-1]["close"], 3.8)

    def test_normalize_binance_rows_rejects_malformed_ohlc(self):
        row = [1_700_000_000_000, "5.0", "4.0", "1.0", "2.0", "10", 1_700_003_599_999]  # high < open
        self.assertEqual(market_data.normalize_binance_rows([row]), [])

    def test_missing_volume_defaults_to_zero_safely(self):
        rows = [{"t": 1000, "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1}]  # no "v" key
        candles = market_data.normalize_polygon_rows(rows)
        self.assertEqual(candles[0]["volume"], 0.0)


# =========================================================
# 5. ENTRY-POINT VALIDATION / DIAGNOSTICS (no silent 1day fallback)
# =========================================================

class EntryPointDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_massive_candles_rejects_invalid_timeframe_without_provider_call(self):
        with patch.object(
            market_data, "request_polygon_candles", AsyncMock(),
        ) as polygon_mock, self.assertLogs("services.market_data", level="WARNING") as log_ctx:
            result = await market_data.request_massive_candles("AAPL", "banana")

        self.assertIsNone(result)
        polygon_mock.assert_not_awaited()
        self.assertTrue(any("Unsupported timeframe" in message for message in log_ctx.output))

    async def test_request_binance_candles_rejects_invalid_timeframe(self):
        result = await market_data.request_binance_candles("BTC-USD", "not-a-timeframe")
        self.assertIsNone(result)

    async def test_fetch_batches_rejects_invalid_timeframe_gracefully(self):
        results = await market_data.fetch_batches(["AAPL"], "not-a-timeframe")
        self.assertEqual(results, [])

    async def test_fetch_live_data_rejects_invalid_timeframe_gracefully(self):
        results = await market_data.fetch_live_data(["AAPL"], "not-a-timeframe")
        self.assertEqual(results, [])

    async def test_fetch_batches_canonicalizes_timeframe_before_dispatch(self):
        with patch.object(
            market_data, "request_massive_candles", AsyncMock(return_value=None),
        ) as candles_mock:
            await market_data.fetch_batches(["AAPL"], "1H", candles_limit=5)

        # "1H" and "1h" must resolve to the exact same canonical timeframe.
        self.assertEqual(candles_mock.await_args.args[1], "1h")


if __name__ == "__main__":
    unittest.main()

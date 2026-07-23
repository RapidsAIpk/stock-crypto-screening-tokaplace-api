"""Regression tests for the candle-timestamp anchoring bug: RTH stock
intraday candles were coming back with minute offsets that drift from the
provider's fetch-window start (e.g. 13:42/14:42/.../19:42 UTC) instead of
the true 09:30-ET-session-anchored boundaries (13:30/14:30/.../19:30 UTC on
a summer/EDT trading day). The regression was that
aggregate_session_anchored_candles copied the SOURCE candle's own timestamp
into the bucket instead of computing the bucket boundary independently via
resolve_session_bucket_start - so any provider misalignment (or scan-time-
dependent fetch window) propagated straight into the stored candle "time".

These tests cover multiple stocks and crypto across
1m, 3m, 5m, 15m, 30m, 45m, 1h, 2h, 4h, 1D, 1W, 1M.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from core.config import settings
from services import market_data
from services.stock_session import (
    SESSION_POLICY_TRADINGVIEW_REGULAR,
    US_EASTERN,
    resolve_session_bucket_start,
)


def _et(year, month, day, hour, minute):
    return int(datetime(year, month, day, hour, minute, tzinfo=US_EASTERN).timestamp())


def _utc(year, month, day, hour, minute):
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp())


def _row(candle_time, close=100.0):
    return {"time": candle_time, "open": close - 0.5, "high": close + 0.5, "low": close - 1.0, "close": close, "volume": 10.0}


def _polygon_row(timestamp_ms, close=100.0):
    return {"t": timestamp_ms, "o": close - 0.5, "h": close + 0.5, "l": close - 1.0, "c": close, "v": 10.0}


# =========================================================
# 1. THE EXACT REPORTED BUG: 13:42/14:42/.../19:42 UTC -> 13:30/.../19:30 UTC
# =========================================================

class ReportedRegressionExactValuesTests(unittest.TestCase):
    """2026-07-20 is a summer (EDT, UTC-4) Monday: 13:30 UTC == 09:30 ET."""

    def test_misaligned_hourly_source_resolves_to_session_anchored_boundaries(self):
        misaligned_utc = [
            _utc(2026, 7, 20, 13, 42),
            _utc(2026, 7, 20, 14, 42),
            _utc(2026, 7, 20, 15, 42),
            _utc(2026, 7, 20, 16, 42),
            _utc(2026, 7, 20, 17, 42),
            _utc(2026, 7, 20, 18, 42),
            _utc(2026, 7, 20, 19, 42),
        ]
        expected_utc = [
            _utc(2026, 7, 20, 13, 30),
            _utc(2026, 7, 20, 14, 30),
            _utc(2026, 7, 20, 15, 30),
            _utc(2026, 7, 20, 16, 30),
            _utc(2026, 7, 20, 17, 30),
            _utc(2026, 7, 20, 18, 30),
            _utc(2026, 7, 20, 19, 30),
        ]
        corrected = [resolve_session_bucket_start(t, 60) for t in misaligned_utc]
        self.assertEqual(corrected, expected_utc)
        # Sanity: the ET wall-clock boundaries really are 09:30, 10:30, ... 15:30.
        self.assertEqual(expected_utc[0], _et(2026, 7, 20, 9, 30))
        self.assertEqual(expected_utc[-1], _et(2026, 7, 20, 15, 30))

    def test_boundary_is_independent_of_which_minute_within_the_bucket_the_source_lands_on(self):
        # Whether the provider's row happens to land at :30, :42, :05 or :59
        # past the hour, every timestamp inside [13:30, 14:30) UTC must
        # resolve to the same 13:30 UTC bucket.
        target = _utc(2026, 7, 20, 13, 30)
        for minute in (30, 35, 42, 50, 59):
            with self.subTest(minute=minute):
                source = _utc(2026, 7, 20, 13, minute)
                self.assertEqual(resolve_session_bucket_start(source, 60), target)


# =========================================================
# 2. BOUNDARIES ARE INDEPENDENT OF SCAN/REQUEST TIME
# =========================================================

class ScanTimeIndependenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_at_1942_utc_still_produces_the_correct_session_bucket(self):
        """A scan launched at 19:42 UTC must not leak its own clock minute
        into the candle it returns - the classic bug pattern was the fetch
        window trailing "now", so the misalignment tracked whatever minute
        the scan happened to run at.
        """
        misaligned_rows = [_polygon_row(_utc(2026, 7, 20, 13, 42) * 1000)]

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR,
        ), patch.object(
            market_data.integration_runtime, "is_enabled", return_value=True,
        ), patch.object(
            market_data, "_polygon_api_key", return_value="token",
        ), patch.object(
            market_data, "_download_polygon_rows", AsyncMock(return_value=misaligned_rows),
        ), patch.object(
            market_data.time, "time", return_value=_utc(2026, 7, 20, 19, 42),
        ):
            payload = await market_data.request_massive_candles("AAPL", "1h", candles_limit=1)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["candles"][-1]["time"], _utc(2026, 7, 20, 13, 30))

    async def test_two_scans_at_different_clock_minutes_agree_on_the_same_bucket(self):
        misaligned_rows = [_polygon_row(_utc(2026, 7, 20, 13, 47) * 1000)]

        async def _fetch_at(scan_time):
            with patch.object(
                settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR,
            ), patch.object(
                market_data.integration_runtime, "is_enabled", return_value=True,
            ), patch.object(
                market_data, "_polygon_api_key", return_value="token",
            ), patch.object(
                market_data, "_download_polygon_rows", AsyncMock(return_value=misaligned_rows),
            ), patch.object(
                market_data.time, "time", return_value=scan_time,
            ):
                return await market_data.request_massive_candles("AAPL", "1h", candles_limit=1)

        payload_a = await _fetch_at(_utc(2026, 7, 20, 14, 3))
        payload_b = await _fetch_at(_utc(2026, 7, 20, 20, 55))

        self.assertEqual(payload_a["candles"][-1]["time"], payload_b["candles"][-1]["time"])
        self.assertEqual(payload_a["candles"][-1]["time"], _utc(2026, 7, 20, 13, 30))


# =========================================================
# 3. ALL SUPPORTED INTRADAY TIMEFRAMES SELF-CORRECT, NOT JUST 1h
# =========================================================

class UniversalIntradayCorrectionTests(unittest.TestCase):
    def test_every_required_intraday_timeframe_resolves_a_boundary_from_a_misaligned_source(self):
        # A source landing 7 minutes into whatever bucket it should belong
        # to must resolve back to the clean session-anchored start, for
        # every timeframe the frontend supports (and future custom ones).
        session_open = _et(2026, 7, 20, 9, 30)
        for timeframe, minutes in [
            ("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15), ("30m", 30),
            ("45m", 45), ("1h", 60), ("2h", 120), ("4h", 240), ("90m", 90),
        ]:
            with self.subTest(timeframe=timeframe):
                offset_minutes = min(minutes - 1, 7) if minutes > 1 else 0
                misaligned = session_open + offset_minutes * 60
                corrected = resolve_session_bucket_start(misaligned, minutes)
                self.assertEqual(corrected, session_open)

    def test_1m_3m_5m_15m_30m_now_route_through_the_same_self_correcting_plan_as_1h_4h(self):
        for timeframe in ("1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "4h"):
            with self.subTest(timeframe=timeframe):
                self.assertIsNotNone(market_data._stock_session_anchor_source_plan(timeframe))


# =========================================================
# 4. SESSION SEMANTICS STILL HOLD (DST, pre/after-hours, no cross-day, final bucket)
# =========================================================

class SessionSemanticsStillHoldTests(unittest.TestCase):
    def test_summer_edt_and_winter_est_both_anchor_to_local_0930(self):
        summer_source = _utc(2026, 7, 20, 13, 47)   # EDT: UTC-4
        winter_source = _utc(2026, 1, 20, 14, 47)   # EST: UTC-5
        self.assertEqual(resolve_session_bucket_start(summer_source, 60), _et(2026, 7, 20, 9, 30))
        self.assertEqual(resolve_session_bucket_start(winter_source, 60), _et(2026, 1, 20, 9, 30))

    def test_premarket_and_afterhours_rows_are_still_excluded_after_rebucketing(self):
        from services.stock_session import aggregate_session_anchored_candles

        premarket = _row(_et(2026, 7, 20, 8, 0))
        regular = _row(_et(2026, 7, 20, 9, 33))
        afterhours = _row(_et(2026, 7, 20, 17, 0))
        aggregated = aggregate_session_anchored_candles([premarket, regular, afterhours], 5)
        self.assertEqual(len(aggregated), 1)
        self.assertEqual(aggregated[0]["time"], _et(2026, 7, 20, 9, 30))

    def test_candles_from_different_trading_dates_are_never_merged(self):
        from services.stock_session import aggregate_session_anchored_candles

        day_one = _row(_et(2026, 7, 20, 9, 33))
        day_two = _row(_et(2026, 7, 21, 9, 33))
        aggregated = aggregate_session_anchored_candles([day_one, day_two], 60)
        self.assertEqual(
            [c["time"] for c in aggregated],
            [_et(2026, 7, 20, 9, 30), _et(2026, 7, 21, 9, 30)],
        )

    def test_final_session_bucket_is_short_and_closes_at_1600(self):
        from services.stock_session import aggregate_session_anchored_candles, session_bucket_close_unix

        last_30m_candle = _row(_et(2026, 7, 20, 15, 33))  # slightly misaligned, still last of day
        aggregated = aggregate_session_anchored_candles([last_30m_candle], 60)
        self.assertEqual(aggregated[-1]["time"], _et(2026, 7, 20, 15, 30))
        self.assertEqual(
            session_bucket_close_unix(aggregated[-1]["time"], 60),
            _et(2026, 7, 20, 16, 0),
        )


# =========================================================
# 5. OHLCV AGGREGATION CORRECTNESS SURVIVES REBUCKETING
# =========================================================

class OhlcvAggregationSurvivesRebucketingTests(unittest.TestCase):
    def test_open_high_low_close_volume_combine_correctly_despite_misaligned_source(self):
        from services.stock_session import aggregate_session_anchored_candles

        candles = [
            {"time": _et(2026, 7, 20, 9, 37), "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100.0},
            {"time": _et(2026, 7, 20, 10, 7), "open": 10.2, "high": 11.0, "low": 10.0, "close": 10.8, "volume": 200.0},
        ]
        aggregated = aggregate_session_anchored_candles(candles, 60)
        self.assertEqual(len(aggregated), 1)
        bucket = aggregated[0]
        self.assertEqual(bucket["time"], _et(2026, 7, 20, 9, 30))
        self.assertEqual(bucket["open"], 10.0)
        self.assertEqual(bucket["close"], 10.8)
        self.assertEqual(bucket["high"], 11.0)
        self.assertEqual(bucket["low"], 9.5)
        self.assertEqual(bucket["volume"], 300.0)


# =========================================================
# 6. CACHE REJECTION FOR MISALIGNED TIMESTAMPS
# =========================================================

class CacheRejectsMisalignedTimestampsTests(unittest.TestCase):
    def test_cache_rejects_a_payload_whose_candle_time_is_the_old_buggy_1342_style_offset(self):
        payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candle_alignment_version": market_data.CANDLE_ALIGNMENT_VERSION,
            "candles": [_row(_utc(2026, 7, 20, 13, 42))],  # the exact buggy pattern
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertFalse(market_data.is_payload_compatible_for_fetch(payload, "AAPL", "1h"))

    def test_cache_accepts_a_payload_with_the_corrected_1330_boundary(self):
        payload = {
            "symbol": "AAPL",
            "candles_provider": "massive",
            "session_policy": "tradingview_regular",
            "candle_alignment_version": market_data.CANDLE_ALIGNMENT_VERSION,
            "candles": [_row(_utc(2026, 7, 20, 13, 30))],
        }
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", SESSION_POLICY_TRADINGVIEW_REGULAR):
            self.assertTrue(market_data.is_payload_compatible_for_fetch(payload, "AAPL", "1h"))


# =========================================================
# 7. CRYPTO AND EXTENDED-HOURS BEHAVIOR ARE UNCHANGED
# =========================================================

class CryptoUnchangedTests(unittest.IsolatedAsyncioTestCase):
    def test_crypto_symbols_never_get_a_session_anchor_plan(self):
        for timeframe in ("1m", "3m", "5m", "15m", "30m", "45m", "1h", "2h", "4h"):
            with self.subTest(timeframe=timeframe):
                self.assertIsNone(market_data._session_anchor_plan_for_symbol("BTC-USD", timeframe))

    def test_crypto_candle_time_is_preserved_exactly_as_the_provider_returned_it(self):
        # Even an "off" clock-minute timestamp must pass through untouched
        # for crypto - continuous markets have no RTH boundary to anchor to.
        arbitrary_time = _utc(2026, 7, 20, 13, 47)
        candles = [_row(arbitrary_time)]
        payload = market_data._build_market_data_payload("BTC-USD", candles, "1h")
        self.assertEqual(payload["candles"][-1]["time"], arbitrary_time)

    async def test_crypto_cache_payload_never_requires_the_alignment_version_tag(self):
        payload = {
            "symbol": "BTC-USD",
            "candles_provider": "massive",
            "candles": [_row(_utc(2026, 7, 20, 13, 47))],
        }
        self.assertTrue(market_data.is_payload_compatible_for_fetch(payload, "BTC-USD", "1h"))


# =========================================================
# 8. 1D / 1W / 1M UNAFFECTED (calendar grouping, not clock-offset prone)
# =========================================================

class DailyWeeklyMonthlyUnaffectedTests(unittest.TestCase):
    def test_daily_weekly_monthly_never_get_a_session_anchor_plan(self):
        for timeframe in ("1day", "1D", "1w", "1W", "1mo", "1M"):
            with self.subTest(timeframe=timeframe):
                self.assertIsNone(market_data._session_anchor_plan_for_symbol("AAPL", timeframe))


if __name__ == "__main__":
    unittest.main()

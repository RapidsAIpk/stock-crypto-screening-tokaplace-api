"""Focused tests for TradingView RTH candle-alignment: session-anchored
intraday aggregation (1h/4h/custom timeframes built from 30m/15m/5m/1m).
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from core.config import settings
from services import market_data
from services.stock_session import (
    US_EASTERN,
    aggregate_session_anchored_candles,
    session_bucket_close_unix,
)


def _et_unix(year, month, day, hour, minute):
    return int(datetime(year, month, day, hour, minute, tzinfo=US_EASTERN).timestamp())


def _session_native_candles(year, month, day, step_minutes, count, base_price=100.0):
    """Build `count` session-anchored native candles starting at 09:30 ET,
    `step_minutes` apart, with distinct OHLCV per candle so aggregation math
    is easy to verify.
    """
    candles = []
    for i in range(count):
        minute_offset = 30 + i * step_minutes
        hour = 9 + minute_offset // 60
        minute = minute_offset % 60
        candles.append(
            {
                "time": _et_unix(year, month, day, hour, minute),
                "open": base_price + i,
                "high": base_price + i + 0.5,
                "low": base_price + i - 0.5,
                "close": base_price + i + 1,
                "volume": 10.0 + i,
            }
        )
    return candles


class SessionAnchorSourcePlanTests(unittest.TestCase):
    def test_native_1m_5m_15m_30m_self_rebucket_at_the_same_granularity(self):
        # The provider's own candle "time" is never trusted as already
        # anchored, so even native granularities are routed through a
        # (1:1 ratio) session-anchored rebucket rather than being skipped.
        for timeframe, minutes in (("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30)):
            with self.subTest(timeframe=timeframe):
                self.assertEqual(
                    market_data._stock_session_anchor_source_plan(timeframe),
                    (timeframe, minutes, minutes),
                )

    def test_1h_resolves_to_30m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("1h"),
            ("30m", 30, 60),
        )

    def test_4h_resolves_to_30m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("4h"),
            ("30m", 30, 240),
        )

    def test_custom_45m_resolves_to_15m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("45m"),
            ("15m", 15, 45),
        )

    def test_custom_90m_resolves_to_30m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("90m"),
            ("30m", 30, 90),
        )

    def test_custom_20m_resolves_to_5m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("20m"),
            ("5m", 5, 20),
        )

    def test_custom_7m_falls_back_to_1m_source(self):
        self.assertEqual(
            market_data._stock_session_anchor_source_plan("7m"),
            ("1m", 1, 7),
        )

    def test_1day_has_no_plan(self):
        self.assertIsNone(market_data._stock_session_anchor_source_plan("1day"))

    def test_crypto_symbol_never_gets_a_plan(self):
        self.assertIsNone(market_data._session_anchor_plan_for_symbol("BTC-USD", "1h"))

    def test_provider_default_policy_disables_the_plan(self):
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", "provider_default"):
            self.assertIsNone(market_data._session_anchor_plan_for_symbol("AAPL", "1h"))

    def test_tradingview_regular_policy_enables_the_plan_for_stocks(self):
        with patch.object(settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular"):
            self.assertEqual(
                market_data._session_anchor_plan_for_symbol("AAPL", "1h"),
                ("30m", 30, 60),
            )


class AggregateSessionAnchoredCandlesMathTests(unittest.TestCase):
    def test_1h_from_30m_builds_seven_bars_with_a_short_final_bar(self):
        candles = _session_native_candles(2026, 7, 20, 30, 13)
        aggregated = aggregate_session_anchored_candles(candles, 60)

        expected_times = [
            _et_unix(2026, 7, 20, hour, minute)
            for hour, minute in [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]
        ]
        self.assertEqual([candle["time"] for candle in aggregated], expected_times)

        # First bucket merges the 09:30 and 10:00 native bars.
        first = aggregated[0]
        self.assertEqual(first["open"], candles[0]["open"])
        self.assertEqual(first["close"], candles[1]["close"])
        self.assertEqual(first["high"], max(candles[0]["high"], candles[1]["high"]))
        self.assertEqual(first["low"], min(candles[0]["low"], candles[1]["low"]))
        self.assertEqual(first["volume"], candles[0]["volume"] + candles[1]["volume"])

        # Final bucket (15:30-16:00) is a lone, shorter 30-minute bar.
        last = aggregated[-1]
        self.assertEqual(last["open"], candles[-1]["open"])
        self.assertEqual(last["close"], candles[-1]["close"])
        self.assertEqual(last["high"], candles[-1]["high"])
        self.assertEqual(last["low"], candles[-1]["low"])
        self.assertEqual(last["volume"], candles[-1]["volume"])

    def test_4h_from_30m_builds_two_bars(self):
        candles = _session_native_candles(2026, 7, 20, 30, 13)
        aggregated = aggregate_session_anchored_candles(candles, 240)

        self.assertEqual(
            [candle["time"] for candle in aggregated],
            [_et_unix(2026, 7, 20, 9, 30), _et_unix(2026, 7, 20, 13, 30)],
        )

        first, second = aggregated
        first_source = candles[0:8]
        second_source = candles[8:13]

        self.assertEqual(first["open"], first_source[0]["open"])
        self.assertEqual(first["close"], first_source[-1]["close"])
        self.assertEqual(first["high"], max(c["high"] for c in first_source))
        self.assertEqual(first["low"], min(c["low"] for c in first_source))
        self.assertEqual(first["volume"], sum(c["volume"] for c in first_source))

        self.assertEqual(second["open"], second_source[0]["open"])
        self.assertEqual(second["close"], second_source[-1]["close"])
        self.assertEqual(second["high"], max(c["high"] for c in second_source))
        self.assertEqual(second["low"], min(c["low"] for c in second_source))
        self.assertEqual(second["volume"], sum(c["volume"] for c in second_source))

    def test_custom_45m_from_15m_has_a_short_final_thirty_minute_bar(self):
        candles = _session_native_candles(2026, 7, 20, 15, 26)
        aggregated = aggregate_session_anchored_candles(candles, 45)

        # 8 full 45-minute bars (3 x 15m each) plus a short 30-minute tail.
        self.assertEqual(len(aggregated), 9)
        self.assertEqual(aggregated[-1]["time"], _et_unix(2026, 7, 20, 15, 30))

        tail_source = candles[24:26]
        self.assertEqual(aggregated[-1]["open"], tail_source[0]["open"])
        self.assertEqual(aggregated[-1]["close"], tail_source[-1]["close"])
        self.assertEqual(aggregated[-1]["volume"], sum(c["volume"] for c in tail_source))

    def test_custom_90m_from_30m_has_a_short_final_bar(self):
        candles = _session_native_candles(2026, 7, 20, 30, 13)
        aggregated = aggregate_session_anchored_candles(candles, 90)

        self.assertEqual(
            [candle["time"] for candle in aggregated],
            [
                _et_unix(2026, 7, 20, 9, 30),
                _et_unix(2026, 7, 20, 11, 0),
                _et_unix(2026, 7, 20, 12, 30),
                _et_unix(2026, 7, 20, 14, 0),
                _et_unix(2026, 7, 20, 15, 30),
            ],
        )
        # The final 90-minute bucket only has one 30m source bar in it.
        self.assertEqual(aggregated[-1]["open"], candles[-1]["open"])
        self.assertEqual(aggregated[-1]["close"], candles[-1]["close"])

    def test_never_combines_different_trading_dates(self):
        day_one = _session_native_candles(2026, 7, 20, 30, 1)
        day_two = _session_native_candles(2026, 7, 21, 30, 1)
        aggregated = aggregate_session_anchored_candles(day_one + day_two, 60)

        self.assertEqual(
            [candle["time"] for candle in aggregated],
            [day_one[0]["time"], day_two[0]["time"]],
        )

    def test_drops_premarket_and_afterhours_candles(self):
        premarket = {
            "time": _et_unix(2026, 7, 20, 9, 0),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        }
        afterhours = {
            "time": _et_unix(2026, 7, 20, 16, 30),
            "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0,
        }
        regular = _session_native_candles(2026, 7, 20, 30, 2)

        aggregated = aggregate_session_anchored_candles([premarket] + regular + [afterhours], 60)

        self.assertEqual(len(aggregated), 1)
        self.assertEqual(aggregated[0]["time"], regular[0]["time"])
        self.assertEqual(aggregated[0]["volume"], regular[0]["volume"] + regular[1]["volume"])

    def test_dst_spring_forward_day_anchors_the_same_as_a_summer_day(self):
        # 2026 US DST begins 2026-03-08, so 2026-03-09 is the first regular
        # trading day observing the new (EDT) offset; 2026-03-06 is the last
        # one observing the old (EST) offset. Both must still anchor their
        # first bucket to local 09:30 despite the differing UTC offset.
        pre_dst = _session_native_candles(2026, 3, 6, 30, 1)
        post_dst = _session_native_candles(2026, 3, 9, 30, 1)

        aggregated_pre = aggregate_session_anchored_candles(pre_dst, 60)
        aggregated_post = aggregate_session_anchored_candles(post_dst, 60)

        self.assertEqual(aggregated_pre[0]["time"], _et_unix(2026, 3, 6, 9, 30))
        self.assertEqual(aggregated_post[0]["time"], _et_unix(2026, 3, 9, 9, 30))


class SessionBucketCloseUnixTests(unittest.TestCase):
    def test_full_bucket_closes_at_its_nominal_end(self):
        bucket_start = _et_unix(2026, 7, 20, 9, 30)
        self.assertEqual(session_bucket_close_unix(bucket_start, 60), _et_unix(2026, 7, 20, 10, 30))

    def test_final_short_bucket_closes_at_1600_not_the_nominal_end(self):
        bucket_start = _et_unix(2026, 7, 20, 15, 30)
        # A nominal 1h close would be 16:30, past the actual 16:00 close.
        self.assertEqual(session_bucket_close_unix(bucket_start, 60), _et_unix(2026, 7, 20, 16, 0))

    def test_close_time_is_dst_aware(self):
        bucket_start = _et_unix(2026, 3, 9, 15, 30)
        self.assertEqual(session_bucket_close_unix(bucket_start, 60), _et_unix(2026, 3, 9, 16, 0))


def _source_payload(candles, symbol="AAPL", candles_provider="massive"):
    return {
        "symbol": symbol,
        "price": candles[-1]["close"],
        "candles": candles,
        "candles_provider": candles_provider,
        "shares_outstanding": None,
        "float_shares": None,
        "next_refresh_at": 0,
        "session_policy": "tradingview_regular",
    }


class RequestMassiveCandlesSessionAnchoringIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_1h_request_aggregates_from_30m_source_and_slices_after_aggregation(self):
        source_candles = _session_native_candles(2026, 7, 20, 30, 13)

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=_source_payload(source_candles)),
        ) as source_mock:
            payload = await market_data.request_massive_candles("AAPL", "1h", candles_limit=3)

        self.assertEqual(source_mock.await_args.args[0], "AAPL")
        self.assertEqual(source_mock.await_args.args[1], "30m")

        self.assertEqual(
            [candle["time"] for candle in payload["candles"]],
            [_et_unix(2026, 7, 20, 13, 30), _et_unix(2026, 7, 20, 14, 30), _et_unix(2026, 7, 20, 15, 30)],
        )
        self.assertEqual(payload["candles_provider"], "massive")
        self.assertEqual(payload["session_policy"], "tradingview_regular")

    async def test_4h_request_aggregates_from_30m_source(self):
        source_candles = _session_native_candles(2026, 7, 20, 30, 13)

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=_source_payload(source_candles)),
        ) as source_mock:
            payload = await market_data.request_massive_candles("AAPL", "4h", candles_limit=5)

        self.assertEqual(source_mock.await_args.args[1], "30m")
        self.assertEqual(
            [candle["time"] for candle in payload["candles"]],
            [_et_unix(2026, 7, 20, 9, 30), _et_unix(2026, 7, 20, 13, 30)],
        )

    async def test_custom_45m_request_uses_15m_source(self):
        source_candles = _session_native_candles(2026, 7, 20, 15, 26)

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=_source_payload(source_candles)),
        ) as source_mock:
            payload = await market_data.request_massive_candles("AAPL", "45m", candles_limit=9)

        self.assertEqual(source_mock.await_args.args[1], "15m")
        self.assertEqual(len(payload["candles"]), 9)
        self.assertEqual(payload["candles"][-1]["time"], _et_unix(2026, 7, 20, 15, 30))

    async def test_native_30m_request_self_rebuckets_at_a_1to1_ratio(self):
        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value={"symbol": "AAPL", "candles": []}),
        ) as source_mock:
            await market_data.request_massive_candles("AAPL", "30m", candles_limit=10)

        # Native "30m" is still its own source (single fetch, no cross-
        # granularity split) but is routed through the same session-anchor
        # rebucket as every other intraday timeframe, so a misaligned
        # provider row would be self-corrected instead of trusted as-is.
        self.assertEqual(source_mock.await_args.args[1], "30m")
        self.assertEqual(source_mock.await_count, 1)

    async def test_crypto_1h_request_bypasses_aggregation_entirely(self):
        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=None),
        ) as source_mock:
            await market_data.request_massive_candles("BTC-USD", "1h", candles_limit=10)

        self.assertEqual(source_mock.await_args.args[1], "1h")

    async def test_final_partial_1h_bucket_is_marked_unclosed_before_session_close(self):
        source_candles = _session_native_candles(2026, 7, 20, 30, 13)
        just_before_close = _et_unix(2026, 7, 20, 15, 59)

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=_source_payload(source_candles)),
        ), patch.object(
            market_data.time, "time", return_value=just_before_close,
        ):
            payload = await market_data.request_massive_candles("AAPL", "1h", candles_limit=7)

        self.assertIs(payload["candles"][-1]["is_closed"], False)

    async def test_final_partial_1h_bucket_closes_exactly_at_session_close(self):
        source_candles = _session_native_candles(2026, 7, 20, 30, 13)
        at_close = _et_unix(2026, 7, 20, 16, 0)

        with patch.object(
            settings, "STOCK_INTRADAY_SESSION_POLICY", "tradingview_regular",
        ), patch.object(
            market_data, "request_polygon_candles", AsyncMock(return_value=_source_payload(source_candles)),
        ), patch.object(
            market_data.time, "time", return_value=at_close,
        ):
            payload = await market_data.request_massive_candles("AAPL", "1h", candles_limit=7)

        self.assertNotIn("is_closed", payload["candles"][-1])


if __name__ == "__main__":
    unittest.main()

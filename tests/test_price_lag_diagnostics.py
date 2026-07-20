"""Diagnostic tests written during the TradingView price-lag/mismatch audit.

These target behaviors that were inspected in services/market_data.py but had
no existing unit coverage: raw timestamp normalization, freshness/refresh-due
boundaries, the "adjusted" price parameter sent to the provider, page
dedup/sort during history backfill, the synthetic quote-candle timestamp used
in the latest_only fast path, and the stale-cache fallback behavior for
worker-managed timeframes (1h/4h/1day) after a live provider fetch fails.

Do not weaken or remove these once the underlying behavior is fixed; update
the assertions to match the corrected behavior instead.
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from core.config import Settings, settings  # noqa: E402
from services import market_data, screener  # noqa: E402


class TimestampNormalizationTests(unittest.TestCase):
    def test_normalize_polygon_rows_converts_open_time_ms_to_utc_epoch_seconds(self):
        rows = [
            {"t": 1_700_000_000_000, "o": 1.0, "h": 1.5, "l": 0.9, "c": 1.2, "v": 100},
        ]

        candles = market_data.normalize_polygon_rows(rows)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0]["time"], 1_700_000_000)
        self.assertEqual(candles[0]["open"], 1.0)
        self.assertEqual(candles[0]["close"], 1.2)

    def test_normalize_polygon_rows_drops_rows_missing_ohlc_fields(self):
        rows = [
            {"t": 1000, "o": 1.0, "h": None, "l": 0.9, "c": 1.2, "v": 10},
            {"t": 2000, "o": 2.0, "h": 2.1, "l": 1.9, "c": 2.0, "v": 10},
        ]

        candles = market_data.normalize_polygon_rows(rows)

        self.assertEqual([c["time"] for c in candles], [2])

    def test_normalize_binance_rows_uses_kline_open_time_not_close_time(self):
        open_time_ms = 1_700_000_000_000
        close_time_ms = open_time_ms + 3_599_999
        row = [open_time_ms, "1.0", "1.5", "0.9", "1.2", "100", close_time_ms]

        candles = market_data.normalize_binance_rows([row])

        self.assertEqual(candles[0]["time"], open_time_ms // 1000)
        self.assertNotEqual(candles[0]["time"], close_time_ms // 1000)


class FreshnessAndRefreshDueTests(unittest.TestCase):
    def test_is_payload_fresh_true_until_the_candle_boundary_then_false(self):
        payload = {"candles": [{"time": 1_000, "close": 10.0}]}

        self.assertTrue(market_data.is_payload_fresh(payload, "1h", now=1_000 + 3_599))
        self.assertFalse(market_data.is_payload_fresh(payload, "1h", now=1_000 + 3_600))

    def test_is_refresh_due_prefers_explicit_next_refresh_at_over_candle_boundary(self):
        payload = {
            "candles": [{"time": 1_000, "close": 10.0}],
            "next_refresh_at": 1_500,
        }

        # Candle boundary alone would say "still fresh" (now well before +3600),
        # but an explicit next_refresh_at in the past must still force a refresh.
        self.assertTrue(market_data.is_refresh_due(payload, "1h", now=1_500))
        self.assertFalse(market_data.is_refresh_due(payload, "1h", now=1_499))

    def test_is_refresh_due_true_for_empty_payload(self):
        self.assertTrue(market_data.is_refresh_due(None, "1h"))
        self.assertTrue(market_data.is_refresh_due({}, "1h"))


class QuoteCandleTimestampTests(unittest.TestCase):
    def test_quote_candle_timestamp_is_wall_clock_not_a_real_candle_boundary(self):
        # The latest_only fast path builds a synthetic single candle out of a
        # ticker price. Its "time" is simply "now", not the open time of the
        # timeframe's actual current candle - so comparing this candle's
        # timestamp against TradingView's live candle open time will not line
        # up, even though the close price itself should match.
        candle = market_data._quote_candle(123.45, now=1_700_000_000)

        self.assertEqual(candle["time"], 1_700_000_000)
        self.assertEqual(candle["open"], candle["high"])
        self.assertEqual(candle["open"], candle["low"])
        self.assertEqual(candle["open"], candle["close"])
        self.assertEqual(candle["close"], 123.45)


class PolygonHistoryPagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_polygon_rows_dedupes_overlapping_pages_and_sorts_ascending(self):
        pages = [
            [
                {"t": 4000, "o": 4.0, "h": 4.1, "l": 3.9, "c": 4.0, "v": 40},
                {"t": 3000, "o": 3.0, "h": 3.1, "l": 2.9, "c": 3.0, "v": 30},
            ],
            [
                # t=3000 duplicates the previous page's oldest row on purpose.
                {"t": 3000, "o": 3.0, "h": 3.1, "l": 2.9, "c": 3.0, "v": 30},
                {"t": 2000, "o": 2.0, "h": 2.1, "l": 1.9, "c": 2.0, "v": 20},
                {"t": 1000, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0, "v": 10},
            ],
        ]

        with patch.object(
            market_data,
            "_polygon_buffer_bars",
            return_value=0,
        ), patch.object(
            market_data,
            "_request_polygon_aggregate_page",
            AsyncMock(side_effect=pages),
        ) as page_mock:
            rows = await market_data._download_polygon_rows("AAPL", "1day", candles_limit=3)

        timestamps = [row["t"] for row in rows]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(timestamps, [1000, 2000, 3000, 4000])
        self.assertEqual(len(timestamps), len(set(timestamps)))
        self.assertEqual(page_mock.await_count, 2)

    async def test_request_polygon_aggregate_page_requests_adjusted_prices(self):
        with patch.object(
            market_data,
            "_polygon_get_json",
            AsyncMock(return_value={"results": []}),
        ) as get_json_mock:
            await market_data._request_polygon_aggregate_page("AAPL", "1day", 1_700_000_000_000, 5)

        get_json_mock.assert_awaited_once()
        _, kwargs = get_json_mock.await_args
        self.assertEqual(kwargs["params"]["adjusted"], "true")
        self.assertEqual(kwargs["params"]["sort"], "desc")


class AdjustedPriceConfigTests(unittest.TestCase):
    def test_grouped_daily_stock_requests_also_use_adjusted_prices(self):
        # Guards against someone quietly making the grouped-daily bulk path
        # (used for large 1day/1w/1mo scans) diverge from the per-symbol
        # aggregate path on the adjusted-vs-raw price question.
        import inspect

        source = inspect.getsource(market_data._request_polygon_grouped_daily)
        self.assertIn('"adjusted": "true"', source)


def _stale_payload(now, close=150.0):
    return {
        "symbol": "AAPL",
        "price": close,
        "candles": [
            {"time": now - 2 * 86400, "open": 1, "high": 1, "low": 1, "close": close - 1, "volume": 10},
            {"time": now - 86400, "open": 1, "high": 1, "low": 1, "close": close, "volume": 10},
        ],
        "candles_provider": "massive",
        "shares_outstanding": None,
        "float_shares": None,
        "next_refresh_at": now - 1,
    }


def _expected_backoff(now, timeframe):
    return now + max(
        market_data.FAILED_REFRESH_BACKOFF_SECONDS,
        market_data.timeframe_seconds(timeframe) // 4,
    )


class StaleCacheFallbackDefaultBehaviorTests(unittest.IsolatedAsyncioTestCase):
    """Required-behavior tests: ALLOW_STALE_MARKET_DATA defaults to False, so
    a failed refresh on a worker-cache timeframe must exclude the stale
    symbol from the response by default, while still keeping the cached row
    in SQLite and still scheduling the normal retry/backoff.
    """

    async def _assert_stale_symbol_excluded_by_default(self, timeframe):
        now = 10_000_000
        stale_payload = _stale_payload(now)
        expected_backoff = _expected_backoff(now, timeframe)

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": stale_payload, "updated_at": now - 120}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ) as fetch_batches_mock, patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock, patch.object(
            market_data.store, "update_interest_schedule",
        ) as update_interest_schedule_mock, patch.object(
            settings, "ALLOW_STALE_MARKET_DATA", False,
        ), patch.object(
            settings, "CANDLES_PROVIDER", "massive",
        ):
            results = await market_data.fetch_live_data(["AAPL"], timeframe, candles_limit=2)

        fetch_batches_mock.assert_awaited_once()

        # 1. The stale symbol must NOT be returned to the API caller.
        self.assertEqual(results, [])

        # The old cached row must be left alone - not rewritten, not deleted.
        store_snapshots_mock.assert_not_called()

        # Retry/backoff scheduling must still occur.
        update_interest_schedule_mock.assert_called_once_with(
            ["AAPL"], timeframe, {"AAPL": expected_backoff},
        )

    async def test_default_config_excludes_stale_1day_symbol_after_provider_failure(self):
        await self._assert_stale_symbol_excluded_by_default("1day")

    async def test_default_config_excludes_stale_1h_symbol_after_provider_failure(self):
        await self._assert_stale_symbol_excluded_by_default("1h")

    async def test_default_config_excludes_stale_4h_symbol_after_provider_failure(self):
        await self._assert_stale_symbol_excluded_by_default("4h")

    async def test_fetch_live_data_drops_symbol_on_intraday_provider_failure_without_stale_fallback(self):
        """Contrast case: for timeframes that never used the worker cache
        (1m/5m/15m/30m), a failed refetch has no stale-serving fallback at
        all - the symbol is simply dropped from the response. This behavior
        is unchanged by this fix and should stay that way.
        """
        with patch.object(
            market_data.store, "get_cached", return_value={},
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ), patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock:
            results = await market_data.fetch_live_data(["AAPL"], "5m", candles_limit=2)

        self.assertEqual(results, [])
        store_snapshots_mock.assert_not_called()


class StaleFallbackExplicitlyEnabledTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_payload_within_max_age_is_returned_with_stale_metadata(self):
        now = 10_000_000
        cache_age = 120
        stale_payload = _stale_payload(now)
        expected_backoff = _expected_backoff(now, "1day")

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": stale_payload, "updated_at": now - cache_age}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ), patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock, patch.object(
            settings, "ALLOW_STALE_MARKET_DATA", True,
        ), patch.object(
            settings, "MAX_STALE_MARKET_DATA_AGE_SECONDS", 300,
        ), patch.object(
            settings, "CANDLES_PROVIDER", "massive",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2)

        self.assertEqual(len(results), 1)
        served = results[0]

        self.assertTrue(served["is_stale"])
        self.assertEqual(served["market_data_source"], "stale_cache")
        self.assertEqual(served["stale_reason"], "provider_refresh_failed")
        self.assertEqual(served["stale_age_seconds"], cache_age)
        self.assertEqual(served["next_refresh_at"], expected_backoff)
        self.assertEqual(served["candles"], stale_payload["candles"])

        # Old data remains stored (re-persisted with the new backoff), never deleted.
        store_snapshots_mock.assert_called_once()

    async def test_stale_payload_older_than_max_age_is_excluded(self):
        now = 10_000_000
        cache_age = 500  # exceeds the configured max below
        stale_payload = _stale_payload(now)
        expected_backoff = _expected_backoff(now, "1day")

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": stale_payload, "updated_at": now - cache_age}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ), patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock, patch.object(
            market_data.store, "update_interest_schedule",
        ) as update_interest_schedule_mock, patch.object(
            settings, "ALLOW_STALE_MARKET_DATA", True,
        ), patch.object(
            settings, "MAX_STALE_MARKET_DATA_AGE_SECONDS", 300,
        ), patch.object(
            settings, "CANDLES_PROVIDER", "massive",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2)

        self.assertEqual(results, [])
        store_snapshots_mock.assert_not_called()
        update_interest_schedule_mock.assert_called_once_with(
            ["AAPL"], "1day", {"AAPL": expected_backoff},
        )


class FreshCacheAndLiveProviderMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_cache_hit_is_marked_not_stale_with_fresh_cache_source(self):
        now = 10_000_000
        cache_age = 42
        fresh_payload = {
            "symbol": "AAPL",
            "price": 155.0,
            "candles": [
                {"time": now - 3600, "open": 1, "high": 1, "low": 1, "close": 154.0, "volume": 10},
                {"time": now, "open": 1, "high": 1, "low": 1, "close": 155.0, "volume": 10},
            ],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,  # not due yet
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": fresh_payload, "updated_at": now - cache_age}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ) as fetch_batches_mock, patch.object(
            settings, "CANDLES_PROVIDER", "massive",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2)

        fetch_batches_mock.assert_not_awaited()
        self.assertEqual(len(results), 1)
        served = results[0]
        self.assertFalse(served["is_stale"])
        self.assertEqual(served["market_data_source"], "fresh_cache")
        self.assertEqual(served["stale_age_seconds"], cache_age)
        self.assertIsNone(served["stale_reason"])

    async def test_successful_live_refresh_is_marked_not_stale_with_live_provider_source(self):
        now = 10_000_000
        live_payload = {
            "symbol": "AAPL",
            "price": 160.0,
            "candles": [
                {"time": now, "open": 1, "high": 1, "low": 1, "close": 160.0, "volume": 10},
            ],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store, "get_cached", return_value={},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[live_payload]),
        ) as fetch_batches_mock, patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock:
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=1)

        fetch_batches_mock.assert_awaited_once()
        self.assertEqual(len(results), 1)
        served = results[0]
        self.assertFalse(served["is_stale"])
        self.assertEqual(served["market_data_source"], "live_provider")
        self.assertEqual(served["stale_age_seconds"], 0)
        self.assertIsNone(served["stale_reason"])

        # The raw payload persisted to SQLite is untouched by the freshness tags.
        store_snapshots_mock.assert_called_once()
        stored_items, _ = store_snapshots_mock.call_args[0]
        self.assertNotIn("is_stale", stored_items[0])


class ApiFreshnessPropagationTests(unittest.TestCase):
    """Confirms freshness metadata reaches the response payloads built by
    services/screener.py for /screen/run, /run-gate, /run-entry (build_response)
    and /screen/details (get_asset_detail's market_data block), when the
    underlying fetch_live_data payload carries the stale-cache tags.
    """

    def test_build_response_surfaces_stale_metadata_when_stale_fallback_is_enabled(self):
        stale_asset = {
            "symbol": "AAPL",
            "price": 150.0,
            "asset_type": "stocks",
            "data_source": "zoya",
            "candles": [{"time": 1, "close": 150.0}],
            "is_stale": True,
            "stale_age_seconds": 120,
            "stale_reason": "provider_refresh_failed",
            "market_data_source": "stale_cache",
        }

        response = screener.build_response([stale_asset], "1day", "single")

        freshness = response["results"][0]["market_data_freshness"]
        self.assertTrue(freshness["is_stale"])
        self.assertEqual(freshness["data_source"], "stale_cache")
        self.assertEqual(freshness["stale_reason"], "provider_refresh_failed")
        self.assertEqual(freshness["stale_age_seconds"], 120)

        # Existing asset-source data_source (zoya/massive/manual) must be untouched.
        self.assertEqual(response["results"][0]["data_source"], "zoya")

    def test_build_response_defaults_to_live_provider_when_untagged(self):
        untagged_asset = {
            "symbol": "AAPL",
            "price": 150.0,
            "asset_type": "stocks",
            "data_source": "zoya",
            "candles": [{"time": 1, "close": 150.0}],
        }

        response = screener.build_response([untagged_asset], "5m", "single")

        freshness = response["results"][0]["market_data_freshness"]
        self.assertFalse(freshness["is_stale"])
        self.assertEqual(freshness["data_source"], "live_provider")
        self.assertEqual(freshness["stale_age_seconds"], 0)
        self.assertIsNone(freshness["stale_reason"])


class StaleConfigurationDefaultsTests(unittest.TestCase):
    def test_allow_stale_market_data_defaults_to_false(self):
        self.assertFalse(Settings.model_fields["ALLOW_STALE_MARKET_DATA"].default)

    def test_max_stale_market_data_age_seconds_defaults_to_300(self):
        self.assertEqual(Settings.model_fields["MAX_STALE_MARKET_DATA_AGE_SECONDS"].default, 300)

    def test_negative_max_stale_age_is_normalized_to_zero(self):
        self.assertEqual(Settings.parse_non_negative_ints(-50), 0)


# =========================================================
# HISTORICAL-CANDLE RETRIEVAL BUG
#
# Root cause: _polygon_base_aggregate_seconds() treated a native 1-HOUR
# Polygon aggregate row as if it only spanned 60 seconds (the same value used
# for "minute" timespans), so the calendar lookback window computed in
# _request_polygon_aggregate_page (window_seconds = base_seconds * base_limit)
# was ~60x too narrow for "1h" (and "4h") requests. A 20-candle request for a
# stock only looked back ~36 real-world hours - and because stocks trade only
# ~6.5 hours/day and not at all on weekends, that narrow window could (and,
# per the reported repro, did) contain only a single actual trading-hour
# candle instead of 20. fetch_live_data(["AAPL"], "1h", candles_limit=20,
# latest_only=False) never touched the quote/snapshot fast path (that is
# gated purely on `latest_only`, which was False) and candles_limit=20 was
# never overwritten anywhere in the call chain - the provider simply never
# had enough calendar time to search.
# =========================================================

def _candle_row(time_value, close=100.0):
    return {
        "time": time_value,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
    }


def _polygon_row(timestamp_ms, close=100.0):
    return {
        "t": timestamp_ms,
        "o": close - 0.5,
        "h": close + 0.5,
        "l": close - 1.0,
        "c": close,
        "v": 1000.0,
    }


class QuoteFastPathNotUsedForHistoricalRequestsTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_only_false_with_candles_limit_20_never_uses_quote_or_snapshot_path(self):
        """Required test 1: latest_only=False with candles_limit=20 does not
        use the quote path. The quote/snapshot fast path in fetch_live_data
        is gated exclusively by `if latest_only:` - with latest_only=False
        that whole block must never execute, regardless of candles_limit.
        """
        twenty_candles = [_candle_row(1_000 + i * 3600) for i in range(20)]
        live_payload = {
            "symbol": "AAPL",
            "price": twenty_candles[-1]["close"],
            "candles": twenty_candles,
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": 100_000,
        }

        with patch.object(
            market_data, "request_massive_snapshots", AsyncMock(),
        ) as snapshot_mock, patch.object(
            market_data, "request_binance_quotes", AsyncMock(),
        ) as quote_mock, patch.object(
            market_data.store, "get_cached", return_value={},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[live_payload]),
        ), patch.object(
            market_data.store, "store_snapshots",
        ):
            results = await market_data.fetch_live_data(
                ["AAPL"], "1h", candles_limit=20, latest_only=False,
            )

        snapshot_mock.assert_not_called()
        quote_mock.assert_not_called()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["candles"]), 20)


class CandlesLimitPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_candles_limit_20_reaches_provider_fetcher_unchanged(self):
        """Required test 2: candles_limit=20 reaches the provider candle
        fetcher unchanged (not silently coerced to 1 anywhere in
        fetch_batches / resolve_candle_fetcher_for_symbol).
        """
        payload = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [_candle_row(1_000 + i * 3600) for i in range(20)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": 100_000,
        }

        with patch.object(
            market_data, "request_massive_candles", AsyncMock(return_value=payload),
        ) as fetcher_mock:
            results = await market_data.fetch_batches(["AAPL"], "1h", candles_limit=20)

        fetcher_mock.assert_awaited_once_with("AAPL", "1h", 20)
        self.assertEqual(len(results), 1)

    async def test_request_polygon_candles_passes_candles_limit_through_to_downloader(self):
        """Required tests 2-3: candles_limit=20 reaches
        _download_polygon_rows unchanged, and a provider response containing
        20 rows produces 20 normalized candles in the final payload.
        """
        twenty_rows = [_polygon_row(1_000_000 + i * 3_600_000) for i in range(20)]

        with patch.object(
            market_data.integration_runtime, "is_enabled", return_value=True,
        ), patch.object(
            market_data, "_polygon_api_key", return_value="token",
        ), patch.object(
            market_data, "_download_polygon_rows", AsyncMock(return_value=twenty_rows),
        ) as download_mock:
            payload = await market_data.request_polygon_candles("AAPL", "1h", candles_limit=20)

        download_mock.assert_awaited_once_with("AAPL", "1h", 20)
        self.assertEqual(len(payload["candles"]), 20)


class PayloadConstructionDoesNotTruncateHistoryTests(unittest.TestCase):
    def test_build_market_data_payload_keeps_all_historical_candles(self):
        """Required test 4: historical candles are not reduced to one during
        payload construction (_build_market_data_payload / _mark_unclosed_
        last_candle only ever *label* the last candle, they never slice).
        """
        candles = [_candle_row(1_000 + i * 3600) for i in range(20)]

        payload = market_data._build_market_data_payload("AAPL", candles, "1h")

        self.assertEqual(len(payload["candles"]), 20)

    def test_current_candle_may_remain_included_with_is_closed_false(self):
        """Required test 9: the current unfinished candle may remain
        included, marked is_closed=False.
        """
        now = 1_000_000
        candles = [
            _candle_row(now - 2 * 3600),
            _candle_row(now - 3600),
            _candle_row(now),  # still forming: now == last candle's open time
        ]

        with patch.object(market_data.time, "time", return_value=now):
            payload = market_data._build_market_data_payload("AAPL", candles, "1h")

        self.assertEqual(len(payload["candles"]), 3)
        self.assertIs(payload["candles"][-1]["is_closed"], False)

    def test_previous_candles_are_not_marked_unclosed(self):
        """Required test 10: previous (already-closed) candles are left
        alone - only the last candle is ever tagged, and only when it
        genuinely has not finished yet.
        """
        now = 1_000_000
        candles = [
            _candle_row(now - 2 * 3600),
            _candle_row(now - 3600),
            _candle_row(now),
        ]

        with patch.object(market_data.time, "time", return_value=now):
            payload = market_data._build_market_data_payload("AAPL", candles, "1h")

        for closed_candle in payload["candles"][:-1]:
            self.assertNotIn("is_closed", closed_candle)


class CacheSufficiencyForCandleHistoryTests(unittest.IsolatedAsyncioTestCase):
    """Required tests 5-8: a cached payload with fewer candles than requested
    must never satisfy a larger candles_limit request, whether or not it is
    otherwise "fresh" (not due for refresh) - the length check runs before
    the freshness check in fetch_live_data's worker-cache branch.
    """

    async def test_one_candle_cache_is_insufficient_and_triggers_live_refetch(self):
        now = 1_000_000
        one_candle_cached = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [_candle_row(now - 3600)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now - 1,  # due for refresh
        }
        twenty_candle_live = {
            "symbol": "AAPL",
            "price": 120.0,
            "candles": [_candle_row(now - (19 - i) * 3600) for i in range(20)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": one_candle_cached, "updated_at": now - 10}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[twenty_candle_live]),
        ) as fetch_batches_mock, patch.object(
            market_data.store, "store_snapshots",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1h", candles_limit=20)

        fetch_batches_mock.assert_awaited_once_with(
            ["AAPL"], "1h", batch_size=market_data.DEFAULT_BATCH_SIZE, candles_limit=20,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["candles"]), 20)
        self.assertEqual(results[0]["market_data_source"], "live_provider")

    async def test_one_candle_cache_is_insufficient_even_when_not_due_for_refresh(self):
        """A cached payload that is otherwise "fresh" (next_refresh_at still
        in the future) must still be rejected as insufficient if it does not
        contain enough candles for the request - freshness cannot substitute
        for having the requested history.
        """
        now = 1_000_000
        one_candle_cached_but_fresh = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [_candle_row(now - 3600)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,  # NOT due - would look "fresh"
        }
        twenty_candle_live = {
            "symbol": "AAPL",
            "price": 120.0,
            "candles": [_candle_row(now - (19 - i) * 3600) for i in range(20)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": one_candle_cached_but_fresh, "updated_at": now - 10}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[twenty_candle_live]),
        ) as fetch_batches_mock, patch.object(
            market_data.store, "store_snapshots",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1h", candles_limit=20)

        fetch_batches_mock.assert_awaited_once()
        self.assertEqual(len(results[0]["candles"]), 20)

    async def test_twenty_candle_fresh_cache_is_reused_without_refetch(self):
        """Required test 7: a fresh cached payload with 20 candles may be
        reused (no live refetch necessary).
        """
        now = 1_000_000
        twenty_candle_cached = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [_candle_row(now - (19 - i) * 3600) for i in range(20)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now + 3600,  # not due
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": twenty_candle_cached, "updated_at": now - 10}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(),
        ) as fetch_batches_mock:
            results = await market_data.fetch_live_data(["AAPL"], "1h", candles_limit=20)

        fetch_batches_mock.assert_not_awaited()
        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["candles"]), 20)
        self.assertFalse(results[0]["is_stale"])
        self.assertEqual(results[0]["market_data_source"], "fresh_cache")

    async def test_insufficient_cache_with_failed_refetch_still_respects_stale_fallback_disabled(self):
        """Required test 11: the stale-cache protection is unaffected by the
        candles_limit fix - an insufficient cache entry that fails to
        refresh is still excluded by default (ALLOW_STALE_MARKET_DATA=False),
        exactly like the plain stale-payload case.
        """
        now = 1_000_000
        one_candle_cached = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [_candle_row(now - 3600)],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": now - 1,
        }

        with patch.object(
            market_data.time, "time", return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": one_candle_cached, "updated_at": now - 10}},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data, "fetch_batches", AsyncMock(return_value=[]),
        ), patch.object(
            market_data.store, "store_snapshots",
        ) as store_snapshots_mock, patch.object(
            market_data.store, "update_interest_schedule",
        ) as update_interest_schedule_mock, patch.object(
            settings, "ALLOW_STALE_MARKET_DATA", False,
        ), patch.object(
            settings, "CANDLES_PROVIDER", "massive",
        ):
            results = await market_data.fetch_live_data(["AAPL"], "1h", candles_limit=20)

        self.assertEqual(results, [])
        store_snapshots_mock.assert_not_called()
        update_interest_schedule_mock.assert_called_once()


class PolygonRowsRemainSortedAndDedupedAtScaleTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_polygon_rows_sorts_and_dedupes_for_a_20_candle_request(self):
        """Required test 12: Polygon rows remain sorted and deduplicated,
        re-checked at the 20-candle scale relevant to this bug.
        """
        page_one = [_polygon_row(20_000 - i * 1000) for i in range(15)]  # 20000..6000 desc
        page_two = [
            _polygon_row(6_000),  # duplicate of the last row in page_one
            _polygon_row(5_000),
            _polygon_row(4_000),
            _polygon_row(3_000),
            _polygon_row(2_000),
            _polygon_row(1_000),
        ]

        with patch.object(
            market_data, "_polygon_buffer_bars", return_value=0,
        ), patch.object(
            market_data, "_request_polygon_aggregate_page", AsyncMock(side_effect=[page_one, page_two]),
        ):
            rows = await market_data._download_polygon_rows("AAPL", "1h", candles_limit=20)

        timestamps = [row["t"] for row in rows]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len(timestamps), len(set(timestamps)))
        self.assertEqual(len(timestamps), 20)


def _window_hours_from_path(path):
    # path looks like /v2/aggs/ticker/{symbol}/range/{mult}/{unit}/{from_ms}/{to_ms}
    parts = path.split("/")
    from_ms, to_ms = int(parts[-2]), int(parts[-1])
    return (to_ms - from_ms) / 1000 / 3600


class IntradayCalendarWindowTests(unittest.IsolatedAsyncioTestCase):
    """Confirms the actual root-cause fix: the calendar lookback window for a
    stock 1h request is wide enough (in real days, not just chronological
    hours) to plausibly survive a weekend/holiday gap, and that crypto (which
    trades 24/7 and does not need this expansion) gets a narrower window than
    a stock for the same request.
    """

    async def test_stock_hourly_window_spans_multiple_days_not_just_requested_hours(self):
        captured_paths = []

        async def fake_get_json(path, params=None):
            captured_paths.append(path)
            return {"results": []}

        with patch.object(market_data, "_polygon_get_json", fake_get_json):
            await market_data._request_polygon_aggregate_page("AAPL", "1h", 2_000_000_000_000, 20)

        window_hours = _window_hours_from_path(captured_paths[0])
        # The previous bug produced a ~36-64 hour window; the fix must be
        # comfortably wider than a single weekend (72h) to be safe.
        self.assertGreater(window_hours, 96)

    async def test_crypto_symbol_gets_a_narrower_window_than_a_stock_for_the_same_request(self):
        async def fake_get_json(path, params=None):
            fake_get_json.last_path = path
            return {"results": []}

        with patch.object(market_data, "_polygon_get_json", fake_get_json):
            await market_data._request_polygon_aggregate_page("BTC-USD", "1h", 2_000_000_000_000, 20)
            crypto_window = _window_hours_from_path(fake_get_json.last_path)

            await market_data._request_polygon_aggregate_page("AAPL", "1h", 2_000_000_000_000, 20)
            stock_window = _window_hours_from_path(fake_get_json.last_path)

        self.assertGreater(stock_window, crypto_window)


class EndToEndHistoricalCandleIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_live_data_returns_20_historical_candles_for_1h_request(self):
        """Integration-style reproduction of the reported bug: no cache, a
        mocked provider response containing 20 rows, and the real
        fetch_batches / resolve_candle_fetcher_for_symbol / request_massive_
        candles / request_polygon_candles chain (only the network boundary,
        _download_polygon_rows, is mocked). Before the fix this returned a
        single candle; it must now return all 20.
        """
        twenty_rows = [_polygon_row(1_700_000_000_000 + i * 3_600_000) for i in range(20)]

        with patch.object(
            market_data.store, "get_cached", return_value={},
        ), patch.object(
            market_data.store, "register_interest",
        ), patch.object(
            market_data.store, "store_snapshots",
        ), patch.object(
            market_data.integration_runtime, "is_enabled", return_value=True,
        ), patch.object(
            market_data, "_polygon_api_key", return_value="token",
        ), patch.object(
            market_data, "_download_polygon_rows", AsyncMock(return_value=twenty_rows),
        ):
            results = await market_data.fetch_live_data(
                ["AAPL"], "1h", candles_limit=20, latest_only=False,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["candles"]), 20)


# =========================================================
# PROVIDER "limit" PARAMETER SEMANTICS
#
# Massive/Polygon's Custom Bars documentation: the `limit` query parameter
# caps the number of underlying 1-MINUTE base aggregates scanned to build the
# response - it does NOT count final aggregated candles. A native "1h" bar is
# built from 60 one-minute base aggregates, a native "4h" bar from 240, and a
# native "1m" bar IS one base aggregate. _polygon_required_base_aggregates
# must therefore multiply the requested bar count by the per-bar base
# aggregate count, not pass the bar count straight through.
# =========================================================

class ProviderBaseAggregateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def _sent_limit(self, symbol, timeframe, target_bars):
        captured = {}

        async def fake_get_json(path, params=None):
            captured["params"] = params
            return {"results": []}

        with patch.object(market_data, "_polygon_get_json", fake_get_json):
            await market_data._request_polygon_aggregate_page(
                symbol, timeframe, 2_000_000_000_000, target_bars,
            )

        return captured["params"]["limit"]

    def test_required_base_aggregates_multiplies_by_minute_equivalent_per_bar(self):
        """Required test 7 (formula): 20 native "1h" bars need >= 20*60=1200
        base aggregates, not 20 and not the old fixed floor of 64.
        """
        self.assertEqual(market_data._polygon_required_base_aggregates("1h", 20), 20 * 60)
        self.assertEqual(market_data._polygon_required_base_aggregates("4h", 20), 20 * 4 * 60)
        self.assertEqual(market_data._polygon_required_base_aggregates("1m", 20), 20)
        self.assertEqual(market_data._polygon_required_base_aggregates("5m", 20), 20 * 5)

    async def test_20_candle_1h_request_sends_a_limit_of_at_least_1200(self):
        """Required test: a 20-candle 1h request sends a provider limit of
        at least 1200 (20 * 60 one-minute base aggregates).
        """
        sent_limit = await self._sent_limit("AAPL", "1h", 20)
        self.assertGreaterEqual(sent_limit, 1200)

    async def test_20_candle_4h_request_scales_the_limit_by_the_multiplier(self):
        """4h bars are 4x as long as 1h bars, so they need 4x as many
        one-minute base aggregates per final candle (240 instead of 60).
        """
        sent_limit = await self._sent_limit("AAPL", "4h", 20)
        self.assertGreaterEqual(sent_limit, 20 * 4 * 60)

    async def test_minute_timeframe_limit_is_not_inflated_by_the_hour_formula(self):
        """A native "1m" bar is itself one base aggregate - the minute branch
        must not apply the *60 hour-only multiplier.
        """
        sent_limit = await self._sent_limit("AAPL", "5m", 20)
        self.assertGreaterEqual(sent_limit, 20 * 5)
        self.assertLess(sent_limit, 20 * 5 * 60)

    async def test_limit_is_never_set_to_only_64_for_an_hourly_request(self):
        sent_limit = await self._sent_limit("AAPL", "1h", 20)
        self.assertNotEqual(sent_limit, market_data.POLYGON_MIN_BASE_AGGREGATES)
        self.assertGreater(sent_limit, market_data.POLYGON_MIN_BASE_AGGREGATES)

    async def test_limit_is_capped_at_the_api_maximum_of_50000(self):
        sent_limit = await self._sent_limit("AAPL", "4h", 500)
        self.assertEqual(sent_limit, market_data.POLYGON_MAX_BASE_AGGREGATES)
        self.assertEqual(market_data.POLYGON_MAX_BASE_AGGREGATES, 50_000)


class ApiKeyRedactionTests(unittest.TestCase):
    def test_redact_secrets_strips_api_key_query_value(self):
        message = (
            "Client error '429' for url "
            "'https://api.massive.com/v2/aggs/ticker/AAPL/range/1/hour/1/2"
            "?adjusted=true&sort=desc&limit=1200&apiKey=SUPERSECRET123'"
        )

        redacted = market_data._redact_secrets(message)

        self.assertNotIn("SUPERSECRET123", redacted)
        self.assertIn("apiKey=[REDACTED]", redacted)

    def test_redact_secrets_passes_through_none(self):
        self.assertIsNone(market_data._redact_secrets(None))

    def test_redact_secrets_leaves_ordinary_text_unchanged(self):
        message = "massive candle request failed for AAPL timeframe=1h status=500"
        self.assertEqual(market_data._redact_secrets(message), message)


if __name__ == "__main__":
    unittest.main()

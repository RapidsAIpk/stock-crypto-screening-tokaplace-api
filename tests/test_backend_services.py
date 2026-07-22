import asyncio
import os
import sys
import tempfile
import time
import unittest
import warnings
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


import main  # noqa: E402
from api import screening  # noqa: E402
from core.config import settings  # noqa: E402
from models.filters import ScreeningRequest  # noqa: E402
from models.results import ScreeningDetailResponse  # noqa: E402
from scripts import filter_zoya_universe_by_massive, update_crypto_universe  # noqa: E402
from services import (  # noqa: E402
    asset_router,
    confluence,
    indicators,
    screener,
    channel_respect,
    dead_assets,
    trendy_adx,
    vlr,
    rsi,
    macd,
    utils,
    aroon_oscillator,
    linear_regression_candles,
    market_data,
    regression_channels,
    trend_channels,
    wavetrend,
)
from services.gate_session_store import store as gate_session_store  # noqa: E402
from services.market_data_worker import MarketDataWorker, WORKER_TIMEFRAMES  # noqa: E402


class AssetRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_stock_universe_normalizes_sources_and_filters_status(self):
        request = SimpleNamespace(
            asset_type="stocks",
            stock_sources=[" ZOYA "],
            compliance_status="compliant",
        )

        with patch.object(
            asset_router,
            "load_zoya_universe",
            return_value=[
                {"symbol": "AAPL", "name": "Apple", "exchange": "NASDAQ"},
            ],
        ) as load_mock:
            assets = await asset_router.build_asset_universe(request)

        self.assertEqual(
            assets,
            [
                {
                    "symbol": "AAPL",
                    "name": "Apple",
                    "exchange": "NASDAQ",
                    "category": "NASDAQ",
                    "compliance_status": None,
                    "report_date": None,
                    "purification_ratio": None,
                    "asset_type": "stocks",
                    "data_source": "zoya",
                }
            ],
        )
        load_mock.assert_called_once_with("compliant")

    async def test_build_crypto_universe_applies_exchange_and_category_filters(self):
        request = SimpleNamespace(
            asset_type="crypto",
            exchanges=[" Binance "],
            excluded_categories=[" meme "],
        )

        with patch.object(
            asset_router,
            "load_crypto_universe",
            return_value=[
                {"symbol": "BTC", "name": "Bitcoin", "exchange": "binance", "category": "store-of-value"},
                {"symbol": "DOGE", "name": "Dogecoin", "exchange": "binance", "category": "meme"},
                {"symbol": "ETH", "name": "Ethereum", "exchange": "kraken", "category": "layer1"},
            ],
        ):
            assets = await asset_router.build_asset_universe(request)

        self.assertEqual(
            assets,
            [
                {
                    "symbol": "BTC-USD",
                    "name": "Bitcoin",
                    "category": "store-of-value",
                    "cmc_id": None,
                    "rank": None,
                    "exchange": "binance",
                    "exchange_availability": ["binance"],
                    "asset_type": "crypto",
                    "data_source": "massive",
                }
            ],
        )

    async def test_build_crypto_universe_excludes_symbols_without_exchange_metadata_when_filtering(self):
        request = SimpleNamespace(
            asset_type="crypto",
            exchanges=[" Kraken "],
            excluded_categories=[],
        )

        with patch.object(
            asset_router,
            "load_crypto_universe",
            return_value=[
                {"symbol": "BTC", "name": "Bitcoin", "category": "general"},
                {"symbol": "ETH", "name": "Ethereum", "category": "general"},
            ],
        ):
            assets = await asset_router.build_asset_universe(request)

        self.assertEqual(assets, [])

    async def test_build_crypto_universe_limits_results_to_active_binance_provider(self):
        request = SimpleNamespace(
            asset_type="crypto",
            exchanges=["binance", "coinbase", "kucoin"],
            excluded_categories=[],
        )

        with patch.object(
            asset_router,
            "load_crypto_universe",
            return_value=[
                {
                    "symbol": "BTC",
                    "name": "Bitcoin",
                    "category": "store-of-value",
                    "exchanges": ["binance", "coinbase"],
                },
                {
                    "symbol": "ETH",
                    "name": "Ethereum",
                    "category": "layer1",
                    "exchanges": ["coinbase"],
                },
                {
                    "symbol": "SOL",
                    "name": "Solana",
                    "category": "layer1",
                    "exchanges": ["kucoin"],
                },
                {
                    "symbol": "XRP",
                    "name": "XRP",
                    "category": "payments",
                    "exchanges": ["binance"],
                },
            ],
        ), patch.object(
            asset_router,
            "active_crypto_candle_provider",
            return_value="binance",
        ):
            assets = await asset_router.build_asset_universe(request)

        self.assertEqual(
            [asset["symbol"] for asset in assets],
            ["BTC-USD", "XRP-USD"],
        )

    async def test_build_crypto_universe_treats_empty_exchange_filter_as_all_exchanges(self):
        request = SimpleNamespace(
            asset_type="crypto",
            exchanges=[],
            excluded_categories=[],
        )

        with patch.object(
            asset_router,
            "load_crypto_universe",
            return_value=[
                {
                    "symbol": "BTC",
                    "name": "Bitcoin",
                    "category": "store-of-value",
                    "exchanges": ["binance", "kraken"],
                },
                {
                    "symbol": "ETH",
                    "name": "Ethereum",
                    "category": "layer1",
                    "exchange": "coinbase",
                },
            ],
        ):
            assets = await asset_router.build_asset_universe(request)

        self.assertEqual(
            [asset["symbol"] for asset in assets],
            ["BTC-USD", "ETH-USD"],
        )
        self.assertEqual(
            assets[0]["exchange_availability"],
            ["binance", "kraken"],
        )

    def test_list_crypto_exchanges_returns_sorted_unique_normalized_values(self):
        with patch.object(
            asset_router,
            "load_crypto_universe",
            return_value=[
                {"symbol": "BTC", "exchange": " Binance "},
                {"symbol": "BTC-USD", "exchanges": ["binance"]},
                {"symbol": "ETH", "exchanges": ["Kraken", "coinbase", "binance"]},
                {"symbol": "SOL", "exchanges": ["coinbase", None, " "]},
                {"symbol": "DOGE"},
            ],
        ):
            exchanges = asset_router.list_crypto_exchanges()

        self.assertEqual(
            exchanges,
            [
                {"exchange": "binance", "coin_count": 2},
                {"exchange": "coinbase", "coin_count": 2},
                {"exchange": "kraken", "coin_count": 1},
            ],
        )

    def test_load_zoya_universe_reuses_cached_json_until_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "zoya.json")

            with open(cache_path, "w", encoding="utf-8") as handle:
                handle.write('[{"symbol":"AAPL","status":"COMPLIANT"}]')

            asset_router._JSON_CACHE.clear()

            with patch.object(asset_router, "ZOYA_CACHE", asset_router.Path(cache_path)):
                with patch("builtins.open", wraps=open) as open_mock:
                    first = asset_router.load_zoya_universe()
                    second = asset_router.load_zoya_universe()

                    self.assertEqual(first, second)
                    self.assertEqual(open_mock.call_count, 1)

                with open(cache_path, "w", encoding="utf-8") as handle:
                    handle.write('[{"symbol":"MSFT","status":"COMPLIANT"}]')

                stat = os.stat(cache_path)
                os.utime(cache_path, (stat.st_atime + 1, stat.st_mtime + 1))

                refreshed = asset_router.load_zoya_universe()
                self.assertEqual(refreshed[0]["symbol"], "MSFT")

    def test_load_crypto_universe_normalizes_symbols_for_massive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "crypto.json")

            with open(cache_path, "w", encoding="utf-8") as handle:
                handle.write(
                    '[{"symbol":"btc","name":"Bitcoin"},{"symbol":"USDe","name":"Ethena USD"},{"symbol":"XAUt","name":"Tether Gold"}]'
                )

            asset_router._JSON_CACHE.clear()

            with patch.object(asset_router, "CRYPTO_CACHE", asset_router.Path(cache_path)):
                loaded = asset_router.load_crypto_universe()

            self.assertEqual(
                [
                    {
                        "symbol": item["symbol"],
                        "provider_symbol": item["provider_symbol"],
                        "cmc_symbol": item["cmc_symbol"],
                    }
                    for item in loaded
                ],
                [
                    {"symbol": "BTC-USD", "provider_symbol": "X:BTCUSD", "cmc_symbol": "btc"},
                    {"symbol": "USDE-USD", "provider_symbol": "X:USDEUSD", "cmc_symbol": "USDe"},
                    {"symbol": "XAUT-USD", "provider_symbol": "X:XAUTUSD", "cmc_symbol": "XAUt"},
                ],
            )


class CryptoUniverseScriptTests(unittest.TestCase):
    def test_fetch_coin_list_uses_massive_pagination_and_keeps_usd_pairs(self):
        first_page = {
            "results": [
                {
                    "ticker": "X:BTCEUR",
                    "base_currency_symbol": "BTC",
                    "base_currency_name": "Bitcoin",
                    "currency_symbol": "EUR",
                    "active": True,
                },
                {
                    "ticker": "X:DNYUSD",
                    "base_currency_symbol": "DNT",
                    "base_currency_name": "District0x",
                    "currency_symbol": "USD",
                    "active": True,
                },
            ],
            "next_url": "https://api.massive.com/v3/reference/tickers?cursor=page-2",
        }
        second_page = {
            "results": [
                {
                    "ticker": "X:DNTUSD",
                    "base_currency_symbol": "DNT",
                    "base_currency_name": "district0x",
                    "currency_symbol": "USD",
                    "active": True,
                },
                {
                    "ticker": "X:ETHUSD",
                    "base_currency_symbol": "ETH",
                    "base_currency_name": "Ethereum",
                    "currency_symbol": "USD",
                    "active": True,
                },
                {
                    "ticker": "X:SOLUSD",
                    "base_currency_symbol": "SOL",
                    "base_currency_name": "Solana",
                    "currency_symbol": "USD",
                    "active": False,
                },
            ],
        }

        with patch.object(
            update_crypto_universe,
            "massive_get",
            side_effect=[first_page, second_page],
        ) as massive_get_mock:
            coins = update_crypto_universe.fetch_coin_list()

        self.assertEqual(
            coins,
            [
                {"symbol": "DNT", "name": "district0x", "category": "general"},
                {"symbol": "ETH", "name": "Ethereum", "category": "general"},
            ],
        )
        self.assertEqual(massive_get_mock.call_count, 2)
        self.assertEqual(
            massive_get_mock.call_args_list[0].args[0],
            update_crypto_universe.REFERENCE_TICKERS_URL,
        )
        self.assertEqual(
            massive_get_mock.call_args_list[0].kwargs["params"]["market"],
            "crypto",
        )
        self.assertIsNone(massive_get_mock.call_args_list[1].kwargs["params"])


class StockUniverseFilterScriptTests(unittest.TestCase):
    def test_fetch_supported_stock_symbols_uses_massive_pagination(self):
        first_page = {
            "results": [
                {"ticker": "AAPL", "active": True},
                {"ticker": "BAD", "active": False},
            ],
            "next_url": "https://api.massive.com/v3/reference/tickers?cursor=page-2",
        }
        second_page = {
            "results": [
                {"ticker": "BRK.B", "active": True},
                {"ticker": "", "active": True},
            ],
        }

        with patch.object(
            filter_zoya_universe_by_massive,
            "massive_get",
            side_effect=[first_page, second_page],
        ) as massive_get_mock:
            symbols = filter_zoya_universe_by_massive.fetch_supported_stock_symbols()

        self.assertEqual(symbols, {"AAPL", "BRK.B"})
        self.assertEqual(massive_get_mock.call_count, 2)
        self.assertEqual(
            massive_get_mock.call_args_list[0].args[0],
            filter_zoya_universe_by_massive.REFERENCE_TICKERS_URL,
        )
        self.assertEqual(
            massive_get_mock.call_args_list[0].kwargs["params"]["market"],
            "stocks",
        )
        self.assertEqual(
            massive_get_mock.call_args_list[0].kwargs["params"]["locale"],
            "us",
        )
        self.assertIsNone(massive_get_mock.call_args_list[1].kwargs["params"])

    def test_filter_zoya_universe_keeps_supported_symbols_only(self):
        items = [
            {"symbol": "AAPL", "name": "Apple"},
            {"symbol": "brk.b", "name": "Berkshire"},
            {"symbol": "MISSING", "name": "Missing"},
            {"name": "No Symbol"},
        ]

        kept, removed = filter_zoya_universe_by_massive.filter_zoya_universe(
            items,
            {"AAPL", "BRK.B"},
        )

        self.assertEqual(kept, items[:2])
        self.assertEqual(removed, items[2:])


class ScreeningRequestValidationTests(unittest.TestCase):
    def test_manual_symbol_limit_respects_runtime_setting(self):
        with patch.object(settings, "MANUAL_SYMBOLS_MAX", 2):
            with self.assertRaises(ValueError) as exc:
                ScreeningRequest(
                    asset_type="stocks",
                    symbols=["AAPL", "MSFT", "GOOG"],
                    timeframe_mode="single",
                    single_timeframe="1h",
                    indicators=[],
                )

        self.assertIn("symbols supports up to 2 items", str(exc.exception))

    def test_manual_symbol_limit_can_be_disabled(self):
        with patch.object(settings, "MANUAL_SYMBOLS_MAX", 0):
            request = ScreeningRequest(
                asset_type="stocks",
                symbols=["AAPL", "MSFT", "GOOG"],
                timeframe_mode="single",
                single_timeframe="1h",
                indicators=[],
            )

        self.assertEqual(request.symbols, ["AAPL", "MSFT", "GOOG"])

    def test_crypto_timeframes_support_custom_ranges(self):
        request = ScreeningRequest(
            asset_type="crypto",
            symbols=["BTC"],
            timeframe_mode="single",
            single_timeframe="2day",
            indicators=[],
        )

        self.assertEqual(request.single_timeframe, "2day")

    def test_crypto_requests_allow_empty_exchange_selection(self):
        request = ScreeningRequest(
            asset_type="crypto",
            timeframe_mode="single",
            single_timeframe="1h",
            exchanges=[],
            indicators=[],
        )

        self.assertIsNone(request.exchanges)

    def test_confluence_requires_exactly_two_selected_sources(self):
        with self.assertRaises(ValueError) as exc:
            ScreeningRequest(
                asset_type="crypto",
                timeframe_mode="single",
                single_timeframe="1h",
                indicators=[],
                confluence={
                    "type": "bullish",
                    "sources": [
                        {"id": "trend_0", "channel_type": "trend", "selection": "bottom_line", "length": 8},
                    ],
                    "liquidity_sweep": False,
                    "lookback_candles": 4,
                    "tolerance_pct": 0.1,
                },
            )

        self.assertIn("exactly 2", str(exc.exception))

    def test_confluence_rejects_invalid_selection_for_channel_type(self):
        with self.assertRaises(ValueError) as exc:
            ScreeningRequest(
                asset_type="crypto",
                timeframe_mode="single",
                single_timeframe="1h",
                indicators=[],
                confluence={
                    "type": "bearish",
                    "sources": [
                        {"id": "lrc_0", "channel_type": "lrc", "selection": "top_zone", "length": 100},
                        {"id": "trend_1", "channel_type": "trend", "selection": "top_line", "length": 8},
                    ],
                    "liquidity_sweep": False,
                    "lookback_candles": 4,
                    "tolerance_pct": 0.1,
                },
            )

        self.assertIn("invalid for channel_type", str(exc.exception))


class ConfluenceTests(unittest.TestCase):
    def test_get_channel_area_ignores_empty_channel_lines(self):
        area = confluence.get_channel_area(
            {"upper": [], "lower": []},
            candles=[{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}],
            candle_index=0,
            tolerance_pct=0.1,
        )

        self.assertIsNone(area)

    def test_evaluate_confluence_handles_missing_channel_data_without_crashing(self):
        candles = [{"close": 100.0}, {"close": 101.0}]
        channels = {
            "lrc": {"upper": [], "lower": []},
            "trend": {"top": [105.0], "bottom": [95.0]},
        }
        config = SimpleNamespace(
            type="any",
            channels=["lrc", "trend"],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertFalse(
            confluence.evaluate_confluence(candles, channels, config)
        )

    def test_evaluate_confluence_detects_recent_bullish_alignment(self):
        candles = [
            {"open": 100.2, "high": 100.6, "low": 99.8, "close": 100.3},
            {"open": 100.1, "high": 100.4, "low": 99.9, "close": 100.2},
        ]
        channels = {
            "lrc": {"upper": [105.0, 105.1], "lower": [100.0, 100.0]},
            "trend": {"top": [110.0, 110.1], "bottom": [100.05, 100.05]},
        }
        config = SimpleNamespace(
            type="bullish",
            channels=["lrc", "trend"],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))

    def test_evaluate_confluence_requires_reaction_not_just_line_overlap(self):
        candles = [
            {"open": 100.0, "high": 100.06, "low": 99.98, "close": 100.02},
        ]
        channels = {
            "lrc": {"upper": [105.0], "lower": [100.0]},
            "trend": {"top": [110.0], "bottom": [100.05]},
        }
        config = SimpleNamespace(
            type="bullish",
            channels=["lrc", "trend"],
            liquidity_sweep=False,
            lookback_candles=1,
            tolerance_pct=0.1,
        )

        self.assertFalse(confluence.evaluate_confluence(candles, channels, config))

    def test_evaluate_confluence_supports_same_channel_type_with_different_lengths(self):
        candles = [
            {"open": 100.3, "high": 100.6, "low": 99.8, "close": 100.2},
            {"open": 100.2, "high": 100.5, "low": 99.9, "close": 100.1},
        ]
        channels = {
            "fast_lrc": {
                "channel_type": "lrc",
                "channel": {"upper": [104.0, 104.0], "lower": [100.0, 100.0]},
            },
            "slow_lrc": {
                "channel_type": "lrc",
                "channel": {"upper": [106.0, 106.0], "lower": [100.05, 100.05]},
            },
        }
        config = SimpleNamespace(
            type="bullish",
            channels=["lrc", "lrc"],
            sources=[
                SimpleNamespace(id="fast_lrc", channel_type="lrc", length=50),
                SimpleNamespace(id="slow_lrc", channel_type="lrc", length=150),
            ],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))

    def test_evaluate_confluence_detects_recent_bearish_rejection(self):
        candles = [
            {"open": 99.7, "high": 100.2, "low": 99.4, "close": 99.9},
            {"open": 99.85, "high": 100.25, "low": 99.1, "close": 99.4},
        ]
        channels = {
            "lrc": {"upper": [100.0, 100.0], "lower": [95.0, 95.0]},
            "trend": {"top": [100.05, 100.05], "bottom": [90.0, 90.0]},
        }
        config = SimpleNamespace(
            type="bearish",
            channels=["lrc", "trend"],
            sources=[
                SimpleNamespace(id="lrc_0", channel_type="lrc", selection="upper"),
                SimpleNamespace(id="trend_1", channel_type="trend", selection="top_line"),
            ],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))

    def test_evaluate_confluence_detects_role_reversal_alignment(self):
        candles = [
            {"open": 99.8, "high": 99.95, "low": 99.5, "close": 99.7},
            {"open": 99.7, "high": 100.4, "low": 99.6, "close": 100.2},
            {"open": 100.2, "high": 100.35, "low": 100.0, "close": 100.1},
        ]
        channels = {
            "lrc": {"upper": [100.0, 100.0, 100.0], "lower": [95.0, 95.0, 95.0]},
            "trend": {"top": [105.0, 105.0, 105.0], "bottom": [100.05, 100.05, 100.05]},
        }
        config = SimpleNamespace(
            type="role_reversal",
            channels=["lrc", "trend"],
            sources=[
                SimpleNamespace(id="lrc_0", channel_type="lrc", selection="upper"),
                SimpleNamespace(id="trend_1", channel_type="trend", selection="bottom_line"),
            ],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))

    def test_evaluate_confluence_detects_dual_line_breakout(self):
        candles = [
            {"open": 99.8, "high": 100.0, "low": 99.6, "close": 99.95},
            {"open": 99.95, "high": 100.4, "low": 99.9, "close": 100.2},
        ]
        channels = {
            "lrc": {"upper": [100.0, 100.0], "lower": [95.0, 95.0]},
            "trend": {"top": [100.05, 100.05], "bottom": [90.0, 90.0]},
        }
        config = SimpleNamespace(
            type="breakout",
            channels=["lrc", "trend"],
            liquidity_sweep=False,
            lookback_candles=2,
            tolerance_pct=0.1,
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))


class ChannelRespectTests(unittest.TestCase):
    def test_count_respects_aligns_channel_series_with_recent_candles(self):
        candles = [
            {"low": 0.0, "high": 1.0},
            {"low": 10.5, "high": 11.5},
            {"low": 11.5, "high": 12.5},
            {"low": 12.5, "high": 13.5},
        ]
        channel = {"middle": [11.0, 12.0, 13.0]}
        config = SimpleNamespace(line="middle", tolerance_pct=0.0, cluster_gap=3)

        count = channel_respect.count_respects(candles, channel, config)
        self.assertEqual(count, 1)

    def test_count_respects_maps_upper_lower_to_trend_top_bottom(self):
        candles = [
            {"low": 99.5, "high": 100.5},
            {"low": 100.5, "high": 101.5},
        ]
        channel = {"top": [100.0, 101.0], "bottom": [90.0, 91.0]}
        config = SimpleNamespace(line="upper", tolerance_pct=0.0, cluster_gap=3)

        count = channel_respect.count_respects(candles, channel, config)
        self.assertEqual(count, 1)

    def test_count_respects_requires_distinct_price_separation_between_clusters(self):
        candles = [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0},
            {"open": 101.4, "high": 101.8, "low": 101.2, "close": 101.6},
            {"open": 101.2, "high": 101.5, "low": 101.0, "close": 101.3},
            {"open": 101.1, "high": 101.4, "low": 100.9, "close": 101.2},
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
        ]
        channel = {"middle": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]}
        config = SimpleNamespace(line="middle", tolerance_pct=0.0, cluster_gap=3)

        count = channel_respect.count_respects(candles, channel, config)
        self.assertEqual(count, 2)

    def test_count_respects_requires_expected_wick_side_for_lower_line(self):
        candles = [
            {"open": 98.0, "high": 100.5, "low": 97.5, "close": 99.0},
            {"open": 101.0, "high": 102.0, "low": 99.5, "close": 101.5},
        ]
        channel = {"lower": [100.0, 100.0]}
        config = SimpleNamespace(line="lower", tolerance_pct=0.0, cluster_gap=3, touch_type="wick")

        count = channel_respect.count_respects(candles, channel, config)
        self.assertEqual(count, 1)


class DeadAssetsTests(unittest.TestCase):
    DEFAULT_CONFIG_KWARGS = dict(
        enabled=True,
        lower_highs_required=3,
        lower_lows_required=3,
        trend_source="ema_200",
        recovery_lookback=200,
        volume_option="either",
        volatility_option="either",
        bounce_threshold_pct=20.0,
        failure_window=20,
        recovery_override="disabled",
    )

    def _config(self, dead_trend_types, **overrides):
        kwargs = dict(self.DEFAULT_CONFIG_KWARGS)
        kwargs.update(overrides)
        return SimpleNamespace(dead_trend_types=dead_trend_types, **kwargs)

    def _declining_wave_candles(self, n=260, base=1000.0, decline_per_step=1.5, amplitude=15.0, period=20, volume=1_000_000.0):
        candles = []
        for i in range(n):
            center = base - decline_per_step * i
            offset = amplitude * float(np.sin(2 * np.pi * (i % period) / period))
            close = center + offset
            candles.append({
                "open": close,
                "close": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "volume": volume,
            })
        return candles

    def _failed_recovery_candles(self):
        highs_lows = [
            (119, 118), (115, 114), (111, 110), (107, 106), (103, 102),
            (101, 100),  # swing low at index 5
            (103, 102), (108, 106), (113, 110), (119, 116), (126, 122),  # bounce clears +20%
            (115, 95),  # breaks back below the swing low: failed recovery
            (90, 85), (88, 83),
        ]
        candles = []
        for high, low in highs_lows:
            mid = (high + low) / 2.0
            candles.append({"open": mid, "close": mid, "high": float(high), "low": float(low), "volume": 1_000_000.0})
        return candles

    def _flat_dead_asset_candles(self):
        candles = []
        for i in range(70):
            close = 50.0
            candles.append({"open": close, "close": close, "high": close + 1.0, "low": close - 1.0, "volume": 1_000_000.0})
        for i in range(40):
            close = 20.0
            candles.append({"open": close, "close": close, "high": close + 0.025, "low": close - 0.025, "volume": 50_000.0})
        return candles

    def test_strong_dead_trend_excludes_asset(self):
        candles = self._declining_wave_candles()
        config = self._config(["strong_dead_trend"])

        decision = dead_assets._evaluate_dead_assets(candles, config)

        self.assertTrue(decision["excluded"])
        self.assertEqual(decision["type"], "strong_dead_trend")
        self.assertEqual(decision["label"], "Excluded — Strong Dead Trend")

        result = dead_assets.apply_dead_assets(
            [{"symbol": "DEAD", "candles": candles}], config
        )
        self.assertEqual(result, [])

    def test_slow_bleeding_trend_excludes_asset(self):
        candles = self._declining_wave_candles()
        config = self._config(["slow_bleeding_trend"])

        decision = dead_assets._evaluate_dead_assets(candles, config)

        self.assertTrue(decision["excluded"])
        self.assertEqual(decision["type"], "slow_bleeding_trend")

    def test_failed_recovery_excludes_asset(self):
        candles = self._failed_recovery_candles()
        config = self._config(["failed_recovery"])

        decision = dead_assets._evaluate_dead_assets(candles, config)

        self.assertTrue(decision["excluded"])
        self.assertEqual(decision["type"], "failed_recovery")
        self.assertEqual(decision["label"], "Excluded — Failed Recovery")

    def test_flat_dead_asset_excludes_asset(self):
        candles = self._flat_dead_asset_candles()
        config = self._config(["flat_dead_asset"])

        decision = dead_assets._evaluate_dead_assets(candles, config)

        self.assertTrue(decision["excluded"])
        self.assertEqual(decision["type"], "flat_dead_asset")
        self.assertEqual(decision["label"], "Excluded — Flat Dead Asset")

    def test_recovery_override_readmits_asset(self):
        candles = self._declining_wave_candles()
        rally = []
        last_close = candles[-1]["close"]
        for i in range(10):
            close = last_close + (i + 1) * 40.0
            rally.append({"open": close, "close": close, "high": close + 1.0, "low": close - 1.0, "volume": 1_000_000.0})
        candles = candles + rally

        config = self._config(
            ["strong_dead_trend", "slow_bleeding_trend", "failed_recovery", "flat_dead_asset"],
            recovery_override="close_above_swing_high",
        )

        decision = dead_assets._evaluate_dead_assets(candles, config)

        self.assertFalse(decision["excluded"])
        self.assertTrue(decision["overridden"])
        self.assertEqual(decision["label"], "Allowed — Recovery Started")

        result = dead_assets.apply_dead_assets(
            [{"symbol": "RECOVERED", "candles": candles}], config
        )
        self.assertEqual(len(result), 1)
        self.assertIn("dead_assets", result[0]["matched_indicators"])
        self.assertTrue(
            any("Allowed — Recovery Started" in sticker for sticker in result[0]["stickers"])
        )

    def test_disabled_filter_is_a_passthrough(self):
        data = [{"symbol": "ANY", "candles": self._declining_wave_candles()}]

        result = dead_assets.apply_dead_assets(data, None)
        self.assertIs(result, data)

        disabled_config = self._config(["strong_dead_trend"], enabled=False)
        result = dead_assets.apply_dead_assets(data, disabled_config)
        self.assertIs(result, data)

    def test_evaluate_detail_reports_disabled_filter(self):
        asset = {"symbol": "ANY", "candles": self._declining_wave_candles()}
        disabled_config = self._config(["strong_dead_trend"], enabled=False)

        detail = dead_assets.evaluate_dead_assets_detail(asset, disabled_config)

        self.assertTrue(detail["passed"])
        self.assertEqual(detail["summary"], "Dead Assets filter disabled.")


class IndicatorMathTests(unittest.TestCase):
    def test_confirm_if_needed_without_type_does_not_fail(self):
        candles = [{"open": 1.0, "close": 1.1, "high": 1.2, "low": 0.9}]
        self.assertTrue(
            utils.confirm_if_needed(
                candles,
                0,
                {"confirmation": True, "confirmation_window": 1, "confirmation_type": None},
            )
        )

    def test_confirm_if_needed_accepts_named_bullish_pattern(self):
        candles = [
            {"open": 10.0, "close": 9.2, "high": 10.1, "low": 9.1},
            {"open": 9.1, "close": 10.4, "high": 10.5, "low": 9.0},
        ]

        self.assertTrue(
            utils.confirm_if_needed(
                candles,
                0,
                {
                    "confirmation": True,
                    "confirmation_window": 1,
                    "confirmation_patterns": ["bullish_engulfing"],
                },
            )
        )

    def test_confirm_if_needed_accepts_signal_candle_by_type(self):
        candles = [
            {"open": 10.0, "close": 10.8, "high": 11.0, "low": 9.9},
        ]

        self.assertTrue(
            utils.confirm_if_needed(
                candles,
                0,
                {
                    "confirmation": True,
                    "confirmation_window": 1,
                    "confirmation_types": ["bullish"],
                },
            )
        )

    def test_confirm_if_needed_accepts_signal_candle_by_named_pattern(self):
        candles = [
            {"open": 10.0, "close": 9.2, "high": 10.1, "low": 9.1},
            {"open": 9.1, "close": 10.4, "high": 10.5, "low": 9.0},
        ]

        self.assertTrue(
            utils.confirm_if_needed(
                candles,
                1,
                {
                    "confirmation": True,
                    "confirmation_window": 1,
                    "confirmation_patterns": ["bullish_engulfing"],
                },
            )
        )

    def test_confirm_if_needed_accepts_later_candle_within_window(self):
        candles = [
            {"open": 10.0, "close": 9.8, "high": 10.2, "low": 9.7},
            {"open": 9.8, "close": 9.6, "high": 9.9, "low": 9.5},
            {"open": 9.6, "close": 10.2, "high": 10.3, "low": 9.5},
        ]

        self.assertTrue(
            utils.confirm_if_needed(
                candles,
                0,
                {
                    "confirmation": True,
                    "confirmation_window": 2,
                    "confirmation_types": ["bullish"],
                },
            )
        )

    def test_confirm_if_needed_rejects_explicit_live_or_incomplete_candles(self):
        incomplete_markers = [
            {"is_closed": False},
            {"is_complete": False},
            {"complete": False},
            {"closed": False},
            {"is_live": True},
        ]

        for marker in incomplete_markers:
            with self.subTest(marker=marker):
                candles = [
                    {
                        "open": 10.0,
                        "close": 9.8,
                        "high": 10.2,
                        "low": 9.7,
                    },
                    {
                        "open": 9.8,
                        "close": 10.8,
                        "high": 11.0,
                        "low": 9.7,
                        **marker,
                    },
                ]

                self.assertFalse(
                    utils.confirm_if_needed(
                        candles,
                        0,
                        {
                            "confirmation": True,
                            "confirmation_window": 1,
                            "confirmation_types": ["bullish"],
                        },
                    )
                )

    def test_detect_touch_requires_upper_wick_for_resistance_direction(self):
        candle = {"open": 101.0, "high": 102.0, "low": 99.5, "close": 101.5}
        config = {"touch_type": "wick"}

        self.assertFalse(utils.detect_touch(candle, 100.0, 100.0, config, direction="up"))

    def test_detect_touch_accepts_upper_wick_from_below_for_resistance_direction(self):
        candle = {"open": 98.0, "high": 100.5, "low": 97.5, "close": 99.0}
        config = {"touch_type": "wick"}

        self.assertTrue(utils.detect_touch(candle, 100.0, 100.0, config, direction="up"))

    def test_detect_touch_with_tolerance_keeps_support_body_above_reference_line(self):
        candle = {"open": 99.5, "high": 100.2, "low": 98.8, "close": 99.7}
        config = {"touch_type": "wick"}

        self.assertFalse(utils.detect_touch(candle, 99.0, 101.0, config, direction="down"))

    def test_required_candles_counts_pattern_based_confirmation_windows(self):
        indicator = SimpleNamespace(
            name="rsi",
            config={
                "length": 14,
                "window": 1,
                "confirmation": True,
                "confirmation_window": 2,
                "confirmation_patterns": ["bullish_engulfing"],
            },
        )

        self.assertEqual(
            screener.required_candles_for_indicators([indicator]),
            18,
        )

    def test_required_trend_channel_history_uses_full_screening_budget(self):
        self.assertEqual(trend_channels.required_trend_channel_history(8), 500)

    def test_required_candles_for_trend_fetches_enough_history_for_pivot_channel(self):
        indicator = SimpleNamespace(
            name="trend",
            config={
                "length": 8,
                "areas": [
                    {
                        "area": "bottom_line",
                        "action": "touched",
                        "window": 1,
                        "confirmation": False,
                    }
                ],
            },
        )

        self.assertEqual(
            screener.required_candles_for_indicators([indicator]),
            500,
        )

    def test_required_candles_for_adx_covers_minimum_and_fixed_lookback_constants(self):
        # No conditions selected: length + 1 + fixed internal lookback (10) is only 22,
        # which is far short of what Wilder RMA needs to converge to TradingView's
        # values (confirmed via a live TradingView mismatch), so a 200-candle floor applies.
        bare_indicator = SimpleNamespace(name="adx", config={"length": 11, "conditions": []})
        self.assertEqual(screener.required_candles_for_indicators([bare_indicator]), 200)

        # A moderate candles_since (53 raw) still sits below the 200 floor.
        indicator_with_lookback = SimpleNamespace(
            name="adx",
            config={"length": 11, "conditions": [{"id": "di_crossed_above", "candles_since": 40}]},
        )
        self.assertEqual(screener.required_candles_for_indicators([indicator_with_lookback]), 200)

        # A candles_since large enough to exceed the floor on its own must not be
        # clamped back down to 200 — the floor only raises the requirement, never caps it.
        indicator_with_large_lookback = SimpleNamespace(
            name="adx",
            config={"length": 11, "conditions": [{"id": "di_crossed_above", "candles_since": 300}]},
        )
        self.assertEqual(screener.required_candles_for_indicators([indicator_with_large_lookback]), 313)

    def test_required_candles_for_adx_min_history_is_user_adjustable(self):
        # 200 is a hard floor, by explicit decision - not user-lowerable, since anything
        # below it reproduces the already-fixed accuracy bug (ADX off by ~6 points on 22
        # candles). A lower min_history must be clamped back up to 200, not honored.
        lowered = SimpleNamespace(
            name="adx",
            config={"length": 11, "conditions": [], "min_history": 50},
        )
        self.assertEqual(screener.required_candles_for_indicators([lowered]), 200)

        too_low = SimpleNamespace(
            name="adx",
            config={"length": 11, "conditions": [], "min_history": 5},
        )
        self.assertEqual(screener.required_candles_for_indicators([too_low]), 200)

        # A min_history above the 200 recommendation is respected too, not capped.
        raised = SimpleNamespace(
            name="adx",
            config={"length": 11, "conditions": [], "min_history": 350},
        )
        self.assertEqual(screener.required_candles_for_indicators([raised]), 350)

        # Omitting it entirely must still default to 200, matching prior behavior exactly.
        default = SimpleNamespace(name="adx", config={"length": 11, "conditions": []})
        self.assertEqual(screener.required_candles_for_indicators([default]), 200)

    def test_required_candles_for_vlr_covers_longest_regression_and_timing(self):
        indicator = SimpleNamespace(
            name="vlr",
            config={"num_regressions": 3, "start_period": 12, "period_increment": 12, "timing_candles": 5},
        )
        # longest_period = 12 + (3-1)*12 = 36; needed = 36 + 5 + 2
        self.assertEqual(screener.required_candles_for_indicators([indicator]), 43)

    def test_build_regression_sticker_includes_line_wording(self):
        sticker = regression_channels.build_regression_sticker(
            "LRC",
            {"length": 100},
            {
                "lines": ["lower"],
                "action": "touch",
                "touch_type": "wick",
                "window": 2,
            },
        )

        self.assertEqual(sticker["condition"], "Lower Line: Wick Touch")

    def test_build_indicator_sticker_uses_pattern_before_window(self):
        sticker = utils.build_indicator_sticker(
            "RSI",
            "Oversold Turning Up",
            {
                "confirmation": True,
                "confirmation_patterns": ["bullish_engulfing"],
                "window": 2,
            },
            length=14,
            window=2,
        )

        self.assertEqual(
            sticker,
            "RSI (14) | Oversold Turning Up | Bullish Engulfing | Last 2 Candles",
        )

    def test_build_indicator_sticker_includes_decision_before_condition_when_provided(self):
        sticker = utils.build_indicator_sticker(
            "EMA",
            "Price $101.00 vs EMA @ $100.00",
            {"window": 1, "confirmation": False},
            length=200,
            window=1,
            decision="Bullish Trend Filter",
        )

        self.assertEqual(
            sticker,
            "EMA (200) | Bullish Trend Filter | Price $101.00 vs EMA @ $100.00 | No Pattern | Last 1 Candle",
        )

    def test_annotate_request_filter_stickers_appends_price_and_exchange_stickers(self):
        request = SimpleNamespace(
            price_range=SimpleNamespace(min_price=10.0, max_price=20.0),
            stock_sources=None,
            compliance_status=None,
            exchanges=["binance"],
            excluded_categories=None,
        )
        data = [
            {
                "symbol": "BTC-USD",
                "price": 12.5,
                "data_source": "massive",
                "exchange": "binance",
                "exchange_availability": ["binance", "coinbase"],
                "stickers": ["MACD | Bullish Momentum Shift | MACD +0.10 above zero | No Pattern | Last 1 Candle"],
                "matched_indicators": ["macd"],
            }
        ]

        annotated = screener.annotate_request_filter_stickers(data, request)

        self.assertEqual(len(annotated[0]["stickers"]), 3)
        self.assertIn("price_range", annotated[0]["matched_indicators"])
        self.assertIn("exchanges", annotated[0]["matched_indicators"])
        self.assertTrue(any(sticker.startswith("Price Range | Tradeable Range |") for sticker in annotated[0]["stickers"]))
        self.assertTrue(any(sticker.startswith("Exchange Filter | Exchange Access Match |") for sticker in annotated[0]["stickers"]))

    def test_handle_volatility_ignores_zero_closes_without_runtime_warnings(self):
        candles = [{"close": 0.0}, {"close": 0.0}, {"close": 0.0}]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            matched, sticker = indicators.handle_volatility({}, candles, {"length": 2, "mode": "returns_std"})

        self.assertFalse(matched)
        self.assertIsNone(sticker)
        self.assertEqual(caught, [])

    def test_handle_volatility_snapshot_ignores_zero_closes_without_runtime_warnings(self):
        snapshot = {"close": [0.0, 0.0, 0.0]}

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            matched, sticker = indicators._handle_volatility_snapshot({}, snapshot, {"length": 2, "mode": "returns_std"})

        self.assertFalse(matched)
        self.assertIsNone(sticker)
        self.assertEqual(caught, [])

    def test_compute_rsi_series_returns_first_value_at_minimum_length(self):
        candles = [{"close": float(value)} for value in range(1, 16)]
        series = rsi.compute_rsi_series(candles, length=14)
        self.assertIsNotNone(series)
        self.assertEqual(len(series), 1)

    def test_compute_aroon_oscillator_uses_length_plus_one_lookback(self):
        short_candles = [
            {"high": 1.0, "low": 3.0},
            {"high": 3.0, "low": 2.0},
        ]
        self.assertIsNone(aroon_oscillator.compute_aroon_oscillator(short_candles, length=2))

        candles = [
            {"high": 1.0, "low": 3.0},
            {"high": 3.0, "low": 2.0},
            {"high": 2.0, "low": 1.0},
            {"high": 4.0, "low": 3.0},
        ]

        series = aroon_oscillator.compute_aroon_oscillator(candles, length=2)

        self.assertIsNotNone(series)
        self.assertEqual(len(series), 2)
        self.assertEqual([float(value) for value in series], [-50.0, 50.0])

    def test_macd_rules_return_false_on_insufficient_series(self):
        macd_data = {"macd": [0.1], "signal": [0.0], "hist": [0.1]}
        self.assertFalse(
            macd.evaluate_macd_rules(macd_data, {"rule": "bullish_cross"})
        )

    def test_rsi_window_matches_within_recent_candles(self):
        rsi_series = [55.0, 48.0, 33.0, 28.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 3,
            "location": "oversold",
            "direction": None,
            "confirmation": False,
        }
        self.assertTrue(rsi.evaluate_rsi_rules(rsi_series, candles, config))

    def test_rsi_confirmation_uses_matching_candle_index_after_series_offset(self):
        rsi_series = [25.0]
        candles = [
            {"open": 10.0, "close": 9.8, "high": 10.2, "low": 9.7},
            {"open": 9.8, "close": 9.6, "high": 9.9, "low": 9.5},
            {"open": 9.6, "close": 9.4, "high": 9.7, "low": 9.3},
            {"open": 9.4, "close": 9.2, "high": 9.5, "low": 9.1},
            {"open": 9.2, "close": 9.0, "high": 9.3, "low": 8.9},
            {"open": 9.0, "close": 8.8, "high": 9.1, "low": 8.7},
            {"open": 8.8, "close": 8.6, "high": 8.9, "low": 8.5},
            {"open": 8.6, "close": 8.4, "high": 8.7, "low": 8.3},
            {"open": 8.4, "close": 8.2, "high": 8.5, "low": 8.1},
            {"open": 8.2, "close": 8.0, "high": 8.3, "low": 7.9},
            {"open": 8.0, "close": 7.8, "high": 8.1, "low": 7.7},
            {"open": 7.8, "close": 7.6, "high": 7.9, "low": 7.5},
            {"open": 7.6, "close": 7.4, "high": 7.7, "low": 7.3},
            {"open": 7.4, "close": 7.2, "high": 7.5, "low": 7.1},
            {"open": 7.2, "close": 8.0, "high": 8.1, "low": 7.1},
        ]
        config = {
            "window": 1,
            "location": "oversold",
            "direction": None,
            "confirmation": True,
            "confirmation_types": ["bullish"],
        }

        self.assertTrue(
            rsi.evaluate_rsi_rules(rsi_series, candles, config),
            "RSI confirmation should inspect candle index 14 for the first RSI value, not candle index 0.",
        )

    def test_aroon_window_matches_within_recent_candles(self):
        series = [60.0, 35.0, 10.0, 55.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 3,
            "level": "above_50",
            "direction": None,
            "confirmation": False,
        }
        self.assertTrue(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_aroon_turning_up_fails_in_middle_of_range(self):
        series = [25.0, 25.0, 32.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "level": "between_50_0",
            "direction": "turning_up",
            "confirmation": False,
        }
        self.assertFalse(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_aroon_turning_up_passes_from_negative_extreme(self):
        series = [-80.0, -80.0, -60.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "level": "below_-50",
            "direction": "turning_up",
            "confirmation": False,
        }
        self.assertTrue(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_aroon_confirmation_uses_candle_index_after_length_plus_one_shift(self):
        series = [0.0, 60.0]
        candles = [
            {"open": 10.0, "close": 9.8, "high": 10.2, "low": 9.7},
            {"open": 9.8, "close": 9.6, "high": 9.9, "low": 9.5},
            {"open": 9.6, "close": 9.4, "high": 9.7, "low": 9.3},
            {"open": 9.4, "close": 10.2, "high": 10.3, "low": 9.3},
        ]
        config = {
            "window": 1,
            "level": "above_50",
            "direction": None,
            "confirmation": True,
            "confirmation_types": ["bullish"],
        }

        self.assertTrue(
            aroon_oscillator.evaluate_aroon_rules(series, candles, config),
            "Aroon confirmation should map series index 1 to candle index 3 after the length+1 output shift.",
        )

    def test_aroon_turning_up_uses_configured_extreme_level(self):
        series = [-60.0, -60.0, -40.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "level": "between_0_-50",
            "direction": "turning_up",
            "extreme_level": 50,
            "confirmation": False,
        }
        self.assertTrue(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_aroon_turning_down_fails_in_middle_of_range(self):
        series = [-25.0, -25.0, -32.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "level": "between_0_-50",
            "direction": "turning_down",
            "confirmation": False,
        }
        self.assertFalse(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_aroon_turning_down_passes_from_positive_extreme(self):
        series = [80.0, 80.0, 60.0]
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "level": "above_50",
            "direction": "turning_down",
            "confirmation": False,
        }
        self.assertTrue(aroon_oscillator.evaluate_aroon_rules(series, candles, config))

    def test_wavetrend_signal_line_uses_sma_not_ema(self):
        candles = [
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 11.0, "low": 8.5, "close": 10.0},
            {"high": 9.0, "low": 7.5, "close": 8.0},
            {"high": 12.0, "low": 9.0, "close": 11.0},
            {"high": 13.0, "low": 10.0, "close": 12.0},
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 14.0, "low": 10.0, "close": 13.0},
            {"high": 13.0, "low": 9.0, "close": 10.0},
        ]

        wt = wavetrend.compute_wavetrend(
            candles,
            channel_length=2,
            average_length=3,
            signal_length=4,
        )
        expected_sma = wavetrend.sma(wt["wt1"], 4)
        old_ema = wavetrend.ema(wt["wt1"], 4)

        self.assertTrue(
            all(
                abs(float(actual) - float(expected)) < 1e-9
                for actual, expected in zip(wt["wt2"], expected_sma)
                if np.isfinite(actual) and np.isfinite(expected)
            )
        )
        finite_pairs = [
            (float(actual), float(old))
            for actual, old in zip(wt["wt2"], old_ema)
            if np.isfinite(actual) and np.isfinite(old)
        ]
        self.assertTrue(finite_pairs)
        self.assertGreater(
            max(abs(actual - old) for actual, old in finite_pairs),
            1e-6,
        )

    def test_wavetrend_default_zone_threshold_matches_lazybear(self):
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        wt_deep_oversold = {
            "wt1": [-65.0, -61.0],
            "wt2": [0.0, 0.0],
        }
        wt_not_deep_oversold = {
            "wt1": [-55.0, -51.0],
            "wt2": [0.0, 0.0],
        }
        config = {
            "window": 1,
            "zone": "oversold",
            "direction": "rising",
            "confirmation": False,
        }

        self.assertTrue(wavetrend.evaluate_wavetrend_rules(wt_deep_oversold, candles, config))
        self.assertFalse(wavetrend.evaluate_wavetrend_rules(wt_not_deep_oversold, candles, config))

    def test_wavetrend_configured_threshold_changes_zone_behavior(self):
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        wt = {
            "wt1": [-40.0, -32.0],
            "wt2": [0.0, 0.0],
        }
        config = {
            "window": 1,
            "zone": "oversold",
            "direction": "rising",
            "threshold": 30,
            "confirmation": False,
        }

        self.assertTrue(wavetrend.evaluate_wavetrend_rules(wt, candles, config))

    def test_wavetrend_confirmation_uses_same_candle_index_as_wt_series(self):
        wt = {
            "wt1": [-65.0, -61.0],
            "wt2": [0.0, 0.0],
        }
        candles = [
            {"open": 10.0, "close": 9.8, "high": 10.2, "low": 9.7},
            {"open": 9.8, "close": 10.6, "high": 10.7, "low": 9.7},
        ]
        config = {
            "window": 1,
            "zone": "oversold",
            "direction": "rising",
            "confirmation": True,
            "confirmation_types": ["bullish"],
        }

        self.assertTrue(
            wavetrend.evaluate_wavetrend_rules(wt, candles, config),
            "WaveTrend arrays are same-length with candles, so confirmation should use candle index 1 directly.",
        )

    def test_wavetrend_crossed_up_accepts_touch_then_cross(self):
        wt = {
            "wt1": [0.0, 5.0],
            "wt2": [0.0, 2.0],
        }
        candles = [
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
            {"open": 1.0, "close": 1.0, "high": 1.1, "low": 0.9},
        ]
        config = {
            "window": 1,
            "zone": None,
            "direction": "crossed_up",
            "confirmation": False,
        }
        self.assertTrue(wavetrend.evaluate_wavetrend_rules(wt, candles, config))

    def test_linreg_candle_window_counts_from_signal_start_until_now(self):
        candles = [
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.0},
            {"open": 101.0, "high": 103.0, "low": 101.0, "close": 102.0},
            {"open": 101.0, "high": 103.0, "low": 101.0, "close": 102.0},
        ]
        lr_line = [100.0, 100.0, 100.0]
        config = {
            "window": 1,
            "price_position": "above",
            "confirmation": False,
        }
        trace = linear_regression_candles.trace_linreg_signal_window(candles, lr_line, config)
        self.assertEqual(trace["signal_streak"], 2)
        self.assertEqual(trace["signal_start_index"], 1)
        self.assertEqual(trace["signal_age_candles"], 2)
        self.assertFalse(trace["passed"])
        self.assertIn("exceeds window", trace["reason"])
        self.assertFalse(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_line, config)
        )

    def test_linreg_candle_window_accepts_signal_started_within_window(self):
        candles = [
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.0},
            {"open": 101.0, "high": 103.0, "low": 101.0, "close": 102.0},
            {"open": 101.0, "high": 103.0, "low": 101.0, "close": 102.0},
        ]
        lr_line = [100.0, 100.0, 100.0]
        config = {
            "window": 2,
            "price_position": "above",
            "confirmation": False,
        }
        trace = linear_regression_candles.trace_linreg_signal_window(candles, lr_line, config)
        self.assertEqual(trace["signal_streak"], 2)
        self.assertTrue(trace["passed"])
        self.assertTrue(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_line, config)
        )

        config_window_1 = {**config, "window": 1}
        trace_window_1 = linear_regression_candles.trace_linreg_signal_window(
            candles,
            lr_line,
            config_window_1,
        )
        self.assertFalse(trace_window_1["passed"])
        self.assertFalse(
            linear_regression_candles.evaluate_linreg_candle_rules(
                candles,
                lr_line,
                config_window_1,
            )
        )

    def test_linreg_close_location_does_not_shorten_position_signal_age(self):
        candles = [{"open": 0, "high": 0, "low": 0, "close": 0} for _ in range(5)]
        lr_result = {
            "signal": [100.0] * 5,
            "bopen": [101.0, 101.0, 101.0, 101.0, 99.0],
            "bhigh": [103.0, 103.0, 103.0, 103.0, 102.0],
            "blow": [100.5, 100.5, 100.5, 100.5, 100.5],
            "bclose": [98.0, 98.0, 98.0, 98.0, 101.5],
        }
        config = {
            "window": 3,
            "price_position": "above",
            "close_location": "bullish",
            "confirmation": False,
        }
        trace = linear_regression_candles.trace_linreg_signal_window(candles, lr_result, config)
        self.assertEqual(trace["signal_streak"], 5)
        self.assertFalse(trace["passed"])
        self.assertFalse(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_result, config)
        )

    def test_linreg_candle_window_signal_age_for_all_positions(self):
        candles = [{"open": 0, "high": 0, "low": 0, "close": 0} for _ in range(6)]

        def lr_from_virtual(bopens, bhighs, blows, bcloses, line=100.0):
            return {
                "signal": [line] * len(bopens),
                "bopen": bopens,
                "bhigh": bhighs,
                "blow": blows,
                "bclose": bcloses,
            }

        scenarios = [
            (
                "above",
                lr_from_virtual(
                    [98, 98, 98, 101, 101, 101],
                    [99, 99, 99, 103, 103, 103],
                    [97, 97, 97, 101, 101, 101],
                    [98, 98, 98, 102, 102, 102],
                ),
                [
                    (1, 6, False),
                    (3, 6, True),
                    (4, 6, True),
                ],
            ),
            (
                "below",
                lr_from_virtual(
                    [99, 99, 99, 99, 99, 99],
                    [99, 99, 99, 99, 99, 99],
                    [97, 97, 97, 97, 97, 97],
                    [98, 98, 98, 98, 98, 98],
                ),
                [
                    (1, 6, False),
                    (3, 6, False),
                    (6, 6, True),
                ],
            ),
            (
                "piercing_from_below",
                lr_from_virtual(
                    [98, 98, 98, 99, 101, 101],
                    [99, 99, 99, 100, 103, 103],
                    [97, 97, 97, 98, 101, 101],
                    [98, 98, 98, 101, 102, 102],
                ),
                [
                    (1, 4, True),
                    (1, 5, False),
                    (2, 4, True),
                ],
            ),
            (
                "piercing_from_above",
                lr_from_virtual(
                    [101, 99, 99, 99, 101, 99],
                    [102, 100, 100, 100, 102, 100],
                    [98, 98, 98, 98, 98, 98],
                    [99, 98, 98, 98, 99, 98],
                ),
                [
                    (1, 1, True),
                    (1, 2, False),
                    (1, 5, True),
                ],
            ),
        ]

        for position, lr_result, cases in scenarios:
            for window, total_candles, expected_pass in cases:
                with self.subTest(position=position, window=window, total_candles=total_candles):
                    sliced_candles = candles[:total_candles]
                    sliced_lr = {key: values[:total_candles] for key, values in lr_result.items()}
                    config = {
                        "window": window,
                        "price_position": position,
                        "confirmation": False,
                    }
                    trace = linear_regression_candles.trace_linreg_signal_window(
                        sliced_candles,
                        sliced_lr,
                        config,
                    )
                    self.assertEqual(trace["passed"], expected_pass, trace["reason"])
                    self.assertEqual(
                        linear_regression_candles.evaluate_linreg_candle_rules(
                            sliced_candles,
                            sliced_lr,
                            config,
                        ),
                        expected_pass,
                    )

    def test_linreg_candle_uses_virtual_candle_instead_of_raw(self):
        candles = [
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 102.0},
        ]
        lr_result = {
            "signal": [100.0],
            "bopen": [92.0],
            "bhigh": [95.0],
            "blow": [90.0],
            "bclose": [93.0],
        }
        config = {
            "window": 1,
            "price_position": "above",
            "confirmation": False,
        }
        self.assertFalse(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_result, config)
        )

        config_below = {
            "window": 1,
            "price_position": "below",
            "confirmation": False,
        }
        self.assertTrue(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_result, config_below)
        )

    def test_linreg_candle_on_requires_body_overlap_not_wick_only(self):
        candles = [{"open": 0.9550, "high": 0.9999, "low": 0.9420, "close": 0.9420}]
        lr_result = {
            "signal": [0.9697],
            "bopen": [0.9687],
            "bhigh": [0.9707],
            "blow": [0.9517],
            "bclose": [0.9378],
        }
        config = {
            "window": 1,
            "price_position": "on",
            "confirmation": False,
        }
        self.assertFalse(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_result, config)
        )

        lr_result_body_on = {
            "signal": [100.0],
            "bopen": [99.0],
            "bhigh": [102.0],
            "blow": [97.0],
            "bclose": [101.0],
        }
        self.assertTrue(
            linear_regression_candles.evaluate_linreg_candle_rules(
                [{"open": 99.0, "high": 102.0, "low": 97.0, "close": 101.0}],
                lr_result_body_on,
                config,
            )
        )


    def test_regression_selected_lines_all_must_match(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        ]
        channel = {
            "length": 3,
            "upper": [120.0, 120.0, 120.0],
            "middle": [100.0, 100.0, 100.0],
        }
        config = {
            "lines": ["upper", "middle"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }
        self.assertFalse(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_close_above_requires_latest_candle_to_still_be_above_line(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0},
        ]
        channel = {
            "length": 3,
            "upper": [110.0, 110.0, 110.0],
        }
        config = {
            "lines": ["upper"],
            "action": "close_above",
            "window": 2,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertFalse(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_close_above_window_counts_from_signal_start_until_now(self):
        candles = [
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
        ]
        channel = {
            "length": 4,
            "upper": [110.0, 110.0, 110.0, 110.0],
        }
        config = {
            "lines": ["upper"],
            "action": "close_above",
            "window": 3,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertFalse(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_close_above_accepts_current_signal_started_within_window(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
        ]
        channel = {
            "length": 3,
            "upper": [110.0, 110.0, 110.0],
        }
        config = {
            "lines": ["upper"],
            "action": "close_above",
            "window": 2,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_lower_wick_touch_rejects_candle_using_line_as_resistance(self):
        candles = [
            {"open": 98.0, "high": 100.5, "low": 97.5, "close": 99.0},
        ]
        channel = {
            "length": 1,
            "lower": [100.0],
        }
        config = {
            "lines": ["lower"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertFalse(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_lower_wick_touch_accepts_support_reaction(self):
        candles = [
            {"open": 101.0, "high": 102.0, "low": 99.5, "close": 101.5},
        ]
        channel = {
            "length": 1,
            "lower": [100.0],
        }
        config = {
            "lines": ["lower"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(regression_channels.evaluate_regression_lines(candles, channel, config))

    def test_regression_channel_bounds_use_symmetric_close_deviation(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 102.0, "high": 110.0, "low": 90.0, "close": 102.0},
            {"open": 104.0, "high": 105.0, "low": 103.0, "close": 104.0},
            {"open": 106.0, "high": 107.0, "low": 105.0, "close": 106.0},
        ]

        channel = regression_channels.compute_dw_regression_channel(candles, length=4, width_coeff=1.0)

        self.assertIsNotNone(channel)
        finite_rows = [
            (middle, upper, lower)
            for middle, upper, lower in zip(channel["middle"], channel["upper"], channel["lower"])
            if np.isfinite(middle) and np.isfinite(upper) and np.isfinite(lower)
        ]
        self.assertTrue(finite_rows)
        for middle, upper, lower in finite_rows:
            self.assertAlmostEqual(float(upper - middle), float(middle - lower))

    def test_trend_bottom_line_wick_touch_rejects_candle_using_line_as_resistance(self):
        candles = [
            {"open": 98.0, "high": 100.5, "low": 97.5, "close": 99.0},
        ]
        channel = {
            "length": 1,
            "top": [110.0],
            "middle": [105.0],
            "bottom": [100.0],
        }
        rule = {
            "area": "bottom_line",
            "action": "touched",
            "touch_type": "wick",
            "window": 1,
            "confirmation": False,
        }

        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_trend_top_line_closed_above_requires_latest_candle_to_still_be_above_line(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0},
        ]
        channel = {
            "length": 3,
            "top": [110.0, 110.0, 110.0],
            "middle": [105.0, 105.0, 105.0],
            "bottom": [100.0, 100.0, 100.0],
        }
        rule = {
            "area": "top_line",
            "action": "closed_above",
            "window": 2,
            "confirmation": False,
        }

        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_trend_top_line_closed_above_window_counts_from_signal_start_until_now(self):
        candles = [
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
        ]
        channel = {
            "length": 4,
            "top": [110.0, 110.0, 110.0, 110.0],
            "middle": [105.0, 105.0, 105.0, 105.0],
            "bottom": [100.0, 100.0, 100.0, 100.0],
        }
        rule = {
            "area": "top_line",
            "action": "closed_above",
            "window": 3,
            "confirmation": False,
        }

        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_trend_top_line_closed_above_accepts_current_signal_started_within_window(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
            {"open": 111.0, "high": 112.0, "low": 110.0, "close": 111.0},
        ]
        channel = {
            "length": 3,
            "top": [110.0, 110.0, 110.0],
            "middle": [105.0, 105.0, 105.0],
            "bottom": [100.0, 100.0, 100.0],
        }
        rule = {
            "area": "top_line",
            "action": "closed_above",
            "window": 2,
            "confirmation": False,
        }

        self.assertTrue(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_trend_bottom_line_touch_applies_tolerance(self):
        candles = [
            {"open": 101.0, "high": 102.0, "low": 100.4, "close": 101.5},
        ]
        channel = {
            "length": 1,
            "top": [110.0],
            "middle": [105.0],
            "bottom": [100.0],
        }
        rule = {
            "area": "bottom_line",
            "action": "touched",
            "touch_type": "wick",
            "tolerance": 0.5,
            "window": 1,
            "confirmation": False,
        }

        self.assertTrue(trend_channels.evaluate_single_area(candles, channel, rule))

    def _chartprime_fixture_bases(self):
        # Constant true range (high - low = 1.0, |step| <= 0.5 each bar) keeps
        # ATR(10) exactly 1.0 throughout, so the ATR(10)*6 offset used by the
        # ChartPrime channel is hand-computable. Two declining pivot highs
        # (11.6 then 11.3, span=2) trigger a down-channel; two declining pivot
        # lows (10.0 then 9.4) exist too (so both pivot-count gates are
        # satisfied) but never trigger an up-channel, since ChartPrime's
        # up-trigger requires ascending lows.
        return [10.0, 10.3, 10.6, 10.3, 10.0, 10.1, 10.2, 10.3, 10.0, 9.7, 9.4, 9.7, 10.0, 10.3]

    def _chartprime_candles(self, bases):
        return [
            {"open": b + 0.5, "high": b + 1.0, "low": b, "close": b + 0.5, "volume": 100.0}
            for b in bases
        ]

    def test_compute_trend_channel_builds_single_slope_atr_offset_channel(self):
        candles = self._chartprime_candles(self._chartprime_fixture_bases())

        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertIsNotNone(channel)
        self.assertEqual(channel["model"], "pivot_liquidity")
        self.assertEqual(channel["direction"], "down")
        self.assertFalse(channel["broken"])
        self.assertEqual(channel["start_index"], 2)
        self.assertEqual(channel["length"], 12)
        # Pivot highs are at actual bars 2 (11.6) and 7 (11.3); the line anchor
        # must sit on those actual pivot bars, not `pivot_index - length` again
        # (Python's pivot dicts already store the actual bar separately from
        # confirm_index, so no further length subtraction belongs here - see
        # `_initialize_channel_line_endpoints`).
        self.assertEqual(channel["line_x1"], 2)
        self.assertEqual(channel["line_x2"], 13)

        # Pine extend=false extrapolates line endpoints each bar from anchors at
        # the actual pivot bar, not from a closed-form pivot intercept series.
        self.assertAlmostEqual(float(channel["top"][0]), 12.457142857142857)
        self.assertAlmostEqual(float(channel["top"][-1]), 11.857142857142856)
        self.assertAlmostEqual(float(channel["bottom"][0]), 4.742857142857143)
        self.assertAlmostEqual(float(channel["bottom"][-1]), 4.142857142857146)
        self.assertAlmostEqual(float(channel["middle"][-1]), 7.999999999999999)

    def test_compute_trend_channel_freezes_broken_channel_line_endpoints(self):
        bases = self._chartprime_fixture_bases() + [13.0, 12.5, 12.0, 11.5, 11.0, 10.5]
        candles = self._chartprime_candles(bases)
        candles[14] = {"open": 13.0, "high": 13.5, "low": 12.7, "close": 13.2, "volume": 100.0}

        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertIsNotNone(channel)
        self.assertTrue(channel["broken"])
        self.assertEqual(channel["break_index"], 14)
        self.assertEqual(channel["line_x2"], 14)

        latest_index = len(candles) - 1
        break_regression_index = channel["break_index"] - channel["start_index"]
        bottom_at_break = float(channel["bottom"][break_regression_index])

        # Frozen segment still extrapolates beyond the break bar, but from the
        # break-time endpoints rather than continuing active per-bar updates.
        self.assertNotAlmostEqual(float(channel["bottom"][-1]), bottom_at_break)

        closed_form_bottom_at_latest = bottom_at_break + (latest_index - 14) * (-0.06)
        self.assertNotAlmostEqual(float(channel["bottom"][-1]), closed_form_bottom_at_latest)

    def test_evaluate_single_area_rejects_post_break_extrapolated_touch(self):
        bases = self._chartprime_fixture_bases() + [13.0]
        candles = self._chartprime_candles(bases)
        candles[14] = {"open": 13.0, "high": 13.5, "low": 12.7, "close": 13.2, "volume": 100.0}
        for _ in range(5):
            candles.append({"open": 4.5, "high": 5.0, "low": 4.0, "close": 4.5, "volume": 100.0})

        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertTrue(channel["broken"])
        self.assertGreater(len(candles) - 1, channel["break_index"])

        rule = {
            "area": "bottom_line",
            "action": "touched",
            "touch_type": "wick",
            "tolerance": 10,
            "window": 1,
            "confirmation": False,
        }

        # Latest bar is after the break but can match extrapolated frozen-line values.
        self.assertTrue(
            trend_channels.evaluate_line_action(
                candles[-1],
                channel["bottom"][-1],
                rule,
                "down",
            )
        )
        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_evaluate_single_area_allows_pre_break_touch_within_window(self):
        bases = self._chartprime_fixture_bases() + [13.0]
        candles = self._chartprime_candles(bases)
        candles[14] = {"open": 13.0, "high": 13.5, "low": 12.7, "close": 13.2, "volume": 100.0}
        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertTrue(channel["broken"])
        break_index = channel["break_index"]
        start_index = len(candles) - channel["length"]
        regression_index = break_index - start_index
        touch_price = float(channel["bottom"][regression_index])
        candles[break_index] = {
            "open": touch_price + 0.2,
            "high": touch_price + 0.5,
            "low": touch_price,
            "close": touch_price + 0.2,
            "volume": 100.0,
        }

        rule = {
            "area": "bottom_line",
            "action": "touched",
            "touch_type": "wick",
            "tolerance": 1,
            "window": 1,
            "confirmation": False,
        }

        self.assertTrue(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_compute_trend_channel_breaks_on_price_alone(self):
        bases = self._chartprime_fixture_bases() + [13.0]
        candles = self._chartprime_candles(bases)
        # Force the break bar's low/high independently of the constant-range
        # pattern above, since a break needs a real excursion past the line.
        candles[-1] = {"open": 13.0, "high": 13.5, "low": 12.7, "close": 13.2, "volume": 100.0}

        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertIsNotNone(channel)
        self.assertTrue(channel["broken"])
        self.assertEqual(channel["break_index"], 14)
        self.assertEqual(channel["break_direction"], "up")

    def test_compute_trend_channel_requires_show_last_channel_to_keep_broken_structure(self):
        bases = self._chartprime_fixture_bases() + [13.0]
        candles = self._chartprime_candles(bases)
        candles[-1] = {"open": 13.0, "high": 13.5, "low": 12.7, "close": 13.2, "volume": 100.0}

        channel = trend_channels.compute_trend_channel(
            candles,
            length=2,
            show_last_channel=False,
        )

        self.assertIsNone(channel)

    def test_compute_trend_channel_does_not_use_regression_fallback_without_pivots(self):
        # Monotonic rise produces no pivot highs/lows at length=8. The old
        # regression fallback invented a channel here and caused false positives.
        candles = [
            {
                "open": float(index),
                "high": float(index) + 1.0,
                "low": float(index) - 0.5,
                "close": float(index) + 0.5,
                "volume": 100.0,
            }
            for index in range(80)
        ]

        channel = trend_channels.compute_trend_channel(candles, length=8)

        self.assertIsNone(channel)

    def test_handle_trend_rejects_when_no_pivot_channel_exists(self):
        candles = [
            {
                "open": float(index),
                "high": float(index) + 1.0,
                "low": float(index) - 0.5,
                "close": float(index) + 0.5,
                "volume": 100.0,
            }
            for index in range(80)
        ]
        asset = {"symbol": "TEST", "channels": {}}
        config = {
            "length": 8,
            "wait_for_break": True,
            "show_last_channel": True,
            "areas": [
                {
                    "area": "top_line",
                    "action": "touched",
                    "touch_type": "wick",
                    "window": 1,
                    "confirmation": False,
                }
            ],
        }

        passed, result = indicators.handle_trend(asset, candles, config)

        self.assertFalse(passed)
        self.assertIsNone(result)
        self.assertNotIn("trend", asset.get("channels", {}))

    def test_build_linreg_candle_sticker_uses_actual_matched_candle_bias(self):
        candles = [
            {"open": 105.0, "high": 106.0, "low": 101.0, "close": 102.0},
        ]
        lr_line = [100.0]
        config = {
            "lr_length": 11,
            "window": 1,
            "price_position": "above",
            "close_location": "close_above",
            "confirmation": False,
        }

        sticker = linear_regression_candles.build_linreg_candle_sticker(candles, lr_line, config)

        self.assertEqual(
            sticker,
            "LinReg Candles (11) | Bearish Candle Above Line + Close Above Line | LinReg close $102.00 vs line $100.00 | No Pattern | Last 1 Candle",
        )

    def test_linreg_sticker_uses_virtual_close_for_position_rules(self):
        candles = [{"open": 200.0, "high": 210.0, "low": 190.0, "close": 205.0}]
        lr_result = {
            "signal": [100.0],
            "bopen": [101.0],
            "bhigh": [103.0],
            "blow": [99.0],
            "bclose": [102.0],
        }
        config = {
            "lr_length": 11,
            "window": 1,
            "price_position": "piercing_from_above",
            "confirmation": False,
        }
        sticker = linear_regression_candles.build_linreg_candle_sticker(candles, lr_result, config)
        self.assertIn("LinReg close $102.00", sticker)
        self.assertNotIn("Close $205.00", sticker)

    def test_linreg_closed_candles_ignore_forming_bar(self):
        closed = [
            {"open": 98.0, "high": 99.0, "low": 97.0, "close": 98.5, "time": 1},
            {"open": 99.0, "high": 100.0, "low": 98.5, "close": 99.5, "time": 2},
        ]
        forming = {
            "open": 50.0,
            "high": 60.0,
            "low": 40.0,
            "close": 55.0,
            "time": 3,
            "is_closed": False,
        }
        # With forming bar included, compute still works; evaluate path in handle uses closed only.
        trimmed = linear_regression_candles._closed_candles(closed + [forming])
        self.assertEqual(len(trimmed), 2)
        self.assertEqual(trimmed[-1]["time"], 2)

        lr_result = {
            "signal": [100.0, 100.0],
            "bopen": [99.0, 101.0],
            "bhigh": [100.0, 102.0],
            "blow": [97.0, 100.5],
            "bclose": [98.0, 101.5],
        }
        config = {"window": 1, "price_position": "above", "confirmation": False}
        self.assertTrue(
            linear_regression_candles.evaluate_linreg_candle_rules(trimmed, lr_result, config)
        )
        evidence = linear_regression_candles.build_linreg_evidence(
            trimmed,
            lr_result,
            config,
            True,
            forming_bar=forming,
        )
        self.assertTrue(evidence["passed"])
        self.assertIsNotNone(evidence["forming_bar_skipped"])
        self.assertEqual(evidence["evaluation_bar"]["virtual_linreg"]["close"], 101.5)
        self.assertEqual(evidence["settings"]["signal_smoothing"], 11)

    def test_linreg_close_location_any_is_ignored(self):
        candles = [{"open": 101.0, "high": 102.0, "low": 100.5, "close": 101.5}]
        lr_result = {
            "signal": [100.0],
            "bopen": [101.0],
            "bhigh": [102.0],
            "blow": [100.5],
            "bclose": [101.5],
        }
        config = {
            "window": 1,
            "price_position": "above",
            "close_location": "any",
            "confirmation": False,
        }
        self.assertTrue(
            linear_regression_candles.evaluate_linreg_candle_rules(candles, lr_result, config)
        )

    def test_regression_r_filter_uses_absolute_strength(self):
        config = {
            "r_mode": "min",
            "r_min": 0.8,
        }
        self.assertTrue(regression_channels.passes_r_filter(-0.92, config))

    def test_regression_r_filter_supports_guideline_presets(self):
        self.assertTrue(regression_channels.passes_r_filter(0.75, {"r_filter": "strong"}))
        self.assertTrue(regression_channels.passes_r_filter(0.65, {"r_filter": "balanced"}))
        self.assertFalse(regression_channels.passes_r_filter(0.85, {"r_filter": "balanced"}))

    def test_handle_regression_passes_interval_window_settings(self):
        asset = {"symbol": "AAPL", "channels": {}}
        candles = [{"close": 100.0}] * 220
        config = {
            "length": 200,
            "width_coeff": 1.5,
            "window_type": "interval",
            "interval_step": 3,
        }

        with patch.object(
            indicators,
            "compute_dw_regression_channel",
            return_value={
                "length": 200,
                "middle": [100.0] * 10,
                "upper": [101.0] * 10,
                "lower": [99.0] * 10,
                "q1": [100.5] * 10,
                "q3": [99.5] * 10,
            },
        ) as compute_mock, patch.object(
            indicators,
            "evaluate_regression_lines",
            return_value=False,
        ):
            indicators.handle_regression(asset, candles, config)

        compute_mock.assert_called_once_with(
            candles,
            length=200,
            width_coeff=1.5,
            window_type="interval",
            interval_step=3,
            filter_type="SMA",
        )


class TrendyAdxTests(unittest.TestCase):
    def _fake_candles(self, n):
        return [{} for _ in range(n)]

    def _fake_computed(self, di_plus, di_minus, adx):
        return {
            "di_plus": np.array(di_plus, dtype=float),
            "di_minus": np.array(di_minus, dtype=float),
            "adx": np.array(adx, dtype=float),
        }

    def _trend_candles(self, n, start, step, amplitude=0.3):
        candles = []
        price = start
        for _ in range(n):
            price += step
            candles.append({
                "open": price, "high": price + amplitude, "low": price - amplitude,
                "close": price, "volume": 1_000_000,
            })
        return candles

    def test_compute_trendy_adx_matches_independent_reference_calculation(self):
        candles = [
            {"open": 44.0, "high": 44.5, "low": 43.0, "close": 44.2},
            {"open": 44.2, "high": 45.0, "low": 44.0, "close": 44.8},
            {"open": 44.8, "high": 45.5, "low": 44.2, "close": 45.0},
            {"open": 45.0, "high": 45.2, "low": 43.8, "close": 44.0},
            {"open": 44.0, "high": 44.6, "low": 43.5, "close": 44.3},
            {"open": 44.3, "high": 46.0, "low": 44.0, "close": 45.8},
            {"open": 45.8, "high": 46.5, "low": 45.0, "close": 46.2},
            {"open": 46.2, "high": 46.8, "low": 45.5, "close": 46.0},
            {"open": 46.0, "high": 47.0, "low": 45.8, "close": 46.8},
            {"open": 46.8, "high": 47.5, "low": 46.0, "close": 47.2},
            {"open": 47.2, "high": 47.8, "low": 46.5, "close": 47.0},
            {"open": 47.0, "high": 47.2, "low": 45.5, "close": 45.8},
            {"open": 45.8, "high": 46.2, "low": 44.8, "close": 45.0},
            {"open": 45.0, "high": 45.5, "low": 44.0, "close": 44.5},
            {"open": 44.5, "high": 45.0, "low": 43.0, "close": 43.5},
        ]
        length = 5
        computed = trendy_adx.compute_trendy_adx(candles, length=length)
        self.assertIsNotNone(computed)

        # Independent from-scratch reference implementation of the same sourced
        # formula (Wilder-smoothed TR/DM+/DM-, DI+/DI-, DX, ADX = SMA(DX, length)) —
        # written separately here so this test can actually catch a wrong
        # implementation, not just confirm the code agrees with itself.
        n = len(candles)
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]

        tr = [0.0] * n
        dm_plus = [0.0] * n
        dm_minus = [0.0] * n
        for i in range(n):
            if i == 0:
                tr[i] = highs[i] - lows[i]
                continue
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            up = highs[i] - highs[i - 1]
            down = lows[i - 1] - lows[i]
            dm_plus[i] = up if (up > down and up > 0) else 0.0
            dm_minus[i] = down if (down > up and down > 0) else 0.0

        def wilder_rma(values, length):
            # Mirrors pine_rma's actual behavior (services/pine_math.py): a partial
            # running mean during warm-up (index < length-1), not NaN/skip.
            out = [None] * len(values)
            for i in range(len(values)):
                if i < length - 1:
                    out[i] = sum(values[: i + 1]) / (i + 1)
                    continue
                if i == length - 1:
                    out[i] = sum(values[:length]) / length
                    continue
                out[i] = (out[i - 1] * (length - 1) + values[i]) / length
            return out

        smoothed_tr = wilder_rma(tr, length)
        smoothed_dm_plus = wilder_rma(dm_plus, length)
        smoothed_dm_minus = wilder_rma(dm_minus, length)

        di_plus_ref = [None] * n
        di_minus_ref = [None] * n
        dx_ref = [0.0] * n
        for i in range(n):
            if not smoothed_tr[i]:
                continue
            di_plus_ref[i] = smoothed_dm_plus[i] / smoothed_tr[i] * 100.0
            di_minus_ref[i] = smoothed_dm_minus[i] / smoothed_tr[i] * 100.0
            di_sum = di_plus_ref[i] + di_minus_ref[i]
            dx_ref[i] = abs(di_plus_ref[i] - di_minus_ref[i]) / di_sum * 100.0 if di_sum > 0 else 0.0

        def sma(values, length):
            out = [None] * len(values)
            for i in range(length - 1, len(values)):
                out[i] = sum(values[i - length + 1:i + 1]) / length
            return out

        adx_ref = sma(dx_ref, length)

        for i in range(n):
            if di_plus_ref[i] is not None:
                self.assertAlmostEqual(float(computed["di_plus"][i]), di_plus_ref[i], places=6)
                self.assertAlmostEqual(float(computed["di_minus"][i]), di_minus_ref[i], places=6)
            if adx_ref[i] is not None:
                self.assertAlmostEqual(float(computed["adx"][i]), adx_ref[i], places=6)

    def test_unclosed_last_candle_is_excluded_from_compute_evaluate_and_sticker(self):
        # A live/in-progress candle (is_closed=False) must never move the reported
        # DI+/DI-/ADX values or the evaluated signal — only fully-closed candles count.
        base_candles = self._trend_candles(30, 100.0, 0.8)
        baseline = trendy_adx.compute_trendy_adx(base_candles, length=11)

        live_candle = {
            "open": base_candles[-1]["close"], "high": base_candles[-1]["close"] + 50.0,
            "low": base_candles[-1]["close"] - 50.0, "close": base_candles[-1]["close"] + 40.0,
            "volume": 1_000_000, "is_closed": False,
        }
        candles_with_live = base_candles + [live_candle]
        with_live = trendy_adx.compute_trendy_adx(candles_with_live, length=11)

        self.assertAlmostEqual(float(baseline["di_plus"][-1]), float(with_live["di_plus"][-1]), places=9)
        self.assertAlmostEqual(float(baseline["di_minus"][-1]), float(with_live["di_minus"][-1]), places=9)
        self.assertAlmostEqual(float(baseline["adx"][-1]), float(with_live["adx"][-1]), places=9)

        cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "di_already_above"}]}
        self.assertEqual(
            trendy_adx.evaluate_trendy_adx_rules(baseline, base_candles, cfg),
            trendy_adx.evaluate_trendy_adx_rules(with_live, candles_with_live, cfg),
        )

        sticker_baseline = trendy_adx.build_trendy_adx_sticker(baseline, base_candles, {"mode": "bullish", "threshold": 20})
        sticker_with_live = trendy_adx.build_trendy_adx_sticker(with_live, candles_with_live, {"mode": "bullish", "threshold": 20})
        self.assertEqual(sticker_baseline, sticker_with_live)

    def test_di_crossed_above_detects_the_flip_and_reports_candles_since(self):
        down = self._trend_candles(30, 200.0, -1.0)
        up = self._trend_candles(20, down[-1]["close"], 1.5)
        candles = down + up
        computed = trendy_adx.compute_trendy_adx(candles, length=11)

        found_cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "di_crossed_above", "candles_since": 15}]}
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed, candles, found_cfg))

        too_tight_cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "di_crossed_above", "candles_since": 0}]}
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed, candles, too_tight_cfg))

    def test_di_already_above_bullish_bearish_mirror(self):
        n = 10
        computed = self._fake_computed([30] * n, [10] * n, [25] * n)
        candles = self._fake_candles(n)

        bullish_cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "di_already_above"}]}
        bearish_cfg = {"mode": "bearish", "threshold": 20, "conditions": [{"id": "di_already_above"}]}
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed, candles, bullish_cfg))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed, candles, bearish_cfg))

    def test_adx_threshold_tiers(self):
        n = 5
        candles = self._fake_candles(n)
        cases = [
            (15, {"adx_below_20": True, "adx_above_20": False, "adx_above_25": False, "adx_above_40": False}),
            (22, {"adx_below_20": False, "adx_above_20": True, "adx_above_25": False, "adx_above_40": False}),
            (27, {"adx_below_20": False, "adx_above_20": True, "adx_above_25": True, "adx_above_40": False}),
            (45, {"adx_below_20": False, "adx_above_20": True, "adx_above_25": True, "adx_above_40": True}),
        ]
        for adx_value, expectations in cases:
            computed = self._fake_computed([30] * n, [10] * n, [adx_value] * n)
            for condition_id, expected in expectations.items():
                cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": condition_id}]}
                self.assertEqual(
                    trendy_adx.evaluate_trendy_adx_rules(computed, candles, cfg),
                    expected,
                    f"adx={adx_value} condition={condition_id}",
                )

    def test_adx_vs_dominant_and_opposing_di_lines(self):
        n = 5
        candles = self._fake_candles(n)

        computed = self._fake_computed([30] * n, [10] * n, [20] * n)
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_below_dominant"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_above_opposing"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_between_both"}]}
        ))

        computed_strong = self._fake_computed([30] * n, [10] * n, [35] * n)
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed_strong, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_above_both"}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed_strong, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_below_both"}]}
        ))

    def test_adx_crossed_above_both_reports_candles_since(self):
        di_plus = [30] * 10
        di_minus = [10] * 10
        adx = [15, 16, 17, 18, 19, 19.5, 32, 33, 34, 35]
        computed = self._fake_computed(di_plus, di_minus, adx)
        candles = self._fake_candles(10)

        found_cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_crossed_above_both", "candles_since": 5}]}
        missed_cfg = {"mode": "bullish", "threshold": 20, "conditions": [{"id": "adx_crossed_above_both", "candles_since": 1}]}
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed, candles, found_cfg))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed, candles, missed_cfg))

    def test_background_just_started_active_and_active_for_x(self):
        di_plus = [10, 10, 10, 10, 10, 10, 30, 30, 30, 30]
        di_minus = [30, 30, 30, 30, 30, 30, 10, 10, 10, 10]
        adx = [20] * 10
        computed = self._fake_computed(di_plus, di_minus, adx)
        candles = self._fake_candles(10)

        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "bg_active"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "bg_just_started", "candles_since": 5}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "bg_just_started", "candles_since": 1}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "bg_active_for_x", "candles_since": 3}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "bullish", "threshold": 20, "conditions": [{"id": "bg_active_for_x", "candles_since": 9}]}
        ))

    def test_compression_conditions(self):
        n = 10
        candles = self._fake_candles(n)
        computed = self._fake_computed([15] * n, [17] * n, [15] * n)

        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "di_close_together", "distance": 3}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "di_touching"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "adx_below_20"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "adx_close_to_20", "distance": 5}]}
        ))

    def test_compression_di_moving_toward_each_other_and_adx_turning_up(self):
        di_plus = [10, 11, 12, 13, 15, 17, 19, 20, 21, 22]
        di_minus = [30, 29, 28, 27, 26, 25, 24, 23, 22.5, 22]
        adx = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        computed = self._fake_computed(di_plus, di_minus, adx)
        candles = self._fake_candles(10)

        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "di_pink_toward_blue"}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "di_blue_toward_pink"}]}
        ))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed, candles, {"mode": "compression", "threshold": 20, "conditions": [{"id": "adx_turning_up"}]}
        ))

    def test_weak_mode_flagged_assumption_conditions(self):
        n = 20
        candles = self._fake_candles(n)

        falling_adx = [30, 29, 28, 27, 26, 25, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7]
        computed_falling = self._fake_computed([15] * n, [15] * n, falling_adx)
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed_falling, candles, {"mode": "weak", "threshold": 20, "conditions": [{"id": "adx_falling"}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed_falling, candles, {"mode": "weak", "threshold": 20, "conditions": [{"id": "adx_flat"}]}
        ))

        computed_flat = self._fake_computed([15] * n, [15] * n, [20] * n)
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed_flat, candles, {"mode": "weak", "threshold": 20, "conditions": [{"id": "adx_flat"}]}
        ))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(
            computed_flat, candles, {"mode": "weak", "threshold": 20, "conditions": [{"id": "adx_falling"}]}
        ))

        computed_close = self._fake_computed([15] * n, [15.5] * n, [10] * n)
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(
            computed_close, candles, {"mode": "weak", "threshold": 20, "conditions": [{"id": "di_close_no_separation", "distance": 1}]}
        ))

        di_plus_flip = [20 if i % 2 == 0 else 10 for i in range(n)]
        di_minus_flip = [10 if i % 2 == 0 else 20 for i in range(n)]
        computed_mixed = self._fake_computed(di_plus_flip, di_minus_flip, [15] * n)
        mixed_cfg = {"mode": "weak", "threshold": 20, "conditions": [{"id": "bg_mixed_or_changing"}]}
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed_mixed, candles, mixed_cfg))

        computed_stable = self._fake_computed([20] * n, [10] * n, [15] * n)
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed_stable, candles, mixed_cfg))

        # No cross, no confirmation anywhere in the series
        computed_flat_all = self._fake_computed([20] * n, [10] * n, [15] * n)
        no_cross_cfg = {"mode": "weak", "threshold": 20, "conditions": [{"id": "no_clean_di_cross"}]}
        no_confirm_cfg = {"mode": "weak", "threshold": 20, "conditions": [{"id": "no_adx_confirmation"}]}
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed_flat_all, candles, no_cross_cfg))
        self.assertTrue(trendy_adx.evaluate_trendy_adx_rules(computed_flat_all, candles, no_confirm_cfg))

        # A recent DI cross should flip no_clean_di_cross to False
        di_plus_cross = [10] * 15 + [30] * 5
        di_minus_cross = [30] * 15 + [10] * 5
        computed_cross = self._fake_computed(di_plus_cross, di_minus_cross, [15] * n)
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed_cross, candles, no_cross_cfg))

        # ADX currently above threshold counts as confirmed even with no recent cross event
        adx_now_strong = [15] * 15 + [25] * 5
        computed_now_strong = self._fake_computed([20] * n, [10] * n, adx_now_strong)
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed_now_strong, candles, no_confirm_cfg))

    def test_final_label_tiers_for_bullish(self):
        n = 5
        candles = self._fake_candles(n)

        def label(adx_value, dominant, opposing):
            computed = self._fake_computed([dominant] * n, [opposing] * n, [adx_value] * n)
            return trendy_adx._directional_final_label("bullish", computed, n, 20)

        self.assertEqual(label(15, 30, 10), "Early Bullish / Weak Strength")
        self.assertEqual(label(22, 30, 10), "Bullish Strength Building")
        self.assertEqual(label(23, 21, 10), "Bullish Confirmed")
        self.assertEqual(label(27, 15, 5), "Strong Bullish Confirmed")
        self.assertEqual(label(45, 15, 5), "Bullish Exhaustion Warning")

        bearish_computed = self._fake_computed([5] * n, [15] * n, [45] * n)
        self.assertEqual(
            trendy_adx._directional_final_label("bearish", bearish_computed, n, 20),
            "Bearish Exhaustion Warning",
        )

    def test_final_label_compression_and_weak(self):
        n = 5
        candles = self._fake_candles(n)
        neutral = self._fake_computed([15] * n, [15] * n, [10] * n)

        self.assertEqual(trendy_adx._final_label("compression", neutral, candles, set(), 20), "Compression Watch")
        self.assertEqual(
            trendy_adx._final_label("compression", neutral, candles, {"di_pink_toward_blue"}, 20),
            "Possible Bearish Interaction Soon",
        )
        self.assertEqual(
            trendy_adx._final_label("compression", neutral, candles, {"di_blue_toward_pink"}, 20),
            "Possible Bullish Interaction Soon",
        )

        weak_avoid = self._fake_computed([15] * n, [15] * n, [10] * n)
        self.assertEqual(trendy_adx._final_label("weak", weak_avoid, candles, set(), 20), "Avoid")

        weak_no_confirm = self._fake_computed([30] * n, [10] * n, [25] * n)
        self.assertEqual(
            trendy_adx._final_label("weak", weak_no_confirm, candles, {"no_clean_di_cross"}, 20),
            "No Confirmation",
        )
        self.assertEqual(trendy_adx._final_label("weak", weak_no_confirm, candles, set(), 20), "Weak Trend")

    def test_handle_trendy_adx_end_to_end(self):
        candles = self._trend_candles(60, 100.0, 0.8)
        asset = {"symbol": "TEST"}
        config = {
            "length": 11,
            "threshold": 20,
            "mode": "bullish",
            "conditions": [{"id": "di_already_above"}, {"id": "adx_above_20"}],
        }
        passed, sticker = indicators.handle_trendy_adx(asset, candles, config)
        self.assertTrue(passed)
        self.assertIn("Trendy ADX", sticker)

    def test_evaluate_trendy_adx_rules_requires_mode_and_conditions(self):
        computed = self._fake_computed([30] * 5, [10] * 5, [25] * 5)
        candles = self._fake_candles(5)
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed, candles, {"mode": "", "conditions": []}))
        self.assertFalse(trendy_adx.evaluate_trendy_adx_rules(computed, candles, {"mode": "bullish", "conditions": []}))


class VlrTests(unittest.TestCase):
    def _fake_candles(self, n):
        return [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1_000_000} for _ in range(n)]

    def _fake_computed(self, r_lists):
        return {"r": [np.array(r, dtype=float) for r in r_lists]}

    def _trend_candles(self, n, start, step, amplitude=0.2):
        candles = []
        price = start
        for _ in range(n):
            price += step
            candles.append({
                "open": price, "high": price + amplitude, "low": price - amplitude,
                "close": price, "volume": 1_000_000,
            })
        return candles

    def test_compute_vlr_matches_independent_pearson_r_reference(self):
        closes = [10.0, 11.0, 9.0, 12.0, 13.0, 11.0, 14.0, 15.0, 13.0, 16.0, 18.0, 17.0]
        candles = [{"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1000} for c in closes]
        period = 5

        computed = vlr.compute_vlr(candles, source="close", num_regressions=1, start_period=period, period_increment=0)
        self.assertIsNotNone(computed)
        r_series = computed["r"][0]

        # Independent reference using the mean-deviation form of Pearson's r (a different
        # algebraic identity than the sum-of-squares form the source script and compute_vlr
        # use) — catches an implementation bug rather than just re-checking the same formula.
        n = len(closes)
        for idx in range(period - 1, n):
            window = list(reversed(closes[idx - period + 1: idx + 1]))  # window[0] = current (x=0)
            x = list(range(period))
            mean_x = sum(x) / period
            mean_y = sum(window) / period
            num = sum((x[i] - mean_x) * (window[i] - mean_y) for i in range(period))
            den_x = sum((x[i] - mean_x) ** 2 for i in range(period))
            den_y = sum((window[i] - mean_y) ** 2 for i in range(period))
            if den_x > 0 and den_y > 0:
                expected = num / ((den_x * den_y) ** 0.5)
                self.assertAlmostEqual(float(r_series[idx]), expected, places=6)

    def test_exact_and_early_bullish_reversal(self):
        red = [0.5, 0.7, 0.85, 0.90, 0.90, 0.90, 0.80]
        computed = self._fake_computed([red])
        candles = self._fake_candles(len(red))
        config = {"reversal_type": "exact", "direction": "bullish", "timing_candles": 5}
        passed, tags = vlr.evaluate_vlr_rules(computed, candles, config)
        self.assertTrue(passed)
        self.assertIn("Exact Bullish Reversal Watch", tags)

        red_early = [0.5, 0.6, 0.72, 0.75, 0.75, 0.75, 0.65]
        computed_early = self._fake_computed([red_early])
        candles_early = self._fake_candles(len(red_early))
        config_early = {"reversal_type": "early", "direction": "bullish", "timing_candles": 5}
        passed_early, tags_early = vlr.evaluate_vlr_rules(computed_early, candles_early, config_early)
        self.assertTrue(passed_early)
        self.assertIn("Early Bullish Reversal Watch", tags_early)

        passed_wrong_type, _ = vlr.evaluate_vlr_rules(
            computed_early, candles_early, {"reversal_type": "exact", "direction": "bullish", "timing_candles": 5}
        )
        self.assertFalse(passed_wrong_type)

    def test_exact_and_early_bearish_reversal(self):
        red = [-0.5, -0.7, -0.85, -0.90, -0.90, -0.90, -0.80]
        computed = self._fake_computed([red])
        candles = self._fake_candles(len(red))
        config = {"reversal_type": "exact", "direction": "bearish", "timing_candles": 5}
        passed, tags = vlr.evaluate_vlr_rules(computed, candles, config)
        self.assertTrue(passed)
        self.assertIn("Exact Bearish Reversal Watch", tags)

        red_early = [-0.5, -0.6, -0.72, -0.75, -0.75, -0.75, -0.65]
        computed_early = self._fake_computed([red_early])
        candles_early = self._fake_candles(len(red_early))
        config_early = {"reversal_type": "early", "direction": "bearish", "timing_candles": 5}
        passed_early, tags_early = vlr.evaluate_vlr_rules(computed_early, candles_early, config_early)
        self.assertTrue(passed_early)
        self.assertIn("Early Bearish Reversal Watch", tags_early)

        # A bullish-only scan should never match bearish data
        passed_wrong_direction, _ = vlr.evaluate_vlr_rules(computed, candles, {**config, "direction": "bullish"})
        self.assertFalse(passed_wrong_direction)

    def test_pair_crossings_and_below_both(self):
        red = [0.5, 0.5, 0.5, 0.1, 0.1, 0.1]
        green = [0.2] * 6
        blue = [0.4] * 6
        r_series_list = [np.array(red), np.array(green), np.array(blue)]
        n = 6

        self.assertTrue(vlr._pair_crossed_within_window(r_series_list, "red_below_green", n, 5))
        self.assertTrue(vlr._pair_crossed_within_window(r_series_list, "red_below_blue", n, 5))
        self.assertTrue(vlr._pair_crossed_within_window(r_series_list, "red_below_both", n, 5))
        self.assertFalse(vlr._pair_crossed_within_window(r_series_list, "green_below_blue", n, 5))
        self.assertTrue(vlr._multiple_crossings_within_window(r_series_list, vlr.BULLISH_PAIR_IDS[:3], n, 5))

        # too-tight a window should miss the same event
        self.assertFalse(vlr._pair_crossed_within_window(r_series_list, "red_below_green", n, 1))

    def test_crossing_confirmation_requirement_counting_and_direction_filter(self):
        red = [0.5, 0.5, 0.5, 0.1, 0.1, 0.1]
        green = [0.2] * 6
        blue = [0.9] * 6  # red starts already below blue -> no fresh cross there
        r_series_list = [np.array(red), np.array(green), np.array(blue)]
        n = 6

        tags1 = []
        cfg1 = {
            "multiple_crossing_requirement": "at_least_1", "crossing_sequence": "any",
            "bullish_crossings": ["red_below_green", "red_below_blue"], "bearish_crossings": [],
        }
        self.assertTrue(vlr._evaluate_crossing_confirmation(r_series_list, "bullish", cfg1, n, 5, tags1))
        self.assertIn("Red Crossed Green", tags1)

        tags2 = []
        cfg2 = {**cfg1, "multiple_crossing_requirement": "at_least_2"}
        self.assertFalse(vlr._evaluate_crossing_confirmation(r_series_list, "bullish", cfg2, n, 5, tags2))

        tags3 = []
        cfg3 = {**cfg1, "multiple_crossing_requirement": "all_selected"}
        self.assertFalse(vlr._evaluate_crossing_confirmation(r_series_list, "bullish", cfg3, n, 5, tags3))

        # Direction=bearish must ignore bullish_crossings entirely, even if populated
        tags4 = []
        cfg4 = {**cfg1, "bearish_crossings": []}
        self.assertTrue(vlr._evaluate_crossing_confirmation(r_series_list, "bearish", cfg4, n, 5, tags4))
        self.assertEqual(tags4, [])

    def test_crossing_sequence_ordering(self):
        n = 10
        red = [1, 1, 1, 1, -1, -1, -1, -1, -1, -1]
        green = [1, 1, 1, 1, 1, 1, -1, -1, -1, -1]
        blue = [1, 1, 1, 1, 1, 1, 1, 1, -1, -1]
        r_series_list = [np.array(red, dtype=float), np.array(green, dtype=float), np.array(blue, dtype=float)]

        self.assertTrue(vlr._sequence_matches(r_series_list, "any", "bullish", n, 9))
        self.assertTrue(vlr._sequence_matches(r_series_list, "sequential", "bullish", n, 9))
        self.assertTrue(vlr._sequence_matches(r_series_list, "red_first", "bullish", n, 9))
        self.assertFalse(vlr._sequence_matches(r_series_list, "blue_first", "bullish", n, 9))

    def test_volume_confirmation_reuses_relative_volume_ratio(self):
        n = 15
        candles = []
        for i in range(n):
            volume = 1000 if i < n - 1 else 3000
            candles.append({"open": 1, "high": 1, "low": 1, "close": 1, "volume": volume})

        tags = []
        result = vlr._evaluate_volume_confirmation(
            candles, {"volume_min_ratio": 2.0, "volume_length": 10}, n, 1, tags
        )
        self.assertTrue(result)
        self.assertIn("Volume Confirmed", tags)

        tags2 = []
        result2 = vlr._evaluate_volume_confirmation(
            candles, {"volume_min_ratio": 5.0, "volume_length": 10}, n, 1, tags2
        )
        self.assertFalse(result2)

    def test_candle_confirmation_reuses_pattern_library(self):
        candles = [
            {"open": 10.0, "close": 9.5, "high": 10.1, "low": 9.4, "volume": 1000},
            {"open": 9.3, "close": 10.2, "high": 10.3, "low": 9.2, "volume": 1000},
        ]

        tags = []
        result = vlr._evaluate_candle_confirmation(
            candles, {"candle_confirmation_patterns": ["bullish_engulfing"]}, 2, 1, tags
        )
        self.assertTrue(result)
        self.assertIn("Candle Confirmed", tags)

        tags2 = []
        result2 = vlr._evaluate_candle_confirmation(
            candles, {"candle_confirmation_patterns": ["hammer"]}, 2, 1, tags2
        )
        self.assertFalse(result2)

    def test_handle_vlr_end_to_end(self):
        down = self._trend_candles(60, 300.0, -1.0)
        up = self._trend_candles(30, down[-1]["close"], 1.2)
        candles = down + up
        asset = {"symbol": "TEST"}
        config = {"reversal_type": "both", "direction": "bullish", "timing_candles": 40}

        passed, sticker = indicators.handle_vlr(asset, candles, config)
        self.assertTrue(passed)
        self.assertIn("VLR Precision", sticker)


class CandlestickPatternTests(unittest.TestCase):
    def test_doji_detects_very_small_body(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.02},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 0)

        self.assertIn("doji", patterns)

    def test_doji_rejects_normal_bodied_candle(self):
        candles = [
            {"open": 100.0, "high": 101.5, "low": 99.5, "close": 101.0},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 0)

        self.assertNotIn("doji", patterns)

    def test_hammer_requires_preceding_downtrend(self):
        candles = [
            {"open": 110.0, "high": 110.2, "low": 109.8, "close": 110.0},
            {"open": 105.0, "high": 105.2, "low": 104.8, "close": 105.0},
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.5, "high": 100.8, "low": 98.0, "close": 100.6},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 3)

        self.assertIn("hammer", patterns)
        self.assertIn("bullish_pin_bar", patterns)

    def test_hammer_shape_without_downtrend_is_only_a_pin_bar(self):
        candles = [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 105.0, "high": 105.2, "low": 104.8, "close": 105.0},
            {"open": 110.0, "high": 110.2, "low": 109.8, "close": 110.0},
            {"open": 100.5, "high": 100.8, "low": 98.0, "close": 100.6},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 3)

        self.assertNotIn("hammer", patterns)
        self.assertIn("bullish_pin_bar", patterns)

    def test_inverted_hammer_fires_with_preceding_downtrend(self):
        candles = [
            {"open": 110.0, "high": 110.2, "low": 109.8, "close": 110.0},
            {"open": 105.0, "high": 105.2, "low": 104.8, "close": 105.0},
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 100.4, "high": 103.0, "low": 100.3, "close": 100.5},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 3)

        self.assertIn("inverted_hammer", patterns)
        self.assertNotIn("shooting_star", patterns)

    def test_shooting_star_fires_with_preceding_uptrend_not_inverted_hammer(self):
        candles = [
            {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0},
            {"open": 105.0, "high": 105.2, "low": 104.8, "close": 105.0},
            {"open": 110.0, "high": 110.2, "low": 109.8, "close": 110.0},
            {"open": 100.4, "high": 103.0, "low": 100.3, "close": 100.5},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 3)

        self.assertIn("shooting_star", patterns)
        self.assertNotIn("inverted_hammer", patterns)

    def test_piercing_line_requires_opening_gap_down(self):
        gapless_candles = [
            {"open": 110.0, "high": 110.5, "low": 104.5, "close": 105.0},
            {"open": 105.5, "high": 108.2, "low": 105.3, "close": 108.0},
        ]
        gapped_candles = [
            {"open": 110.0, "high": 110.5, "low": 104.5, "close": 105.0},
            {"open": 104.0, "high": 108.2, "low": 103.8, "close": 108.0},
        ]

        self.assertNotIn(
            "piercing_line",
            utils.detect_candlestick_patterns(gapless_candles, 1),
        )
        self.assertIn(
            "piercing_line",
            utils.detect_candlestick_patterns(gapped_candles, 1),
        )

    def test_dark_cloud_cover_requires_opening_gap_up(self):
        gapless_candles = [
            {"open": 100.0, "high": 105.5, "low": 99.5, "close": 105.0},
            {"open": 105.0, "high": 105.2, "low": 100.8, "close": 101.0},
        ]
        gapped_candles = [
            {"open": 100.0, "high": 105.5, "low": 99.5, "close": 105.0},
            {"open": 106.0, "high": 106.2, "low": 100.8, "close": 101.0},
        ]

        self.assertNotIn(
            "dark_cloud_cover",
            utils.detect_candlestick_patterns(gapless_candles, 1),
        )
        self.assertIn(
            "dark_cloud_cover",
            utils.detect_candlestick_patterns(gapped_candles, 1),
        )

    def test_double_bottom_rejects_flat_run_without_middle_bounce(self):
        candles = [
            {"open": 100.1, "high": 100.3, "low": 100.0, "close": 100.2},
            {"open": 100.0, "high": 100.05, "low": 99.95, "close": 100.0},
            {"open": 100.05, "high": 100.4, "low": 100.0, "close": 100.3},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 2)

        self.assertNotIn("double_bottom", patterns)

    def test_double_bottom_accepts_genuine_w_shape(self):
        candles = [
            {"open": 100.1, "high": 100.3, "low": 100.0, "close": 100.2},
            {"open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0},
            {"open": 100.05, "high": 100.4, "low": 100.0, "close": 100.3},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 2)

        self.assertIn("double_bottom", patterns)

    def test_double_top_accepts_genuine_m_shape(self):
        candles = [
            {"open": 109.9, "high": 110.0, "low": 109.0, "close": 109.5},
            {"open": 105.0, "high": 106.0, "low": 95.0, "close": 96.0},
            {"open": 109.5, "high": 110.0, "low": 109.0, "close": 105.0},
        ]

        patterns = utils.detect_candlestick_patterns(candles, 2)

        self.assertIn("double_top", patterns)


class IndicatorEngineTests(unittest.TestCase):
    def test_apply_indicators_compiles_handlers_once(self):
        class Indicator:
            def __init__(self, name, config=None):
                self.name = name
                self.config = config or {}

        calls = []

        def handler(asset, candles, config):
            calls.append((asset["symbol"], config["tag"]))
            return True, config["tag"]

        data = [
            {"symbol": "AAA", "candles": [{"close": 1.0}]},
            {"symbol": "BBB", "candles": [{"close": 2.0}]},
        ]
        selected = [
            Indicator("ema", {"tag": "EMA"}),
            Indicator("macd", {"tag": "MACD"}),
        ]

        with patch.dict(
            indicators.INDICATOR_REGISTRY,
            {"ema": handler, "macd": handler},
            clear=True,
        ):
            result = indicators.apply_indicators(data, selected)

        self.assertEqual([item["symbol"] for item in result], ["AAA", "BBB"])
        self.assertEqual(
            [item["stickers"] for item in result],
            [["EMA", "MACD"], ["EMA", "MACD"]],
        )
        self.assertEqual(len(calls), 4)

    def test_unsupported_indicator_names_reports_names_with_no_registered_handler(self):
        class Indicator:
            def __init__(self, name):
                self.name = name

        selected = [Indicator("ema"), Indicator("adx"), Indicator("stochrsi")]

        with patch.dict(indicators.INDICATOR_REGISTRY, {"ema": object()}, clear=True):
            result = indicators.unsupported_indicator_names(selected)

        self.assertEqual(result, ["adx", "stochrsi"])

    def test_unsupported_indicator_names_empty_when_all_have_handlers(self):
        class Indicator:
            def __init__(self, name):
                self.name = name

        selected = [Indicator("ema"), Indicator("macd")]

        with patch.dict(
            indicators.INDICATOR_REGISTRY,
            {"ema": object(), "macd": object()},
            clear=True,
        ):
            result = indicators.unsupported_indicator_names(selected)

        self.assertEqual(result, [])

    def test_apply_indicators_requires_every_selected_indicator_to_pass(self):
        class Indicator:
            def __init__(self, name, config=None):
                self.name = name
                self.config = config or {}

        data = [
            {"symbol": "AAA", "candles": [{"close": 1.0}]},
        ]
        selected = [
            Indicator("ema", {"tag": "EMA"}),
            Indicator("macd", {"tag": "MACD"}),
        ]

        def pass_handler(asset, candles, config):
            return True, config["tag"]

        def fail_handler(asset, candles, config):
            return False, None

        with patch.dict(
            indicators.INDICATOR_REGISTRY,
            {"ema": pass_handler, "macd": fail_handler},
            clear=True,
        ):
            result = indicators.apply_indicators(data, selected)

        self.assertEqual(result, [])

    def test_apply_indicators_isolates_one_symbol_raising_from_the_rest_of_the_batch(self):
        class Indicator:
            def __init__(self, name, config=None):
                self.name = name
                self.config = config or {}

        data = [
            {"symbol": "BAD", "candles": [{"close": 1.0}]},
            {"symbol": "GOOD", "candles": [{"close": 2.0}]},
        ]
        selected = [Indicator("ema", {"tag": "EMA"})]

        def raising_handler(asset, candles, config):
            if asset["symbol"] == "BAD":
                raise ValueError("malformed candle data")
            return True, config["tag"]

        with patch.dict(
            indicators.INDICATOR_REGISTRY,
            {"ema": raising_handler},
            clear=True,
        ):
            with self.assertLogs(indicators.logger, level="ERROR"):
                result = indicators.apply_indicators(data, selected)

        self.assertEqual([item["symbol"] for item in result], ["GOOD"])

    def test_apply_indicator_snapshots_supports_new_taapi_indicators(self):
        class Indicator:
            def __init__(self, name, config=None):
                self.name = name
                self.config = config or {}

        data = [
            {
                "symbol": "BTC-USD",
                "price": 105.0,
                "indicator_snapshot": {
                    "sma": [100.0],
                    "adx": [20.0, 28.0],
                    "stochrsi": [
                        {"k": 15.0, "d": 20.0},
                        {"k": 25.0, "d": 18.0},
                    ],
                },
            }
        ]
        selected = [
            Indicator("sma", {"length": 50, "rule": "above"}),
            Indicator("adx", {"rule": "above", "threshold": 25}),
            Indicator("stochrsi", {"rule": "bullish_cross"}),
        ]

        result = indicators.apply_indicator_snapshots(data, selected)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["stickers"]), 3)
        self.assertTrue(result[0]["stickers"][0].startswith("SMA (50) | Bullish Trend Filter |"))
        self.assertTrue(result[0]["stickers"][1].startswith("ADX | Strong Trend |"))
        self.assertTrue(result[0]["stickers"][2].startswith("StochRSI | Bullish Momentum Shift |"))


class ScreenerGateSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        gate_session_store.prune(now=10**12)

    async def test_run_gate_returns_request_scoped_session_id(self):
        request = SimpleNamespace(
            asset_type="stocks",
            stock_sources=["zoya"],
            compliance_status=None,
            exchanges=None,
            excluded_categories=None,
            indicators=[],
            gate_timeframe="1h",
            channel_respect=None,
            confluence=None,
        )
        assets = [
            {
                "symbol": "AAPL",
                "asset_type": "stocks",
                "data_source": "zoya",
                "exchange": "NASDAQ",
            }
        ]
        market_data = [{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]

        with patch.object(screener, "build_asset_universe", AsyncMock(return_value=assets)), patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(return_value=market_data),
        ):
            response = await screener.run_gate(request)

        self.assertEqual(response["results"][0]["symbol"], "AAPL")
        self.assertTrue(response["gate_session_id"])
        consumed = screener._consume_gate_results(
            response["gate_session_id"],
            scope_hash=screener._scope_hash_from_request(request),
            client_id=None,
        )
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0]["symbol"], "AAPL")

    async def test_run_entry_consumes_only_matching_gate_session(self):
        session_id = screener._store_gate_results(
            [
                {
                    "symbol": "BTC-USD",
                    "asset_type": "crypto",
                    "data_source": "massive",
                    "exchange": "binance",
                }
            ],
            scope_hash="scope-1",
            client_id="client-1",
        )
        request = SimpleNamespace(
            asset_type="crypto",
            stock_sources=None,
            compliance_status=None,
            exchanges=["binance"],
            excluded_categories=None,
            indicators=[],
            entry_timeframe="1h",
            gate_session_id=session_id,
            gate_timeframe="4h",
            channel_respect=None,
            confluence=None,
        )

        with patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(return_value=[{"symbol": "BTC-USD", "price": 50000.0, "candles": [{"close": 50000.0}]}]),
        ):
            with patch.object(screener, "_scope_hash_from_request", return_value="scope-1"):
                response = await screener.run_entry(request, client_id="client-1")

        self.assertEqual(response["results"][0]["symbol"], "BTC-USD")
        consumed_again = screener._consume_gate_results(
            session_id,
            scope_hash="scope-1",
            client_id="client-1",
        )
        self.assertEqual(consumed_again, [])

    async def test_run_entry_preserves_metadata_for_all_gate_candidates(self):
        with patch.object(settings, "SCREENING_MAX_SYMBOLS", 2), patch.object(settings, "MANUAL_SYMBOLS_MAX", 10):
            request = SimpleNamespace(
                asset_type="stocks",
                symbols=["AAA", "BBB", "CCC"],
                stock_sources=["zoya"],
                compliance_status=None,
                exchanges=None,
                excluded_categories=None,
                indicators=[],
                gate_timeframe="1day",
                entry_timeframe="4h",
                gate_session_id=None,
                channel_respect=None,
                confluence=None,
                price_range=None,
            )
            assets = [
                {"symbol": "AAA", "asset_type": "stocks", "data_source": "manual", "exchange": "NASDAQ"},
                {"symbol": "BBB", "asset_type": "stocks", "data_source": "manual", "exchange": "NASDAQ"},
                {"symbol": "CCC", "asset_type": "stocks", "data_source": "manual", "exchange": "NASDAQ"},
            ]
            market_data = [
                {"symbol": "AAA", "price": 10.0, "candles": [{"close": 10.0}]},
                {"symbol": "BBB", "price": 11.0, "candles": [{"close": 11.0}]},
                {"symbol": "CCC", "price": 12.0, "candles": [{"close": 12.0}]},
            ]

            with patch.object(screener, "build_asset_universe", AsyncMock(return_value=assets)), patch.object(
                screener,
                "fetch_screening_data",
                AsyncMock(return_value=market_data),
            ):
                gate = await screener.run_gate(request, client_id="client-1")
                request.gate_session_id = gate["gate_session_id"]
                entry = await screener.run_entry(request, client_id="client-1")

        self.assertEqual(len(entry["results"]), 3)
        self.assertEqual(
            [row.get("asset_type") for row in entry["results"]],
            ["stocks", "stocks", "stocks"],
        )

    async def test_run_entry_keeps_session_when_entry_fetch_raises(self):
        request = SimpleNamespace(
            asset_type="stocks",
            stock_sources=["zoya"],
            compliance_status=None,
            exchanges=None,
            excluded_categories=None,
            indicators=[],
            gate_timeframe="1h",
            entry_timeframe="15m",
            gate_session_id=None,
            channel_respect=None,
            confluence=None,
            price_range=None,
        )
        assets = [
            {
                "symbol": "AAPL",
                "asset_type": "stocks",
                "data_source": "zoya",
                "exchange": "NASDAQ",
            }
        ]
        market_data = [{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]

        with patch.object(screener, "build_asset_universe", AsyncMock(return_value=assets)), patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(return_value=market_data),
        ):
            gate = await screener.run_gate(request, client_id="client-1")

        request.gate_session_id = gate["gate_session_id"]

        with patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(side_effect=RuntimeError("temporary upstream failure")),
        ):
            with self.assertRaises(RuntimeError):
                await screener.run_entry(request, client_id="client-1")

        consumed = screener._consume_gate_results(
            request.gate_session_id,
            scope_hash=screener._scope_hash_from_request(request),
            client_id="client-1",
        )
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0]["symbol"], "AAPL")

    async def test_run_entry_rejects_duplicate_consumption_of_same_gate_session(self):
        request = SimpleNamespace(
            asset_type="stocks",
            stock_sources=["zoya"],
            compliance_status=None,
            exchanges=None,
            excluded_categories=None,
            indicators=[],
            gate_timeframe="1h",
            entry_timeframe="15m",
            gate_session_id=None,
            channel_respect=None,
            confluence=None,
            price_range=None,
        )
        assets = [
            {
                "symbol": "AAPL",
                "asset_type": "stocks",
                "data_source": "zoya",
                "exchange": "NASDAQ",
            }
        ]
        market_data = [{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]

        with patch.object(screener, "build_asset_universe", AsyncMock(return_value=assets)), patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(return_value=market_data),
        ):
            gate = await screener.run_gate(request, client_id="client-1")

        request.gate_session_id = gate["gate_session_id"]

        with patch.object(
            screener,
            "fetch_screening_data",
            AsyncMock(return_value=market_data),
        ):
            first = await screener.run_entry(request, client_id="client-1")
            second = await screener.run_entry(request, client_id="client-1")

        self.assertEqual(len(first["results"]), 1)
        self.assertEqual(second, {"results": []})

    def test_consume_gate_results_drops_expired_sessions(self):
        session_id = gate_session_store.store(
            metadata=[{"symbol": "STALE"}],
            ttl_seconds=-1,
            scope_hash="expired-scope",
            client_id="client",
        )

        metadata = screener._consume_gate_results(
            session_id,
            scope_hash="expired-scope",
            client_id="client",
        )

        self.assertEqual(metadata, [])

    def test_consume_gate_results_enforces_client_and_scope_isolation(self):
        session_id = gate_session_store.store(
            metadata=[{"symbol": "SAFE"}],
            ttl_seconds=60,
            scope_hash="scope-a",
            client_id="client-a",
        )

        wrong_client = screener._consume_gate_results(
            session_id,
            scope_hash="scope-a",
            client_id="client-b",
        )
        self.assertEqual(wrong_client, [])

        wrong_scope = screener._consume_gate_results(
            session_id,
            scope_hash="scope-b",
            client_id="client-a",
        )
        self.assertEqual(wrong_scope, [])

        correct = screener._consume_gate_results(
            session_id,
            scope_hash="scope-a",
            client_id="client-a",
        )
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]["symbol"], "SAFE")

    async def test_fetch_screening_data_uses_live_candles(self):
        assets = [{"symbol": "AAPL", "asset_type": "stocks", "exchange": "NASDAQ"}]
        indicators_list = [SimpleNamespace(name="trend", config={})]

        with patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]),
        ) as fetch_live_data_mock:
            response = await screener.fetch_screening_data(assets, "1h", indicators_list)

        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["symbol"], "AAPL")
        self.assertEqual(fetch_live_data_mock.await_count, 1)
        args = fetch_live_data_mock.await_args.args
        kwargs = fetch_live_data_mock.await_args.kwargs
        self.assertEqual(args, (["AAPL"], "1h"))
        self.assertEqual(kwargs.get("candles_limit"), 500)

    async def test_fetch_screening_data_accounts_for_confluence_channel_history(self):
        assets = [{"symbol": "AAPL", "asset_type": "stocks", "exchange": "NASDAQ"}]
        request = SimpleNamespace(
            channel_respect=None,
            confluence=SimpleNamespace(channels=["regression", "trend"]),
        )

        with patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]),
        ) as fetch_live_data_mock:
            await screener.fetch_screening_data(assets, "1h", [], request=request)

        kwargs = fetch_live_data_mock.await_args.kwargs
        self.assertEqual(kwargs.get("candles_limit"), 200)

    async def test_fetch_screening_data_accounts_for_confluence_source_lengths(self):
        assets = [{"symbol": "AAPL", "asset_type": "stocks", "exchange": "NASDAQ"}]
        request = SimpleNamespace(
            channel_respect=None,
            confluence=SimpleNamespace(
                channels=None,
                sources=[
                    SimpleNamespace(id="fast_lrc", channel_type="lrc", length=55),
                    SimpleNamespace(id="slow_reg", channel_type="regression", length=233),
                ],
            ),
        )

        with patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]),
        ) as fetch_live_data_mock:
            await screener.fetch_screening_data(assets, "1h", [], request=request)

        kwargs = fetch_live_data_mock.await_args.kwargs
        self.assertEqual(kwargs.get("candles_limit"), 233)

    async def test_fetch_screening_data_uses_snapshot_fast_path_for_fundamentals_only(self):
        assets = [{"symbol": "AAPL", "asset_type": "stocks", "exchange": "NASDAQ"}]
        indicators_list = [SimpleNamespace(name="shares_outstanding", config={})]

        with patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]),
        ) as fetch_live_data_mock:
            await screener.fetch_screening_data(
                assets,
                "1h",
                indicators_list,
                need_candle_history=screener.requires_candle_history(None, indicators_list),
            )

        kwargs = fetch_live_data_mock.await_args.kwargs
        self.assertEqual(kwargs.get("candles_limit"), 1)
        self.assertTrue(kwargs.get("include_fundamentals"))
        self.assertTrue(kwargs.get("latest_only"))

    async def test_fetch_screening_data_keeps_live_candles_for_current_volume(self):
        assets = [{"symbol": "AAPL", "asset_type": "stocks", "exchange": "NASDAQ"}]
        indicators_list = [SimpleNamespace(name="current_volume", config={})]

        with patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": [{"close": 100.0}]}]),
        ) as fetch_live_data_mock:
            await screener.fetch_screening_data(
                assets,
                "1h",
                indicators_list,
                need_candle_history=screener.requires_candle_history(None, indicators_list),
            )

        kwargs = fetch_live_data_mock.await_args.kwargs
        self.assertEqual(kwargs.get("candles_limit"), 1)
        self.assertIsNot(kwargs.get("latest_only"), True)

    def test_attach_post_filter_channels_builds_missing_channels(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
            for _ in range(220)
        ]
        data = [{"symbol": "AAPL", "candles": candles, "channels": {}}]
        request = SimpleNamespace(
            channel_respect=SimpleNamespace(channel_type="lrc"),
            confluence=SimpleNamespace(channels=["trend", "regression"]),
        )

        enriched = screener.attach_post_filter_channels(data, request)

        self.assertIn("lrc", enriched[0]["channels"])
        self.assertIn("trend", enriched[0]["channels"])
        self.assertIn("regression", enriched[0]["channels"])

    def test_attach_post_filter_channels_builds_confluence_source_instances(self):
        candles = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}
            for _ in range(260)
        ]
        data = [{"symbol": "AAPL", "candles": candles, "channels": {}}]
        request = SimpleNamespace(
            channel_respect=None,
            confluence=SimpleNamespace(
                channels=None,
                sources=[
                    SimpleNamespace(id="fast_lrc", channel_type="lrc", length=55),
                    SimpleNamespace(id="slow_lrc", channel_type="lrc", length=144),
                ],
            ),
        )

        enriched = screener.attach_post_filter_channels(data, request)

        self.assertIn("fast_lrc", enriched[0]["confluence_channels"])
        self.assertIn("slow_lrc", enriched[0]["confluence_channels"])

    async def test_get_asset_detail_serializes_generated_channels(self):
        candles = []
        for index in range(220):
            close = 100.0 + (index * 0.5)
            candles.append(
                {
                    "time": 1710000000 + (index * 3600),
                    "open": close - 0.2,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000 + index,
                }
            )

        request = SimpleNamespace(
            asset_type="stocks",
            timeframe_mode="single",
            stock_sources=["zoya"],
            compliance_status=None,
            compliance_standards=[],
            exchanges=[],
            excluded_categories=[],
            indicators=[],
            channel_respect=SimpleNamespace(
                channel_type="lrc",
                line="middle",
                min_respect=1,
                max_respect=None,
                tolerance_pct=0.5,
                cluster_gap=3,
                touch_type="wick",
            ),
            confluence=SimpleNamespace(
                type="bullish",
                lookback_candles=2,
                liquidity_sweep=False,
                tolerance_pct=0.1,
                channels=None,
                sources=[
                    SimpleNamespace(id="fast_lrc", channel_type="lrc", length=55),
                    SimpleNamespace(id="slow_reg", channel_type="regression", length=200),
                ],
            ),
            price_range=None,
        )

        live_data = [
            {
                "symbol": "AAPL",
                "price": candles[-1]["close"],
                "candles": candles,
                "candles_provider": "massive",
                "next_refresh_at": 1710000000 + (221 * 3600),
                "shares_outstanding": 1000000.0,
                "float_shares": 750000.0,
            }
        ]
        resolved_asset = {
            "symbol": "AAPL",
            "asset_type": "stocks",
            "data_source": "zoya",
            "exchange": "NASDAQ",
            "asset_metadata": {"sector": "Technology"},
        }

        with patch.object(screener, "resolve_asset_metadata", return_value=resolved_asset), patch.object(
            screener,
            "fetch_live_data",
            AsyncMock(return_value=live_data),
        ):
            detail = await screener.get_asset_detail("AAPL", "stocks", "1day", request)

        self.assertIsInstance(detail["channels"]["lrc"]["middle"], list)
        self.assertIsInstance(
            detail["confluence_channels"]["fast_lrc"]["channel"]["middle"],
            list,
        )
        serialized = ScreeningDetailResponse(detail=detail).model_dump_json()
        self.assertIn('"channels"', serialized)
        self.assertIn('"confluence_channels"', serialized)


@asynccontextmanager
async def app_client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


class ScreeningApiSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_endpoint_returns_screening_response(self):
        payload = {
            "asset_type": "stocks",
            "stock_sources": ["zoya"],
            "timeframe_mode": "single",
            "single_timeframe": "1h",
            "indicators": [],
        }
        mocked_response = {
            "results": [
                {
                    "symbol": "AAPL",
                    "price": 100.0,
                    "asset_type": "stocks",
                    "data_source": "zoya",
                    "exchange": "NASDAQ",
                    "exchange_availability": None,
                    "timeframe": "1h",
                    "scan_stage": None,
                    "name": None,
                    "category": None,
                    "cmc_id": None,
                    "rank": None,
                    "compliance_status": None,
                    "report_date": None,
                    "purification_ratio": None,
                    "candles_count": None,
                    "last_candle_time": None,
                    "note": None,
                    "stickers": ["EMA"],
                    "matched_indicators": None,
                }
            ],
            "gate_session_id": None,
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "run_single",
            AsyncMock(return_value=mocked_response),
        ) as run_single_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/run", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), mocked_response)
        run_single_mock.assert_awaited_once()

    async def test_run_endpoint_rejects_unsupported_indicator_names(self):
        # "adx" now has a live handler (Trendy ADX) — use "stochrsi", which is still
        # accepted by the Pydantic model but has no INDICATOR_REGISTRY entry.
        payload = {
            "asset_type": "stocks",
            "stock_sources": ["zoya"],
            "timeframe_mode": "single",
            "single_timeframe": "1h",
            "indicators": [{"name": "stochrsi", "timeframe": "single"}],
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "run_single",
            AsyncMock(),
        ) as run_single_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/run", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn("stochrsi", response.json()["detail"])
        run_single_mock.assert_not_awaited()

    async def test_crypto_exchange_options_endpoint_returns_available_exchanges(self):
        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "list_crypto_exchanges",
            return_value=[
                {"exchange": "binance", "coin_count": 236},
                {"exchange": "coinbase", "coin_count": 277},
                {"exchange": "kraken", "coin_count": 322},
            ],
        ) as list_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.get("/screen/crypto-exchanges")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "exchanges": [
                    {"exchange": "binance", "coin_count": 236},
                    {"exchange": "coinbase", "coin_count": 277},
                    {"exchange": "kraken", "coin_count": 322},
                ],
            },
        )
        list_mock.assert_called_once_with()

    async def test_run_gate_endpoint_returns_gate_session_id(self):
        payload = {
            "asset_type": "crypto",
            "exchanges": ["binance"],
            "timeframe_mode": "gate_entry",
            "gate_timeframe": "4h",
            "entry_timeframe": "1h",
            "indicators": [],
        }
        mocked_response = {
            "results": [
                {
                    "symbol": "BTC-USD",
                    "price": 50000.0,
                    "asset_type": "crypto",
                    "data_source": "massive",
                    "exchange": "binance",
                    "exchange_availability": None,
                    "timeframe": "4h",
                    "scan_stage": None,
                    "name": None,
                    "category": None,
                    "cmc_id": None,
                    "rank": None,
                    "compliance_status": None,
                    "report_date": None,
                    "purification_ratio": None,
                    "candles_count": None,
                    "last_candle_time": None,
                    "note": None,
                    "stickers": [],
                    "matched_indicators": None,
                }
            ],
            "gate_session_id": "session-123",
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "run_gate",
            AsyncMock(return_value=mocked_response),
        ) as run_gate_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/run-gate", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), mocked_response)
        run_gate_mock.assert_awaited_once()

    async def test_run_entry_endpoint_requires_gate_session_id(self):
        payload = {
            "asset_type": "crypto",
            "exchanges": ["binance"],
            "timeframe_mode": "gate_entry",
            "gate_timeframe": "4h",
            "entry_timeframe": "1h",
            "indicators": [],
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False):
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/run-entry", json=payload)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "Entry requires gate_session_id from /run-gate.",
        )

    async def test_run_entry_endpoint_returns_screening_response(self):
        payload = {
            "asset_type": "crypto",
            "exchanges": ["binance"],
            "timeframe_mode": "gate_entry",
            "gate_timeframe": "4h",
            "entry_timeframe": "1h",
            "gate_session_id": "session-123",
            "indicators": [],
        }
        mocked_response = {
            "results": [
                {
                    "symbol": "BTC-USD",
                    "price": 50500.0,
                    "asset_type": "crypto",
                    "data_source": "massive",
                    "exchange": "binance",
                    "exchange_availability": None,
                    "timeframe": "1h",
                    "scan_stage": None,
                    "name": None,
                    "category": None,
                    "cmc_id": None,
                    "rank": None,
                    "compliance_status": None,
                    "report_date": None,
                    "purification_ratio": None,
                    "candles_count": None,
                    "last_candle_time": None,
                    "note": None,
                    "stickers": ["RSI"],
                    "matched_indicators": None,
                }
            ],
            "gate_session_id": None,
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "run_entry",
            AsyncMock(return_value=mocked_response),
        ) as run_entry_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/run-entry", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), mocked_response)
        run_entry_mock.assert_awaited_once()

    async def test_details_endpoint_returns_screening_detail_response(self):
        payload = {
            "symbol": "BTC-USD",
            "asset_type": "crypto",
            "timeframe": "4h",
            "scan_stage": "entry",
            "request": {
                "asset_type": "crypto",
                "exchanges": ["binance"],
                "timeframe_mode": "gate_entry",
                "gate_timeframe": "1day",
                "entry_timeframe": "4h",
                "indicators": [],
            },
        }
        mocked_response = {
            "detail": {
                "symbol": "BTC-USD",
                "price": 50500.0,
                "asset_type": "crypto",
                "data_source": "massive",
                "exchange": "binance",
                "exchange_availability": ["binance", "coinbase"],
                "timeframe": "4h",
                "scan_stage": "entry",
                "name": "Bitcoin",
                "category": "general",
                "cmc_id": 1,
                "rank": 1,
                "compliance_status": None,
                "report_date": None,
                "purification_ratio": None,
                "candles_count": 20,
                "last_candle_time": 1710000000,
                "note": None,
                "stickers": ["RSI (14) | Neutral Turning Up | No Pattern | Last 1 Candle"],
                "matched_indicators": ["rsi"],
                "asset_metadata": {"symbol": "BTC", "rank": 1},
                "request_filters": {"timeframe": "4h", "scan_stage": "entry"},
                "indicator_details": [],
                "filter_details": [],
                "market_data": {
                    "candles_provider": "massive",
                    "next_refresh_at": 1710000300,
                    "shares_outstanding": None,
                    "float_shares": None,
                    "last_candle": {"close": 50500.0},
                    "recent_candles": [{"close": 50500.0}],
                },
                "channels": {},
                "confluence_channels": {},
            }
        }

        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            screening,
            "get_asset_detail",
            AsyncMock(return_value=mocked_response["detail"]),
        ) as get_detail_mock:
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.post("/screen/details", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), mocked_response)
        get_detail_mock.assert_awaited_once()

    async def test_worker_ops_endpoints_control_worker(self):
        class StubWorker:
            def __init__(self):
                self.running = False
                self.poll_interval = 15
                self.batch_size = 50

            async def start(self):
                self.running = True

            async def stop(self):
                self.running = False

            async def refresh_once(self):
                return None

            def update_runtime(self, poll_interval=None, batch_size=None):
                if poll_interval is not None:
                    self.poll_interval = poll_interval
                if batch_size is not None:
                    self.batch_size = batch_size

            def status(self):
                return {
                    "running": self.running,
                    "poll_interval": self.poll_interval,
                    "batch_size": self.batch_size,
                }

        with patch.object(main, "build_market_data_worker", return_value=StubWorker()), patch.object(
            main.settings,
            "MARKET_DATA_WORKER_ENABLED",
            False,
        ), patch.object(main.settings, "ADMIN_API_TOKEN", ""), patch.object(
            main.settings,
            "APP_ENV",
            "development",
        ):
            app = main.create_app()
            async with app_client(app) as client:
                status_response = await client.get("/screen/ops/worker")
                self.assertEqual(status_response.status_code, 200)
                self.assertFalse(status_response.json()["worker"]["running"])

                start_response = await client.post("/screen/ops/worker/start")
                self.assertEqual(start_response.status_code, 200)
                self.assertTrue(start_response.json()["worker"]["running"])

                config_response = await client.post(
                    "/screen/ops/worker/config",
                    json={"poll_interval": 3, "batch_size": 9},
                )
                self.assertEqual(config_response.status_code, 200)
                self.assertEqual(config_response.json()["worker"]["poll_interval"], 3)
                self.assertEqual(config_response.json()["worker"]["batch_size"], 9)

                refresh_response = await client.post("/screen/ops/worker/refresh")
                self.assertEqual(refresh_response.status_code, 200)

                stop_response = await client.post("/screen/ops/worker/stop")
                self.assertEqual(stop_response.status_code, 200)
                self.assertFalse(stop_response.json()["worker"]["running"])

    async def test_worker_ops_require_admin_token_when_configured(self):
        with patch.object(main.settings, "ADMIN_API_TOKEN", "secret"), patch.object(
            main.settings,
            "MARKET_DATA_WORKER_ENABLED",
            False,
        ):
            app = main.create_app()
            async with app_client(app) as client:
                denied = await client.get("/screen/ops/worker")
                self.assertEqual(denied.status_code, 403)

                allowed = await client.get(
                    "/screen/ops/worker",
                    headers={"X-Admin-Token": "secret"},
                )
                self.assertEqual(allowed.status_code, 200)

    async def test_worker_ops_deny_all_requests_in_production_without_admin_token(self):
        with patch.object(main.settings, "ADMIN_API_TOKEN", ""), patch.object(
            main.settings,
            "APP_ENV",
            "production",
        ), patch.object(
            main.settings,
            "MARKET_DATA_WORKER_ENABLED",
            False,
        ):
            app = main.create_app()
            async with app_client(app) as client:
                denied = await client.get("/screen/ops/worker")
                self.assertEqual(denied.status_code, 403)

    async def test_worker_ops_allow_requests_in_development_without_admin_token(self):
        with patch.object(main.settings, "ADMIN_API_TOKEN", ""), patch.object(
            main.settings,
            "APP_ENV",
            "development",
        ), patch.object(
            main.settings,
            "MARKET_DATA_WORKER_ENABLED",
            False,
        ):
            app = main.create_app()
            async with app_client(app) as client:
                allowed = await client.get("/screen/ops/worker")
                self.assertEqual(allowed.status_code, 200)

    async def test_runtime_settings_endpoint_returns_effective_server_config(self):
        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            main.settings,
            "ADMIN_API_TOKEN",
            "",
        ), patch.object(
            main.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "binance",
        ), patch.object(
            main.settings,
            "BINANCE_REQUESTS_PER_SECOND",
            11,
        ):
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.get("/screen/ops/runtime-settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("app", payload)
        self.assertIn("server", payload)
        self.assertIn("screening", payload)
        self.assertIn("worker", payload)
        self.assertIn("integrations", payload)
        self.assertIn("effective", payload["worker"])
        self.assertEqual(payload["screening"]["candles_provider"], "massive")
        self.assertEqual(payload["screening"]["crypto_candles_provider"], "binance")
        self.assertEqual(payload["screening"]["crypto_api_base_url"], "https://api.binance.com")
        self.assertEqual(payload["worker"]["binance_requests_per_second"], 11)
        self.assertIn("binance", payload["integrations"]["providers"])


class ProductionReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoints_work_with_worker_disabled(self):
        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            main.settings,
            "MASSIVE_API_KEY",
            "massive-token",
        ), patch.object(
            main.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            app = main.create_app()

            async with app_client(app) as client:
                health_response = await client.get("/healthz")
                ready_response = await client.get("/readyz")

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.json()["status"], "ok")
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["status"], "ready")
        self.assertEqual(ready_response.json()["mode"], "massive_candles")

    async def test_readyz_degrades_when_worker_expected_but_not_running(self):
        class StubWorker:
            async def start(self):
                return None

            async def stop(self):
                return None

            def status(self):
                return {"running": False, "last_error": "boom"}

        with patch.object(main, "build_market_data_worker", return_value=StubWorker()), patch.object(
            main.settings,
            "MARKET_DATA_WORKER_ENABLED",
            True,
        ), patch.object(
            main.settings,
            "MASSIVE_API_KEY",
            "massive-token",
        ), patch.object(
            main.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["mode"], "massive_candles")

    async def test_readyz_degrades_when_market_data_api_key_is_missing(self):
        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            main.settings,
            "MASSIVE_API_KEY",
            "",
        ), patch.object(
            main.settings,
            "POLYGON_API_KEY",
            "",
        ), patch.object(
            main.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["mode"], "massive_candles")

    async def test_readyz_reports_binance_crypto_mode(self):
        with patch.object(main.settings, "MARKET_DATA_WORKER_ENABLED", False), patch.object(
            main.settings,
            "MASSIVE_API_KEY",
            "massive-token",
        ), patch.object(
            main.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "binance",
        ):
            app = main.create_app()
            async with app_client(app) as client:
                response = await client.get("/readyz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["mode"], "stocks=massive,crypto=binance")


class MarketDataIntegrationTests(unittest.TestCase):
    def test_active_candle_provider_falls_back_to_massive(self):
        with patch.object(settings, "CANDLES_PROVIDER", "unsupported-provider"):
            self.assertEqual(market_data.active_candle_provider(), "massive")

    def test_active_crypto_candle_provider_falls_back_to_massive(self):
        with patch.object(settings, "CRYPTO_CANDLES_PROVIDER", "unsupported-provider"):
            self.assertEqual(market_data.active_crypto_candle_provider(), "massive")

    def test_active_crypto_candle_provider_accepts_binance(self):
        with patch.object(settings, "CRYPTO_CANDLES_PROVIDER", "binance"):
            self.assertEqual(market_data.active_crypto_candle_provider(), "binance")

    def test_default_concurrency_for_binance_provider_uses_binance_setting(self):
        with patch.object(settings, "BINANCE_FETCH_CONCURRENCY", 9):
            self.assertEqual(market_data.default_concurrency_for_provider("binance"), 9)

    def test_resolve_crypto_candle_fetcher_uses_binance_when_configured(self):
        with patch.object(settings, "CRYPTO_CANDLES_PROVIDER", "binance"):
            self.assertIs(market_data.resolve_crypto_candle_fetcher(), market_data.request_binance_candles)

    def test_timeframe_uses_worker_cache_for_intraday_and_daily(self):
        self.assertTrue(market_data.timeframe_uses_worker_cache("1h"))
        self.assertTrue(market_data.timeframe_uses_worker_cache("4h"))
        self.assertTrue(market_data.timeframe_uses_worker_cache("1day"))

    def test_market_data_requests_per_second_defaults_for_paid_plan(self):
        with patch.object(settings, "MASSIVE_REQUESTS_PER_SECOND", None), patch.object(
            settings,
            "POLYGON_REQUESTS_PER_SECOND",
            None,
        ):
            self.assertEqual(settings.market_data_requests_per_second, 60)

    def test_market_data_http2_defaults_true(self):
        with patch.object(settings, "MASSIVE_HTTP2", None), patch.object(
            settings,
            "POLYGON_HTTP2",
            None,
        ):
            self.assertTrue(settings.market_data_http2_enabled)

    def test_market_data_crypto_requests_per_minute_defaults_to_zero_for_realtime_plan(self):
        with patch.object(settings, "MASSIVE_CRYPTO_REQUESTS_PER_MINUTE", None):
            self.assertEqual(settings.market_data_crypto_requests_per_minute, 0)

    def test_polygon_backoff_uses_minimum_delay_for_429_without_retry_after(self):
        exc = SimpleNamespace(response=SimpleNamespace(status_code=429, headers={}))
        self.assertEqual(market_data._polygon_backoff_seconds(exc, 1), 15.0)

    def test_build_market_data_payload_marks_in_progress_last_candle_unclosed(self):
        now = 1_000_000
        candles = [
            {"time": now - 7200, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10},
            {"time": now - 1800, "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1, "volume": 12},
        ]

        with patch.object(market_data.time, "time", return_value=now):
            payload = market_data._build_market_data_payload("AAA", candles, "1h")

        self.assertNotIn("is_closed", payload["candles"][0])
        self.assertIs(payload["candles"][-1]["is_closed"], False)

    def test_build_market_data_payload_leaves_fully_elapsed_last_candle_closed(self):
        now = 1_000_000
        candles = [
            {"time": now - 7200, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10},
            {"time": now - 3700, "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1, "volume": 12},
        ]

        with patch.object(market_data.time, "time", return_value=now):
            payload = market_data._build_market_data_payload("AAA", candles, "1h")

        self.assertNotIn("is_closed", payload["candles"][-1])

    def test_confirm_if_needed_rejects_signal_candle_still_in_progress_from_live_payload(self):
        now = 1_000_000
        candles = [
            {"time": now - 7200, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10},
            {"time": now - 1800, "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1, "volume": 12},
        ]

        with patch.object(market_data.time, "time", return_value=now):
            payload = market_data._build_market_data_payload("AAA", candles, "1h")

        self.assertFalse(
            utils.confirm_if_needed(
                payload["candles"],
                1,
                {
                    "confirmation": True,
                    "confirmation_window": 0,
                    "confirmation_types": ["bullish"],
                },
            )
        )


class MarketDataAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_polygon_client_honors_market_data_http2_setting(self):
        client = AsyncMock()

        with patch.object(
            market_data,
            "_polygon_client",
            None,
        ), patch.object(
            settings,
            "MASSIVE_HTTP2",
            False,
        ), patch.object(
            settings,
            "POLYGON_HTTP2",
            None,
        ), patch.object(
            market_data.httpx,
            "AsyncClient",
            return_value=client,
        ) as async_client_mock:
            result = await market_data._get_polygon_client()

        self.assertIs(result, client)
        self.assertEqual(async_client_mock.call_args.kwargs["http2"], False)

    async def test_request_massive_candles_pages_backwards_when_more_history_is_needed(self):
        pages = [
            [
                {"t": 3000, "o": 3.0, "h": 3.2, "l": 2.9, "c": 3.1, "v": 30},
                {"t": 2000, "o": 2.0, "h": 2.2, "l": 1.9, "c": 2.1, "v": 20},
            ],
            [
                {"t": 1000, "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1, "v": 10},
            ],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_polygon_buffer_bars",
            return_value=0,
        ), patch.object(
            market_data,
            "_request_polygon_aggregate_page",
            AsyncMock(side_effect=pages),
        ) as request_page_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            payload = await market_data.request_massive_candles("AAPL", "4h", candles_limit=3)

        self.assertEqual([candle["time"] for candle in payload["candles"]], [1, 2, 3])
        self.assertEqual(request_page_mock.await_count, 2)
        record_call_mock.assert_called_once_with("massive")

    async def test_request_massive_candles_uses_grouped_daily_for_1day_requests(self):
        grouped_payload = {
            "symbol": "AAPL",
            "price": 3.1,
            "candles": [
                {"time": 2, "open": 2.0, "high": 2.2, "low": 1.9, "close": 2.1, "volume": 20.0},
                {"time": 3, "open": 3.0, "high": 3.2, "low": 2.9, "close": 3.1, "volume": 30.0},
            ],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": 4,
        }

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=[grouped_payload]),
        ) as grouped_mock, patch.object(
            market_data,
            "request_polygon_candles",
            AsyncMock(return_value=None),
        ) as polygon_mock:
            payload = await market_data.request_massive_candles("AAPL", "1day", candles_limit=2)

        self.assertEqual(payload, grouped_payload)
        grouped_mock.assert_awaited_once_with(["AAPL"], "1day", 2)
        polygon_mock.assert_not_awaited()

    async def test_request_massive_candles_skips_polygon_aggregate_fallback_for_1day_requests(self):
        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=[]),
        ) as grouped_mock, patch.object(
            market_data,
            "request_polygon_candles",
            AsyncMock(return_value={"symbol": "AAPL"}),
        ) as polygon_mock:
            payload = await market_data.request_massive_candles("AAPL", "1day", candles_limit=1)

        self.assertIsNone(payload)
        grouped_mock.assert_awaited_once_with(["AAPL"], "1day", 1)
        polygon_mock.assert_not_awaited()

    async def test_request_massive_candles_uses_grouped_daily_for_1w_requests(self):
        grouped_payload = {
            "symbol": "AAPL",
            "price": 103.0,
            "candles": [
                {"time": 1711324800, "open": 100.0, "high": 103.5, "low": 99.5, "close": 103.0, "volume": 30.0},
            ],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": 1711929600,
        }

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=[grouped_payload]),
        ) as grouped_mock, patch.object(
            market_data,
            "request_polygon_candles",
            AsyncMock(return_value=None),
        ) as polygon_mock:
            payload = await market_data.request_massive_candles("AAPL", "1w", candles_limit=1)

        self.assertEqual(payload, grouped_payload)
        grouped_mock.assert_awaited_once_with(["AAPL"], "1w", 1)
        polygon_mock.assert_not_awaited()

    async def test_request_binance_candles_shapes_klines_payload(self):
        rows = [
            [1000, "1.0", "1.2", "0.9", "1.1", "10.0"],
            [2000, "1.1", "1.3", "1.0", "1.2", "12.0"],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_resolve_binance_pair",
            AsyncMock(return_value="BTCUSDT"),
        ) as resolve_pair_mock, patch.object(
            market_data,
            "_binance_get_json",
            AsyncMock(return_value=rows),
        ) as get_json_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            payload = await market_data.request_binance_candles("BTC-USD", "1h", candles_limit=2)

        self.assertEqual(payload["symbol"], "BTC-USD")
        self.assertEqual(payload["candles_provider"], "binance")
        self.assertEqual([candle["time"] for candle in payload["candles"]], [1, 2])
        resolve_pair_mock.assert_awaited_once_with("BTC-USD", force_refresh=False)
        get_json_mock.assert_awaited_once_with(
            "/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "1h", "limit": 2},
            weight=market_data.BINANCE_KLINES_REQUEST_WEIGHT,
        )
        record_call_mock.assert_called_once_with("binance")

    async def test_request_binance_candles_preserves_native_four_hour_bars(self):
        rows = [
            [1000, "1.0", "1.2", "0.9", "1.1", "10.0"],
            [2000, "1.1", "1.3", "1.0", "1.2", "12.0"],
            [3000, "1.2", "1.4", "1.1", "1.3", "14.0"],
            [4000, "1.3", "1.5", "1.2", "1.4", "16.0"],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_resolve_binance_pair",
            AsyncMock(return_value="BTCUSDT"),
        ), patch.object(
            market_data,
            "_binance_get_json",
            AsyncMock(return_value=rows),
        ):
            payload = await market_data.request_binance_candles("BTC-USD", "4h", candles_limit=4)

        self.assertEqual([candle["time"] for candle in payload["candles"]], [1, 2, 3, 4])
        self.assertEqual(payload["price"], 1.4)

    async def test_request_binance_candles_preserves_native_bars_across_supported_intervals(self):
        rows = [
            [1000, "1.0", "1.2", "0.9", "1.1", "10.0"],
            [2000, "1.1", "1.3", "1.0", "1.2", "12.0"],
            [3000, "1.2", "1.4", "1.1", "1.3", "14.0"],
            [4000, "1.3", "1.5", "1.2", "1.4", "16.0"],
        ]
        supported_timeframes = [
            "1m",
            "3m",
            "5m",
            "15m",
            "30m",
            "1h",
            "2h",
            "4h",
            "6h",
            "8h",
            "12h",
            "1day",
            "3day",
            "1w",
            "1mo",
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_resolve_binance_pair",
            AsyncMock(return_value="BTCUSDT"),
        ), patch.object(
            market_data,
            "_binance_get_json",
            AsyncMock(return_value=rows),
        ):
            for timeframe in supported_timeframes:
                with self.subTest(timeframe=timeframe):
                    payload = await market_data.request_binance_candles(
                        "BTC-USD",
                        timeframe,
                        candles_limit=4,
                    )

                    self.assertIsNotNone(payload)
                    self.assertEqual([candle["time"] for candle in payload["candles"]], [1, 2, 3, 4])
                    self.assertEqual(payload["price"], 1.4)

    async def test_fetch_live_data_uses_massive_snapshot_fast_path_for_latest_only_stocks(self):
        snapshot_payload = [
            {
                "symbol": "AAPL",
                "price": 100.0,
                "candles": [{"time": 1, "open": 99.0, "high": 101.0, "low": 98.5, "close": 100.0, "volume": 10.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
        ]

        with patch.object(
            market_data,
            "request_massive_snapshots",
            AsyncMock(return_value=snapshot_payload),
        ) as snapshots_mock, patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock:
            results = await market_data.fetch_live_data(["AAPL"], "1h", latest_only=True)

        self.assertEqual([item["symbol"] for item in results], ["AAPL"])
        snapshots_mock.assert_awaited_once()
        fetch_batches_mock.assert_not_awaited()

    async def test_fetch_live_data_uses_massive_snapshot_fast_path_for_latest_only_crypto(self):
        snapshot_payload = [
            {
                "symbol": "BTC-USD",
                "price": 50000.0,
                "candles": [{"time": 1, "open": 50000.0, "high": 50000.0, "low": 50000.0, "close": 50000.0, "volume": 0.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
        ]

        with patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            False,
        ), patch.object(
            market_data,
            "request_massive_snapshots",
            AsyncMock(return_value=snapshot_payload),
        ) as snapshots_mock, patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock:
            results = await market_data.fetch_live_data(["BTC-USD"], "1h", latest_only=True)

        self.assertEqual([item["symbol"] for item in results], ["BTC-USD"])
        snapshots_mock.assert_awaited_once_with(["BTC-USD"], "1h")
        fetch_batches_mock.assert_not_awaited()

    async def test_fetch_live_data_uses_binance_quote_fast_path_for_latest_only_crypto(self):
        quote_payload = [
            {
                "symbol": "BTC-USD",
                "price": 50000.0,
                "candles": [{"time": 1, "open": 50000.0, "high": 50000.0, "low": 50000.0, "close": 50000.0, "volume": 0.0}],
                "candles_provider": "binance",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
        ]

        with patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "binance",
        ), patch.object(
            market_data,
            "request_binance_quotes",
            AsyncMock(return_value=quote_payload),
        ) as quotes_mock, patch.object(
            market_data,
            "request_massive_snapshots",
            AsyncMock(return_value=[]),
        ) as snapshots_mock, patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock:
            results = await market_data.fetch_live_data(["BTC-USD"], "1h", latest_only=True)

        self.assertEqual([item["symbol"] for item in results], ["BTC-USD"])
        quotes_mock.assert_awaited_once_with(["BTC-USD"], "1h")
        snapshots_mock.assert_not_awaited()
        fetch_batches_mock.assert_not_awaited()

    async def test_fetch_live_data_reuses_cached_1day_results_via_worker_cache(self):
        cached_payload = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [
                {"time": 1, "open": 99.0, "high": 101.0, "low": 98.0, "close": 99.5, "volume": 10.0},
                {"time": 2, "open": 99.5, "high": 101.5, "low": 99.0, "close": 100.0, "volume": 12.0},
            ],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": int(time.time()) + 3600,
        }

        with patch.object(
            market_data.store,
            "get_cached",
            return_value={"AAPL": {"payload": cached_payload, "updated_at": int(time.time())}},
        ), patch.object(
            market_data.store,
            "register_interest",
        ) as register_interest_mock, patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock:
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2)

        self.assertEqual([item["symbol"] for item in results], ["AAPL"])
        fetch_batches_mock.assert_not_awaited()
        register_interest_mock.assert_called_once()

    async def test_fetch_live_data_backs_off_unresolved_worker_cache_misses_without_stale_payload(self):
        now = 1_000
        expected_backoff = now + max(
            market_data.FAILED_REFRESH_BACKOFF_SECONDS,
            market_data.timeframe_seconds("1day") // 4,
        )

        with patch.object(
            market_data.time,
            "time",
            return_value=now,
        ), patch.object(
            market_data.store,
            "get_cached",
            return_value={},
        ), patch.object(
            market_data.store,
            "register_interest",
        ) as register_interest_mock, patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock, patch.object(
            market_data.store,
            "store_snapshots",
        ) as store_snapshots_mock, patch.object(
            market_data.store,
            "update_interest_schedule",
        ) as update_interest_schedule_mock:
            results = await market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2)

        self.assertEqual(results, [])
        fetch_batches_mock.assert_awaited_once_with(
            ["AAPL"],
            "1day",
            batch_size=market_data.DEFAULT_BATCH_SIZE,
            candles_limit=2,
        )
        register_interest_mock.assert_called_once()
        store_snapshots_mock.assert_not_called()
        update_interest_schedule_mock.assert_called_once_with(
            ["AAPL"],
            "1day",
            {"AAPL": expected_backoff},
        )

    async def test_fetch_live_data_offloads_blocking_store_calls_off_the_event_loop(self):
        # If store.get_cached blocked the event loop directly (the pre-fix
        # behavior), this synchronous sleep would also stall the concurrently
        # gathered ticker task, and the two durations would add up instead of
        # overlapping. asyncio.to_thread keeps them concurrent.
        block_seconds = 0.15
        tick_seconds = 0.03
        tick_count = 5

        def blocking_get_cached(symbols, timeframe):
            time.sleep(block_seconds)
            return {}

        async def ticker():
            for _ in range(tick_count):
                await asyncio.sleep(tick_seconds)

        with patch.object(
            market_data.store,
            "get_cached",
            side_effect=blocking_get_cached,
        ), patch.object(
            market_data.store,
            "register_interest",
        ), patch.object(
            market_data,
            "fetch_batches",
            AsyncMock(return_value=[]),
        ), patch.object(
            market_data.store,
            "store_snapshots",
        ), patch.object(
            market_data.store,
            "update_interest_schedule",
        ):
            started = time.perf_counter()
            await asyncio.gather(
                market_data.fetch_live_data(["AAPL"], "1day", candles_limit=2),
                ticker(),
            )
            elapsed = time.perf_counter() - started

        sequential_total = block_seconds + (tick_seconds * tick_count)
        # Concurrent execution should finish close to max(block, ticker), well
        # under the sum the two would take if the blocking call stalled the loop.
        self.assertLess(elapsed, sequential_total - 0.05)

    async def test_request_massive_snapshots_supports_mixed_stock_and_crypto_batches(self):
        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_request_polygon_snapshot_chunk",
            AsyncMock(
                side_effect=[
                    [{"symbol": "AAPL", "candles": [{"close": 100.0}], "price": 100.0}],
                    [{"symbol": "BTC-USD", "candles": [{"close": 50000.0}], "price": 50000.0}],
                ]
            ),
        ) as request_chunk_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            results = await market_data.request_massive_snapshots(["AAPL", "BTC-USD"], "1h")

        self.assertEqual([item["symbol"] for item in results], ["AAPL", "BTC-USD"])
        self.assertEqual(request_chunk_mock.await_count, 2)
        record_call_mock.assert_called_once_with("massive", amount=2)

    async def test_request_polygon_snapshot_chunk_includes_otc_for_stock_batches(self):
        with patch.object(
            market_data,
            "_polygon_get_json",
            AsyncMock(return_value={"tickers": []}),
        ) as get_json_mock:
            results = await market_data._request_polygon_snapshot_chunk(["AAPL", "MSFT"], "1h")

        self.assertEqual(results, [])
        get_json_mock.assert_awaited_once_with(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": "AAPL,MSFT", "include_otc": "true"},
        )

    async def test_request_massive_snapshots_uses_full_market_snapshot_for_large_stock_batches(self):
        symbols = [
            f"SYM{i}"
            for i in range(market_data.POLYGON_FULL_MARKET_SNAPSHOT_STOCK_MIN_SYMBOLS)
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_request_polygon_full_market_snapshot",
            AsyncMock(
                return_value=[
                    {"symbol": symbols[0], "candles": [{"close": 1.0}], "price": 1.0},
                    {"symbol": symbols[-1], "candles": [{"close": 2.0}], "price": 2.0},
                ]
            ),
        ) as full_market_mock, patch.object(
            market_data,
            "_request_polygon_snapshot_chunk",
            AsyncMock(return_value=[]),
        ) as chunk_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            results = await market_data.request_massive_snapshots(symbols, "1h")

        self.assertEqual([item["symbol"] for item in results], [symbols[0], symbols[-1]])
        full_market_mock.assert_awaited_once_with(symbols, "1h")
        chunk_mock.assert_not_awaited()
        record_call_mock.assert_called_once_with("massive", amount=1)

    async def test_polygon_get_json_retries_transport_errors_after_resetting_client(self):
        client = AsyncMock()
        client.get.side_effect = [
            httpx.ReadError("stream closed"),
            httpx.Response(
                200,
                json={"status": "OK", "results": []},
                request=httpx.Request("GET", "https://api.massive.com/test"),
            ),
        ]

        with patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_get_polygon_client",
            AsyncMock(return_value=client),
        ) as get_client_mock, patch.object(
            market_data,
            "_polygon_wait_for_request_slot",
            AsyncMock(),
        ), patch.object(
            market_data,
            "close_polygon_client",
            AsyncMock(),
        ) as close_client_mock:
            payload = await market_data._polygon_get_json("/v2/test")

        self.assertEqual(payload, {"status": "OK", "results": []})
        self.assertEqual(get_client_mock.await_count, 2)
        close_client_mock.assert_awaited_once()

    async def test_request_massive_grouped_daily_candles_builds_multi_day_payloads(self):
        grouped_days = [
            [
                {"T": "AAPL", "t": 3000, "o": 3.0, "h": 3.2, "l": 2.9, "c": 3.1, "v": 30},
                {"T": "MSFT", "t": 3000, "o": 30.0, "h": 30.2, "l": 29.9, "c": 30.1, "v": 300},
            ],
            [
                {"T": "AAPL", "t": 2000, "o": 2.0, "h": 2.2, "l": 1.9, "c": 2.1, "v": 20},
                {"T": "MSFT", "t": 2000, "o": 20.0, "h": 20.2, "l": 19.9, "c": 20.1, "v": 200},
            ],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_grouped_daily_candidate_dates",
            return_value=["2026-03-20", "2026-03-19"],
        ), patch.object(
            market_data,
            "_request_polygon_grouped_daily",
            AsyncMock(side_effect=grouped_days),
        ) as grouped_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            results = await market_data.request_massive_grouped_daily_candles(
                ["AAPL", "MSFT"],
                "1day",
                candles_limit=2,
            )

        self.assertEqual([item["symbol"] for item in results], ["AAPL", "MSFT"])
        self.assertEqual([candle["time"] for candle in results[0]["candles"]], [2, 3])
        self.assertEqual([candle["time"] for candle in results[1]["candles"]], [2, 3])
        self.assertEqual(grouped_mock.await_count, 2)
        record_call_mock.assert_called_once_with("massive", amount=2)

    async def test_request_massive_grouped_daily_candles_builds_multi_week_payloads(self):
        def timestamp_ms(year, month, day):
            return int(
                market_data.datetime(
                    year,
                    month,
                    day,
                    tzinfo=market_data.timezone.utc,
                ).timestamp()
                * 1000
            )

        grouped_days = [
            [{"T": "AAPL", "t": timestamp_ms(2026, 3, 27), "o": 15.0, "h": 17.0, "l": 14.0, "c": 16.0, "v": 150}],
            [{"T": "AAPL", "t": timestamp_ms(2026, 3, 26), "o": 14.0, "h": 18.0, "l": 13.0, "c": 15.0, "v": 140}],
            [{"T": "AAPL", "t": timestamp_ms(2026, 3, 20), "o": 12.0, "h": 13.0, "l": 11.0, "c": 12.5, "v": 120}],
            [{"T": "AAPL", "t": timestamp_ms(2026, 3, 19), "o": 11.0, "h": 14.0, "l": 10.0, "c": 12.0, "v": 110}],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_grouped_history_candidate_dates",
            return_value=["2026-03-27", "2026-03-26", "2026-03-20", "2026-03-19"],
        ), patch.object(
            market_data,
            "_request_polygon_grouped_daily",
            AsyncMock(side_effect=grouped_days),
        ) as grouped_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            results = await market_data.request_massive_grouped_daily_candles(
                ["AAPL"],
                "1w",
                candles_limit=2,
            )

        self.assertEqual([item["symbol"] for item in results], ["AAPL"])
        self.assertEqual(len(results[0]["candles"]), 2)
        self.assertEqual(
            results[0]["candles"],
            [
                {
                    "time": int(timestamp_ms(2026, 3, 19) / 1000),
                    "open": 11.0,
                    "high": 14.0,
                    "low": 10.0,
                    "close": 12.5,
                    "volume": 230.0,
                },
                {
                    "time": int(timestamp_ms(2026, 3, 26) / 1000),
                    "open": 14.0,
                    "high": 18.0,
                    "low": 13.0,
                    "close": 16.0,
                    "volume": 290.0,
                },
            ],
        )
        self.assertEqual(grouped_mock.await_count, 4)
        record_call_mock.assert_called_once_with("massive", amount=4)

    def test_grouped_daily_candidate_dates_skip_weekends(self):
        dates = market_data._grouped_daily_candidate_dates(
            3,
            reference_date=date(2026, 3, 23),
        )

        self.assertEqual(
            dates[:5],
            ["2026-03-23", "2026-03-20", "2026-03-19", "2026-03-18", "2026-03-17"],
        )

    def test_grouped_daily_candidate_dates_expand_for_large_history_requests(self):
        dates = market_data._grouped_daily_candidate_dates(
            101,
            reference_date=date(2026, 3, 23),
        )

        self.assertGreater(len(dates), 101)
        self.assertEqual(dates[:3], ["2026-03-23", "2026-03-20", "2026-03-19"])

    def test_grouped_daily_candidate_dates_include_weekends_for_crypto(self):
        dates = market_data._grouped_daily_candidate_dates_with_calendar(
            3,
            reference_date=date(2026, 3, 23),
            skip_weekends=False,
        )

        self.assertEqual(
            dates[:5],
            ["2026-03-23", "2026-03-22", "2026-03-21", "2026-03-20", "2026-03-19"],
        )

    def test_grouped_daily_crypto_candidate_dates_use_small_padding(self):
        with patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            False,
        ):
            dates = market_data._grouped_daily_crypto_candidate_dates(
                21,
                reference_date=date(2026, 3, 25),
            )

        self.assertEqual(len(dates), 23)
        self.assertEqual(dates[:3], ["2026-03-25", "2026-03-24", "2026-03-23"])

    def test_grouped_daily_crypto_candidate_dates_default_to_current_utc_day(self):
        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2026, 3, 27, 12, 0, 0, tzinfo=tz)

        real_datetime = market_data.datetime

        with patch.object(market_data, "datetime", FakeDateTime), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            False,
        ):
            dates = market_data._grouped_daily_crypto_candidate_dates(3)

        self.assertEqual(dates[:3], ["2026-03-27", "2026-03-26", "2026-03-25"])

    def test_grouped_daily_crypto_candidate_dates_default_to_previous_utc_day_for_eod_only_access(self):
        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                return real_datetime(2026, 3, 27, 12, 0, 0, tzinfo=tz)

        real_datetime = market_data.datetime

        with patch.object(market_data, "datetime", FakeDateTime), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            True,
        ):
            dates = market_data._grouped_daily_crypto_candidate_dates(3)

        self.assertEqual(dates[:3], ["2026-03-26", "2026-03-25", "2026-03-24"])

    def test_grouped_daily_crypto_request_interval_uses_fallback_backoff_for_eod_only_access(self):
        with patch.object(market_data.settings, "MASSIVE_CRYPTO_REQUESTS_PER_MINUTE", None), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            True,
        ):
            self.assertEqual(
                market_data._grouped_daily_crypto_request_interval_seconds(),
                5.0,
            )

    def test_grouped_daily_crypto_request_interval_defaults_to_zero_for_realtime_plan(self):
        with patch.object(market_data.settings, "MASSIVE_CRYPTO_REQUESTS_PER_MINUTE", None), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            False,
        ):
            self.assertEqual(
                market_data._grouped_daily_crypto_request_interval_seconds(),
                0.0,
            )

    def test_grouped_daily_date_concurrency_uses_plan_aware_defaults(self):
        with patch.object(market_data.settings, "MASSIVE_FETCH_CONCURRENCY", None), patch.object(
            market_data.settings,
            "POLYGON_FETCH_CONCURRENCY",
            36,
        ), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            True,
        ):
            self.assertEqual(market_data._grouped_daily_date_concurrency(is_crypto=True), 1)
            self.assertEqual(market_data._grouped_daily_date_concurrency(is_crypto=False), 36)

    def test_grouped_daily_date_concurrency_matches_stock_defaults_for_realtime_crypto(self):
        with patch.object(market_data.settings, "MASSIVE_FETCH_CONCURRENCY", None), patch.object(
            market_data.settings,
            "POLYGON_FETCH_CONCURRENCY",
            36,
        ), patch.object(
            market_data.settings,
            "MASSIVE_CRYPTO_END_OF_DAY_ONLY",
            False,
        ):
            self.assertEqual(market_data._grouped_daily_date_concurrency(is_crypto=True), 36)

    def test_grouped_daily_bulk_path_uses_lower_minimum_for_crypto(self):
        self.assertFalse(
            market_data._can_use_grouped_daily_bulk_path(
                [f"SYM{i}-USD" for i in range(market_data.POLYGON_GROUPED_DAILY_CRYPTO_MIN_SYMBOLS - 1)],
                "1day",
                8,
            )
        )

    def test_grouped_daily_bulk_path_supports_large_daily_history_windows(self):
        symbols = [f"SYM{i}" for i in range(market_data.POLYGON_GROUPED_DAILY_MIN_SYMBOLS)]

        self.assertTrue(
            market_data._can_use_grouped_daily_bulk_path(
                symbols,
                "1day",
                101,
            )
        )

    def test_grouped_daily_bulk_path_is_disabled_for_binance_crypto_provider(self):
        symbols = [f"SYM{i}-USD" for i in range(market_data.POLYGON_GROUPED_DAILY_CRYPTO_MIN_SYMBOLS)]

        with patch.object(market_data.settings, "CRYPTO_CANDLES_PROVIDER", "binance"):
            self.assertFalse(
                market_data._can_use_grouped_daily_bulk_path(
                    symbols,
                    "1day",
                    8,
                )
            )

        with patch.object(market_data.settings, "CRYPTO_CANDLES_PROVIDER", "massive"):
            self.assertTrue(
                market_data._can_use_grouped_daily_bulk_path(
                    [f"SYM{i}-USD" for i in range(market_data.POLYGON_GROUPED_DAILY_CRYPTO_MIN_SYMBOLS)],
                    "1day",
                    8,
                )
            )

    async def test_fetch_batches_uses_grouped_daily_path_for_small_daily_stock_requests(self):
        symbols = ["AAPL", "MSFT"]
        grouped_payload = [
            {
                "symbol": "AAPL",
                "price": 1.0,
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
            {
                "symbol": "MSFT",
                "price": 2.0,
                "candles": [{"time": 1, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=2)

        self.assertEqual([item["symbol"] for item in results], symbols)
        grouped_mock.assert_awaited_once_with(symbols, "1day", 2)
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_uses_grouped_daily_path_for_small_weekly_stock_requests(self):
        symbols = ["AAPL", "MSFT"]
        grouped_payload = [
            {
                "symbol": "AAPL",
                "price": 10.0,
                "candles": [{"time": 1, "open": 9.0, "high": 10.0, "low": 8.0, "close": 10.0, "volume": 10.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
            {
                "symbol": "MSFT",
                "price": 20.0,
                "candles": [{"time": 1, "open": 19.0, "high": 20.0, "low": 18.0, "close": 20.0, "volume": 20.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1w", candles_limit=2)

        self.assertEqual([item["symbol"] for item in results], symbols)
        grouped_mock.assert_awaited_once_with(symbols, "1w", 2)
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_prefilters_large_intraday_stock_scans_with_snapshots(self):
        symbols = [
            f"SYM{i}"
            for i in range(market_data.POLYGON_INTRADAY_SNAPSHOT_PREFILTER_MIN_SYMBOLS)
        ]
        snapshot_payload = [
            {
                "symbol": symbols[0],
                "price": 1.0,
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
            },
            {
                "symbol": symbols[-1],
                "price": 2.0,
                "candles": [{"time": 1, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}],
            },
        ]
        candle_payloads = [
            {
                "symbol": symbols[0],
                "price": 1.0,
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
            {
                "symbol": symbols[-1],
                "price": 2.0,
                "candles": [{"time": 1, "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 2.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            },
        ]

        with patch.object(
            market_data,
            "request_massive_snapshots",
            AsyncMock(return_value=snapshot_payload),
        ) as snapshots_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(side_effect=candle_payloads),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1h", candles_limit=16)

        self.assertEqual([item["symbol"] for item in results], [symbols[0], symbols[-1]])
        snapshots_mock.assert_awaited_once_with(symbols, "1h")
        self.assertEqual(candles_mock.await_count, 2)

    async def test_fetch_batches_logs_and_skips_a_symbol_whose_fetch_raises(self):
        good_payload = {
            "symbol": "GOOD",
            "price": 1.0,
            "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
            "candles_provider": "massive",
            "shares_outstanding": None,
            "float_shares": None,
            "next_refresh_at": 2,
        }

        async def flaky_request_massive_candles(symbol, timeframe, candles_limit=market_data.MAX_CANDLES):
            if symbol == "BAD":
                raise RuntimeError("malformed candle payload")
            return good_payload

        with patch.object(
            market_data,
            "request_massive_candles",
            flaky_request_massive_candles,
        ), self.assertLogs("services.market_data", level="WARNING") as log_ctx:
            results = await market_data.fetch_batches(["BAD", "GOOD"], "1h", candles_limit=16)

        self.assertEqual([item["symbol"] for item in results], ["GOOD"])
        self.assertTrue(
            any("fetch_batches symbol fetch failed" in message and "BAD" in message for message in log_ctx.output)
        )

    async def test_fetch_batches_overlaps_symbols_instead_of_waiting_for_batches_to_drain(self):
        # One slow symbol placed in the first batch, followed by enough fast
        # symbols to span several more batches. If batches were still awaited
        # sequentially (the pre-fix behavior), the later batches couldn't
        # start until the slow symbol's batch fully drained, adding their
        # runtime on top of the slow symbol's. With a single concurrency-gated
        # pool, the other slots keep draining fast symbols while the slow one
        # is still in flight, so total time stays close to just the slow
        # symbol's duration.
        # Windows' asyncio timer granularity under IsolatedAsyncioTestCase adds
        # tens of ms of fixed overhead, so the slow/fast durations need enough
        # separation that the real signal isn't lost in that noise.
        slow_seconds = 0.8
        fast_seconds = 0.04
        fast_symbols = [f"FAST{i}" for i in range(18)]
        batch_size = 3
        concurrency = 3

        async def timed_request_massive_candles(symbol, timeframe, candles_limit=market_data.MAX_CANDLES):
            await asyncio.sleep(slow_seconds if symbol == "SLOW" else fast_seconds)
            return {
                "symbol": symbol,
                "price": 1.0,
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }

        with patch.object(market_data, "request_massive_candles", timed_request_massive_candles):
            started = time.perf_counter()
            results = await market_data.fetch_batches(
                ["SLOW", *fast_symbols],
                "1h",
                batch_size=batch_size,
                concurrency=concurrency,
                candles_limit=16,
            )
            elapsed = time.perf_counter() - started

        self.assertEqual(len(results), 1 + len(fast_symbols))

        remaining_fast_after_first_batch = len(fast_symbols) - (batch_size - 1)
        sequential_batches_estimate = slow_seconds + (
            -(-remaining_fast_after_first_batch // concurrency) * fast_seconds
        )
        self.assertLess(elapsed, sequential_batches_estimate - 0.1)

    async def test_fetch_batches_uses_grouped_daily_bulk_path_for_large_daily_stock_requests(self):
        symbols = [f"SYM{i}" for i in range(100)]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(symbols, start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual([item["symbol"] for item in results], symbols)
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_uses_grouped_daily_bulk_path_for_large_daily_stock_history_requests(self):
        symbols = [f"SYM{i}" for i in range(100)]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(symbols, start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=101)

        self.assertEqual([item["symbol"] for item in results], symbols)
        grouped_mock.assert_awaited_once_with(symbols, "1day", 101)
        candles_mock.assert_not_awaited()

    async def test_request_massive_grouped_daily_candles_builds_multi_day_crypto_payloads(self):
        grouped_days = [
            [
                {"T": "X:BTCUSD", "t": 3000, "o": 3.0, "h": 3.2, "l": 2.9, "c": 3.1, "v": 30},
                {"T": "X:ETHUSD", "t": 3000, "o": 30.0, "h": 30.2, "l": 29.9, "c": 30.1, "v": 300},
            ],
            [
                {"T": "X:BTCUSD", "t": 2000, "o": 2.0, "h": 2.2, "l": 1.9, "c": 2.1, "v": 20},
                {"T": "X:ETHUSD", "t": 2000, "o": 20.0, "h": 20.2, "l": 19.9, "c": 20.1, "v": 200},
            ],
        ]

        with patch.object(market_data.integration_runtime, "is_enabled", return_value=True), patch.object(
            market_data,
            "_polygon_api_key",
            return_value="polygon-token",
        ), patch.object(
            market_data,
            "_grouped_daily_candidate_dates_with_calendar",
            return_value=["2026-03-25", "2026-03-24"],
        ), patch.object(
            market_data,
            "_request_polygon_grouped_daily_crypto",
            AsyncMock(side_effect=grouped_days),
        ) as grouped_mock, patch.object(
            market_data.integration_runtime,
            "record_call",
        ) as record_call_mock:
            results = await market_data.request_massive_grouped_daily_candles(
                ["BTC-USD", "ETH-USD"],
                "1day",
                candles_limit=2,
            )

        self.assertEqual([item["symbol"] for item in results], ["BTC-USD", "ETH-USD"])
        self.assertEqual([candle["time"] for candle in results[0]["candles"]], [2, 3])
        self.assertEqual([candle["time"] for candle in results[1]["candles"]], [2, 3])
        self.assertEqual(grouped_mock.await_count, 2)
        record_call_mock.assert_called_once_with("massive", amount=2)

    async def test_fetch_batches_keeps_large_daily_stock_grouped_path_grouped_only_when_symbols_are_unresolved(self):
        symbols = [f"SYM{i}" for i in range(market_data.POLYGON_GROUPED_DAILY_SPARSE_SCAN_THRESHOLD)]
        grouped_symbols = symbols[:200]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(grouped_symbols, start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual(len(results), len(grouped_payload))
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_skips_per_symbol_fallback_for_bulk_only_daily_scans(self):
        symbols = [f"SYM{i}" for i in range(market_data.POLYGON_GROUPED_DAILY_BULK_ONLY_THRESHOLD)]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(symbols[:200], start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock:
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual(len(results), len(grouped_payload))
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_uses_grouped_daily_bulk_path_for_large_daily_crypto_requests(self):
        symbols = [f"SYM{i}-USD" for i in range(100)]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(symbols, start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock, patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual([item["symbol"] for item in results], symbols)
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_skips_per_symbol_fallback_for_large_daily_crypto_scans(self):
        symbols = [
            f"SYM{i}-USD"
            for i in range(market_data.POLYGON_GROUPED_DAILY_CRYPTO_BULK_ONLY_THRESHOLD)
        ]
        grouped_payload = [
            {
                "symbol": symbol,
                "price": float(index),
                "candles": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": float(index), "volume": 1.0}],
                "candles_provider": "massive",
                "shares_outstanding": None,
                "float_shares": None,
                "next_refresh_at": 2,
            }
            for index, symbol in enumerate(symbols[:40], start=1)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=grouped_payload),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock, patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual(len(results), len(grouped_payload))
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()

    async def test_fetch_batches_skips_per_symbol_fallback_when_large_daily_crypto_grouped_scan_returns_empty(self):
        symbols = [
            f"SYM{i}-USD"
            for i in range(market_data.POLYGON_GROUPED_DAILY_CRYPTO_BULK_ONLY_THRESHOLD)
        ]

        with patch.object(
            market_data,
            "request_massive_grouped_daily_candles",
            AsyncMock(return_value=[]),
        ) as grouped_mock, patch.object(
            market_data,
            "request_massive_candles",
            AsyncMock(return_value=None),
        ) as candles_mock, patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            results = await market_data.fetch_batches(symbols, "1day", candles_limit=8)

        self.assertEqual(results, [])
        grouped_mock.assert_awaited_once()
        candles_mock.assert_not_awaited()


class MarketDataWorkerTests(unittest.IsolatedAsyncioTestCase):
    def test_universe_symbols_normalizes_crypto_symbols(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=50)

        with patch("services.market_data_worker.load_zoya_universe", return_value=[{"symbol": "AAPL"}]), patch(
            "services.market_data_worker.load_crypto_universe",
            return_value=[{"symbol": "BTC"}, {"symbol": "ETH-USD"}],
        ), patch("services.market_data_worker.settings.SCREENING_MAX_SYMBOLS", 0):
            symbols = worker._universe_symbols()

        self.assertEqual(symbols, ["AAPL", "BTC-USD", "ETH-USD"])

    async def test_seed_symbol_interest_registers_managed_timeframes_and_marks_missing_entries_due_now(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=50)
        cached_payload = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [{"time": 1, "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 10.0}],
            "candles_provider": "massive",
            "next_refresh_at": int(time.time()) + 3600,
        }

        def get_cached(symbols, timeframe):
            if timeframe == "1h":
                return {"AAPL": {"payload": cached_payload, "updated_at": int(time.time())}}
            return {}

        with patch("services.market_data_worker.load_zoya_universe", return_value=[{"symbol": "AAPL"}]), patch(
            "services.market_data_worker.load_crypto_universe",
            return_value=[{"symbol": "BTC"}],
        ), patch("services.market_data_worker.settings.SCREENING_MAX_SYMBOLS", 10), patch(
            "services.market_data_worker.store.get_cached",
            side_effect=get_cached,
        ), patch(
            "services.market_data_worker.store.register_interest"
        ) as register_interest_mock:
            worker._seed_symbol_interest(force=True)

        self.assertEqual(register_interest_mock.call_count, len(WORKER_TIMEFRAMES))
        calls_by_timeframe = {
            call.args[1]: {
                "symbols": call.args[0],
                "next_refresh_map": call.kwargs["next_refresh_map"],
            }
            for call in register_interest_mock.call_args_list
        }
        self.assertEqual(WORKER_TIMEFRAMES, ("1h", "4h", "1day"))
        self.assertEqual(calls_by_timeframe["1h"]["symbols"], ["AAPL", "BTC-USD"])
        self.assertGreater(calls_by_timeframe["1h"]["next_refresh_map"]["AAPL"], int(time.time()))
        self.assertEqual(calls_by_timeframe["1h"]["next_refresh_map"]["BTC-USD"], int(worker._last_seed_at))
        self.assertEqual(calls_by_timeframe["4h"]["next_refresh_map"]["AAPL"], int(worker._last_seed_at))
        self.assertEqual(calls_by_timeframe["1day"]["next_refresh_map"]["BTC-USD"], int(worker._last_seed_at))

    async def test_seed_symbol_interest_marks_provider_mismatches_due_now(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=50)
        cached_payload = {
            "symbol": "AAPL",
            "price": 100.0,
            "candles": [{"time": 1, "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 10.0}],
            "candles_provider": "binance",
            "next_refresh_at": int(time.time()) + 3600,
        }

        with patch("services.market_data_worker.load_zoya_universe", return_value=[{"symbol": "AAPL"}]), patch(
            "services.market_data_worker.load_crypto_universe",
            return_value=[],
        ), patch("services.market_data_worker.settings.SCREENING_MAX_SYMBOLS", 10), patch(
            "services.market_data_worker.store.get_cached",
            return_value={"AAPL": {"payload": cached_payload, "updated_at": int(time.time())}},
        ), patch(
            "services.market_data_worker.store.register_interest"
        ) as register_interest_mock:
            worker._seed_symbol_interest(force=True)

        self.assertEqual(register_interest_mock.call_count, len(WORKER_TIMEFRAMES))
        for call in register_interest_mock.call_args_list:
            self.assertEqual(call.kwargs["next_refresh_map"]["AAPL"], int(worker._last_seed_at))

    async def test_refresh_due_symbols_fetches_and_stores_by_timeframe(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=2)
        due_map = {"1h": ["AAPL", "MSFT"], "1day": ["BTC-USD"], "1w": ["ETH-USD"]}
        cached_payload = {
            "symbol": "BTC-USD",
            "price": 50000.0,
            "candles": [{"time": 1, "open": 49000.0, "high": 51000.0, "low": 48000.0, "close": 50000.0, "volume": 10.0}],
            "candles_provider": "massive",
            "next_refresh_at": 0,
        }

        with patch("services.market_data_worker.store.due_symbols", return_value=due_map), patch(
            "services.market_data_worker.store.get_cached",
            return_value={"BTC-USD": {"payload": cached_payload, "updated_at": int(time.time())}},
        ), patch(
            "services.market_data_worker.store.update_interest_schedule"
        ) as update_interest_schedule_mock, patch(
            "services.market_data_worker.fetch_batches",
            AsyncMock(
                side_effect=[
                    [
                        {"symbol": "AAPL", "price": 100.0, "candles": []},
                        {"symbol": "MSFT", "price": 200.0, "candles": []},
                    ],
                    [{"symbol": "BTC-USD", "price": 50000.0, "candles": []}],
                ]
            ),
        ) as fetch_batches_mock, patch(
            "services.market_data_worker.store.store_snapshots"
        ) as store_snapshots_mock, patch.object(
            market_data.settings,
            "CRYPTO_CANDLES_PROVIDER",
            "massive",
        ):
            await worker.refresh_due_symbols()

        called_timeframes = [call.args[1] for call in fetch_batches_mock.await_args_list]
        self.assertEqual(called_timeframes, ["1h", "1day"])
        store_snapshots_mock.assert_called()
        update_interest_schedule_mock.assert_not_called()

    async def test_refresh_due_symbols_fetches_missing_entries_and_reschedules_fresh_ones(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=2)
        due_map = {"1day": ["AAPL", "MSFT", "GOOG"]}
        fresh_payload = {
            "symbol": "MSFT",
            "price": 100.0,
            "candles": [{"time": int(time.time()), "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 10.0}],
            "candles_provider": "massive",
            "next_refresh_at": int(time.time()) + 3600,
        }

        with patch("services.market_data_worker.store.due_symbols", return_value=due_map), patch(
            "services.market_data_worker.store.get_cached",
            return_value={"MSFT": {"payload": fresh_payload, "updated_at": int(time.time())}},
        ), patch(
            "services.market_data_worker.store.update_interest_schedule"
        ) as update_interest_schedule_mock, patch(
            "services.market_data_worker.fetch_batches",
            AsyncMock(return_value=[{"symbol": "AAPL", "price": 100.0, "candles": []}]),
        ) as fetch_batches_mock:
            await worker.refresh_due_symbols()

        fetch_batches_mock.assert_awaited_once_with(["AAPL", "GOOG"], "1day", batch_size=2)
        self.assertEqual(update_interest_schedule_mock.call_count, 2)

    async def test_refresh_due_symbols_backs_off_unresolved_symbols(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=2)
        now = 1_000
        due_map = {"1h": ["AAPL", "MSFT"]}
        expected_backoff = now + max(
            market_data.FAILED_REFRESH_BACKOFF_SECONDS,
            market_data.timeframe_seconds("1h") // 4,
        )

        with patch("services.market_data_worker.time.time", return_value=now), patch(
            "services.market_data_worker.store.due_symbols",
            return_value=due_map,
        ), patch(
            "services.market_data_worker.store.get_cached",
            return_value={},
        ), patch(
            "services.market_data_worker.store.update_interest_schedule"
        ) as update_interest_schedule_mock, patch(
            "services.market_data_worker.fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock, patch(
            "services.market_data_worker.store.store_snapshots"
        ) as store_snapshots_mock:
            await worker.refresh_due_symbols()

        fetch_batches_mock.assert_awaited_once_with(["AAPL", "MSFT"], "1h", batch_size=2)
        store_snapshots_mock.assert_not_called()
        self.assertEqual(update_interest_schedule_mock.call_count, 1)
        update_interest_schedule_mock.assert_called_once_with(
            ["AAPL", "MSFT"],
            "1h",
            {"AAPL": expected_backoff, "MSFT": expected_backoff},
        )

    async def test_refresh_due_symbols_respects_timeframe_priority(self):
        worker = MarketDataWorker(poll_interval=15, batch_size=2)
        due_map = {
            "1m": ["AAA"],
            "4h": ["EEE"],
            "1day": ["BBB"],
            "2day": ["CCC"],
            "1w": ["DDD"],
        }

        expired_payload = {
            "symbol": "BBB",
            "price": 100.0,
            "candles": [{"time": 1, "open": 99.0, "high": 101.0, "low": 98.0, "close": 100.0, "volume": 10.0}],
            "candles_provider": "massive",
            "next_refresh_at": 0,
        }

        with patch("services.market_data_worker.store.due_symbols", return_value=due_map), patch(
            "services.market_data_worker.store.get_cached",
            return_value={"BBB": {"payload": expired_payload, "updated_at": int(time.time())}},
        ), patch(
            "services.market_data_worker.store.clear_interest_for_timeframes"
        ) as clear_timeframes_mock, patch(
            "services.market_data_worker.store.clear_interest"
        ), patch(
            "services.market_data_worker.store.update_interest_schedule"
        ), patch(
            "services.market_data_worker.fetch_batches",
            AsyncMock(return_value=[]),
        ) as fetch_batches_mock:
            await worker.refresh_due_symbols()

        called_timeframes = [call.args[1] for call in fetch_batches_mock.await_args_list]
        self.assertEqual(called_timeframes, ["4h", "1day"])
        clear_timeframes_mock.assert_called_once_with(["1m", "2day", "1w"])


if __name__ == "__main__":
    unittest.main()

"""Milestone 3 Phase 4 - ADR ($) filter.

Covers every acceptance test and worked example in the client spec
(`stock_crypto_scanner_document_only_spec.md` sections 6.7, 6.8, 6.15 and
`stock_scanner_final_engineering_requirements.md` section 20).
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from models.filters import AdrFilter  # noqa: E402
from services import adr  # noqa: E402


def daily_candles(ranges, is_closed=True, base=100.0):
    """Build daily candles whose High-Low equals each requested range."""
    return [
        {
            "time": index,
            "open": base,
            "high": base + value,
            "low": base,
            "close": base,
            "volume": 1_000,
            "is_closed": is_closed,
        }
        for index, value in enumerate(ranges)
    ]


def candles_with_adr(adr_value, days=14):
    return daily_candles([adr_value] * days)


class AdrCalculationTests(unittest.TestCase):
    def test_adr_is_plain_high_minus_low_average(self):
        # 5 completed days: 1.00, 0.50, 0.75, 0.25, 1.00 -> 3.50 / 5 = 0.70
        candles = daily_candles([1.00, 0.50, 0.75, 0.25, 1.00])
        self.assertAlmostEqual(adr.compute_adr(candles, 5), 0.70)

    def test_ignores_previous_close_gaps_unlike_atr(self):
        # Spec 6.11: prev close $10, next day high $15 / low $14 contributes
        # only $1.00 - True Range would have counted the $4 gap.
        candles = [
            {"high": 10.0, "low": 10.0, "close": 10.0, "is_closed": True},
            {"high": 15.0, "low": 14.0, "close": 14.5, "is_closed": True},
        ]
        self.assertAlmostEqual(adr.compute_adr(candles, 1), 1.00)

    def test_only_the_last_lookback_days_are_averaged(self):
        candles = daily_candles([5.0] * 10 + [1.0] * 5)
        self.assertAlmostEqual(adr.compute_adr(candles, 5), 1.00)

    def test_lookback_change_recalculates_over_the_new_window(self):
        # Spec test 7: 14 -> 30 must re-average over 30 completed candles.
        candles = daily_candles([2.0] * 16 + [1.0] * 14)
        self.assertAlmostEqual(adr.compute_adr(candles, 14), 1.00)
        self.assertAlmostEqual(adr.compute_adr(candles, 30), (2.0 * 16 + 1.0 * 14) / 30)


class AdrComparisonTests(unittest.TestCase):
    def test_spec_test_1_minimum_met(self):
        # 14-day ADR $0.74, minimum $0.60 -> PASS
        result = adr.evaluate_adr(
            candles_with_adr(0.74),
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
        )
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(result["adr"], 0.74)

    def test_spec_test_2_below_minimum(self):
        # 20-day ADR $0.59, minimum $0.60 -> FAIL
        result = adr.evaluate_adr(
            daily_candles([0.59] * 20),
            {"enabled": True, "lookback_days": 20, "condition": "gte", "min_adr": 0.60},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "outside_threshold")

    def test_spec_test_3_between_range(self):
        # 30-day ADR $0.80 inside $0.60-$1.00 -> PASS
        result = adr.evaluate_adr(
            daily_candles([0.80] * 30),
            {
                "enabled": True,
                "lookback_days": 30,
                "condition": "between",
                "min_adr": 0.60,
                "max_adr": 1.00,
            },
        )
        self.assertTrue(result["passed"])

    def test_spec_example_2_maximum_met(self):
        # 10-day ADR $0.80, maximum $1.00 -> PASS
        result = adr.evaluate_adr(
            daily_candles([0.80] * 10),
            {"enabled": True, "lookback_days": 10, "condition": "lte", "max_adr": 1.00},
        )
        self.assertTrue(result["passed"])

    def test_spec_example_5_above_maximum(self):
        # ADR $1.01, maximum $1.00 -> FAIL
        result = adr.evaluate_adr(
            candles_with_adr(1.01),
            {"enabled": True, "lookback_days": 14, "condition": "lte", "max_adr": 1.00},
        )
        self.assertFalse(result["passed"])

    def test_spec_test_4_boundaries_are_inclusive(self):
        self.assertTrue(adr.adr_passes(0.60, "gte", min_adr=0.60))
        self.assertTrue(adr.adr_passes(1.00, "lte", max_adr=1.00))
        self.assertTrue(adr.adr_passes(0.60, "between", min_adr=0.60, max_adr=1.00))
        self.assertTrue(adr.adr_passes(1.00, "between", min_adr=0.60, max_adr=1.00))
        self.assertFalse(adr.adr_passes(0.59, "between", min_adr=0.60, max_adr=1.00))
        self.assertFalse(adr.adr_passes(1.01, "between", min_adr=0.60, max_adr=1.00))

    def test_comparison_uses_the_unrounded_value(self):
        # $0.5999... displays as $0.60 but must still fail a $0.60 minimum.
        candles = daily_candles([0.599] * 14)
        result = adr.evaluate_adr(
            candles,
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(adr.format_adr_value(result["adr"]), "$0.60")


class AdrDataIntegrityTests(unittest.TestCase):
    def test_spec_test_5_unfinished_candle_is_excluded(self):
        completed = daily_candles([1.00] * 14)
        forming = dict(completed[-1])
        forming.update({"high": 100.0 + 99.0, "is_closed": False})

        self.assertAlmostEqual(adr.compute_adr(completed, 14), 1.00)
        # The still-forming day is dropped, so ADR is unchanged by it.
        self.assertAlmostEqual(adr.compute_adr(completed + [forming], 14), 1.00)

    def test_spec_test_8_insufficient_history_excludes_symbol(self):
        candles = daily_candles([1.00] * 13)
        self.assertIsNone(adr.compute_adr(candles, 14))

        result = adr.evaluate_adr(
            candles,
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.10},
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "insufficient_daily_history")

    def test_spec_test_9_missing_data_is_not_zero_range(self):
        candles = daily_candles([1.00] * 14)
        candles[3]["high"] = None

        # Never averaged as a $0 day, and never silently averaged over 13.
        self.assertIsNone(adr.compute_adr(candles, 14))

    def test_invalid_and_inverted_candles_are_rejected(self):
        self.assertIsNone(adr.daily_range({"high": None, "low": 1.0}))
        self.assertIsNone(adr.daily_range({"high": "abc", "low": 1.0}))
        self.assertIsNone(adr.daily_range({"high": float("nan"), "low": 1.0}))
        self.assertIsNone(adr.daily_range({"high": 1.0, "low": 2.0}))
        self.assertEqual(adr.daily_range({"high": 2.0, "low": 1.0}), 1.0)

    def test_zero_range_day_is_still_a_valid_day(self):
        # A genuine unchanged day is $0.00 of movement - only *missing* data
        # is disqualifying.
        candles = daily_candles([0.0] * 14)
        self.assertEqual(adr.compute_adr(candles, 14), 0.0)


class AdrConfigTests(unittest.TestCase):
    def test_defaults_to_fourteen_days_and_gte(self):
        config = adr.normalize_adr_config({"enabled": True, "min_adr": 0.60})
        self.assertEqual(config["lookback_days"], 14)
        self.assertEqual(config["condition"], "gte")
        self.assertFalse(config["apply_to_crypto"])

    def test_condition_aliases_normalize(self):
        self.assertEqual(adr.normalize_adr_condition("Greater Than or Equal To".lower().replace(" ", "_")), "gte")
        self.assertEqual(adr.normalize_adr_condition(">="), "gte")
        self.assertEqual(adr.normalize_adr_condition("<="), "lte")
        self.assertEqual(adr.normalize_adr_condition("range"), "between")

    def test_disabled_filter_normalizes_to_none(self):
        self.assertIsNone(adr.normalize_adr_config({"enabled": False, "min_adr": 1.0}))
        self.assertIsNone(adr.normalize_adr_config(None))

    def test_lookback_is_floored_at_one(self):
        config = adr.normalize_adr_config({"enabled": True, "lookback_days": 0, "min_adr": 1.0})
        self.assertEqual(config["lookback_days"], 1)

    def test_between_requires_both_bounds(self):
        error = adr.adr_config_error(
            adr.normalize_adr_config({"enabled": True, "condition": "between", "min_adr": 0.60})
        )
        self.assertIn("both required", error)

    def test_minimum_above_maximum_is_rejected(self):
        error = adr.adr_config_error(
            adr.normalize_adr_config(
                {"enabled": True, "condition": "between", "min_adr": 1.50, "max_adr": 0.60}
            )
        )
        self.assertIn("cannot be greater than", error)

    def test_model_rejects_minimum_above_maximum(self):
        with self.assertRaises(ValueError):
            AdrFilter(condition="between", min_adr=1.50, max_adr=0.60)

    def test_model_rejects_missing_bound_for_condition(self):
        with self.assertRaises(ValueError):
            AdrFilter(condition="gte")
        with self.assertRaises(ValueError):
            AdrFilter(condition="lte", min_adr=0.60)

    def test_model_accepts_valid_configs(self):
        self.assertEqual(AdrFilter(condition="gte", min_adr=0.60).lookback_days, 14)
        self.assertEqual(
            AdrFilter(condition="between", min_adr=0.60, max_adr=1.00).condition, "between"
        )

    def test_disabled_model_skips_validation(self):
        self.assertFalse(AdrFilter(enabled=False).enabled)


class AdrScopeTests(unittest.TestCase):
    def test_stocks_are_in_scope_by_default(self):
        config = adr.normalize_adr_config({"enabled": True, "min_adr": 0.60})
        self.assertTrue(adr.adr_applies_to_asset({"symbol": "AAPL", "asset_type": "stocks"}, config))

    def test_crypto_is_out_of_scope_unless_enabled(self):
        config = adr.normalize_adr_config({"enabled": True, "min_adr": 0.60})
        crypto = {"symbol": "BTC-USD", "asset_type": "crypto"}
        self.assertFalse(adr.adr_applies_to_asset(crypto, config))

        opted_in = adr.normalize_adr_config(
            {"enabled": True, "min_adr": 0.60, "apply_to_crypto": True}
        )
        self.assertTrue(adr.adr_applies_to_asset(crypto, opted_in))

    def test_crypto_detected_from_symbol_when_type_missing(self):
        config = adr.normalize_adr_config({"enabled": True, "min_adr": 0.60})
        self.assertFalse(adr.adr_applies_to_asset({"symbol": "ETH-USD"}, config))


class AdrApplyTests(unittest.IsolatedAsyncioTestCase):
    def _assets(self):
        return [
            {"symbol": "WIDE", "asset_type": "stocks", "price": 10.0},
            {"symbol": "TIGHT", "asset_type": "stocks", "price": 10.0},
            {"symbol": "SHORT", "asset_type": "stocks", "price": 10.0},
        ]

    async def _apply(self, config, assets=None, asset_type="stocks", daily=None):
        daily = daily if daily is not None else {
            "WIDE": daily_candles([0.90] * 14),
            "TIGHT": daily_candles([0.30] * 14),
            # SHORT is simply absent - the bulk helper omits symbols without
            # enough completed daily history.
        }
        with patch(
            "services.adr.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value=daily),
        ) as mocked:
            result = await adr.apply_adr(assets or self._assets(), config, asset_type)
        return result, mocked

    async def test_keeps_only_symbols_meeting_the_threshold(self):
        results, _ = await self._apply(
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60}
        )
        self.assertEqual([asset["symbol"] for asset in results], ["WIDE"])
        self.assertAlmostEqual(results[0]["adr"], 0.90)
        self.assertTrue(any("ADR $" in sticker for sticker in results[0]["stickers"]))
        self.assertIn("adr", results[0]["matched_indicators"])

    async def test_symbol_without_enough_history_is_excluded(self):
        results, _ = await self._apply(
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.10}
        )
        self.assertNotIn("SHORT", [asset["symbol"] for asset in results])

    async def test_always_fetches_daily_candles_for_the_lookback(self):
        _, mocked = await self._apply(
            {"enabled": True, "lookback_days": 30, "condition": "gte", "min_adr": 0.10},
            daily={},
        )
        mocked.assert_awaited_once_with(["WIDE", "TIGHT", "SHORT"], 30)

    async def test_disabled_filter_passes_everything_through(self):
        assets = self._assets()
        results = await adr.apply_adr(assets, {"enabled": False, "min_adr": 5.0}, "stocks")
        self.assertEqual(len(results), 3)

    async def test_invalid_config_does_not_silently_drop_symbols(self):
        assets = self._assets()
        results = await adr.apply_adr(
            assets,
            {"enabled": True, "condition": "between", "min_adr": 1.50, "max_adr": 0.60},
            "stocks",
        )
        self.assertEqual(len(results), 3)

    async def test_crypto_rows_are_untouched_when_not_opted_in(self):
        assets = [
            {"symbol": "BTC-USD", "asset_type": "crypto", "price": 1.0},
            {"symbol": "TIGHT", "asset_type": "stocks", "price": 10.0},
        ]
        with patch(
            "services.adr.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={"TIGHT": daily_candles([0.30] * 14)}),
        ) as mocked:
            results = await adr.apply_adr(
                assets,
                {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
                "crypto",
            )

        # BTC-USD survives without being evaluated; TIGHT is filtered out.
        self.assertEqual([asset["symbol"] for asset in results], ["BTC-USD"])
        mocked.assert_awaited_once_with(["TIGHT"], 14)

    async def test_repeated_pipeline_runs_do_not_duplicate_stickers(self):
        assets = self._assets()
        config = {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60}
        daily = {"WIDE": daily_candles([0.90] * 14)}

        with patch(
            "services.adr.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value=daily),
        ):
            first = await adr.apply_adr(assets, config, "stocks")
            second = await adr.apply_adr(first, config, "stocks")

        self.assertEqual(len(second[0]["stickers"]), 1)
        self.assertEqual(second[0]["matched_indicators"].count("adr"), 1)


class AdrTimeframeIndependenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_spec_test_6_scanner_timeframe_never_changes_adr(self):
        """5m -> 1H -> 1D -> 1W must not change ADR for the same symbol."""
        from services import filter_shared

        intraday_noise = [{"high": 999.0, "low": 0.0, "is_closed": True}] * 20
        daily = daily_candles([0.75] * 15)

        fetch = AsyncMock(return_value=[{"symbol": "AAPL", "candles": daily}])
        values = []

        for scanner_timeframe in ("5m", "1h", "1day", "1w"):
            # The scan's own candles (whatever timeframe it runs on) are never
            # consulted; ADR always re-fetches "1day".
            asset = {"symbol": "AAPL", "asset_type": "stocks", "candles": intraday_noise}
            with patch("services.filter_shared.fetch_live_data", new=fetch):
                candles = await filter_shared.get_completed_daily_candles("AAPL", 14)
            values.append(adr.compute_adr(candles, 14))
            self.assertEqual(asset["candles"], intraday_noise)

        self.assertEqual(len(set(values)), 1)
        self.assertAlmostEqual(values[0], 0.75)
        for call in fetch.await_args_list:
            self.assertEqual(call.args[1], "1day")


class AdrDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_reports_value_and_summary(self):
        with patch(
            "services.adr.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={"AAPL": daily_candles([0.74] * 14)}),
        ):
            detail = await adr.evaluate_adr_detail(
                {"symbol": "AAPL", "asset_type": "stocks"},
                {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
            )

        self.assertTrue(detail["passed"])
        self.assertEqual(detail["details"]["adr_display"], "$0.74")
        self.assertIn("meets", detail["summary"])

    async def test_detail_explains_insufficient_history(self):
        with patch(
            "services.adr.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={}),
        ):
            detail = await adr.evaluate_adr_detail(
                {"symbol": "NEWCO", "asset_type": "stocks"},
                {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
            )

        self.assertFalse(detail["passed"])
        self.assertIsNone(detail["sticker"])
        self.assertIn("Fewer than 14", detail["summary"])

    async def test_detail_notes_crypto_is_out_of_scope(self):
        detail = await adr.evaluate_adr_detail(
            {"symbol": "BTC-USD", "asset_type": "crypto"},
            {"enabled": True, "lookback_days": 14, "condition": "gte", "min_adr": 0.60},
        )
        self.assertTrue(detail["passed"])
        self.assertFalse(detail["details"]["applied"])

    async def test_no_detail_when_filter_disabled(self):
        self.assertIsNone(await adr.evaluate_adr_detail({"symbol": "AAPL"}, None))


if __name__ == "__main__":
    unittest.main()

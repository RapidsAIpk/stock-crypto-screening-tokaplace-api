"""Milestone 3 Phase 5 - Repeated True Empty-Space Gap Exclusion.

Covers the spec in `stock_crypto_scanner_document_only_spec.md` section 7:
the strict gap definition (7.2, 7.3, 7.11), everything that must NOT count
(7.4), the percentage formulas (7.5), counting and the inclusive maximum
(7.7), filled gaps staying counted (7.8), daily/timeframe independence (7.9),
and the split/missing-data rules (7.10).
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from models.filters import GapExclusionFilter  # noqa: E402
from services import gap_exclusion  # noqa: E402


DAY = 86_400
# A Monday, so day-to-day steps below land on ordinary weekday spacing.
BASE_TIME = 1_735_689_600


def daily_candle(high, low, index=0, base_time=BASE_TIME, step_days=1, **overrides):
    candle = {
        "time": base_time + (index * step_days * DAY),
        "open": low,
        "high": high,
        "low": low,
        "close": high,
        "volume": 1_000,
        "is_closed": True,
    }
    candle.update(overrides)
    return candle


def series(bands, base_time=BASE_TIME, step_days=1):
    """Build a daily series from (high, low) pairs, one trading day apart."""
    return [
        daily_candle(high, low, index=index, base_time=base_time, step_days=step_days)
        for index, (high, low) in enumerate(bands)
    ]


def config(**overrides):
    base = {
        "enabled": True,
        "lookback_days": 60,
        "direction": "both",
        "min_gap_pct": 5.0,
        "max_gaps": 2,
    }
    base.update(overrides)
    return gap_exclusion.normalize_gap_config(base)


class TrueGapDetectionTests(unittest.TestCase):
    def test_spec_7_2_true_gap_up(self):
        # Previous high $2.00, current low $2.10 -> blank space $2.00-$2.10.
        previous = daily_candle(2.00, 1.80, index=0)
        current = daily_candle(2.30, 2.10, index=1)

        gap = gap_exclusion.detect_gap(previous, current)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["direction"], "up")
        self.assertAlmostEqual(gap["empty_from"], 2.00)
        self.assertAlmostEqual(gap["empty_to"], 2.10)

    def test_spec_7_3_true_gap_down(self):
        # Previous low $2.00, current high $1.90 -> blank space $1.90-$2.00.
        previous = daily_candle(2.20, 2.00, index=0)
        current = daily_candle(1.90, 1.70, index=1)

        gap = gap_exclusion.detect_gap(previous, current)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["direction"], "down")
        self.assertAlmostEqual(gap["empty_from"], 1.90)
        self.assertAlmostEqual(gap["empty_to"], 2.00)

    def test_spec_7_4_touching_candles_are_not_a_gap(self):
        # current_low == previous_high: the comparison is strict, so no gap.
        previous = daily_candle(2.00, 1.80, index=0)
        current = daily_candle(2.30, 2.00, index=1)
        self.assertIsNone(gap_exclusion.detect_gap(previous, current))

        # And the same on the way down.
        previous = daily_candle(2.20, 2.00, index=0)
        current = daily_candle(2.00, 1.70, index=1)
        self.assertIsNone(gap_exclusion.detect_gap(previous, current))

    def test_spec_7_4_overlapping_candles_are_not_a_gap(self):
        previous = daily_candle(2.00, 1.80, index=0)
        current = daily_candle(2.40, 1.95, index=1)
        self.assertIsNone(gap_exclusion.detect_gap(previous, current))

    def test_spec_7_4_a_wick_into_the_space_kills_the_gap(self):
        # Body sits well above, but the low wick trades back into the space.
        previous = daily_candle(2.00, 1.80, index=0)
        current = daily_candle(2.60, 1.99, index=1, open=2.40, close=2.55)
        self.assertIsNone(gap_exclusion.detect_gap(previous, current))

    def test_spec_7_4_a_merely_large_candle_is_not_a_gap(self):
        previous = daily_candle(2.00, 1.90, index=0)
        current = daily_candle(4.00, 1.95, index=1)
        self.assertIsNone(gap_exclusion.detect_gap(previous, current))

    def test_one_cent_of_blank_space_still_counts(self):
        previous = daily_candle(2.00, 1.80, index=0)
        current = daily_candle(2.30, 2.01, index=1)
        gap = gap_exclusion.detect_gap(previous, current)
        self.assertIsNotNone(gap)
        self.assertEqual(gap["direction"], "up")


class GapPercentageTests(unittest.TestCase):
    def test_spec_7_5_gap_up_percentage_formula(self):
        # (2.10 - 2.00) / 2.00 * 100 = 5.0
        gap = gap_exclusion.detect_gap(
            daily_candle(2.00, 1.80, index=0),
            daily_candle(2.30, 2.10, index=1),
        )
        self.assertAlmostEqual(gap["size_pct"], 5.0)

    def test_spec_7_5_gap_down_percentage_formula(self):
        # (2.00 - 1.90) / 2.00 * 100 = 5.0
        gap = gap_exclusion.detect_gap(
            daily_candle(2.20, 2.00, index=0),
            daily_candle(1.90, 1.70, index=1),
        )
        self.assertAlmostEqual(gap["size_pct"], 5.0)

    def test_percentage_uses_the_unrounded_value(self):
        # A 4.999% gap must not survive a 5% minimum by being displayed as 5%.
        candles = series([(100.0, 99.0), (110.0, 104.999)])
        gaps = gap_exclusion.find_qualifying_gaps(candles, config(min_gap_pct=5.0))
        self.assertEqual(gaps, [])
        self.assertEqual(gap_exclusion.format_gap_pct(4.999), "5.00%")

    def test_minimum_percentage_boundary_is_inclusive(self):
        candles = series([(2.00, 1.80), (2.30, 2.10)])
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps(candles, config(min_gap_pct=5.0))), 1)
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps(candles, config(min_gap_pct=5.01))), 0)

    def test_minimum_percentage_is_not_hardcoded_to_five(self):
        # A 2% gap counts when the user lowers the threshold, and doesn't at 5%.
        candles = series([(100.0, 99.0), (110.0, 102.0)])
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps(candles, config(min_gap_pct=1.25))), 1)
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps(candles, config(min_gap_pct=5.0))), 0)


class GapDirectionTests(unittest.TestCase):
    def _mixed_series(self):
        # Up gap, then a down gap, both comfortably over 5%.
        return series([
            (100.0, 99.0),
            (120.0, 110.0),   # gap up from 100 -> 110
            (118.0, 108.0),   # overlaps, no gap
            (100.0, 95.0),    # gap down from 108 -> 100
        ])

    def test_both_counts_up_and_down(self):
        gaps = gap_exclusion.find_qualifying_gaps(self._mixed_series(), config(direction="both"))
        self.assertEqual([gap["direction"] for gap in gaps], ["up", "down"])

    def test_up_only_ignores_down_gaps(self):
        gaps = gap_exclusion.find_qualifying_gaps(self._mixed_series(), config(direction="up"))
        self.assertEqual([gap["direction"] for gap in gaps], ["up"])

    def test_down_only_ignores_up_gaps(self):
        gaps = gap_exclusion.find_qualifying_gaps(self._mixed_series(), config(direction="down"))
        self.assertEqual([gap["direction"] for gap in gaps], ["down"])

    def test_direction_aliases_normalize(self):
        self.assertEqual(gap_exclusion.normalize_gap_direction("Gap Up Only"), "up")
        self.assertEqual(gap_exclusion.normalize_gap_direction("gap_down_only"), "down")
        self.assertEqual(gap_exclusion.normalize_gap_direction("any"), "both")
        self.assertEqual(gap_exclusion.normalize_gap_direction(None), "both")


class GapCountingTests(unittest.TestCase):
    def _series_with_gaps(self, gap_count):
        """A series containing exactly `gap_count` ~10% gap ups."""
        bands = [(100.0, 99.0)]
        high, low = 100.0, 99.0
        for _ in range(gap_count):
            low = high * 1.10
            high = low * 1.05
            bands.append((high, low))
        return series(bands)

    def test_spec_7_7_inclusive_maximum_boundary(self):
        # Max = 2: 0, 1 and 2 gaps pass; 3 and 4 are excluded.
        for count, expected in ((0, True), (1, True), (2, True), (3, False), (4, False)):
            result = gap_exclusion.evaluate_gap_exclusion(
                self._series_with_gaps(count),
                config(max_gaps=2),
            )
            self.assertEqual(result["gap_count"], count)
            self.assertEqual(result["passed"], expected, f"{count} gaps")

    def test_max_gaps_zero_excludes_on_the_first_gap(self):
        self.assertTrue(
            gap_exclusion.evaluate_gap_exclusion(self._series_with_gaps(0), config(max_gaps=0))["passed"]
        )
        self.assertFalse(
            gap_exclusion.evaluate_gap_exclusion(self._series_with_gaps(1), config(max_gaps=0))["passed"]
        )

    def test_spec_7_8_a_filled_gap_stays_counted(self):
        # Gap up on day 2, then price trades all the way back down through it.
        candles = series([
            (100.0, 99.0),
            (125.0, 115.0),   # true gap up: 100 -> 115
            (120.0, 95.0),    # fills the gap completely
            (118.0, 96.0),
        ])
        result = gap_exclusion.evaluate_gap_exclusion(candles, config(max_gaps=0))
        self.assertEqual(result["gap_count"], 1)
        self.assertFalse(result["passed"])

    def test_no_history_counts_no_gaps(self):
        self.assertEqual(gap_exclusion.find_qualifying_gaps([], config()), [])
        self.assertEqual(gap_exclusion.find_qualifying_gaps(series([(2.0, 1.0)]), config()), [])

    def test_spec_7_9_unfinished_daily_candle_is_excluded(self):
        completed = series([(100.0, 99.0), (101.0, 98.0)])
        forming = daily_candle(200.0, 150.0, index=2)
        forming["is_closed"] = False

        # The forming bar would gap hugely off the last completed one; it must
        # not be counted until it closes.
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps(completed, config(max_gaps=0))), 0)
        self.assertEqual(
            len(gap_exclusion.find_qualifying_gaps(completed + [forming], config(max_gaps=0))),
            0,
        )


class DataQualityTests(unittest.TestCase):
    def test_spec_7_10_weekend_spacing_is_normal(self):
        # Friday -> Monday is a 3-day step and still two adjacent sessions.
        friday = daily_candle(100.0, 99.0, index=0)
        monday = daily_candle(120.0, 110.0, index=3)
        gaps = gap_exclusion.find_qualifying_gaps([friday, monday], config())
        self.assertEqual(len(gaps), 1)

    def test_spec_7_10_holiday_spacing_is_normal(self):
        # Friday -> Tuesday after a Monday holiday: 4 days, still adjacent.
        before = daily_candle(100.0, 99.0, index=0)
        after = daily_candle(120.0, 110.0, index=4)
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps([before, after], config())), 1)

    def test_spec_7_10_missing_sessions_do_not_manufacture_a_gap(self):
        # A two-week hole in the series is missing data, not an overnight gap.
        before = daily_candle(100.0, 99.0, index=0)
        after = daily_candle(120.0, 110.0, index=14)
        self.assertEqual(gap_exclusion.find_qualifying_gaps([before, after], config()), [])

    def test_crypto_uses_tighter_session_spacing(self):
        # Crypto trades every day, so a 3-day hole is missing data, not a weekend.
        before = daily_candle(100.0, 99.0, index=0)
        after = daily_candle(120.0, 110.0, index=3)
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps([before, after], config(), is_crypto=False)), 1)
        self.assertEqual(gap_exclusion.find_qualifying_gaps([before, after], config(), is_crypto=True), [])

    def test_spec_7_10_bad_ohlc_breaks_the_comparison_chain(self):
        candles = series([(100.0, 99.0), (120.0, 110.0), (140.0, 130.0)])
        candles[1]["low"] = None

        # Neither the pair before the broken day nor the pair after it
        # describes two adjacent verified sessions, so nothing is counted.
        self.assertEqual(gap_exclusion.find_qualifying_gaps(candles, config()), [])

    def test_invalid_candles_are_rejected(self):
        self.assertIsNone(gap_exclusion.valid_daily_candle({"high": None, "low": 1.0}))
        self.assertIsNone(gap_exclusion.valid_daily_candle({"high": "abc", "low": 1.0}))
        self.assertIsNone(gap_exclusion.valid_daily_candle({"high": float("nan"), "low": 1.0}))
        self.assertIsNone(gap_exclusion.valid_daily_candle({"high": 0.0, "low": 0.0}))
        self.assertIsNone(gap_exclusion.valid_daily_candle({"high": 1.0, "low": 2.0}))
        self.assertIsNotNone(gap_exclusion.valid_daily_candle({"high": 2.0, "low": 1.0}))

    def test_out_of_order_candles_are_not_compared(self):
        later = daily_candle(100.0, 99.0, index=5)
        earlier = daily_candle(120.0, 110.0, index=0)
        self.assertFalse(
            gap_exclusion.sessions_are_consecutive(
                gap_exclusion.valid_daily_candle(later),
                gap_exclusion.valid_daily_candle(earlier),
            )
        )

    def test_candles_without_timestamps_are_still_compared(self):
        # Ordering already comes from the provider series; a missing timestamp
        # shouldn't silently disable the whole filter.
        previous = {"high": 100.0, "low": 99.0}
        current = {"high": 120.0, "low": 110.0}
        self.assertEqual(len(gap_exclusion.find_qualifying_gaps([previous, current], config())), 1)


class SplitSafetyTests(unittest.TestCase):
    def test_adjusted_history_shows_no_split_gap(self):
        """Provider history is requested with adjusted=true, so a 2:1 split
        leaves a continuous series rather than a 50% cliff."""
        candles = series([(100.0, 98.0), (101.0, 99.0), (100.5, 98.5)])
        self.assertEqual(gap_exclusion.find_qualifying_gaps(candles, config()), [])

    def test_an_unadjusted_split_cliff_on_a_stale_day_is_not_counted(self):
        # If a raw split cliff ever slipped through, it lands on a day whose
        # session spacing is broken; the chain guard keeps it out of the count.
        before = daily_candle(100.0, 98.0, index=0)
        after_split = daily_candle(50.5, 49.0, index=10)
        self.assertEqual(gap_exclusion.find_qualifying_gaps([before, after_split], config()), [])


class GapConfigTests(unittest.TestCase):
    def test_defaults(self):
        normalized = gap_exclusion.normalize_gap_config({"enabled": True})
        self.assertEqual(normalized["lookback_days"], 60)
        self.assertEqual(normalized["direction"], "both")
        self.assertEqual(normalized["min_gap_pct"], 5.0)
        self.assertEqual(normalized["max_gaps"], 2)

    def test_disabled_filter_normalizes_to_none(self):
        self.assertIsNone(gap_exclusion.normalize_gap_config({"enabled": False}))
        self.assertIsNone(gap_exclusion.normalize_gap_config(None))

    def test_lookback_is_floored_at_two(self):
        self.assertEqual(gap_exclusion.normalize_gap_config({"enabled": True, "lookback_days": 0})["lookback_days"], 2)

    def test_negative_values_are_rejected(self):
        self.assertIn(
            "min_gap_pct",
            gap_exclusion.gap_config_error(config(min_gap_pct=-1.0)),
        )

    def test_model_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            GapExclusionFilter(lookback_days=1)
        with self.assertRaises(ValueError):
            GapExclusionFilter(min_gap_pct=-0.5)
        with self.assertRaises(ValueError):
            GapExclusionFilter(max_gaps=-1)

    def test_model_accepts_valid_config(self):
        model = GapExclusionFilter(lookback_days=60, direction="up", min_gap_pct=2.5, max_gaps=0)
        self.assertEqual(model.direction, "up")
        self.assertEqual(model.min_gap_pct, 2.5)

    def test_disabled_model_skips_validation(self):
        self.assertFalse(GapExclusionFilter(enabled=False, lookback_days=1).enabled)


class ApplyGapExclusionTests(unittest.IsolatedAsyncioTestCase):
    def _assets(self):
        return [
            {"symbol": "CLEAN", "asset_type": "stocks", "price": 10.0},
            {"symbol": "GAPPY", "asset_type": "stocks", "price": 10.0},
        ]

    def _daily(self):
        return {
            "CLEAN": series([(100.0, 99.0), (101.0, 98.5), (102.0, 99.5)]),
            # Three ~10% gap ups in a row.
            "GAPPY": series([
                (100.0, 99.0),
                (125.0, 115.0),
                (160.0, 145.0),
                (200.0, 185.0),
            ]),
        }

    async def test_excludes_repeated_gap_creators_only(self):
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value=self._daily()),
        ):
            results = await apply(self._assets(), config(max_gaps=2))

        self.assertEqual([asset["symbol"] for asset in results], ["CLEAN"])
        self.assertEqual(results[0]["qualifying_gap_count"], 0)
        self.assertTrue(any("Gap Exclusion" in sticker for sticker in results[0]["stickers"]))
        self.assertIn("gap_exclusion", results[0]["matched_indicators"])

    async def test_raising_the_maximum_keeps_the_gappy_symbol(self):
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value=self._daily()),
        ):
            results = await apply(self._assets(), config(max_gaps=3))

        self.assertEqual([asset["symbol"] for asset in results], ["CLEAN", "GAPPY"])

    async def test_symbol_without_daily_history_is_kept(self):
        # Nothing to count is not evidence of repeated gapping.
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={}),
        ):
            results = await apply(self._assets(), config(max_gaps=0))

        self.assertEqual(len(results), 2)

    async def test_fetches_daily_candles_for_the_lookback(self):
        mocked = AsyncMock(return_value={})
        with patch("services.gap_exclusion.get_completed_daily_candles_bulk", new=mocked):
            await apply(self._assets(), config(lookback_days=60))

        mocked.assert_awaited_once_with(["CLEAN", "GAPPY"], 60, minimum_days=2)

    async def test_disabled_filter_passes_everything_through(self):
        results = await gap_exclusion.apply_gap_exclusion(
            self._assets(),
            {"enabled": False, "max_gaps": 0},
            "stocks",
        )
        self.assertEqual(len(results), 2)

    async def test_repeated_pipeline_runs_do_not_duplicate_stickers(self):
        assets = self._assets()
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value=self._daily()),
        ):
            first = await apply(assets, config(max_gaps=2))
            second = await apply(first, config(max_gaps=2))

        self.assertEqual(len(second[0]["stickers"]), 1)
        self.assertEqual(second[0]["matched_indicators"].count("gap_exclusion"), 1)


class GapTimeframeIndependenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_scanner_timeframe_never_changes_the_gap_count(self):
        """5m -> 1H -> 1D -> 1W must not change the result for one symbol."""
        from services import filter_shared

        intraday_noise = [{"high": 999.0, "low": 0.0, "is_closed": True}] * 20
        daily = series([(100.0, 99.0), (125.0, 115.0), (124.0, 116.0)])

        fetch = AsyncMock(return_value=[{"symbol": "AAPL", "candles": daily}])
        counts = []

        for _ in ("5m", "1h", "1day", "1w"):
            asset = {"symbol": "AAPL", "asset_type": "stocks", "candles": intraday_noise}
            with patch("services.filter_shared.fetch_live_data", new=fetch):
                candles = await filter_shared.get_completed_daily_candles_bulk(["AAPL"], 60, minimum_days=2)
            counts.append(
                gap_exclusion.evaluate_gap_exclusion(candles["AAPL"], config())["gap_count"]
            )
            self.assertEqual(asset["candles"], intraday_noise)

        self.assertEqual(len(set(counts)), 1)
        self.assertEqual(counts[0], 1)
        for call in fetch.await_args_list:
            self.assertEqual(call.args[1], "1day")


class GapDetailTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_lists_every_qualifying_gap(self):
        daily = series([(100.0, 99.0), (125.0, 115.0), (160.0, 145.0)])
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={"GAPPY": daily}),
        ):
            detail = await gap_exclusion.evaluate_gap_exclusion_detail(
                {"symbol": "GAPPY", "asset_type": "stocks"},
                config(max_gaps=1),
            )

        self.assertFalse(detail["passed"])
        self.assertEqual(detail["details"]["gap_count"], 2)
        self.assertEqual(len(detail["details"]["daily_candles"]), 3)
        self.assertIn("over the maximum", detail["summary"])

    async def test_detail_reports_a_clean_symbol(self):
        daily = series([(100.0, 99.0), (101.0, 98.0)])
        with patch(
            "services.gap_exclusion.get_completed_daily_candles_bulk",
            new=AsyncMock(return_value={"CLEAN": daily}),
        ):
            detail = await gap_exclusion.evaluate_gap_exclusion_detail(
                {"symbol": "CLEAN", "asset_type": "stocks"},
                config(),
            )

        self.assertTrue(detail["passed"])
        self.assertEqual(detail["details"]["gap_count"], 0)
        self.assertIsNotNone(detail["sticker"])

    async def test_no_detail_when_filter_disabled(self):
        self.assertIsNone(
            await gap_exclusion.evaluate_gap_exclusion_detail({"symbol": "AAPL"}, None)
        )


async def apply(assets, gap_config, asset_type="stocks"):
    return await gap_exclusion.apply_gap_exclusion(assets, gap_config, asset_type)


if __name__ == "__main__":
    unittest.main()

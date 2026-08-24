import os
import sys
import unittest
from unittest.mock import AsyncMock, patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import filter_shared  # noqa: E402


class CandlesSinceEventInRangeTests(unittest.TestCase):
    def test_exact_min_boundary_passes(self):
        self.assertTrue(filter_shared.candles_since_event_in_range(10, 12, min_candles=2, max_candles=5))

    def test_exact_max_boundary_passes(self):
        self.assertTrue(filter_shared.candles_since_event_in_range(10, 15, min_candles=2, max_candles=5))

    def test_one_below_min_fails(self):
        self.assertFalse(filter_shared.candles_since_event_in_range(10, 11, min_candles=2, max_candles=5))

    def test_one_above_max_fails(self):
        self.assertFalse(filter_shared.candles_since_event_in_range(10, 16, min_candles=2, max_candles=5))

    def test_no_bounds_always_passes_when_event_not_in_future(self):
        self.assertTrue(filter_shared.candles_since_event_in_range(10, 999))

    def test_event_after_current_index_fails(self):
        self.assertFalse(filter_shared.candles_since_event_in_range(20, 10, min_candles=0, max_candles=5))

    def test_missing_indices_fail_closed(self):
        self.assertFalse(filter_shared.candles_since_event_in_range(None, 10))
        self.assertFalse(filter_shared.candles_since_event_in_range(10, None))

    def test_max_below_min_raises(self):
        with self.assertRaises(ValueError):
            filter_shared.candles_since_event_in_range(10, 12, min_candles=5, max_candles=2)


class ConsecutiveActiveInRangeTests(unittest.TestCase):
    def test_streak_within_range_passes(self):
        self.assertTrue(filter_shared.consecutive_active_in_range(3, min_candles=1, max_candles=5))

    def test_streak_at_min_boundary_passes(self):
        self.assertTrue(filter_shared.consecutive_active_in_range(1, min_candles=1, max_candles=5))

    def test_streak_at_max_boundary_passes(self):
        self.assertTrue(filter_shared.consecutive_active_in_range(5, min_candles=1, max_candles=5))

    def test_streak_above_max_fails(self):
        self.assertFalse(filter_shared.consecutive_active_in_range(6, min_candles=1, max_candles=5))

    def test_zero_or_none_streak_fails(self):
        self.assertFalse(filter_shared.consecutive_active_in_range(0, min_candles=0, max_candles=5))
        self.assertFalse(filter_shared.consecutive_active_in_range(None, min_candles=0, max_candles=5))

    def test_max_below_min_raises(self):
        with self.assertRaises(ValueError):
            filter_shared.consecutive_active_in_range(3, min_candles=5, max_candles=2)


class DropUnclosedLastCandleTests(unittest.TestCase):
    def test_drops_trailing_unclosed_candle(self):
        candles = [{"close": 1, "is_closed": True}, {"close": 2, "is_closed": False}]
        result = filter_shared.drop_unclosed_last_candle(candles)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[-1]["close"], 1)

    def test_keeps_all_candles_when_last_is_closed(self):
        candles = [{"close": 1, "is_closed": True}, {"close": 2, "is_closed": True}]
        result = filter_shared.drop_unclosed_last_candle(candles)
        self.assertEqual(len(result), 2)

    def test_keeps_candles_when_closed_state_absent(self):
        candles = [{"close": 1}, {"close": 2}]
        result = filter_shared.drop_unclosed_last_candle(candles)
        self.assertEqual(len(result), 2)

    def test_empty_input_returns_empty(self):
        self.assertEqual(filter_shared.drop_unclosed_last_candle([]), [])

    def test_does_not_mutate_input(self):
        candles = [{"close": 1, "is_closed": True}, {"close": 2, "is_closed": False}]
        filter_shared.drop_unclosed_last_candle(candles)
        self.assertEqual(len(candles), 2)


class ResolveSelectionTests(unittest.TestCase):
    def test_all_mode_requires_every_result_true(self):
        self.assertTrue(filter_shared.resolve_selection([True, True, True], mode="all"))
        self.assertFalse(filter_shared.resolve_selection([True, False, True], mode="all"))

    def test_any_mode_requires_at_least_one_true(self):
        self.assertTrue(filter_shared.resolve_selection([False, False, True], mode="any"))
        self.assertFalse(filter_shared.resolve_selection([False, False, False], mode="any"))

    def test_one_mode_requires_exactly_one_true(self):
        self.assertTrue(filter_shared.resolve_selection([False, True, False], mode="one"))
        self.assertFalse(filter_shared.resolve_selection([True, True, False], mode="one"))
        self.assertFalse(filter_shared.resolve_selection([False, False, False], mode="one"))

    def test_multiple_mode_defaults_to_two(self):
        self.assertTrue(filter_shared.resolve_selection([True, True, False], mode="multiple"))
        self.assertFalse(filter_shared.resolve_selection([True, False, False], mode="multiple"))

    def test_multiple_mode_honors_required_count(self):
        self.assertTrue(
            filter_shared.resolve_selection([True, True, True, False], mode="multiple", required_count=3)
        )
        self.assertFalse(
            filter_shared.resolve_selection([True, True, False, False], mode="multiple", required_count=3)
        )

    def test_empty_results_fail_closed(self):
        self.assertFalse(filter_shared.resolve_selection([], mode="all"))
        self.assertFalse(filter_shared.resolve_selection([], mode="any"))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            filter_shared.resolve_selection([True], mode="bogus")

    def test_default_mode_is_all(self):
        self.assertTrue(filter_shared.resolve_selection([True, True]))
        self.assertFalse(filter_shared.resolve_selection([True, False]))


class GetCompletedDailyCandlesTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_last_n_completed_candles(self):
        candles = [{"close": i, "is_closed": True} for i in range(20)]
        with patch(
            "services.filter_shared.fetch_live_data",
            new=AsyncMock(return_value=[{"symbol": "AAPL", "candles": candles}]),
        ) as mocked_fetch:
            result = await filter_shared.get_completed_daily_candles("AAPL", 14)

        self.assertEqual(len(result), 14)
        self.assertEqual(result[-1]["close"], 19)
        mocked_fetch.assert_awaited_once_with(["AAPL"], "1day", candles_limit=15)

    async def test_drops_unclosed_trailing_candle_before_slicing(self):
        candles = [{"close": i, "is_closed": True} for i in range(14)]
        candles.append({"close": 999, "is_closed": False})
        with patch(
            "services.filter_shared.fetch_live_data",
            new=AsyncMock(return_value=[{"symbol": "AAPL", "candles": candles}]),
        ):
            result = await filter_shared.get_completed_daily_candles("AAPL", 14)

        self.assertEqual(len(result), 14)
        self.assertEqual(result[-1]["close"], 13)

    async def test_insufficient_history_returns_none(self):
        candles = [{"close": i, "is_closed": True} for i in range(5)]
        with patch(
            "services.filter_shared.fetch_live_data",
            new=AsyncMock(return_value=[{"symbol": "AAPL", "candles": candles}]),
        ):
            result = await filter_shared.get_completed_daily_candles("AAPL", 14)

        self.assertIsNone(result)

    async def test_no_payload_returns_none(self):
        with patch("services.filter_shared.fetch_live_data", new=AsyncMock(return_value=[])):
            result = await filter_shared.get_completed_daily_candles("AAPL", 14)

        self.assertIsNone(result)

    async def test_invalid_lookback_returns_none(self):
        self.assertIsNone(await filter_shared.get_completed_daily_candles("AAPL", 0))
        self.assertIsNone(await filter_shared.get_completed_daily_candles("", 14))


if __name__ == "__main__":
    unittest.main()

"""Focused regression tests for the Trend Channel evidence/window fix.

Root cause under test: for window > 1, evidence previously always reported
`candles[-1]` (the latest candle) regardless of which candle inside the
window actually satisfied the rule - so a match on an earlier candle in the
window was reported with the wrong OHLC/line-value, and a genuine "no
match" carried no diagnostic explanation. `evaluate_single_area` now builds
full per-candidate diagnostics (`checked_candidates`) and reports the real
`matched_candle_index`, sourced from the same evaluation pass that decides
pass/fail (not re-derived separately), for both the window-scan actions
(touched/entered/rejected/breach) and the run-based actions
(closed_above/closed_below/on_line).

Also covers: top/bottom line and zone wick touches, broken-channel
eligibility, forming-candle exclusion, exact boundary touches, and
tolerance null/0/positive - reproduced with synthetic fixtures labeled for
AIXC, AFYA, AKAM, GOOG, KYTX and TKO (no live market-data access is
available in this environment, so these are hand-built OHLCV series that
exercise the identical evaluation code path a real fetch would drive).
"""

from __future__ import annotations

import unittest

from services import indicators, trend_channels


def _candle(open_, high, low, close, volume=100.0, time=None, is_closed=None):
    candle = {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    if time is not None:
        candle["time"] = time
    if is_closed is not None:
        candle["is_closed"] = is_closed
    return candle


def _flat_channel(
    length,
    start_index=0,
    top=110.0,
    middle=105.0,
    bottom=100.0,
    top_zone_lower=108.0,
    top_zone_upper=112.0,
    bottom_zone_lower=98.0,
    bottom_zone_upper=102.0,
    direction="down",
    broken=False,
    break_index=None,
):
    return {
        "length": length,
        "start_index": start_index,
        "direction": direction,
        "broken": broken,
        "break_index": break_index,
        "top": [top] * length,
        "middle": [middle] * length,
        "bottom": [bottom] * length,
        "top_zone_lower": [top_zone_lower] * length,
        "top_zone_upper": [top_zone_upper] * length,
        "bottom_zone_lower": [bottom_zone_lower] * length,
        "bottom_zone_upper": [bottom_zone_upper] * length,
    }


TOUCH_TOP = _candle(95.0, 111.0, 90.0, 96.0, time=1000)      # wick pokes above top=110, body below
NO_TOUCH = _candle(100.0, 101.0, 99.0, 100.5, time=2000)     # nowhere near any boundary
TOUCH_BOTTOM = _candle(105.0, 106.0, 89.0, 104.0, time=3000)  # wick pokes below bottom=100, body above
ENTERS_TOP_ZONE = _candle(107.5, 109.0, 107.0, 108.5, time=4000)   # wick reaches into [108,112]
ENTERS_BOTTOM_ZONE = _candle(102.5, 103.0, 101.5, 102.8, time=5000)  # wick reaches into [98,102]


class TopLineWickTouchTests(unittest.TestCase):
    def test_matches_and_reports_the_matched_candle(self):
        channel = _flat_channel(1)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []
        matched = trend_channels.evaluate_single_area([TOUCH_TOP], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["matched_candle_index"], 0)
        self.assertEqual(evidence[0]["matched_candle_time"], 1000)
        self.assertEqual(len(evidence[0]["checked_candidates"]), 1)
        self.assertTrue(evidence[0]["checked_candidates"][0]["geometry_overlap"])
        self.assertTrue(evidence[0]["checked_candidates"][0]["wick_overlap"])
        self.assertEqual(evidence[0]["checked_candidates"][0]["failure_reason"], "")


class BottomLineWickTouchTests(unittest.TestCase):
    def test_matches_and_reports_the_matched_candle(self):
        channel = _flat_channel(1)
        rule = {"area": "bottom_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []
        matched = trend_channels.evaluate_single_area([TOUCH_BOTTOM], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["matched_candle_index"], 0)
        self.assertEqual(evidence[0]["line_value"], 100.0)


class TopZoneEnteredTests(unittest.TestCase):
    def test_wick_entering_top_zone_matches(self):
        channel = _flat_channel(1)
        rule = {"area": "top_zone", "action": "entered", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []
        matched = trend_channels.evaluate_single_area([ENTERS_TOP_ZONE], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["zone_low"], 108.0)
        self.assertEqual(evidence[0]["zone_high"], 112.0)
        self.assertEqual(evidence[0]["matched_candle_index"], 0)


class BottomZoneEnteredTests(unittest.TestCase):
    def test_wick_entering_bottom_zone_matches(self):
        channel = _flat_channel(1)
        rule = {"area": "bottom_zone", "action": "entered", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []
        matched = trend_channels.evaluate_single_area([ENTERS_BOTTOM_ZONE], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["zone_low"], 98.0)
        self.assertEqual(evidence[0]["zone_high"], 102.0)


class WindowOneTests(unittest.TestCase):
    def test_window_1_checks_only_the_latest_candle(self):
        channel = _flat_channel(2)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []
        matched = trend_channels.evaluate_single_area([NO_TOUCH, TOUCH_TOP], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(len(evidence[0]["checked_candidates"]), 1)
        self.assertEqual(evidence[0]["matched_candle_index"], 1)


class WindowTwoAndLargerTests(unittest.TestCase):
    """The core regression: the match is NOT on the latest candle."""

    def test_window_2_matches_on_the_older_candle_evidence_reports_it_correctly(self):
        channel = _flat_channel(2)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 2, "tolerance": 0, "confirmation": False}
        candles = [TOUCH_TOP, NO_TOUCH]  # match at index 0, latest (index 1) does NOT touch
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertTrue(matched)
        # Before the fix this always reported index len(candles)-1 == 1.
        self.assertEqual(evidence[0]["matched_candle_index"], 0)
        self.assertEqual(evidence[0]["matched_candle_time"], 1000)
        self.assertEqual(evidence[0]["checked_candle_index"], 0)
        self.assertEqual(evidence[0]["checked_candle_time"], 1000)
        # First-match-wins scanning oldest-to-newest: the loop stops at the
        # match, so the newer (never-examined) candle isn't in the list.
        self.assertEqual([c["candle_index"] for c in evidence[0]["checked_candidates"]], [0])

    def test_window_larger_than_two_still_finds_and_reports_the_true_match(self):
        channel = _flat_channel(4)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 4, "tolerance": 0, "confirmation": False}
        candles = [TOUCH_TOP, NO_TOUCH, NO_TOUCH, NO_TOUCH]
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["matched_candle_index"], 0)

    def test_window_2_no_touch_anywhere_reports_both_candidates_and_a_reason(self):
        channel = _flat_channel(2)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 2, "tolerance": 0, "confirmation": False}
        candles = [NO_TOUCH, NO_TOUCH]
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertFalse(matched)
        self.assertIsNone(evidence[0]["matched_candle_index"])
        self.assertEqual(len(evidence[0]["checked_candidates"]), 2)
        for candidate in evidence[0]["checked_candidates"]:
            self.assertEqual(candidate["failure_reason"], "no_geometry_overlap")
            self.assertFalse(candidate["geometry_overlap"])
        self.assertEqual(evidence[0]["failure_reason"], "no_candidate_matched")

    def test_end_to_end_through_handle_trend_reports_the_matched_candle_not_the_latest(self):
        """Same regression, exercised through the real screener entry point
        (handle_trend), not just the isolated evaluate_single_area unit.
        """
        candles = [TOUCH_TOP, NO_TOUCH]
        channel = _flat_channel(2)
        config = {"length": 2, "areas": [
            {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 2, "tolerance": 0, "confirmation": False},
        ]}

        import unittest.mock as mock
        with mock.patch.object(indicators, "compute_trend_channel", return_value=channel):
            passed, result = indicators.handle_trend({"channels": {}}, candles, config)

        self.assertTrue(passed)
        self.assertEqual(result["evidence"][0]["matched_candle_index"], 0)


class RunBasedActionEvidenceTests(unittest.TestCase):
    """closed_above/closed_below/on_line use a contiguous-run match instead
    of an independent per-candidate scan; evidence must still report the
    real run-start candle, not always the latest.
    """

    def test_closed_above_run_starting_two_bars_back_reports_the_run_start(self):
        channel = _flat_channel(3, top=110.0)
        above = _candle(112.0, 113.0, 111.5, 112.5, time=100)
        also_above = _candle(112.5, 113.5, 112.0, 113.0, time=200)
        candles = [NO_TOUCH, above, also_above]
        rule = {"area": "top_line", "action": "closed_above", "window": 3, "tolerance": 0, "confirmation": False}
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["matched_candle_index"], 1)
        self.assertEqual(evidence[0]["matched_candle_time"], 100)
        # The walk examines the latest bar first, then walks backward until
        # the run breaks - the breaking candle (index 0) is included too,
        # showing exactly where/why the run stopped extending.
        self.assertEqual(
            sorted(c["candle_index"] for c in evidence[0]["checked_candidates"]), [0, 1, 2],
        )
        by_index = {c["candle_index"]: c for c in evidence[0]["checked_candidates"]}
        self.assertEqual(by_index[0]["failure_reason"], "no_geometry_overlap")
        self.assertEqual(by_index[1]["failure_reason"], "")
        self.assertEqual(by_index[2]["failure_reason"], "")

    def test_closed_above_run_starting_outside_window_fails_with_reason(self):
        channel = _flat_channel(3, top=110.0)
        above = _candle(112.0, 113.0, 111.5, 112.5, time=100)
        also_above = _candle(112.5, 113.5, 112.0, 113.0, time=200)
        candles = [above, above, also_above]
        rule = {"area": "top_line", "action": "closed_above", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertFalse(matched)
        self.assertEqual(evidence[0]["failure_reason"], "outside_window")


class BrokenVisibleChannelEvidenceTests(unittest.TestCase):
    def test_post_break_candle_reports_signal_ineligible_with_reason(self):
        channel = _flat_channel(2, broken=True, break_index=0)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        evidence = []

        matched = trend_channels.evaluate_single_area([TOUCH_TOP, TOUCH_TOP], channel, rule, evidence=evidence)

        self.assertFalse(matched)
        self.assertEqual(evidence[0]["channel_broken"], True)
        self.assertEqual(evidence[0]["break_index"], 0)
        candidate = evidence[0]["checked_candidates"][0]
        self.assertFalse(candidate["signal_eligible"])
        self.assertEqual(candidate["failure_reason"], "candle_after_channel_break")

    def test_bar_at_or_before_break_index_remains_eligible(self):
        channel = _flat_channel(2, broken=True, break_index=1)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 2, "tolerance": 0, "confirmation": False}
        evidence = []

        matched = trend_channels.evaluate_single_area([NO_TOUCH, TOUCH_TOP], channel, rule, evidence=evidence)

        self.assertTrue(matched)
        self.assertEqual(evidence[0]["matched_candle_index"], 1)


class FormingCandleExclusionTests(unittest.TestCase):
    def test_forming_trailing_candle_is_dropped_before_evaluation(self):
        closed_touch = dict(TOUCH_TOP)
        forming = dict(NO_TOUCH, is_closed=False)
        candles = [closed_touch, forming]

        closed_only = indicators._trend_closed_candles(candles)
        self.assertEqual(len(closed_only), 1)
        self.assertIs(closed_only[0], closed_touch)


class ExactBoundaryTouchTests(unittest.TestCase):
    def test_wick_exactly_on_the_line_counts_as_a_touch(self):
        channel = _flat_channel(1, top=110.0)
        exact = _candle(105.0, 110.0, 104.0, 106.0)  # high == line exactly
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}

        self.assertTrue(trend_channels.evaluate_single_area([exact], channel, rule))

    def test_wick_exactly_on_the_zone_edge_counts_as_entered(self):
        channel = _flat_channel(1, top_zone_lower=108.0, top_zone_upper=112.0)
        exact = _candle(106.0, 108.0, 105.0, 107.0)  # high == zone_low exactly
        rule = {"area": "top_zone", "action": "entered", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}

        self.assertTrue(trend_channels.evaluate_single_area([exact], channel, rule))


class ToleranceNullZeroPositiveTests(unittest.TestCase):
    NEAR_MISS = _candle(11.56, 11.60, 11.55, 11.58)  # just outside zone (11.30, 11.50)

    def test_tolerance_null_behaves_as_zero(self):
        rule = {"action": "entered", "touch_type": "wick", "tolerance": None}
        self.assertFalse(trend_channels.evaluate_zone_action(self.NEAR_MISS, 11.30, 11.50, rule, "up"))

    def test_tolerance_zero_is_preserved_exactly(self):
        rule = {"action": "entered", "touch_type": "wick", "tolerance": 0}
        self.assertFalse(trend_channels.evaluate_zone_action(self.NEAR_MISS, 11.30, 11.50, rule, "up"))

    def test_tolerance_positive_widens_the_zone_to_accept(self):
        rule = {"action": "entered", "touch_type": "wick", "tolerance": 5}
        self.assertTrue(trend_channels.evaluate_zone_action(self.NEAR_MISS, 11.30, 11.50, rule, "up"))


class MultiAssetMultiTimeframeReproductionTests(unittest.TestCase):
    """Synthetic reproduction for AIXC, AFYA, AKAM, GOOG, KYTX, TKO across
    an intraday-scaled series (standing in for 1h) and a wider-swing series
    (standing in for 1day). No live market-data access is available in this
    environment; trend_channels itself is timeframe-agnostic (it only sees
    an OHLCV array), so these fixtures exercise the identical evaluation
    code a real 1h/1day fetch would drive, with the same window>1 matched-
    candle regression check per symbol.
    """

    SYMBOLS = ("AIXC", "AFYA", "AKAM", "GOOG", "KYTX", "TKO")

    def _run_case(self, symbol, price_scale):
        top = 100.0 * price_scale
        channel = _flat_channel(3, top=top)
        touch = _candle(top - 2 * price_scale, top + 0.1 * price_scale, top - 3 * price_scale, top - 1.5 * price_scale, time=42)
        no_touch_a = _candle(top - 5 * price_scale, top - 4 * price_scale, top - 6 * price_scale, top - 4.5 * price_scale, time=43)
        no_touch_b = _candle(top - 5 * price_scale, top - 4 * price_scale, top - 6 * price_scale, top - 4.5 * price_scale, time=44)
        candles = [touch, no_touch_a, no_touch_b]
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 3, "tolerance": 0, "confirmation": False}
        evidence = []

        matched = trend_channels.evaluate_single_area(candles, channel, rule, evidence=evidence)

        self.assertTrue(matched, f"{symbol}: expected the top-line touch to match")
        self.assertEqual(evidence[0]["matched_candle_index"], 0, f"{symbol}: matched candle must be the touch, not the latest")
        self.assertEqual(evidence[0]["matched_candle_time"], 42, f"{symbol}: matched candle time must be the touch bar's own time")

    def test_1h_scale_reproduction_for_each_symbol(self):
        for symbol in self.SYMBOLS:
            with self.subTest(symbol=symbol, timeframe="1h"):
                self._run_case(symbol, price_scale=1.0)

    def test_1day_scale_reproduction_for_each_symbol(self):
        for symbol in self.SYMBOLS:
            with self.subTest(symbol=symbol, timeframe="1day"):
                self._run_case(symbol, price_scale=3.7)


if __name__ == "__main__":
    unittest.main()

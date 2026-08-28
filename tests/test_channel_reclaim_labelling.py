"""M3-ISS-02 — "Reclaimed From Below" must not be confused with "Rejected From Above".

The client reported that a Reclaim scan returned symbols that had only been
rejected from above and never closed below the line. The underlying reclaim
math was correct; what was wrong was the reported *decision*: the legacy
single-candle `close_above` action was labelled "Bullish Reclaim" even though
it never checks for a prior close below, while the genuine multi-stage
interactions fell through to a generic "Channel Match".

These tests lock in both halves: only a verified reclaim may be called one,
and each real interaction reports its own decision.
"""

import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import channel_interactions, channel_line_rules  # noqa: E402


FLAT_LINE = [10.0] * 6


def candle(close, high=None, low=None):
    return {
        "open": close,
        "high": close if high is None else high,
        "low": close if low is None else low,
        "close": close,
    }


class RegressionDecisionLabelTests(unittest.TestCase):
    """The label the client actually sees on the result sticker."""

    def test_close_above_no_longer_claims_a_reclaim(self):
        # The exact case behind M3-ISS-02: a plain close-above on the middle
        # or lower line never verified a prior close below, so it must not be
        # reported as a reclaim.
        for lines in (["middle"], ["lower"], ["middle", "lower"]):
            decision = channel_line_rules._regression_decision(lines, "close_above")
            self.assertNotIn("Reclaim", decision, f"lines={lines}")
            self.assertEqual(decision, "Bullish Close Above")

    def test_close_above_on_upper_line_still_reads_as_a_breakout(self):
        # Pre-existing behaviour that must not regress.
        self.assertEqual(
            channel_line_rules._regression_decision(["upper"], "close_above"),
            "Bullish Breakout",
        )

    def test_only_the_verified_reclaim_action_is_called_a_reclaim(self):
        self.assertEqual(
            channel_line_rules._regression_decision(["lower"], "reclaimed_from_below_bullish"),
            "Bullish Reclaim",
        )

    def test_each_interaction_reports_its_own_decision(self):
        expected = {
            "piercing_from_below": "Bullish Piercing",
            "reclaimed_from_below_bullish": "Bullish Reclaim",
            "rejected_from_above_bullish": "Bullish Support Rejection",
            "rejected_from_below_bearish": "Bearish Resistance Rejection",
        }
        for action, decision in expected.items():
            self.assertEqual(channel_line_rules._regression_decision(["lower"], action), decision)

    def test_action_aliases_resolve_to_the_same_decision(self):
        self.assertEqual(
            channel_line_rules._regression_decision(["lower"], "reclaim_bullish"),
            "Bullish Reclaim",
        )
        self.assertEqual(
            channel_line_rules._regression_decision(["lower"], "bullish_support_rejection"),
            "Bullish Support Rejection",
        )

    def test_rejection_is_never_labelled_as_a_reclaim(self):
        for action in ("rejected_from_above_bullish", "rejected_from_below_bearish"):
            self.assertNotIn(
                "Reclaim",
                channel_line_rules._regression_decision(["lower"], action),
            )

    def test_legacy_actions_are_otherwise_unchanged(self):
        self.assertEqual(channel_line_rules._regression_decision(["lower"], "touch"), "Support Test")
        self.assertEqual(channel_line_rules._regression_decision(["upper"], "touch"), "Resistance Test")
        self.assertEqual(channel_line_rules._regression_decision(["lower"], "close_below"), "Bearish Breakdown")
        self.assertEqual(channel_line_rules._regression_decision(["upper"], "stay_above"), "Breakout Holding")
        self.assertEqual(channel_line_rules._regression_decision(["lower"], "bogus_action"), "Channel Match")


class ReclaimRequiresAllThreeStagesTests(unittest.TestCase):
    """M3-ISS-02 action item: a true reclaim requires a close below, then a
    close back above, and the newest candle still above."""

    def _evaluate(self, closes, **overrides):
        config = {"candles_since_min": 0, "candles_since_max": 5, **overrides}
        return channel_interactions.evaluate_channel_interaction(
            [candle(close) for close in closes],
            FLAT_LINE,
            "reclaimed_from_below_bullish",
            config,
        )

    def test_full_reclaim_sequence_passes(self):
        # below, below, close back above, still above now
        result = self._evaluate([11.0, 9.0, 9.5, 10.5, 10.6])
        self.assertTrue(result["passed"])

    def test_stage_one_missing_never_closed_below(self):
        # The client's exact complaint: price stayed above the line the whole
        # time, so there is nothing to reclaim.
        result = self._evaluate([10.5, 10.6, 10.7, 10.8, 10.9])
        self.assertFalse(result["passed"])
        self.assertIsNone(result["event_index"])

    def test_stage_two_missing_still_below(self):
        result = self._evaluate([11.0, 9.0, 9.2, 9.4, 9.6])
        self.assertFalse(result["passed"])

    def test_stage_three_missing_dipped_back_below_after_reclaiming(self):
        # Reclaimed, then lost the line again - must not still qualify.
        result = self._evaluate([11.0, 9.0, 9.5, 10.5, 9.8])
        self.assertFalse(result["passed"])

    def test_still_above_now_can_be_switched_off(self):
        result = self._evaluate([11.0, 9.0, 9.5, 10.5, 9.8], require_still_above_now=False)
        self.assertTrue(result["passed"])

    def test_touching_the_line_is_not_closing_below_it(self):
        # close == line is not "below"; the comparison is strict.
        result = self._evaluate([11.0, 10.0, 10.0, 10.5, 10.6])
        self.assertFalse(result["passed"])

    def test_consecutive_below_count_is_honoured(self):
        closes = [11.0, 9.0, 10.5, 10.6]
        self.assertTrue(self._evaluate(closes, below_candles_min=1)["passed"])
        self.assertFalse(self._evaluate(closes, below_candles_min=2)["passed"])

    def test_at_least_one_close_below_is_always_required(self):
        # Even if the caller asks for zero, a reclaim without a prior close
        # below is not a reclaim.
        result = self._evaluate([10.5, 10.6, 10.7], below_candles_min=0)
        self.assertFalse(result["passed"])


class RejectionDoesNotRequireACloseBelowTests(unittest.TestCase):
    """M3-ISS-02 action item: rejection is a touch/penetration followed by a
    close back above - it must NOT require a close below."""

    def _rejected_from_above(self, candles):
        return channel_interactions.evaluate_channel_interaction(
            candles,
            FLAT_LINE,
            "rejected_from_above_bullish",
            {"candles_since_min": 0, "candles_since_max": 5},
        )

    def test_wick_into_the_line_then_close_above_passes(self):
        candles = [
            candle(11.0),
            candle(10.8),
            candle(10.5, high=11.0, low=9.6),  # pierced intraday, closed above
            candle(10.7),
        ]
        self.assertTrue(self._rejected_from_above(candles)["passed"])

    def test_rejection_does_not_fire_when_price_closed_below(self):
        # A close below means the level was lost, not defended.
        candles = [
            candle(11.0),
            candle(10.8),
            candle(9.5, high=11.0, low=9.4),
            candle(10.7),
        ]
        self.assertFalse(self._rejected_from_above(candles)["passed"])

    def test_reclaim_and_rejection_never_match_the_same_candle(self):
        """The two conditions are mutually exclusive by construction: reclaim
        needs the previous close below the line, rejection needs it above."""
        sequences = [
            [candle(11.0), candle(10.8), candle(10.5, high=11.0, low=9.6), candle(10.7)],
            [candle(11.0), candle(9.0), candle(9.5), candle(10.5), candle(10.6)],
            [candle(9.0), candle(9.5), candle(10.5, high=10.9, low=9.4), candle(10.8)],
        ]
        for candles in sequences:
            for index in range(len(candles)):
                reclaimed = channel_interactions._condition_matches(
                    candles, FLAT_LINE, index, "reclaimed_from_below_bullish", {},
                )
                rejected = channel_interactions._condition_matches(
                    candles, FLAT_LINE, index, "rejected_from_above_bullish", {},
                )
                self.assertFalse(
                    reclaimed and rejected,
                    f"candle {index} matched both reclaim and rejection",
                )


class EndToEndChannelRuleTests(unittest.TestCase):
    """The same distinction through the public channel-rule entry point."""

    CHANNEL = {"length": 5, "lower": [10.0] * 5, "middle": [12.0] * 5, "upper": [20.0] * 5}

    def _candles(self, closes):
        return [candle(close) for close in closes]

    def test_rejection_only_symbol_is_not_returned_by_a_reclaim_scan(self):
        # Never closed below the lower line - only wicked into it.
        candles = [
            candle(11.0), candle(10.8),
            candle(10.5, high=11.0, low=9.6),
            candle(10.7), candle(10.9),
        ]
        config = {"lines": ["lower"], "candles_since_min": 0, "candles_since_max": 5}

        self.assertTrue(channel_line_rules.evaluate_regression_lines(
            candles, self.CHANNEL, {**config, "action": "rejected_from_above_bullish"},
        ))
        self.assertFalse(channel_line_rules.evaluate_regression_lines(
            candles, self.CHANNEL, {**config, "action": "reclaimed_from_below_bullish"},
        ))

    def test_reclaim_symbol_is_not_returned_by_a_rejection_scan(self):
        candles = self._candles([11.0, 9.0, 9.5, 10.5, 10.6])
        config = {"lines": ["lower"], "candles_since_min": 0, "candles_since_max": 5}

        self.assertTrue(channel_line_rules.evaluate_regression_lines(
            candles, self.CHANNEL, {**config, "action": "reclaimed_from_below_bullish"},
        ))
        self.assertFalse(channel_line_rules.evaluate_regression_lines(
            candles, self.CHANNEL, {**config, "action": "rejected_from_above_bullish"},
        ))


class InteractionStageEvidenceTests(unittest.TestCase):
    """The per-stage breakdown the detail chart highlights, so a reclaim and a
    rejection are visually distinguishable against TradingView."""

    def _stages(self, closes, action, highs=None, lows=None):
        candles = []
        for index, close in enumerate(closes):
            candles.append({
                "time": 1_700_000_000 + (index * 86_400),
                "open": close,
                "high": close if highs is None else highs[index],
                "low": close if lows is None else lows[index],
                "close": close,
            })
        event_index = channel_interactions.latest_channel_interaction_event(
            candles, FLAT_LINE, action, {},
        )
        return channel_interactions.channel_interaction_stages(
            candles, FLAT_LINE, action, {}, event_index,
        )

    def test_reclaim_evidence_shows_the_run_of_closes_below(self):
        stages = self._stages([11.0, 9.0, 9.2, 10.5, 10.6], "reclaimed_from_below_bullish")
        names = [stage["stage"] for stage in stages]

        self.assertEqual(names.count("closed_below"), 2)
        self.assertIn("reclaim_close_above", names)
        self.assertIn("still_above_now", names)
        # Every stage carries the line value on that same candle, which is what
        # makes a TradingView comparison possible.
        for stage in stages:
            self.assertEqual(stage["line_value"], 10.0)
            self.assertIsNotNone(stage["candle_time"])

    def test_rejection_evidence_has_no_closed_below_stage(self):
        # The distinguishing evidence for M3-ISS-02: a rejection never closes
        # below the line, so it can never show a "closed_below" stage.
        stages = self._stages(
            [11.0, 10.8, 10.5, 10.7],
            "rejected_from_above_bullish",
            highs=[11.2, 11.0, 11.0, 10.9],
            lows=[10.8, 10.6, 9.6, 10.5],
        )
        names = [stage["stage"] for stage in stages]

        self.assertNotIn("closed_below", names)
        self.assertEqual(names, ["came_from_above", "rejected_close_above"])

    def test_no_event_yields_no_stages(self):
        self.assertEqual(
            channel_interactions.channel_interaction_stages([], FLAT_LINE, "reclaimed_from_below_bullish", {}, None),
            [],
        )


class HandlerEvidenceTests(unittest.TestCase):
    """The evidence actually reaches the detail payload the chart reads."""

    def _candles(self, closes):
        return [
            {
                "time": 1_700_000_000 + (index * 86_400),
                "open": close,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": 1,
                "is_closed": True,
            }
            for index, close in enumerate(closes)
        ]

    def test_lrc_handler_returns_channel_interaction_evidence(self):
        from services.indicators import handle_lrc

        asset = {"symbol": "TEST", "channels": {}}
        candles = self._candles([12.0, 11.5, 9.0, 9.2, 9.4, 10.6, 10.8, 11.0])
        config = {
            "length": 8,
            "lines": ["middle"],
            "action": "reclaimed_from_below_bullish",
            "candles_since_min": 0,
            "candles_since_max": 5,
        }

        passed, result = handle_lrc(asset, candles, config)
        self.assertTrue(passed)
        self.assertIsInstance(result, dict)

        entries = result["evidence"]["channel_interactions"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "reclaimed_from_below_bullish")
        self.assertTrue(entries[0]["matched"])
        self.assertTrue(
            any(stage["stage"] == "closed_below" for stage in entries[0]["stages"])
        )
        # The sticker must still report the honest decision.
        self.assertIn("Bullish Reclaim", result["sticker"])

    def test_legacy_action_returns_a_plain_sticker_and_no_reclaim_claim(self):
        from services.indicators import handle_lrc

        asset = {"symbol": "TEST", "channels": {}}
        candles = self._candles([9.0, 9.2, 9.4, 9.6, 9.8, 10.0, 10.4, 10.9])
        config = {"length": 8, "lines": ["middle"], "action": "close_above", "window": 1}

        passed, result = handle_lrc(asset, candles, config)
        if passed:
            sticker = result["sticker"] if isinstance(result, dict) else result
            self.assertNotIn("Reclaim", sticker)


if __name__ == "__main__":
    unittest.main()

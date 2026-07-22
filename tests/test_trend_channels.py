# tests/test_trend_channels.py
#
# Focused regression suite for the ChartPrime "Trend Channels With Liquidity
# Breaks" parity fixes (see docs/pinescript/trend_channel.md for the Pine
# source of truth). Covers: pivot detection/confirmation, pivot-anchored
# line positioning, ATR(10)*6 width, per-bar line progression, wait_for_break
# / show_last_channel gating, price-only break detection, the custom area
# rules (line + zone actions, tolerance, touch_type, window, confirmation),
# and the unclosed-candle guard on confirmed screener signals.

import unittest

from services import indicators, trend_channels


def _candles_from_bases(bases):
    """OHLCV fixture with constant true range (high - low = 1.0) so ATR(10)
    stays exactly 1.0 and the ATR(10)*6 offset is hand-computable.
    """
    return [
        {"open": b + 0.5, "high": b + 1.0, "low": b, "close": b + 0.5, "volume": 100.0}
        for b in bases
    ]


# Two declining pivot highs (11.6 @ bar2, then 11.3 @ bar7, span=5) trigger a
# down-channel at length=2. Two declining pivot lows also exist (10.0 @ bar4,
# 9.4 @ bar10) but never trigger an up-channel, since ChartPrime's up-trigger
# requires ascending lows.
DOWN_BASES = [10.0, 10.3, 10.6, 10.3, 10.0, 10.1, 10.2, 10.3, 10.0, 9.7, 9.4, 9.7, 10.0, 10.3]


class PivotDetectionTests(unittest.TestCase):
    """Phase 1/2A: ta.pivothigh(length, length) / ta.pivotlow(length, length) parity."""

    @staticmethod
    def _candles_from_highs(highs):
        return [{"high": h, "low": h - 10} for h in highs]

    @staticmethod
    def _candles_from_lows(lows):
        return [{"high": l + 10, "low": l} for l in lows]

    def test_unique_pivot_high(self):
        candles = self._candles_from_highs([1, 2, 5, 2, 1])
        self.assertTrue(trend_channels._is_pivot_high(candles, 2, 2))

    def test_unique_pivot_low(self):
        candles = self._candles_from_lows([5, 4, 1, 4, 5])
        self.assertTrue(trend_channels._is_pivot_low(candles, 2, 2))

    def test_equal_high_on_right_side_still_confirms(self):
        # ta.pivothigh allows a tie on the *right* (current >= max(right)).
        candles = self._candles_from_highs([1, 2, 5, 5, 1])
        self.assertTrue(trend_channels._is_pivot_high(candles, 2, 2))

    def test_equal_high_on_left_side_is_rejected(self):
        # A tie on the *left* fails (current > max(left) is strict).
        candles = self._candles_from_highs([1, 5, 5, 2, 1])
        self.assertFalse(trend_channels._is_pivot_high(candles, 2, 2))

    def test_equal_low_on_right_side_still_confirms(self):
        candles = self._candles_from_lows([5, 4, 1, 1, 5])
        self.assertTrue(trend_channels._is_pivot_low(candles, 2, 2))

    def test_equal_low_on_left_side_is_rejected(self):
        candles = self._candles_from_lows([5, 1, 1, 4, 5])
        self.assertFalse(trend_channels._is_pivot_low(candles, 2, 2))

    def test_confirmation_occurs_exactly_length_bars_after_pivot(self):
        candles = _candles_from_bases(DOWN_BASES)
        pivots = trend_channels._collect_confirmed_pivots(candles, 2)
        self.assertTrue(pivots)
        for pivot in pivots:
            self.assertEqual(pivot["confirm_index"] - pivot["index"], 2)

    def test_pivot_dict_stores_actual_index_separately_from_confirm_index(self):
        # Root cause of the anchor bug: Python already separates the actual
        # pivot bar ("index") from the bar it becomes known on
        # ("confirm_index" = index + length). The line anchor must consume
        # "index" as-is and must NOT subtract length a second time.
        candles = _candles_from_bases(DOWN_BASES)
        pivots = trend_channels._collect_confirmed_pivots(candles, 2)
        first_high = next(p for p in pivots if p["type"] == "high")
        self.assertEqual(first_high["index"], 2)
        self.assertEqual(first_high["confirm_index"], 4)


class ChannelConstructionTests(unittest.TestCase):
    """Phase 2B/2C: pivot-anchored coordinates and ATR(10)*6 width."""

    def test_down_channel_line_passes_through_actual_pivot_prices(self):
        candles = _candles_from_bases(DOWN_BASES)
        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertIsNotNone(channel)
        self.assertEqual(channel["direction"], "down")
        self.assertEqual(channel["start_index"], 2)
        # The line anchor must sit on the actual pivot bar (2), not
        # pivot_index - length again (which would land on bar 0).
        self.assertEqual(channel["line_x1"], 2)

        offset = 6.0  # ATR(10)=1.0 (constant true range) * 6
        pivot_high_price = 11.6  # bar 2
        self.assertAlmostEqual(float(channel["top"][0]), pivot_high_price + offset / 7)
        self.assertAlmostEqual(
            float(channel["bottom"][0]), pivot_high_price - offset - offset / 7
        )
        self.assertAlmostEqual(
            float(channel["middle"][0]), pivot_high_price - offset / 2
        )

    def test_up_channel_line_passes_through_actual_pivot_prices(self):
        # Mirror the down fixture in time: highs become ascending (fails the
        # down trigger's slope<=0 requirement) and lows become ascending
        # (satisfies the up trigger's slope>=0 requirement).
        up_bases = list(reversed(DOWN_BASES))
        candles = _candles_from_bases(up_bases)
        channel = trend_channels.compute_trend_channel(candles, length=2)

        self.assertIsNotNone(channel)
        self.assertEqual(channel["direction"], "up")
        self.assertEqual(channel["start_index"], 3)
        self.assertEqual(channel["line_x1"], 3)

        offset = 6.0
        pivot_low_price = 9.4  # actual bar 3
        self.assertAlmostEqual(float(channel["top"][0]), pivot_low_price + offset + offset / 7)
        self.assertAlmostEqual(float(channel["bottom"][0]), pivot_low_price - offset / 7)
        self.assertAlmostEqual(float(channel["middle"][0]), pivot_low_price + offset / 2)

    def test_atr10_times_6_offset(self):
        candles = _candles_from_bases(DOWN_BASES)
        channel = trend_channels.compute_trend_channel(candles, length=2)
        width = float(channel["top"][0]) - float(channel["bottom"][0])
        # width = offset + 2*(offset/7) = offset * 9/7
        self.assertAlmostEqual(width, 6.0 * 9.0 / 7.0)

    def test_width_stays_fixed_after_creation_despite_later_volatility(self):
        candles = _candles_from_bases(DOWN_BASES)
        # A huge-range candle after creation would spike ATR if recomputed,
        # but must not affect the already-captured channel offset. Its wick
        # spans far enough both ways that price-alone break never trips.
        candles.append({"open": 8.0, "high": 50.0, "low": -50.0, "close": 8.0, "volume": 100.0})
        candles.append({"open": 8.0, "high": 8.5, "low": 7.5, "close": 8.0, "volume": 100.0})

        channel = trend_channels.compute_trend_channel(candles, length=2)
        self.assertFalse(channel["broken"])

        widths = [top - bottom for top, bottom in zip(channel["top"], channel["bottom"])]
        for width in widths:
            self.assertAlmostEqual(width, 6.0 * 9.0 / 7.0)

    def test_channel_progression_creation_next_and_five_bars_later(self):
        bases = DOWN_BASES + [10.0, 9.7, 9.4, 9.1, 8.8]
        candles = _candles_from_bases(bases)
        channel = trend_channels.compute_trend_channel(candles, length=2)
        self.assertFalse(channel["broken"])

        start_index = channel["start_index"]

        def value_at(bar_index):
            regression_index = bar_index - start_index
            return float(channel["top"][regression_index])

        creation_bar_value = value_at(9)
        next_bar_value = value_at(10)
        five_bars_later_value = value_at(14)

        # Each bar's top must be strictly declining (down channel, negative
        # slope) and monotonic bar-over-bar - i.e. no double-advance, no
        # skipped first step, no horizontal channel shift.
        self.assertLess(next_bar_value, creation_bar_value)
        self.assertLess(five_bars_later_value, next_bar_value)
        self.assertAlmostEqual(creation_bar_value, 12.063392857142855)
        self.assertAlmostEqual(next_bar_value, 12.007142857142856)
        self.assertAlmostEqual(five_bars_later_value, 11.782142857142855)

    def test_no_fallback_channel_without_confirmed_pivots(self):
        candles = [
            {
                "open": float(i),
                "high": float(i) + 1.0,
                "low": float(i) - 0.5,
                "close": float(i) + 0.5,
                "volume": 100.0,
            }
            for i in range(80)
        ]
        self.assertIsNone(trend_channels.compute_trend_channel(candles, length=8))


class WaitForBreakAndShowLastChannelTests(unittest.TestCase):
    """Phase 2E/2F: wait_for_break gating and show_last_channel retention.

    Pivots are injected directly (bypassing scan heuristics) so the gating
    logic itself is isolated from pivot-detection concerns. Candle OHLC
    values are flat and far from the synthetic pivot prices so price-based
    breaks never interfere unless a test explicitly crafts one.
    """

    FLAT_CANDLE = {"open": 1.0, "high": 1.5, "low": 0.5, "close": 1.0, "volume": 100.0}

    # Up pivots (ascending lows) confirm first (bar 9); down pivots
    # (descending highs) confirm later (bar 18) while up is still active.
    PIVOTS = [
        {"type": "low", "index": 2, "price": 1.0, "confirm_index": 4},
        {"type": "low", "index": 7, "price": 1.05, "confirm_index": 9},
        {"type": "high", "index": 11, "price": 1.05, "confirm_index": 13},
        {"type": "high", "index": 16, "price": 1.0, "confirm_index": 18},
    ]

    def _candles(self, count=19, extra=None):
        candles = [dict(self.FLAT_CANDLE) for _ in range(count)]
        if extra:
            candles.extend(extra)
        return candles

    def test_wait_for_break_true_blocks_opposite_channel_while_active(self):
        channel = trend_channels._compute_pivot_liquidity_channel(
            self._candles(),
            2,
            confirmed_pivots=self.PIVOTS,
            wait_for_break=True,
            show_last_channel=True,
        )
        # Down pivots confirm while the up channel is still active and
        # unbroken; wait_for_break=True must block the new down channel.
        self.assertEqual(channel["direction"], "up")

    def test_wait_for_break_false_allows_opposite_channel_while_active(self):
        channel = trend_channels._compute_pivot_liquidity_channel(
            self._candles(),
            2,
            confirmed_pivots=self.PIVOTS,
            wait_for_break=False,
            show_last_channel=True,
        )
        # With gating disabled, the down channel forms immediately; a single
        # rendered channel always prefers the newer/active down state.
        self.assertEqual(channel["direction"], "down")

    def test_show_last_channel_true_retains_prior_channel_after_break(self):
        # A break bar far above both synthetic bands breaks the (newer) down
        # channel; with show_last_channel=True the still-active up channel
        # (never cleared) surfaces once down drops out.
        break_candle = {"open": 5.0, "high": 5.5, "low": 4.8, "close": 5.2, "volume": 100.0}
        channel = trend_channels._compute_pivot_liquidity_channel(
            self._candles(19, extra=[break_candle]),
            2,
            confirmed_pivots=self.PIVOTS,
            wait_for_break=False,
            show_last_channel=True,
        )
        self.assertEqual(channel["direction"], "up")
        self.assertFalse(channel["broken"])

    def test_show_last_channel_false_clears_opposite_channel_after_break(self):
        break_candle = {"open": 5.0, "high": 5.5, "low": 4.8, "close": 5.2, "volume": 100.0}
        channel = trend_channels._compute_pivot_liquidity_channel(
            self._candles(19, extra=[break_candle]),
            2,
            confirmed_pivots=self.PIVOTS,
            wait_for_break=False,
            show_last_channel=False,
        )
        # show_last_channel=False cleared the up channel the moment the down
        # channel formed, so once down breaks nothing is left to show.
        self.assertIsNone(channel)


class BreakDetectionTests(unittest.TestCase):
    """Phase 2G: price-alone break detection (no volume/range gating)."""

    def test_downward_break_on_low_range_channel(self):
        candles = _candles_from_bases(DOWN_BASES)
        candles.append({"open": 3.8, "high": 3.9, "low": 3.5, "close": 3.7, "volume": 100.0})
        channel = trend_channels.compute_trend_channel(candles, length=2)
        self.assertTrue(channel["broken"])
        self.assertEqual(channel["break_index"], 14)
        self.assertEqual(channel["break_direction"], "down")

    def test_upward_break_on_up_channel(self):
        up_bases = list(reversed(DOWN_BASES))
        candles = _candles_from_bases(up_bases)
        candles.append({"open": 18.0, "high": 18.5, "low": 17.5, "close": 18.2, "volume": 100.0})
        channel = trend_channels.compute_trend_channel(candles, length=2)
        self.assertTrue(channel["broken"])
        self.assertEqual(channel["break_index"], 14)
        self.assertEqual(channel["break_direction"], "up")

    def test_broken_channel_liquidity_break_is_metadata_only(self):
        # liquidity_break must never influence the break decision itself -
        # only price (low/high vs top/bottom) decides broken/break_direction.
        candles = _candles_from_bases(DOWN_BASES)
        candles.append({"open": 3.8, "high": 3.9, "low": 3.5, "close": 3.7, "volume": 0.0})
        channel = trend_channels.compute_trend_channel(candles, length=2)
        self.assertTrue(channel["broken"])
        self.assertIn("liquidity_break", channel)
        self.assertIsInstance(channel["liquidity_break"], bool)


class LineAreaActionTests(unittest.TestCase):
    """Phase 3: line touch/body/breach semantics."""

    WICK_TOUCH_CANDLE = {"open": 95.0, "high": 111.0, "low": 90.0, "close": 96.0}
    NO_TOUCH_CANDLE = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}

    def test_top_line_wick_touch(self):
        rule = {"action": "touched", "touch_type": "wick", "tolerance": 0}
        self.assertTrue(
            trend_channels.evaluate_line_action(self.WICK_TOUCH_CANDLE, 110.0, rule, "up")
        )

    def test_bottom_line_wick_touch(self):
        rule = {"action": "touched", "touch_type": "wick", "tolerance": 0}
        candle = {"open": 102.0, "high": 103.0, "low": 99.0, "close": 101.5}
        self.assertTrue(trend_channels.evaluate_line_action(candle, 100.0, rule, "down"))

    def test_body_touch_with_tolerance(self):
        rule = {"action": "touched", "touch_type": "body", "tolerance": 1}
        candle = {"open": 108.0, "high": 109.0, "low": 107.0, "close": 109.8}
        self.assertTrue(trend_channels.evaluate_line_action(candle, 110.0, rule, "up"))

    def test_wick_only_touch_does_not_pass_body_rule(self):
        rule = {"action": "touched", "touch_type": "body", "tolerance": 0}
        self.assertFalse(
            trend_channels.evaluate_line_action(self.WICK_TOUCH_CANDLE, 110.0, rule, "up")
        )

    def test_no_touch_fails(self):
        rule = {"action": "touched", "touch_type": "wick", "tolerance": 0}
        self.assertFalse(
            trend_channels.evaluate_line_action(self.NO_TOUCH_CANDLE, 110.0, rule, "up")
        )

    def test_line_tolerance_zero_is_preserved_not_replaced_by_default(self):
        # on_line's default tolerance is 0.1%; an explicit tolerance=0 must
        # stay exactly zero, not fall back to the default via `0 or default`.
        rule_explicit_zero = {"action": "on_line", "tolerance": 0}
        candle_just_outside = {"open": 110.02, "high": 110.3, "low": 109.9, "close": 110.02}
        self.assertFalse(
            trend_channels.evaluate_line_action(candle_just_outside, 110.0, rule_explicit_zero)
        )


class ZoneAreaActionTests(unittest.TestCase):
    """Phase 3: zone normalization, tolerance, touch_type, entered/rejected/breach."""

    def test_ccu_regression_body_completely_above_top_zone_fails(self):
        # CCU: body 11.60-11.67, top_zone entirely below it (11.30-11.50),
        # touch_type=body, tolerance=0 -> must not match.
        rule = {"action": "entered", "touch_type": "body", "tolerance": 0}
        candle = {"open": 11.60, "high": 11.70, "low": 11.58, "close": 11.67}
        self.assertFalse(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule, "up"))

    def test_top_zone_body_entry_matches(self):
        rule = {"action": "entered", "touch_type": "body", "tolerance": 0}
        candle = {"open": 11.20, "high": 11.45, "low": 11.10, "close": 11.40}
        self.assertTrue(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule, "up"))

    def test_wick_overlap_does_not_satisfy_body_rule(self):
        # Lower wick dips into the zone but the body sits entirely above it.
        rule_body = {"action": "entered", "touch_type": "body", "tolerance": 0}
        rule_wick = {"action": "entered", "touch_type": "wick", "tolerance": 0}
        candle = {"open": 11.60, "high": 11.75, "low": 11.45, "close": 11.67}
        self.assertTrue(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule_wick, "up"))
        self.assertFalse(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule_body, "up"))

    def test_body_completely_below_bottom_zone_fails(self):
        rule = {"action": "entered", "touch_type": "body", "tolerance": 0}
        candle = {"open": 9.50, "high": 9.65, "low": 9.45, "close": 9.60}
        self.assertFalse(trend_channels.evaluate_zone_action(candle, 9.80, 10.00, rule, "down"))

    def test_zone_tolerance_zero_rejects_near_miss(self):
        rule = {"action": "entered", "touch_type": "wick", "tolerance": 0}
        candle = {"open": 11.56, "high": 11.60, "low": 11.55, "close": 11.58}
        self.assertFalse(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule, "up"))

    def test_zone_tolerance_nonzero_accepts_near_miss(self):
        rule = {"action": "entered", "touch_type": "wick", "tolerance": 5}
        candle = {"open": 11.56, "high": 11.60, "low": 11.55, "close": 11.58}
        self.assertTrue(trend_channels.evaluate_zone_action(candle, 11.30, 11.50, rule, "up"))

    def test_zone_bounds_are_normalized_regardless_of_argument_order(self):
        rule = {"action": "entered", "touch_type": "body", "tolerance": 0}
        candle = {"open": 11.20, "high": 11.45, "low": 11.10, "close": 11.40}
        # Pass (upper, lower) reversed - normalization must still work.
        self.assertTrue(trend_channels.evaluate_zone_action(candle, 11.50, 11.30, rule, "up"))

    def test_top_zone_rejected_requires_entry_then_close_back_below(self):
        rule = {"action": "rejected", "touch_type": "wick", "tolerance": 0}
        rejecting_candle = {"open": 11.20, "high": 11.55, "low": 11.15, "close": 11.20}
        self.assertTrue(
            trend_channels.evaluate_zone_action(rejecting_candle, 11.30, 11.50, rule, "up")
        )
        holding_candle = {"open": 11.40, "high": 11.55, "low": 11.35, "close": 11.52}
        self.assertFalse(
            trend_channels.evaluate_zone_action(holding_candle, 11.30, 11.50, rule, "up")
        )

    def test_breach_respects_breach_type_and_outer_boundary(self):
        wick_rule = {"action": "breach", "breach_type": "wick", "tolerance": 0}
        body_rule = {"action": "breach", "breach_type": "body", "tolerance": 0}
        wick_only_candle = {"open": 11.20, "high": 11.55, "low": 11.10, "close": 11.30}
        self.assertTrue(
            trend_channels.evaluate_zone_action(wick_only_candle, 11.30, 11.50, wick_rule, "up")
        )
        self.assertFalse(
            trend_channels.evaluate_zone_action(wick_only_candle, 11.30, 11.50, body_rule, "up")
        )


class WindowAndConfirmationTests(unittest.TestCase):
    """Phase 3F/H: window boundaries and confirmation gating."""

    TOUCH_CANDLE = {"open": 95.0, "high": 111.0, "low": 90.0, "close": 96.0}
    NO_TOUCH_CANDLE = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}

    def _channel(self, length):
        return {
            "length": length,
            "top": [110.0] * length,
            "middle": [105.0] * length,
            "bottom": [100.0] * length,
        }

    def test_window_1_ignores_older_matching_candle(self):
        candles = [self.TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE]
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        self.assertFalse(trend_channels.evaluate_single_area(candles, self._channel(4), rule))

    def test_window_2_still_excludes_bar_outside_window(self):
        candles = [self.TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE]
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 2, "tolerance": 0, "confirmation": False}
        self.assertFalse(trend_channels.evaluate_single_area(candles, self._channel(4), rule))

    def test_window_n_includes_the_last_n_completed_candles(self):
        candles = [self.TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE, self.NO_TOUCH_CANDLE]
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 4, "tolerance": 0, "confirmation": False}
        self.assertTrue(trend_channels.evaluate_single_area(candles, self._channel(4), rule))

    def test_multiple_area_rules_require_all_to_pass(self):
        touch = self.TOUCH_CANDLE
        channel = self._channel(1)
        rule_top = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}
        rule_bottom = {"area": "bottom_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}

        self.assertFalse(
            trend_channels.evaluate_trend_channel_rules([touch], channel, {"areas": [rule_top, rule_bottom]})
        )
        self.assertTrue(
            trend_channels.evaluate_trend_channel_rules([touch], channel, {"areas": [rule_top, rule_top]})
        )

    def test_confirmation_enabled_requires_matching_pattern(self):
        neutral = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5}
        candles = [self.TOUCH_CANDLE, neutral]
        channel = self._channel(2)
        rule = {
            "area": "top_line",
            "action": "touched",
            "touch_type": "wick",
            "window": 2,
            "tolerance": 0,
            "confirmation": True,
            "confirmation_types": ["strong_bullish"],
            "confirmation_window": 1,
        }
        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))

    def test_confirmation_disabled_ignores_pattern_requirement(self):
        neutral = {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5}
        candles = [self.TOUCH_CANDLE, neutral]
        channel = self._channel(2)
        rule = {
            "area": "top_line",
            "action": "touched",
            "touch_type": "wick",
            "window": 2,
            "tolerance": 0,
            "confirmation": False,
            "confirmation_types": ["strong_bullish"],
            "confirmation_window": 1,
        }
        self.assertTrue(trend_channels.evaluate_single_area(candles, channel, rule))


class BrokenChannelRetentionTests(unittest.TestCase):
    """Phase 2F/3: a retained broken channel's frozen lines must not
    generate fresh post-break signals, even though the raw numbers can still
    be matched directly against evaluate_line_action.
    """

    @staticmethod
    def _bases():
        return DOWN_BASES + [13.0]

    def test_post_break_bar_is_excluded_from_area_evaluation(self):
        candles = _candles_from_bases(self._bases())
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
        # The raw frozen line value can still be matched directly...
        self.assertTrue(
            trend_channels.evaluate_line_action(candles[-1], channel["bottom"][-1], rule, "down")
        )
        # ...but the screener-facing evaluator must reject it: only bars at
        # or before break_index are eligible to generate a signal.
        self.assertFalse(trend_channels.evaluate_single_area(candles, channel, rule))


class FormingCandleAndEvidenceTests(unittest.TestCase):
    """Phase 2G/7: unclosed candles never produce a confirmed match, and
    handle_trend's evidence reflects the exact candle/channel index used.
    """

    def _config(self, rule):
        return {
            "length": 2,
            "wait_for_break": True,
            "show_last_channel": True,
            "areas": [rule],
        }

    def test_forming_candle_does_not_generate_a_confirmed_signal(self):
        candles = _candles_from_bases(DOWN_BASES)
        forming = {"open": 10.5, "high": 11.9, "low": 10.4, "close": 10.6, "volume": 100.0}
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}

        closed_candles = candles + [dict(forming)]
        passed_closed, _ = indicators.handle_trend({"channels": {}}, closed_candles, self._config(rule))
        self.assertTrue(passed_closed)

        unclosed_candles = candles + [dict(forming, is_closed=False)]
        passed_unclosed, result_unclosed = indicators.handle_trend(
            {"channels": {}}, unclosed_candles, self._config(rule)
        )
        self.assertFalse(passed_unclosed)
        self.assertFalse(result_unclosed["evidence"][0]["matched"])

    def test_evidence_reflects_the_last_closed_candle_and_channel_indexes(self):
        candles = _candles_from_bases(DOWN_BASES)
        rule = {"area": "top_line", "action": "touched", "touch_type": "wick", "window": 1, "tolerance": 0, "confirmation": False}

        passed, result = indicators.handle_trend({"channels": {}}, candles, self._config(rule))
        self.assertFalse(passed)
        evidence = result["evidence"][0]

        self.assertEqual(evidence["checked_candle_index"], len(candles) - 1)
        self.assertTrue(evidence["checked_candle_closed"])
        self.assertEqual(evidence["channel_direction"], "down")
        self.assertEqual(evidence["channel_start_index"], 2)
        self.assertIn("line_value", evidence)


if __name__ == "__main__":
    unittest.main()

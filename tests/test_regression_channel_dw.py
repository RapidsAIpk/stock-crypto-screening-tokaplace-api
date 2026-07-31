import os
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import channel_line_rules, indicators, linear_regression_channel, regression_channel_dw, screener  # noqa: E402


def _ts(year, month, day, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp())


def _candle(close, timestamp=None, high=None, low=None, open_=None):
    return {
        "time": timestamp if timestamp is not None else _ts(2026, 1, 1),
        "open": float(close if open_ is None else open_),
        "high": float(close if high is None else high),
        "low": float(close if low is None else low),
        "close": float(close),
    }


class DWRegressionChannelTests(unittest.TestCase):
    def test_quartile_order_is_upper_q3_middle_q1_lower(self):
        candles = [_candle(close) for close in (100, 102, 104, 106)]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=4)

        self.assertIsNotNone(channel)
        finite_rows = [
            (upper, q3, middle, q1, lower)
            for upper, q3, middle, q1, lower in zip(
                channel["upper"],
                channel["q3"],
                channel["middle"],
                channel["q1"],
                channel["lower"],
            )
            if np.isfinite(upper) and np.isfinite(middle) and np.isfinite(lower)
        ]
        self.assertTrue(finite_rows)
        strict_rows = 0
        for upper, q3, middle, q1, lower in finite_rows:
            self.assertGreaterEqual(upper, q3)
            self.assertGreaterEqual(q3, middle)
            self.assertGreaterEqual(middle, q1)
            self.assertGreaterEqual(q1, lower)
            if upper > q3 > middle > q1 > lower:
                strict_rows += 1
        self.assertGreater(strict_rows, 0)

    def test_upper_and_lower_width_are_symmetric(self):
        candles = [_candle(close) for close in (100, 102, 104, 106)]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=4)

        self.assertIsNotNone(channel)
        finite_rows = [
            (upper, middle, lower)
            for upper, middle, lower in zip(channel["upper"], channel["middle"], channel["lower"])
            if np.isfinite(upper) and np.isfinite(middle) and np.isfinite(lower)
        ]
        self.assertTrue(finite_rows)
        for upper, middle, lower in finite_rows:
            self.assertAlmostEqual(float(upper - middle), float(middle - lower))

    def test_width_coefficient_scales_filtered_standard_deviation(self):
        candles = [_candle(close) for close in (100, 102, 104, 106)]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=4, width_coeff=2.5)

        self.assertIsNotNone(channel)
        self.assertAlmostEqual(
            float(channel["upper"][-1] - channel["middle"][-1]),
            float(channel["middle"][-1] - channel["lower"][-1]),
        )
        self.assertGreater(float(channel["upper"][-1] - channel["middle"][-1]), 0.0)

    def test_q3_and_q1_wick_touches_are_not_restricted_to_one_side(self):
        q3_channel = {"length": 1, "q3": [100.0]}
        q1_channel = {"length": 1, "q1": [100.0]}
        resistance_candle = [_candle(99.0, open_=99.0, high=100.5, low=98.5)]
        support_candle = [_candle(101.0, open_=101.0, high=101.5, low=99.5)]
        config = {
            "lines": ["q3"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(channel_line_rules.evaluate_regression_lines(resistance_candle, q3_channel, config))
        self.assertTrue(channel_line_rules.evaluate_regression_lines(support_candle, q3_channel, config))

        config["lines"] = ["q1"]
        self.assertTrue(channel_line_rules.evaluate_regression_lines(support_candle, q1_channel, config))
        self.assertTrue(channel_line_rules.evaluate_regression_lines(resistance_candle, q1_channel, config))

    def test_q3_both_accepts_body_crossing_from_either_side(self):
        channel = {"length": 1, "q3": [1080.4026]}
        config = {
            "lines": ["q3"],
            "action": "touch",
            "touch_type": "both",
            "window": 1,
            "tolerance": 0,
            "mintick": 0.01,
            "confirmation": False,
        }
        blk_rejection = [
            _candle(1079.19, open_=1086.07, high=1110.00, low=1079.19)
        ]
        bullish_crossing = [
            _candle(1086.07, open_=1079.19, high=1110.00, low=1079.19)
        ]

        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                blk_rejection,
                channel,
                config,
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                bullish_crossing,
                channel,
                config,
            )
        )

    def test_touch_type_body_wick_and_both_use_the_selected_candle_parts(self):
        channel = {"length": 1, "middle": [100.0]}
        body_only_touch = [_candle(101.0, open_=99.0, high=102.0, low=98.0)]
        wick_only_touch = [_candle(99.0, open_=99.0, high=101.0, low=98.0)]
        config = {
            "lines": ["middle"],
            "action": "touch",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                body_only_touch,
                channel,
                {**config, "touch_type": "body"},
            )
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                body_only_touch,
                channel,
                {**config, "touch_type": "wick"},
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                body_only_touch,
                channel,
                {**config, "touch_type": "both"},
            )
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                wick_only_touch,
                channel,
                {**config, "touch_type": "body"},
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                wick_only_touch,
                channel,
                {**config, "touch_type": "wick"},
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                wick_only_touch,
                channel,
                {**config, "touch_type": "both"},
            )
        )

    def test_stay_below_requires_the_high_to_remain_below_the_line(self):
        channel = {"length": 1, "middle": [116.9614]}
        config = {
            "lines": ["middle"],
            "action": "stay_below",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "mintick": 0.01,
            "confirmation": False,
        }

        cm_body_crosses_line = [
            _candle(116.23, open_=119.30, high=119.39, low=115.90)
        ]
        entirely_below = [
            _candle(116.23, open_=116.40, high=116.80, low=115.90)
        ]

        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                cm_body_crosses_line,
                channel,
                config,
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                entirely_below,
                channel,
                config,
            )
        )

    def test_stay_above_requires_the_low_to_remain_above_the_line(self):
        channel = {"length": 1, "middle": [100.0]}
        config = {
            "lines": ["middle"],
            "action": "stay_above",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        lower_wick_crosses_line = [
            _candle(101.5, open_=101.0, high=102.0, low=99.5)
        ]
        entirely_above = [
            _candle(101.5, open_=101.0, high=102.0, low=100.5)
        ]

        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                lower_wick_crosses_line,
                channel,
                config,
            )
        )
        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                entirely_above,
                channel,
                config,
            )
        )

    def test_sub_dollar_stock_mintick_rejects_edtk_window_two_false_positive(self):
        candles = [
            _candle(0.947, high=0.9735, low=0.947, open_=0.952),
            _candle(0.932, high=0.9575, low=0.932, open_=0.945),
            _candle(0.940, high=0.9699, low=0.930, open_=0.930),
        ]
        channel = {
            "length": 3,
            "middle": [0.969537855175, 0.968490895725, 0.967327193775],
        }
        config = {
            "lines": ["middle"],
            "action": "stay_below",
            "touch_type": "wick",
            "window": 2,
            "tolerance": 0,
            "confirmation": False,
            "mintick": indicators._regression_mintick(
                {"symbol": "EDTK", "asset_type": "stocks"},
                {},
                candles,
            ),
        }

        self.assertEqual(config["mintick"], 0.0001)
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(candles, channel, config)
        )

    def test_upper_wick_near_touch_below_tick_rounded_line_fails(self):
        config = {
            "lines": ["upper"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "mintick": 0.01,
            "confirmation": False,
        }

        just_below_cent_line = [_candle(0.530, open_=0.530, high=0.539, low=0.520)]
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                just_below_cent_line,
                {"length": 1, "upper": [0.536]},
                config,
            )
        )

        just_below_outward_rounded_line = [_candle(0.530, open_=0.530, high=0.540, low=0.520)]
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                just_below_outward_rounded_line,
                {"length": 1, "upper": [0.542]},
                config,
            )
        )

    def test_touch_window_does_not_match_an_old_touch_when_latest_candle_misses(self):
        channel = {"length": 2, "upper": [0.536, 0.536]}
        previous_touch = _candle(0.530, open_=0.530, high=0.540, low=0.520)
        latest_miss = _candle(0.530, open_=0.530, high=0.539, low=0.520)
        config = {
            "lines": ["upper"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "mintick": 0.01,
            "confirmation": False,
        }

        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                [previous_touch, latest_miss],
                channel,
                config,
            )
        )

        config["window"] = 2
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                [previous_touch, latest_miss],
                channel,
                config,
            )
        )

    def test_touch_window_requires_the_exact_current_consecutive_signal_age(self):
        channel = {"length": 5, "lower": [2.34, 2.33, 2.32, 2.31, 2.30]}
        miss = _candle(2.36, open_=2.36, high=2.37, low=2.35)

        def lower_touch(line):
            return _candle(
                line + 0.01,
                open_=line + 0.01,
                high=line + 0.02,
                low=line - 0.01,
            )

        four_candle_signal = [
            miss,
            lower_touch(2.33),
            lower_touch(2.32),
            lower_touch(2.31),
            lower_touch(2.30),
        ]
        five_candle_signal = [
            lower_touch(2.34),
            lower_touch(2.33),
            lower_touch(2.32),
            lower_touch(2.31),
            lower_touch(2.30),
        ]
        three_candle_signal = [
            miss,
            miss,
            lower_touch(2.32),
            lower_touch(2.31),
            lower_touch(2.30),
        ]
        old_touch_only = [
            miss,
            lower_touch(2.33),
            miss,
            miss,
            miss,
        ]
        config = {
            "lines": ["lower"],
            "action": "touch",
            "touch_type": "both",
            "window": 4,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(
            channel_line_rules.evaluate_regression_lines(
                four_candle_signal,
                channel,
                config,
            )
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                five_candle_signal,
                channel,
                config,
            )
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                three_candle_signal,
                channel,
                config,
            )
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(
                old_touch_only,
                channel,
                config,
            )
        )

    def test_stock_dw_regression_evaluation_defaults_to_cent_tick(self):
        raw_channel = {"length": 1, "upper": [0.536]}
        candle = [_candle(0.530, open_=0.530, high=0.539, low=0.520)]
        config = {
            "lines": ["upper"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
            "confirmation": False,
        }

        self.assertTrue(channel_line_rules.evaluate_regression_lines(candle, raw_channel, config))

        stock_config = dict(config)
        stock_config["mintick"] = indicators._regression_mintick(
            {"symbol": "FURY", "asset_type": "stocks"},
            stock_config,
        )
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(candle, raw_channel, stock_config)
        )

    def test_hourly_interval_candles_grow_through_same_day(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 0)),
            _candle(101, _ts(2026, 1, 1, 1)),
            _candle(102, _ts(2026, 1, 1, 2)),
        ]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=200, window_type="interval")

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 3)

    def test_interval_resets_when_next_day_begins(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 22)),
            _candle(101, _ts(2026, 1, 1, 23)),
            _candle(102, _ts(2026, 1, 2, 0)),
        ]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=200, window_type="interval")

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 1)
        self.assertAlmostEqual(float(channel["middle"][0]), 102.0)

    def test_every_candle_from_current_day_is_included(self):
        candles = [
            _candle(90, _ts(2026, 1, 1, 23)),
            _candle(100, _ts(2026, 1, 2, 0)),
            _candle(110, _ts(2026, 1, 2, 1)),
            _candle(120, _ts(2026, 1, 2, 2)),
        ]

        channel = regression_channel_dw.compute_dw_regression_channel(candles, length=200, window_type="interval")

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 3)
        self.assertTrue(np.isfinite(channel["middle"][-1]))

    def test_interval_step_samples_input_but_preserves_output_alignment(self):
        candles = [
            _candle(10, _ts(2026, 1, 2, 0)),
            _candle(100, _ts(2026, 1, 2, 1)),
            _candle(20, _ts(2026, 1, 2, 2)),
            _candle(200, _ts(2026, 1, 2, 3)),
        ]

        step_one = regression_channel_dw.compute_dw_regression_channel(
            candles,
            length=200,
            window_type="interval",
            interval_step=1,
        )
        step_two = regression_channel_dw.compute_dw_regression_channel(
            candles,
            length=200,
            window_type="interval",
            interval_step=2,
        )
        unsampled_values_changed = [
            _candle(10, _ts(2026, 1, 2, 0)),
            _candle(-999, _ts(2026, 1, 2, 1)),
            _candle(20, _ts(2026, 1, 2, 2)),
            _candle(999, _ts(2026, 1, 2, 3)),
        ]
        step_two_changed = regression_channel_dw.compute_dw_regression_channel(
            unsampled_values_changed,
            length=200,
            window_type="interval",
            interval_step=2,
        )

        self.assertIsNotNone(step_one)
        self.assertIsNotNone(step_two)
        self.assertEqual(step_two["length"], 4)
        self.assertEqual(len(step_two["middle"]), 4)
        self.assertEqual(step_two["interval_step"], 2)
        np.testing.assert_allclose(step_two["middle"], step_two_changed["middle"])
        self.assertFalse(np.allclose(step_one["middle"], step_two["middle"]))
        self.assertAlmostEqual(float(step_two["tracer"][0]), float(step_two["tracer"][1]))
        self.assertAlmostEqual(float(step_two["tracer"][2]), float(step_two["tracer"][3]))

    def test_continuous_channel_is_latest_static_model_and_tracer_remains_rolling(self):
        candles = [
            _candle(close, timestamp=_ts(2026, 1, index + 1))
            for index, close in enumerate((10, 10, 10, 10, 12, 14, 16))
        ]

        channel = regression_channel_dw.compute_dw_regression_channel(
            candles,
            length=4,
            width_coeff=1,
            window_type="continuous",
            filter_type="SMA",
        )

        self.assertIsNotNone(channel)
        middle = np.asarray(channel["middle"], dtype=float)
        tracer = np.asarray(channel["tracer"], dtype=float)
        upper = np.asarray(channel["upper"], dtype=float)
        lower = np.asarray(channel["lower"], dtype=float)

        np.testing.assert_allclose(np.diff(middle), np.full(3, np.diff(middle)[0]))
        np.testing.assert_allclose(upper - middle, middle - lower)
        np.testing.assert_allclose(upper - middle, np.full(4, upper[-1] - middle[-1]))
        self.assertAlmostEqual(float(middle[-1]), float(tracer[-1]))
        self.assertFalse(np.allclose(middle, tracer))

    def test_interval_step_sampling_restarts_on_each_utc_day(self):
        candles = [
            _candle(10, _ts(2026, 1, 1, 22)),
            _candle(999, _ts(2026, 1, 1, 23)),
            _candle(20, _ts(2026, 1, 2, 0)),
            _candle(888, _ts(2026, 1, 2, 1)),
        ]

        sample_indices = regression_channel_dw._interval_sample_indices(candles, 2)

        np.testing.assert_array_equal(sample_indices, np.array([0, 2]))

    def test_continuous_mode_ignores_interval_settings(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 22)),
            _candle(101, _ts(2026, 1, 1, 23)),
            _candle(102, _ts(2026, 1, 2, 0)),
            _candle(103, _ts(2026, 1, 2, 1)),
            _candle(104, _ts(2026, 1, 2, 2)),
        ]

        channel = regression_channel_dw.compute_dw_regression_channel(
            candles,
            length=4,
            window_type="continuous",
            interval_step=2,
        )

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 4)
        self.assertEqual(len(channel["middle"]), 4)

    def test_continuous_mode_preserves_history_for_nested_pine_filters(self):
        candles = [
            _candle(close, timestamp=_ts(2026, 1, index + 1), high=close + 0.4, low=close - 0.4)
            for index, close in enumerate((10, 10, 10, 10, 12, 14, 16))
        ]
        config = {
            "lines": ["middle"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
        }

        channel = regression_channel_dw.compute_dw_regression_channel(
            candles,
            length=4,
            width_coeff=1,
            window_type="continuous",
            filter_type="SMA",
        )

        self.assertIsNotNone(channel)
        self.assertAlmostEqual(float(channel["middle"][-1]), 14.75)
        self.assertGreater(candles[-1]["low"], float(channel["middle"][-1]))
        self.assertFalse(
            channel_line_rules.evaluate_regression_lines(candles, channel, config)
        )

    def test_continuous_dw_requests_nested_filter_history(self):
        indicators = [
            SimpleNamespace(
                name="regression",
                config={
                    "length": 200,
                    "window": 1,
                    "window_type": "continuous",
                },
            )
        ]

        self.assertEqual(screener.required_candles_for_indicators(indicators), 399)
        self.assertEqual(
            screener._required_candles_for_channel_type("regression", 200),
            399,
        )

    def test_intraday_and_daily_share_completed_candle_and_line_alignment(self):
        closes = (10, 10, 10, 10, 12, 14, 16)
        minute_times = [
            _ts(2026, 1, 2, 19) + index * 60
            for index in range(len(closes))
        ]
        hourly_times = [
            _ts(2026, 1, 2, hour)
            for hour in (14, 15, 16, 17, 18, 19, 20)
        ]
        daily_times = [
            _ts(2025, 12, 22 + index, 20)
            for index in range(len(closes))
        ]
        config = {
            "lines": ["middle"],
            "action": "touch",
            "touch_type": "wick",
            "window": 1,
            "tolerance": 0,
        }

        def evaluate(times):
            completed = [
                _candle(
                    close,
                    timestamp=timestamp,
                    high=close + 0.4,
                    low=close - 0.4,
                )
                for close, timestamp in zip(closes, times)
            ]
            forming = _candle(
                99,
                timestamp=times[-1] + 3600,
                high=100,
                low=1,
            )
            forming["is_closed"] = False
            snapshot = screener._completed_candle_snapshot(
                [{"symbol": "FURY", "candles": [*completed, forming]}],
                candles_limit=len(completed),
            )[0]["candles"]
            channel = regression_channel_dw.compute_dw_regression_channel(
                snapshot,
                length=4,
                width_coeff=1,
                window_type="continuous",
            )
            candle_index = len(snapshot) - 1
            start_index = len(snapshot) - channel["length"]
            regression_index = candle_index - start_index
            middle = float(channel["middle"][regression_index])
            latest = snapshot[candle_index]
            return {
                "snapshot": snapshot,
                "candle_index": candle_index,
                "regression_index": regression_index,
                "middle": middle,
                "formula": latest["low"] <= middle <= latest["high"],
                "passed": channel_line_rules.evaluate_regression_lines(
                    snapshot,
                    channel,
                    config,
                ),
            }

        minute = evaluate(minute_times)
        hourly = evaluate(hourly_times)
        daily = evaluate(daily_times)

        self.assertEqual(len(minute["snapshot"]), len(closes))
        self.assertEqual(len(hourly["snapshot"]), len(closes))
        self.assertEqual(len(daily["snapshot"]), len(closes))
        self.assertNotIn("is_closed", minute["snapshot"][-1])
        self.assertNotIn("is_closed", hourly["snapshot"][-1])
        self.assertNotIn("is_closed", daily["snapshot"][-1])
        self.assertEqual(minute["candle_index"], daily["candle_index"])
        self.assertEqual(hourly["candle_index"], daily["candle_index"])
        self.assertEqual(minute["regression_index"], daily["regression_index"])
        self.assertEqual(hourly["regression_index"], daily["regression_index"])
        self.assertAlmostEqual(minute["middle"], daily["middle"])
        self.assertAlmostEqual(hourly["middle"], daily["middle"])
        self.assertEqual(minute["formula"], minute["passed"])
        self.assertEqual(hourly["formula"], hourly["passed"])
        self.assertEqual(daily["formula"], daily["passed"])
        self.assertEqual(minute["passed"], daily["passed"])
        self.assertEqual(hourly["passed"], daily["passed"])

    def test_lrc_output_keeps_existing_contract_with_dynamic_metadata(self):
        candles = [_candle(close) for close in (100, 101, 102, 103)]

        channel = linear_regression_channel.compute_lrc_channel(candles, length=4, upper_dev=2.0, lower_dev=2.0)

        self.assertIsNotNone(channel)
        self.assertTrue({"middle", "upper", "lower", "r", "length"}.issubset(set(channel.keys())))
        self.assertEqual(channel["length"], 4)

    def test_lrc_uses_lonesomeblue_single_latest_channel(self):
        candles = [_candle(close) for close in (100, 102, 104, 106)]

        channel = linear_regression_channel.compute_lrc_channel(candles, length=4, upper_dev=2.0, lower_dev=2.0)

        self.assertIsNotNone(channel)
        self.assertAlmostEqual(float(channel["slope"]), 2.0)
        self.assertAlmostEqual(float(channel["intercept"]), 100.0)
        self.assertAlmostEqual(float(channel["end"]), 106.0)
        self.assertTrue(np.allclose(channel["middle"], np.array([100.0, 102.0, 104.0, 106.0])))

    def test_lrc_source_and_asymmetric_deviation_are_configurable(self):
        candles = [
            _candle(100, high=110, low=95),
            _candle(101, high=112, low=95),
            _candle(102, high=114, low=95),
            _candle(103, high=116, low=95),
        ]

        channel = linear_regression_channel.compute_lrc_channel(
            candles,
            length=4,
            source="high",
            upper_dev=3.0,
            lower_dev=1.0,
        )

        self.assertIsNotNone(channel)
        self.assertEqual(channel["source"], "high")
        self.assertGreater(
            float(channel["upper"][-1] - channel["middle"][-1]),
            float(channel["middle"][-1] - channel["lower"][-1]),
        )


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from datetime import datetime, timezone

import numpy as np


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import regression_channels  # noqa: E402


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

        channel = regression_channels.compute_dw_regression_channel(candles, length=4)

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
        for upper, q3, middle, q1, lower in finite_rows:
            self.assertGreater(upper, q3)
            self.assertGreater(q3, middle)
            self.assertGreater(middle, q1)
            self.assertGreater(q1, lower)

    def test_upper_and_lower_width_are_symmetric(self):
        candles = [_candle(close) for close in (100, 102, 104, 106)]

        channel = regression_channels.compute_dw_regression_channel(candles, length=4)

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

        channel = regression_channels.compute_dw_regression_channel(candles, length=4, width_coeff=2.5)

        self.assertIsNotNone(channel)
        self.assertAlmostEqual(
            float(channel["upper"][-1] - channel["middle"][-1]),
            float(channel["middle"][-1] - channel["lower"][-1]),
        )
        self.assertGreater(float(channel["upper"][-1] - channel["middle"][-1]), 0.0)

    def test_q3_is_resistance_and_q1_is_support_for_touches(self):
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

        self.assertTrue(regression_channels.evaluate_regression_lines(resistance_candle, q3_channel, config))
        self.assertFalse(regression_channels.evaluate_regression_lines(support_candle, q3_channel, config))

        config["lines"] = ["q1"]
        self.assertTrue(regression_channels.evaluate_regression_lines(support_candle, q1_channel, config))
        self.assertFalse(regression_channels.evaluate_regression_lines(resistance_candle, q1_channel, config))

    def test_hourly_interval_candles_grow_through_same_day(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 0)),
            _candle(101, _ts(2026, 1, 1, 1)),
            _candle(102, _ts(2026, 1, 1, 2)),
        ]

        channel = regression_channels.compute_dw_regression_channel(candles, length=200, window_type="interval")

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 3)

    def test_interval_resets_when_next_day_begins(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 22)),
            _candle(101, _ts(2026, 1, 1, 23)),
            _candle(102, _ts(2026, 1, 2, 0)),
        ]

        channel = regression_channels.compute_dw_regression_channel(candles, length=200, window_type="interval")

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

        channel = regression_channels.compute_dw_regression_channel(candles, length=200, window_type="interval")

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 3)
        self.assertTrue(np.isfinite(channel["middle"][-1]))

    def test_interval_mode_does_not_downsample(self):
        candles = [
            _candle(100, _ts(2026, 1, 2, 0)),
            _candle(101, _ts(2026, 1, 2, 1)),
            _candle(102, _ts(2026, 1, 2, 2)),
            _candle(103, _ts(2026, 1, 2, 3)),
        ]

        channel = regression_channels.compute_dw_regression_channel(
            candles,
            length=200,
            window_type="interval",
            interval_step=2,
        )

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 4)
        self.assertEqual(len(channel["middle"]), 4)

    def test_continuous_mode_ignores_interval_settings(self):
        candles = [
            _candle(100, _ts(2026, 1, 1, 22)),
            _candle(101, _ts(2026, 1, 1, 23)),
            _candle(102, _ts(2026, 1, 2, 0)),
            _candle(103, _ts(2026, 1, 2, 1)),
            _candle(104, _ts(2026, 1, 2, 2)),
        ]

        channel = regression_channels.compute_dw_regression_channel(
            candles,
            length=4,
            window_type="continuous",
            interval_step=2,
        )

        self.assertIsNotNone(channel)
        self.assertEqual(channel["length"], 4)
        self.assertEqual(len(channel["middle"]), 4)

    def test_lrc_output_remains_unchanged(self):
        candles = [_candle(close) for close in (100, 101, 102, 103)]

        channel = regression_channels.compute_lrc_channel(candles, length=4, upper_dev=2.0, lower_dev=2.0)

        self.assertIsNotNone(channel)
        self.assertEqual(set(channel.keys()), {"middle", "upper", "lower", "r", "length"})
        self.assertEqual(channel["length"], 4)


if __name__ == "__main__":
    unittest.main()

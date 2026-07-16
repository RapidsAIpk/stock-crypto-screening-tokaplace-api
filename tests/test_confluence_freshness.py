import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import confluence  # noqa: E402


def _candle(open_, high, low, close):
    return {
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
    }


def _flat_channel(count, upper=100.0, lower=95.0):
    return {
        "upper": [float(upper)] * count,
        "lower": [float(lower)] * count,
    }


def _sources(first_selection, second_selection):
    return [
        SimpleNamespace(id="first", channel_type="lrc", selection=first_selection),
        SimpleNamespace(id="second", channel_type="lrc", selection=second_selection),
    ]


def _config(confluence_type, first_selection, second_selection):
    return SimpleNamespace(
        type=confluence_type,
        channels=["lrc", "lrc"],
        sources=_sources(first_selection, second_selection),
        liquidity_sweep=False,
        lookback_candles=4,
        tolerance_pct=0.1,
    )


def _channels(count, first_upper=100.0, first_lower=95.0, second_upper=200.0, second_lower=90.0):
    return {
        "first": {
            "channel_type": "lrc",
            "channel": _flat_channel(count, upper=first_upper, lower=first_lower),
        },
        "second": {
            "channel_type": "lrc",
            "channel": _flat_channel(count, upper=second_upper, lower=second_lower),
        },
    }


class ConfluenceFreshnessTests(unittest.TestCase):
    def test_breakout_path_1_exactly_4_passes(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100, 101),
            _candle(201, 202, 200, 201),
        ]

        self.assertTrue(
            confluence.evaluate_confluence(candles, _channels(len(candles)), _config("breakout", "upper", "upper"))
        )

    def test_breakout_path_1_exactly_5_fails(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 101.5, 101),
            _candle(101, 102, 101.5, 101),
            _candle(201, 202, 200, 201),
            _candle(201, 202, 200, 201),
        ]

        self.assertFalse(
            confluence.evaluate_confluence(candles, _channels(len(candles)), _config("breakout", "upper", "upper"))
        )

    def test_breakout_path_2_exactly_4_passes(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(201, 202, 200, 201),
        ]

        self.assertTrue(
            confluence.evaluate_confluence(candles, _channels(len(candles)), _config("breakout", "upper", "upper"))
        )

    def test_breakout_path_2_exactly_5_fails(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(201, 202, 200, 201),
            _candle(201, 202, 200, 201),
        ]

        self.assertFalse(
            confluence.evaluate_confluence(candles, _channels(len(candles)), _config("breakout", "upper", "upper"))
        )

    def test_bullish_dual_support_run_exactly_4_passes(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=100.0)

        self.assertTrue(
            confluence.evaluate_confluence(candles, channels, _config("bullish", "lower", "lower"))
        )

    def test_bullish_dual_support_run_exactly_5_fails(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(91, 92, 89.8, 91),
            _candle(110, 111, 109, 110),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=90.0)

        self.assertFalse(
            confluence.evaluate_confluence(candles, channels, _config("bullish", "lower", "lower"))
        )

    def test_bearish_clustered_path_exactly_4_passes(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(99, 100.2, 98, 99),
            _candle(99, 100, 98, 99),
            _candle(99, 100, 98, 99),
            _candle(99, 100.2, 98, 99),
        ]
        channels = _channels(len(candles), first_upper=100.0, second_upper=100.0)

        with patch.object(confluence, "_candidate_first_indices", return_value=[1]):
            self.assertTrue(
                confluence.evaluate_confluence(candles, channels, _config("bearish", "upper", "upper"))
            )

    def test_bearish_clustered_path_exactly_5_fails(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(99, 100.2, 98, 99),
            _candle(99, 100, 98, 99),
            _candle(99, 100, 98, 99),
            _candle(99.9, 100.0, 98, 99.9),
            _candle(90, 91, 89, 90),
        ]
        channels = _channels(len(candles), first_upper=100.09, second_upper=100.0)

        with patch.object(confluence, "_candidate_first_indices", return_value=[1]):
            self.assertFalse(
                confluence.evaluate_confluence(candles, channels, _config("bearish", "upper", "upper"))
            )

    def test_existing_role_reversal_freshness_keeps_4_valid(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(100.05, 102, 99.95, 100.05),
        ]
        channels = _channels(len(candles), first_upper=100.0, second_lower=100.0)

        self.assertTrue(
            confluence.evaluate_confluence(candles, channels, _config("role_reversal", "upper", "lower"))
        )

    def test_existing_role_reversal_freshness_rejects_5(self):
        candles = [
            _candle(99, 100, 98, 99),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(100.05, 102, 99.95, 100.05),
            _candle(100.05, 102, 100.5, 100.05),
        ]
        channels = _channels(len(candles), first_upper=100.0, second_lower=100.0)

        self.assertFalse(
            confluence.evaluate_confluence(candles, channels, _config("role_reversal", "upper", "lower"))
        )

    def test_stale_first_touch_cannot_pass_because_later_event_is_recent(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(201, 202, 200, 201),
            _candle(201, 202, 200, 201),
        ]

        self.assertFalse(
            confluence.evaluate_confluence(candles, _channels(len(candles)), _config("breakout", "upper", "upper"))
        )


if __name__ == "__main__":
    unittest.main()

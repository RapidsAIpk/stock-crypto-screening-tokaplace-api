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


def _sources(first_selection, second_selection, first_overrides=None, second_overrides=None):
    return [
        SimpleNamespace(id="first", channel_type="lrc", selection=first_selection, **(first_overrides or {})),
        SimpleNamespace(id="second", channel_type="lrc", selection=second_selection, **(second_overrides or {})),
    ]


def _config(
    confluence_type,
    first_selection,
    second_selection,
    first_overrides=None,
    second_overrides=None,
    **overrides,
):
    return SimpleNamespace(
        type=confluence_type,
        channels=["lrc", "lrc"],
        sources=_sources(first_selection, second_selection, first_overrides, second_overrides),
        liquidity_sweep=False,
        lookback_candles=overrides.pop("lookback_candles", 4),
        tolerance_pct=0.1,
        **overrides,
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

    # --------------------------------------------------------------
    # Client issue #1/#3: lookback_candles is no longer capped at 4.
    # --------------------------------------------------------------

    def test_normalized_lookback_no_longer_capped_at_4(self):
        self.assertEqual(confluence._normalized_lookback(10), 10)
        self.assertEqual(confluence._normalized_lookback(0), 1)
        self.assertEqual(confluence._normalized_lookback(-5), 1)

    def test_confluence_config_accepts_lookback_above_4(self):
        from models.filters import ConfluenceConfig

        config = ConfluenceConfig(
            type="bullish",
            sources=[
                {"channel_type": "lrc", "selection": "lower"},
                {"channel_type": "lrc", "selection": "lower"},
            ],
            lookback_candles=25,
        )
        self.assertEqual(config.lookback_candles, 25)

    def test_confluence_config_still_rejects_lookback_below_1(self):
        from pydantic import ValidationError

        from models.filters import ConfluenceConfig

        with self.assertRaises(ValidationError):
            ConfluenceConfig(
                type="bullish",
                sources=[
                    {"channel_type": "lrc", "selection": "lower"},
                    {"channel_type": "lrc", "selection": "lower"},
                ],
                lookback_candles=-1,
            )

    # --------------------------------------------------------------
    # Client issue #4: bullish confluence can require price to close
    # back near the first source's line before matching.
    # --------------------------------------------------------------

    def test_bullish_reclose_to_first_line_passes_when_close_is_near_first_line(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=100.0)

        self.assertTrue(
            confluence.evaluate_confluence(
                candles,
                channels,
                _config("bullish", "lower", "lower", reclose_to_first_line=True),
            )
        )

    def test_bullish_reclose_to_first_line_fails_when_price_stays_far_below_first_line(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(151, 152, 149.8, 151),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=150.0, second_lower=100.0)
        config = _config("bullish", "lower", "lower", reclose_to_first_line=True)

        self.assertTrue(
            confluence.evaluate_confluence(candles, channels, _config("bullish", "lower", "lower"))
        )
        self.assertFalse(confluence.evaluate_confluence(candles, channels, config))

    # --------------------------------------------------------------
    # Client issue #2: per-line sub-filters (close above/below a
    # specific line, and how many candles since that close happened).
    # --------------------------------------------------------------

    def test_source_sub_filter_close_above_within_range_passes(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=100.0)
        config = _config(
            "bullish",
            "lower",
            "lower",
            first_overrides={
                "line_relation": "close_above",
                "target_line": "lower",
                "candles_since_close_min": 1,
                "candles_since_close_max": 10,
            },
        )

        self.assertTrue(confluence.evaluate_confluence(candles, channels, config))

    def test_source_sub_filter_candles_since_close_out_of_range_fails(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=100.0)
        config = _config(
            "bullish",
            "lower",
            "lower",
            first_overrides={
                "line_relation": "close_above",
                "target_line": "lower",
                "candles_since_close_min": 1,
                "candles_since_close_max": 1,
            },
        )

        self.assertFalse(confluence.evaluate_confluence(candles, channels, config))

    def test_source_sub_filter_wrong_relation_fails(self):
        candles = [
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 100.5, 101),
            _candle(101, 102, 99.8, 101),
        ]
        channels = _channels(len(candles), first_lower=100.0, second_lower=100.0)
        config = _config(
            "bullish",
            "lower",
            "lower",
            first_overrides={"line_relation": "close_below", "target_line": "lower"},
        )

        self.assertFalse(confluence.evaluate_confluence(candles, channels, config))

    # --------------------------------------------------------------
    # IBTA bug reproduction: a source's close_above/close_below
    # sub-filter must be checked against the exact candle that source
    # matched on, not against an unrelated later ("latest") candle.
    # --------------------------------------------------------------

    def test_sub_filter_does_not_borrow_close_above_from_a_later_unrelated_candle(self):
        # Bearish "stacked_resistance": Source 1 (first) rejects a rising
        # line at candle 1; Source 2 (second) rejects a flat line at
        # candle 3 (close 97, NOT above its own line of 100). Candle 4
        # (the latest candle) is an unrelated later candle whose close
        # (102) happens to sit above Source 2's line - this must not be
        # allowed to satisfy a close_above sub-filter configured on
        # Source 2, since Source 2's actual matched event (candle 3)
        # never closed above its line.
        candles = [
            _candle(79, 75, 76, 79),
            _candle(84, 85.3, 83, 84),
            _candle(90, 91, 89, 90),
            _candle(96, 100.2, 93, 97),
            _candle(100, 103, 99, 102),
        ]
        channels = {
            "first": {
                "channel_type": "lrc",
                "channel": {"upper": [80.0, 85.0, 90.0, 95.0, 105.0], "lower": [70.0] * 5},
            },
            "second": {
                "channel_type": "lrc",
                "channel": {"upper": [100.0] * 5, "lower": [85.0] * 5},
            },
        }

        base_config = _config(
            "bearish",
            "upper",
            "upper",
        )
        # Sanity check: without the sub-filter, the underlying scenario
        # genuinely matches (first_index=1, second_index=3) - proving the
        # sub-filter, not the core matcher, is what must reject this case.
        evidence = {}
        self.assertTrue(
            confluence.evaluate_confluence(candles, channels, base_config, evidence=evidence)
        )
        self.assertEqual(evidence["scenario"], "stacked_resistance")
        matched_by_id = {m["source_id"]: m["candle_index"] for m in evidence["source_matches"]}
        self.assertEqual(matched_by_id["second"], 3)

        config_with_subfilter = _config(
            "bearish",
            "upper",
            "upper",
            second_overrides={"line_relation": "close_above"},
        )

        self.assertFalse(
            confluence.evaluate_confluence(candles, channels, config_with_subfilter)
        )

    def test_sub_filter_passes_when_close_above_holds_on_the_actual_matched_candle(self):
        # Positive control: a breakout scenario where Source 2's matched
        # candle (the one that broke resistance) genuinely closes above
        # its own line at that same candle - the intended timing - so the
        # close_above sub-filter must still allow the match through.
        candles = [
            _candle(99, 100, 98, 99),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100, 101),
            _candle(101, 102, 100, 101),
            _candle(201, 202, 200, 201),
        ]
        channels = _channels(len(candles), first_upper=100.0, second_upper=200.0)
        config = _config(
            "breakout",
            "upper",
            "upper",
            second_overrides={"line_relation": "close_above"},
        )

        evidence = {}
        self.assertTrue(
            confluence.evaluate_confluence(candles, channels, config, evidence=evidence)
        )
        matched_by_id = {m["source_id"]: m["candle_index"] for m in evidence["source_matches"]}
        # The matched candle (index 4) is also the latest candle here, so
        # this additionally proves the fix does not regress the common
        # case where the matched event and the latest candle coincide.
        self.assertEqual(matched_by_id["second"], 4)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from types import SimpleNamespace


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from services import ema, indicators, screener  # noqa: E402


class IndicatorDefaultTests(unittest.TestCase):
    def test_required_candles_uses_ema_default_length_9(self):
        indicator = SimpleNamespace(name="ema", config={})
        self.assertEqual(screener.required_candles_for_indicators([indicator]), 11)

    def test_required_candles_uses_ema_periods_and_range_budget(self):
        indicator = SimpleNamespace(
            name="ema",
            config={
                "simple_ema": True,
                "periods": [9, 20],
                "conditions": {
                    "touch_from_above": {
                        "enabled": True,
                        "candles_since_max": 5,
                    },
                },
            },
        )
        self.assertEqual(screener.required_candles_for_indicators([indicator]), 27)

    def test_required_candles_uses_tradingview_standard_ema_preset(self):
        indicator = SimpleNamespace(
            name="ema",
            config={
                "simple_ema": True,
                "title": "EMA 20/50/100/200",
                "conditions": {
                    "touch_from_above": {
                        "enabled": True,
                        "candles_since_max": 5,
                    },
                },
            },
        )
        self.assertEqual(screener.required_candles_for_indicators([indicator]), 207)

    def test_tradingview_standard_ema_preset_normalizes_periods(self):
        self.assertEqual(
            ema.normalize_ema_periods({"title": "EMA 20/50/100/200"}),
            [20, 50, 100, 200],
        )
        self.assertEqual(
            ema.normalize_ema_periods({
                "title": "EMA 20/50/100/200",
                "periods": [9],
            }),
            [9],
        )

    def test_required_candles_uses_trend_pivot_history_budget(self):
        indicator = SimpleNamespace(name="trend", config={})
        self.assertEqual(screener.required_candles_for_indicators([indicator]), 500)

    def test_ema_helpers_use_default_length_9(self):
        candles = [{"close": float(price)} for price in range(1, 21)]

        sticker = ema.build_ema_sticker(candles, {"rule": "above"})
        self.assertTrue(sticker.startswith("EMA (9) |"))

    def test_ema_snapshot_uses_default_length_9(self):
        data = [
            {
                "symbol": "AAPL",
                "price": 110.0,
                "indicator_snapshot": {
                    "ema": [100.0],
                },
            }
        ]
        selected = [SimpleNamespace(name="ema", config={"rule": "above"})]

        result = indicators.apply_indicator_snapshots(data, selected)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["stickers"][0].startswith("EMA (9) |"))


if __name__ == "__main__":
    unittest.main()

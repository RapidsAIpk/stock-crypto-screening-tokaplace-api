# services/macd.py

import numpy as np
from services.ema import compute_ema
from services.utils import build_indicator_sticker, format_decimal


# =========================================================
# MACD
# =========================================================

def compute_macd(candles, fast=12, slow=26, signal=9):

    closes = np.array([c["close"] for c in candles])

    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)

    macd = ema_fast - ema_slow

    signal_line = compute_ema(macd, signal)

    histogram = macd - signal_line

    return {
        "macd": macd,
        "signal": signal_line,
        "hist": histogram
    }


# =========================================================
# RULES
# =========================================================

def evaluate_macd_rules(macd_data, config):

    macd = macd_data["macd"]
    signal = macd_data["signal"]

    rule = config.get("rule")

    if len(macd) < 2 or len(signal) < 2:
        return False

    m1, m2 = macd[-2], macd[-1]
    s1, s2 = signal[-2], signal[-1]
    tolerance = abs(float(config.get("tolerance_pct", 0) or 0)) / 100.0

    if rule == "bullish_cross":
        return m1 <= (s1 + tolerance) and m2 >= (s2 - tolerance)

    if rule == "bearish_cross":
        return m1 >= (s1 - tolerance) and m2 <= (s2 + tolerance)

    if rule == "above_zero":
        return m2 >= -tolerance

    if rule == "below_zero":
        return m2 <= tolerance

    return False


# =========================================================
# STICKER
# =========================================================

def build_macd_sticker(macd_data, config):
    rule = config.get("rule")
    macd_value = float(macd_data["macd"][-1]) if len(macd_data["macd"]) else 0.0
    signal_value = float(macd_data["signal"][-1]) if len(macd_data["signal"]) else 0.0
    histogram_value = float(macd_data["hist"][-1]) if len(macd_data["hist"]) else 0.0

    if rule in {"bullish_cross", "bearish_cross"}:
        condition = (
            f"MACD {format_decimal(macd_value, 2, signed=True)} vs signal "
            f"{format_decimal(signal_value, 2, signed=True)}"
        )
    elif rule in {"above_zero", "below_zero"}:
        condition = f"MACD {format_decimal(macd_value, 2, signed=True)}; histogram {format_decimal(histogram_value, 2, signed=True)}"
    else:
        condition = "MACD rule match"

    return build_indicator_sticker(
        "MACD",
        condition,
        {"window": 1, "confirmation": False},
        window=1,
        decision=_macd_decision(rule),
    )


def _macd_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "bullish_cross":
        return "Bullish Momentum Shift"
    if normalized == "bearish_cross":
        return "Bearish Momentum Shift"
    if normalized == "above_zero":
        return "Bullish Momentum Regime"
    if normalized == "below_zero":
        return "Bearish Momentum Regime"
    return "MACD Match"

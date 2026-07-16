# services/ema.py

import numpy as np
from services.utils import build_indicator_sticker, format_price_value


# =========================================================
# EMA
# =========================================================

def compute_ema(series, length):

    series = np.asarray(series)

    ema = np.zeros_like(series)

    multiplier = 2 / (length + 1)

    ema[0] = series[0]

    for i in range(1, len(series)):
        ema[i] = (series[i] - ema[i-1]) * multiplier + ema[i-1]

    return ema


def price_matches_ema_rule(price, ema_value, rule, tolerance_pct=0):

    tolerance_pct = max(0.0, float(tolerance_pct or 0))
    tolerance = abs(float(ema_value)) * (tolerance_pct / 100.0)

    if rule == "above":
        return float(price) >= (float(ema_value) - tolerance)

    if rule == "below":
        return float(price) <= (float(ema_value) + tolerance)

    if rule == "touch":
        base_tolerance = abs(float(ema_value)) * 0.002
        return abs(float(price) - float(ema_value)) <= max(base_tolerance, tolerance)

    return False


# =========================================================
# RULES
# =========================================================

def evaluate_ema_rules(candles, config):

    closes = np.array([c["close"] for c in candles])

    length = config.get("length", 9)
    rule = config.get("rule")

    ema = compute_ema(closes, length)

    price = closes[-1]
    ema_val = ema[-1]
    tolerance_pct = max(0.0, float(config.get("tolerance_pct", 0) or 0))
    return price_matches_ema_rule(price, ema_val, rule, tolerance_pct=tolerance_pct)


def build_moving_average_sticker(label, length, rule, price, ma_value):
    condition = f"Price {format_price_value(price)} vs {label} @ {format_price_value(ma_value)}"
    return build_indicator_sticker(
        label,
        condition,
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision=_moving_average_decision(rule),
    )


def build_ema_sticker(candles, config):
    length = config.get("length", 9)
    rule = config.get("rule")
    closes = np.array([c["close"] for c in candles], dtype=float)
    ema_series = compute_ema(closes, length)
    price = float(closes[-1])
    ema_value = float(ema_series[-1])
    return build_moving_average_sticker("EMA", length, rule, price, ema_value)


def _moving_average_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "above":
        return "Bullish Trend Filter"
    if normalized == "below":
        return "Bearish Trend Filter"
    if normalized == "touch":
        return "Retest Watch"
    return "Moving Average Match"

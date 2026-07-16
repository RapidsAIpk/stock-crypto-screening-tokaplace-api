# services/rsi.py

import numpy as np
from services.utils import build_indicator_sticker, confirm_if_needed, format_decimal, series_direction_matches


# =========================================================
# RSI (WILDER STANDARD)
# =========================================================

def compute_rsi_series(candles, length=14):

    n = len(candles)

    if n < length + 1:
        return None

    closes = np.array([c["close"] for c in candles])

    deltas = np.diff(closes)

    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:length])
    avg_loss = np.mean(losses[:length])

    rsi_values = []

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100 - (100 / (1 + rs)))

    for i in range(length, len(deltas)):

        gain = gains[i]
        loss = losses[i]

        avg_gain = ((avg_gain * (length - 1)) + gain) / length
        avg_loss = ((avg_loss * (length - 1)) + loss) / length

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        rsi_values.append(rsi)

    return np.array(rsi_values)


# =========================================================
# RULE EVALUATION
# =========================================================

def evaluate_rsi_rules(
    rsi_series,
    candles,
    config
):

    window = int(config.get("window", 1) or 1)
    location = config.get("location")
    direction = config.get("direction")
    tolerance_pct = float(config.get("tolerance_pct", 0) or 0)

    if window <= 0:
        window = 1

    if len(rsi_series) < window:
        return False

    start = len(rsi_series) - window
    candle_offset = max(0, len(candles) - len(rsi_series))

    for idx in range(start, len(rsi_series)):
        if not _rsi_location_matches(rsi_series, idx, location, tolerance_pct):
            continue

        if not _rsi_direction_matches(rsi_series, idx, direction):
            continue

        if config.get("confirmation"):
            candle_idx = idx + candle_offset
            if candle_idx >= len(candles):
                continue

            if not confirm_if_needed(candles, candle_idx, config):
                continue

        return True

    return False


def _rsi_location_matches(rsi_series, idx, location, tolerance_pct=0):
    if not location:
        return True

    value = float(rsi_series[idx])
    tolerance = max(0.0, float(tolerance_pct))

    if location == "oversold":
        return value <= (30 + tolerance)
    if location == "neutral":
        return (30 - tolerance) <= value <= (70 + tolerance)
    if location == "overbought":
        return value >= (70 - tolerance)

    return False


def _rsi_direction_matches(rsi_series, idx, direction):
    if direction not in {None, "turning_up", "turning_down"}:
        return False
    return series_direction_matches(rsi_series, idx, direction)


# =========================================================
# STICKER
# =========================================================

def build_rsi_sticker(
    rsi_series,
    config
):
    location = config.get("location")
    direction = config.get("direction")
    idx = _latest_matching_rsi_index(rsi_series, config)
    latest_value = float(rsi_series[idx]) if len(rsi_series) else 0.0
    location_text = location.replace("_", " ").title() if location else None
    direction_text = direction.replace("_", " ").title() if direction else None
    condition_parts = [f"RSI {format_decimal(latest_value, 1)}"]

    if location_text:
        condition_parts.append(f"in {location_text.lower()}")

    if direction_text:
        condition_parts.append(direction_text.lower())

    condition = ", ".join(condition_parts[:2])
    if len(condition_parts) > 2:
        condition = f"{condition}, {condition_parts[2]}"

    return build_indicator_sticker(
        "RSI",
        condition or "RSI match",
        config,
        length=config.get("length", 14),
        decision=_rsi_decision(location, direction),
    )


def _latest_matching_rsi_index(rsi_series, config):
    if len(rsi_series) == 0:
        return 0

    window = max(1, int(config.get("window", 1) or 1))
    start = max(0, len(rsi_series) - window)
    latest_match = None

    for idx in range(start, len(rsi_series)):
        if not _rsi_location_matches(rsi_series, idx, config.get("location"), float(config.get("tolerance_pct", 0) or 0)):
            continue
        if not _rsi_direction_matches(rsi_series, idx, config.get("direction")):
            continue
        latest_match = idx

    return latest_match if latest_match is not None else len(rsi_series) - 1


def _rsi_decision(location, direction):
    normalized_location = str(location or "").strip().lower()
    normalized_direction = str(direction or "").strip().lower()

    if normalized_location == "oversold":
        if normalized_direction == "turning_up":
            return "Bullish Reversal"
        if normalized_direction in {"rising", "crossed_up"}:
            return "Bullish Recovery"
        if normalized_direction == "turning_down":
            return "Oversold Weakness"
        return "Oversold Watch"

    if normalized_location == "overbought":
        if normalized_direction == "turning_down":
            return "Bearish Reversal"
        if normalized_direction in {"falling", "crossed_down"}:
            return "Bearish Follow-Through"
        if normalized_direction == "turning_up":
            return "Overbought Strength"
        return "Overbought Watch"

    if normalized_direction in {"rising", "turning_up", "crossed_up"}:
        return "Bullish Bias"
    if normalized_direction in {"falling", "turning_down", "crossed_down"}:
        return "Bearish Bias"
    return "RSI Filter Match"

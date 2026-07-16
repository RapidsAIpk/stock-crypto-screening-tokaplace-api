# services/aroon_oscillator.py
import numpy as np
from services.utils import build_indicator_sticker, confirm_if_needed, format_decimal, series_direction_matches


# -------------------------------------------------
# AROON OSCILLATOR
# -------------------------------------------------

def compute_aroon_oscillator(candles, length=14):

    n = len(candles)
    lookback = length + 1

    if n < lookback:
        return None

    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])

    oscillator_values = []

    for i in range(length, n):

        high_window = highs[i-length:i+1]
        low_window = lows[i-length:i+1]

        idx_high = np.argmax(high_window)
        idx_low = np.argmin(low_window)

        periods_since_high = length - idx_high
        periods_since_low = length - idx_low

        aroon_up = ((length - periods_since_high) / length) * 100
        aroon_down = ((length - periods_since_low) / length) * 100

        oscillator = aroon_up - aroon_down

        oscillator_values.append(oscillator)

    return np.array(oscillator_values)


# -------------------------------------------------
# RULE EVALUATION
# -------------------------------------------------

def evaluate_aroon_rules(
    aroon_series,
    candles,
    config
):

    window = int(config.get("window", 1) or 1)
    level_rule = config.get("level")
    direction_rule = config.get("direction")
    tolerance_pct = float(config.get("tolerance_pct", 0) or 0)
    extreme_level = _normalize_extreme_level(config)

    if window <= 0:
        window = 1

    if len(aroon_series) < window:
        return False

    if not level_rule:
        return False

    start = len(aroon_series) - window
    candle_offset = max(0, len(candles) - len(aroon_series))

    for idx in range(start, len(aroon_series)):
        if not _aroon_level_matches(aroon_series, idx, level_rule, tolerance_pct):
            continue

        if not _aroon_direction_matches(aroon_series, idx, direction_rule, extreme_level):
            continue

        if config.get("confirmation"):
            candle_idx = idx + candle_offset
            if candle_idx >= len(candles):
                continue

            if not confirm_if_needed(candles, candle_idx, config):
                continue

        return True

    return False


def _aroon_level_matches(aroon_series, idx, level_rule, tolerance_pct=0):
    value = float(aroon_series[idx])
    tolerance = max(0.0, float(tolerance_pct))

    if level_rule == "above_50":
        return value >= (50 - tolerance)
    if level_rule == "between_50_0":
        return (-tolerance) < value <= (50 + tolerance)
    if level_rule == "near_0":
        return (-10 - tolerance) <= value <= (10 + tolerance)
    if level_rule == "between_0_-50":
        return (-50 - tolerance) <= value < tolerance
    if level_rule == "below_-50":
        return value <= (-50 + tolerance)

    return False


def _normalize_extreme_level(config):
    try:
        return abs(float(config.get("extreme_level", 70) or 70))
    except (TypeError, ValueError):
        return 70.0


def _aroon_direction_matches(aroon_series, idx, direction_rule, extreme_level=70):
    if not series_direction_matches(aroon_series, idx, direction_rule):
        return False

    if direction_rule == "turning_up":
        return float(aroon_series[idx - 1]) <= -extreme_level

    if direction_rule == "turning_down":
        return float(aroon_series[idx - 1]) >= extreme_level

    return True


# -------------------------------------------------
# STICKER
# -------------------------------------------------

def build_aroon_sticker(
    aroon_series,
    candles,
    config
):
    level = config.get("level")
    direction = config.get("direction")
    idx = _latest_matching_aroon_index(aroon_series, config)
    latest_value = float(aroon_series[idx]) if len(aroon_series) else 0.0

    level_map = {
        "above_50": "Above +50",
        "between_50_0": "Between +50 and 0",
        "near_0": "Near 0",
        "between_0_-50": "Between 0 and -50",
        "below_-50": "Below −50",
    }

    condition_parts = [f"Oscillator {format_decimal(latest_value, 1, signed=True)}"]
    if level:
        condition_parts.append(level_map.get(level, level).lower())
    if direction:
        condition_parts.append(direction.replace("_", " ").lower())

    return build_indicator_sticker(
        "Aroon",
        "; ".join([condition_parts[0], ", ".join(condition_parts[1:])]) if len(condition_parts) > 1 else condition_parts[0],
        config,
        length=config.get("length", 14),
        decision=_aroon_decision(level, direction),
    )


def _latest_matching_aroon_index(aroon_series, config):
    if len(aroon_series) == 0:
        return 0

    window = max(1, int(config.get("window", 1) or 1))
    start = max(0, len(aroon_series) - window)
    latest_match = None
    extreme_level = _normalize_extreme_level(config)

    for idx in range(start, len(aroon_series)):
        if not _aroon_level_matches(aroon_series, idx, config.get("level"), float(config.get("tolerance_pct", 0) or 0)):
            continue
        if not _aroon_direction_matches(aroon_series, idx, config.get("direction"), extreme_level):
            continue
        latest_match = idx

    return latest_match if latest_match is not None else len(aroon_series) - 1


def _aroon_decision(level, direction):
    normalized_level = str(level or "").strip().lower()
    normalized_direction = str(direction or "").strip().lower()

    if normalized_level == "above_50":
        return "Bullish Trend" if normalized_direction in {"rising", "turning_up"} else "Bullish Strength"
    if normalized_level == "below_-50":
        return "Bearish Trend" if normalized_direction in {"falling", "turning_down"} else "Bearish Strength"
    if normalized_level == "near_0":
        return "Trend Transition"
    if normalized_level == "between_50_0":
        return "Bullish Pullback" if normalized_direction in {"falling", "turning_down"} else "Bullish Lean"
    if normalized_level == "between_0_-50":
        return "Bearish Pullback" if normalized_direction in {"rising", "turning_up"} else "Bearish Lean"
    return "Aroon Match"

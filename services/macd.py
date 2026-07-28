# services/macd.py

import numpy as np
from services.pine_math import pine_ema, pine_sma
from services.utils import build_indicator_sticker, format_decimal


# =========================================================
# MACD
# =========================================================

def compute_macd(candles, fast=12, slow=26, signal=9, source="close"):

    candles = _completed_candles(candles)
    values = _source_series(candles, source)
    fast = int(fast)
    slow = int(slow)
    signal = int(signal)

    if len(values) == 0 or min(fast, slow, signal) <= 0:
        empty = np.array([], dtype=float)
        return {
            "macd": empty,
            "signal": empty,
            "hist": empty,
            "histogram": empty,
            "histA_IsUp": np.array([], dtype=bool),
            "histA_IsDown": np.array([], dtype=bool),
            "histB_IsDown": np.array([], dtype=bool),
            "histB_IsUp": np.array([], dtype=bool),
            "macd_IsAbove": np.array([], dtype=bool),
            "macd_IsBelow": np.array([], dtype=bool),
            "cross": np.array([], dtype=bool),
            "source": str(source or "close").strip().lower(),
            "fast": fast,
            "slow": slow,
            "signal_length": signal,
        }

    fast_ma = pine_ema(values, fast)
    slow_ma = pine_ema(values, slow)

    macd = fast_ma - slow_ma

    signal_line = pine_sma(macd, signal)
    histogram = macd - signal_line

    histA_is_up = _compare_histogram(histogram, greater=True, above_zero=True)
    histA_is_down = _compare_histogram(histogram, greater=False, above_zero=True)
    histB_is_down = _compare_histogram(histogram, greater=False, above_zero=False)
    histB_is_up = _compare_histogram(histogram, greater=True, above_zero=False)
    macd_is_above = np.isfinite(macd) & np.isfinite(signal_line) & (macd >= signal_line)
    macd_is_below = np.isfinite(macd) & np.isfinite(signal_line) & (macd < signal_line)
    cross = _cross(macd, signal_line)

    return {
        "macd": macd,
        "signal": signal_line,
        "hist": histogram,
        "histogram": histogram,
        "histA_IsUp": histA_is_up,
        "histA_IsDown": histA_is_down,
        "histB_IsDown": histB_is_down,
        "histB_IsUp": histB_is_up,
        "macd_IsAbove": macd_is_above,
        "macd_IsBelow": macd_is_below,
        "cross": cross,
        "source": str(source or "close").strip().lower(),
        "fast": fast,
        "slow": slow,
        "signal_length": signal,
    }


# =========================================================
# RULES
# =========================================================

def evaluate_macd_rules(macd_data, config):

    macd = macd_data["macd"]
    signal = macd_data["signal"]

    rule = config.get("rule")
    rule = str(rule or "").strip().lower()

    if len(macd) == 0:
        return False

    tolerance = abs(float(config.get("tolerance_pct", 0) or 0))

    if rule in {"above_zero", "below_zero", "histogram_above_zero", "histogram_below_zero"}:
        series = macd_data["hist"] if rule.startswith("histogram") else macd
        index = _last_finite_index(series)
        if index is None:
            return False
        value = float(series[index])
        amount = abs(value) * tolerance / 100.0

        if rule in {"above_zero", "histogram_above_zero"}:
            return value >= -amount

        if rule in {"below_zero", "histogram_below_zero"}:
            return value <= amount

    current = _last_finite_pair_index(macd, signal)
    previous = _previous_finite_pair_index(macd, signal, current)
    if current is None or previous is None:
        return False

    m1, m2 = float(macd[previous]), float(macd[current])
    s1, s2 = float(signal[previous]), float(signal[current])
    previous_amount = max(abs(m1), abs(s1)) * tolerance / 100.0
    current_amount = max(abs(m2), abs(s2)) * tolerance / 100.0

    if rule == "bullish_cross":
        return m1 <= (s1 + previous_amount) and m2 > (s2 - current_amount)

    if rule == "bearish_cross":
        return m1 >= (s1 - previous_amount) and m2 < (s2 + current_amount)

    if rule in {"macd_above_signal", "above_signal"}:
        return m2 >= s2 - current_amount

    if rule in {"macd_below_signal", "below_signal"}:
        return m2 <= s2 + current_amount

    return False


# =========================================================
# STICKER
# =========================================================

def build_macd_sticker(macd_data, config):
    rule = config.get("rule")
    macd_index = _last_finite_index(macd_data["macd"])
    signal_index = _last_finite_index(macd_data["signal"])
    hist_index = _last_finite_index(macd_data["hist"])
    macd_value = float(macd_data["macd"][macd_index]) if macd_index is not None else 0.0
    signal_value = float(macd_data["signal"][signal_index]) if signal_index is not None else 0.0
    histogram_value = float(macd_data["hist"][hist_index]) if hist_index is not None else 0.0

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
    if normalized in {"above_signal", "macd_above_signal"}:
        return "MACD Above Signal"
    if normalized in {"below_signal", "macd_below_signal"}:
        return "MACD Below Signal"
    if normalized == "histogram_above_zero":
        return "Positive Histogram"
    if normalized == "histogram_below_zero":
        return "Negative Histogram"
    return "MACD Match"


def _source_series(candles, source):
    normalized = str(source or "close").strip().lower()
    values = np.zeros(len(candles), dtype=float)

    for index, candle in enumerate(candles):
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        if normalized == "open":
            values[index] = open_
        elif normalized == "high":
            values[index] = high
        elif normalized == "low":
            values[index] = low
        elif normalized == "hl2":
            values[index] = (high + low) / 2.0
        elif normalized == "hlc3":
            values[index] = (high + low + close) / 3.0
        elif normalized == "ohlc4":
            values[index] = (open_ + high + low + close) / 4.0
        else:
            values[index] = close

    return values


def _completed_candles(candles):
    candles = list(candles or [])
    if not candles:
        return candles

    latest = candles[-1]
    if not isinstance(latest, dict):
        return candles

    if (
        latest.get("is_closed") is False
        or latest.get("is_complete") is False
        or latest.get("complete") is False
        or latest.get("closed") is False
        or latest.get("is_live") is True
    ):
        return candles[:-1]

    return candles


def _compare_histogram(histogram, greater, above_zero):
    output = np.zeros(len(histogram), dtype=bool)
    for index in range(1, len(histogram)):
        current = histogram[index]
        previous = histogram[index - 1]
        if not np.isfinite(current) or not np.isfinite(previous):
            continue
        direction_ok = current > previous if greater else current < previous
        zero_ok = current > 0 if above_zero else current <= 0
        output[index] = bool(direction_ok and zero_ok)
    return output


def _cross(left, right):
    output = np.zeros(len(left), dtype=bool)
    for index in range(1, min(len(left), len(right))):
        if not all(np.isfinite(value) for value in (left[index - 1], right[index - 1], left[index], right[index])):
            continue
        output[index] = bool(
            (left[index - 1] <= right[index - 1] and left[index] >= right[index])
            or (left[index - 1] >= right[index - 1] and left[index] <= right[index])
        )
    return output


def _last_finite_index(series):
    array = np.asarray(series, dtype=float)
    indexes = np.flatnonzero(np.isfinite(array))
    return int(indexes[-1]) if indexes.size else None


def _last_finite_pair_index(left, right):
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    indexes = np.flatnonzero(np.isfinite(left) & np.isfinite(right))
    return int(indexes[-1]) if indexes.size else None


def _previous_finite_pair_index(left, right, current):
    if current is None or current <= 0:
        return None
    left = np.asarray(left, dtype=float)
    right = np.asarray(right, dtype=float)
    indexes = np.flatnonzero(np.isfinite(left[:current]) & np.isfinite(right[:current]))
    return int(indexes[-1]) if indexes.size else None

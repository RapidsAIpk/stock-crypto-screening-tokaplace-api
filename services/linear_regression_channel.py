# services/linear_regression_channel.py
"""LonesomeTheBlue Linear Regression Channel (LRC) indicator."""

import numpy as np

from services.pine_math import lonesomeblue_linreg_channel


def compute_lrc_channel(
    candles,
    length=100,
    upper_dev=2.0,
    lower_dev=2.0,
    source="close",
):
    if len(candles) < length:
        return None

    values = _source_series(candles, source)
    channel = lonesomeblue_linreg_channel(
        values,
        length,
        upper_dev=float(upper_dev),
        lower_dev=float(lower_dev),
    )

    middle = channel["middle"]
    upper = channel["upper"]
    lower = channel["lower"]

    if not np.any(np.isfinite(middle)):
        return None

    try:
        r = np.corrcoef(np.arange(length), values[-length:])[0, 1]
    except Exception:
        r = None

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "r": r,
        "length": length,
        "source": str(source or "close").strip().lower(),
        "slope": channel.get("slope"),
        "deviation": channel.get("deviation"),
        "intercept": channel.get("intercept"),
        "end": channel.get("end"),
    }


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


def passes_r_filter(r_value, config):
    if r_value is None:
        return False

    preset = str(config.get("r_filter", "") or "").strip().lower()
    strength = abs(float(r_value))

    if preset == "ignore":
        return True

    if preset == "strong":
        return strength >= 0.70

    if preset == "balanced":
        return 0.50 <= strength <= 0.80

    mode = config.get("r_mode", "ignore")
    r_min = config.get("r_min")
    r_max = config.get("r_max")

    if mode == "ignore":
        if r_min is not None and r_max is not None:
            mode = "range"
        elif r_min is not None:
            mode = "min"
        elif r_max is not None:
            mode = "max"

    if mode == "ignore":
        return True

    if mode == "min":
        threshold = float(r_min if r_min is not None else 0)
        return strength >= threshold

    if mode == "range":
        if r_min is None or r_max is None:
            return False

        return float(r_min) <= strength <= float(r_max)

    if mode == "max":
        if r_max is None:
            return False
        return strength <= float(r_max)

    return True

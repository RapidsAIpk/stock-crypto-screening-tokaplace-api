from __future__ import annotations

from typing import Any

import numpy as np
import talib

from .talib_engine import arrays
from services.pine_math import (
    dw_channel_series,
    jwammo12_channel,
    pine_daily_volatility,
    pine_ema,
    pine_range_volatility,
    pine_relative_volume_ratio,
    pine_sma,
    rolling_linreg,
)


def _rolling_regression(values: np.ndarray, length: int) -> np.ndarray:
    output = np.full(len(values), np.nan)
    x = np.arange(length, dtype=float)
    for index in range(length - 1, len(values)):
        slope, intercept = np.polyfit(x, values[index - length + 1:index + 1], 1)
        output[index] = intercept + slope * (length - 1)
    return output


def wavetrend(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray]:
    values = arrays(candles)
    source = (values["high"] + values["low"] + values["close"]) / 3.0
    channel = int(config["channel_length"])
    average = int(config["average_length"])
    signal = int(config["signal_length"])
    esa = talib.EMA(source, timeperiod=channel)
    deviation = talib.EMA(np.abs(source - esa), timeperiod=channel)
    ci = np.divide(source - esa, 0.015 * deviation, out=np.full_like(source, np.nan), where=deviation > 0)
    wt1 = talib.EMA(ci, timeperiod=average)
    wt2 = talib.SMA(wt1, timeperiod=signal)
    return {"wt1": wt1, "wt2": wt2}


def linear_regression_candles(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray]:
    values = arrays(candles)
    lr_length = int(config["lr_length"])
    signal_smoothing = int(config["signal_smoothing"])
    lin_reg = bool(config.get("lin_reg", True))
    bopen = rolling_linreg(values["open"], lr_length, 0) if lin_reg else values["open"]
    bhigh = rolling_linreg(values["high"], lr_length, 0) if lin_reg else values["high"]
    blow = rolling_linreg(values["low"], lr_length, 0) if lin_reg else values["low"]
    bclose = rolling_linreg(values["close"], lr_length, 0) if lin_reg else values["close"]
    sma_signal = bool(config.get("sma_signal", True))
    line = pine_sma(bclose, signal_smoothing) if sma_signal else pine_ema(bclose, signal_smoothing)
    return {
        "line": line,
        "bopen": bopen,
        "bhigh": bhigh,
        "blow": blow,
        "bclose": bclose,
    }


def lrc(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray | float]:
    close = arrays(candles)["close"]
    length = int(config["length"])
    if len(close) < length:
        return {"middle": np.array([]), "upper": np.array([]), "lower": np.array([]), "r": np.nan}
    channel = jwammo12_channel(close, length, float(config.get("upper_dev", 2.0)))
    middle = channel["middle"][-length:]
    upper = channel["upper"][-length:]
    lower = channel["lower"][-length:]
    try:
        r = float(np.corrcoef(np.arange(length), close[-length:])[0, 1])
    except Exception:
        r = np.nan
    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "r": r,
    }


def regression_channel(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray]:
    values = arrays(candles)
    length = int(config["length"])
    if len(values["close"]) < length:
        return {"middle": np.array([]), "upper": np.array([]), "lower": np.array([])}
    step = int(config.get("interval_step", 1)) if config.get("window_type", "continuous") == "interval" else 1
    x = np.arange(0, length, step, dtype=float)
    close = values["close"][-length:][::step]
    high = values["high"][-length:][::step]
    low = values["low"][-length:][::step]
    slope, intercept = np.polyfit(x, close, 1)
    sampled_middle = intercept + slope * x
    width = max(float(np.max(high - sampled_middle)), float(np.max(sampled_middle - low))) * float(config["width_coeff"])
    full_x = np.arange(length, dtype=float)
    middle = intercept + slope * full_x
    return {"middle": middle, "upper": middle + width, "lower": middle - width}


def trend_channel(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray]:
    values = arrays(candles)
    length = int(config["length"])
    if len(candles) < length:
        return {"top_line": np.array([]), "middle_line": np.array([]), "bottom_line": np.array([])}
    highs = values["high"][-length:]
    lows = values["low"][-length:]
    x = np.arange(length, dtype=float)
    top_slope, top_intercept = np.polyfit(x, highs, 1)
    bottom_slope, bottom_intercept = np.polyfit(x, lows, 1)
    top = top_intercept + top_slope * x
    bottom = bottom_intercept + bottom_slope * x
    return {"top_line": top, "middle_line": (top + bottom) / 2, "bottom_line": bottom}


def volatility(candles: list[dict[str, Any]], config: dict[str, Any]) -> float | None:
    length = int(config["length"])
    mode = str(config.get("mode", "range_avg") or "range_avg").strip().lower()
    if len(candles) < max(2, length):
        return None
    if mode == "daily":
        latest = dict(candles[-1])
        latest["previous_close"] = float(candles[-2]["close"])
        value = pine_daily_volatility(latest)
    elif mode == "returns_std":
        close = arrays(candles)["close"]
        previous = close[-length - 1:-1]
        current = close[-length:]
        returns = np.divide(current - previous, previous, out=np.zeros_like(current), where=previous != 0)
        value = float(np.std(returns) * 100)
    else:
        value = pine_range_volatility(candles, length)
    return None if value is None or not np.isfinite(value) else float(value)

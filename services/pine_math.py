# services/pine_math.py
"""TradingView Pine Script math primitives shared across indicator services."""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np

NAN = float("nan")


def as_float_array(values: Iterable[float]) -> np.ndarray:
    return np.asarray(list(values), dtype=float)


def pine_ema(values: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    multiplier = 2.0 / (length + 1.0)
    output[0] = values[0]
    for index in range(1, len(values)):
        previous = output[index - 1]
        if not np.isfinite(previous):
            previous = values[index]
        output[index] = (values[index] - previous) * multiplier + previous
    return output


def pine_sma(values: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.mean(window))
    return output


def pine_rma(values: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    for index in range(len(values)):
        if index < length - 1:
            window = values[: index + 1]
            if np.all(np.isfinite(window)):
                output[index] = float(np.mean(window))
            continue
        if index == length - 1:
            output[index] = float(np.mean(values[:length]))
            continue
        previous = output[index - 1]
        if not np.isfinite(previous):
            previous = values[index]
        output[index] = (previous * (length - 1) + values[index]) / length
    return output


def pine_lwma(values: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    weights = np.arange(length, 0, -1, dtype=float)
    weight_sum = float(np.sum(weights))
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.dot(window, weights) / weight_sum)
    return output


def pine_alma(values: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    m = 0.85 * (length - 1)
    s = length / 6.0
    offsets = np.arange(length, dtype=float)
    weights = np.exp(-np.power(offsets - m, 2) / (2.0 * pow(s, 2)))
    weight_sum = float(np.sum(weights))

    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1][::-1]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.dot(window, weights) / weight_sum)
    return output


def pine_vwma(values: np.ndarray, volumes: np.ndarray, length: int) -> np.ndarray:
    values = as_float_array(values)
    volumes = as_float_array(volumes)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) == 0 or length <= 0:
        return output

    safe_volumes = np.where(np.isfinite(volumes) & (volumes > 0), volumes, 0.0)
    for index in range(length - 1, len(values)):
        value_window = values[index - length + 1 : index + 1]
        volume_window = safe_volumes[index - length + 1 : index + 1]
        if np.any(~np.isfinite(value_window)):
            continue
        volume_sum = float(np.sum(volume_window))
        if volume_sum <= 0:
            continue
        output[index] = float(np.sum(value_window * volume_window) / volume_sum)
    return output


def pine_filter(values: np.ndarray, length: int, filter_type: str, volumes: np.ndarray | None = None) -> np.ndarray:
    normalized = str(filter_type or "SMA").strip().upper()
    if normalized == "EMA":
        return pine_ema(values, length)
    if normalized == "RMA":
        return pine_rma(values, length)
    if normalized == "LWMA":
        return pine_lwma(values, length)
    if normalized == "ALMA":
        return pine_alma(values, length)
    if normalized == "VWMA":
        return pine_vwma(values, volumes if volumes is not None else np.ones_like(values), length)
    return pine_sma(values, length)


def rolling_linreg(values: np.ndarray, length: int, offset: int = 0) -> np.ndarray:
    values = as_float_array(values)
    output = np.full(len(values), NAN, dtype=float)
    if len(values) < length or length <= 0:
        return output

    x = np.arange(length, dtype=float)
    for index in range(length - 1, len(values)):
        window = values[index - length + 1 : index + 1]
        if np.any(~np.isfinite(window)):
            continue
        slope, intercept = np.polyfit(x, window, 1)
        output[index] = intercept + slope * (length - 1 - offset)
    return output


def pine_linreg_slope_intercept(window: np.ndarray) -> tuple[float, float]:
    x = np.arange(len(window), dtype=float)
    slope, intercept = np.polyfit(x, window, 1)
    return float(slope), float(intercept)


def jwammo12_channel(closes: np.ndarray, length: int, deviation_mult: float) -> dict[str, np.ndarray]:
    closes = as_float_array(closes)
    middle = np.full(len(closes), NAN, dtype=float)
    upper = np.full(len(closes), NAN, dtype=float)
    lower = np.full(len(closes), NAN, dtype=float)

    lrc = rolling_linreg(closes, length, offset=0)
    lrc1 = rolling_linreg(closes, length, offset=1)

    for index in range(length - 1, len(closes)):
        if not np.isfinite(lrc[index]) or not np.isfinite(lrc1[index]):
            continue
        lr_slope = float(lrc[index] - lrc1[index])
        lr_intercept = float(lrc[index] - lr_slope * (length - 1))
        deviation_sum = 0.0
        for offset in range(length):
            source_value = closes[index - offset]
            fitted = lr_slope * (length - 1 - offset) + lr_intercept
            deviation_sum += (source_value - fitted) ** 2
        deviation = math.sqrt(deviation_sum / length)
        middle[index] = lrc[index]
        upper[index] = lrc[index] + deviation * deviation_mult
        lower[index] = lrc[index] - deviation * deviation_mult

    return {"middle": middle, "upper": upper, "lower": lower}


def _dw_filtered_std(
    values: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    width_coeff: float,
    volumes: np.ndarray | None,
) -> float:
    if length <= 0 or index < length - 1:
        return NAN

    filtered = pine_filter(values, length, filter_type, volumes)
    if not np.isfinite(filtered[index]):
        return NAN

    squared = np.power(values - filtered, 2)
    working = np.where(np.isfinite(squared), squared, 0.0)
    filtered_squared = pine_filter(working, length, filter_type, volumes)
    if not np.isfinite(filtered_squared[index]):
        return NAN
    return math.sqrt(max(0.0, float(filtered_squared[index]))) * float(width_coeff)


def _dw_correlation(
    values: np.ndarray,
    bar_indices: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    volumes: np.ndarray | None,
) -> float:
    if length <= 1 or index < length - 1:
        return 0.0

    x_dev = round(length / 2)
    filtered = pine_filter(values, length, filter_type, volumes)
    y_dev = values - filtered

    xy_sum = 0.0
    x2_sum = 0.0
    y2_sum = 0.0
    for offset in range(length):
        point_index = index - offset
        deviation = y_dev[point_index]
        if not np.isfinite(deviation):
            deviation = 0.0
        xy_sum += x_dev * deviation
        x2_sum += x_dev * x_dev
        y2_sum += deviation * deviation

    denominator = math.sqrt(x2_sum * y2_sum)
    if denominator == 0:
        return 0.0
    return xy_sum / denominator


def dw_regression_point(
    values: np.ndarray,
    bar_indices: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    width_coeff: float,
    volumes: np.ndarray | None = None,
) -> tuple[float, float, float]:
    if length <= 0 or index < length - 1:
        return NAN, NAN, NAN

    filtered = pine_filter(values, length, filter_type, volumes)
    y_mean = filtered[index]
    if not np.isfinite(y_mean):
        return NAN, NAN, NAN

    std_dev = _dw_filtered_std(values, index, length, filter_type, width_coeff, volumes)
    if not np.isfinite(std_dev):
        return NAN, NAN, NAN

    correlation = _dw_correlation(values, bar_indices, index, length, filter_type, volumes)
    sx = round(length / 2)
    x_mean = float(bar_indices[index - sx]) if index - sx >= 0 else 0.0
    slope = 0.0 if length == 1 else correlation * (std_dev / sx if sx else 0.0)
    intercept = y_mean - slope * x_mean
    current_x = float(bar_indices[index])
    y2 = intercept + slope * current_x
    return y2, std_dev, slope


def dw_channel_series(
    values: np.ndarray,
    bar_indices: np.ndarray,
    length: int,
    filter_type: str = "SMA",
    width_coeff: float = 1.0,
    volumes: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    values = as_float_array(values)
    bar_indices = as_float_array(bar_indices)
    middle = np.full(len(values), NAN, dtype=float)
    upper = np.full(len(values), NAN, dtype=float)
    lower = np.full(len(values), NAN, dtype=float)
    q3 = np.full(len(values), NAN, dtype=float)
    q1 = np.full(len(values), NAN, dtype=float)

    for index in range(len(values)):
        y2, std_dev, _ = dw_regression_point(
            values,
            bar_indices,
            index,
            length,
            filter_type,
            width_coeff,
            volumes,
        )
        if not np.isfinite(y2) or not np.isfinite(std_dev):
            continue
        middle[index] = y2
        upper[index] = y2 + std_dev
        lower[index] = y2 - std_dev
        q3[index] = y2 + std_dev / 2.0
        q1[index] = y2 - std_dev / 2.0

    return {"middle": middle, "upper": upper, "lower": lower, "q3": q3, "q1": q1}


def pine_range_volatility(candles: list[dict], length: int) -> float:
    if length <= 0 or len(candles) < length:
        return NAN

    selected = candles[-length:]
    contributions = []
    for candle in selected:
        low = abs(float(candle["low"]))
        if low <= 0:
            continue
        contributions.append((float(candle["high"]) - float(candle["low"])) / low * 100.0 / length)
    if not contributions:
        return NAN
    return float(sum(contributions))


def pine_daily_volatility(candle: dict) -> float:
    low = abs(float(candle["low"]))
    if low <= 0:
        return NAN
    high = float(candle["high"])
    previous_close = float(candle.get("previous_close", candle["close"]))
    true_range = max(
        high - float(candle["low"]),
        abs(high - previous_close),
        abs(float(candle["low"]) - previous_close),
    )
    return true_range * 100.0 / low


def pine_relative_volume_ratio(volumes: np.ndarray, length: int = 10) -> float:
    volumes = as_float_array(volumes)
    if len(volumes) < length + 1:
        return NAN

    average = pine_sma(volumes, length)
    previous_average = average[-2]
    if not np.isfinite(previous_average) or previous_average <= 0:
        return NAN
    return float(volumes[-1] / previous_average)

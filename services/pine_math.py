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


def lonesomeblue_linreg_channel(
    values: np.ndarray,
    length: int,
    upper_dev: float = 2.0,
    lower_dev: float = 2.0,
) -> dict[str, np.ndarray | float]:
    """LonesomeTheBlue Linear Regression Channel `get_channel()` port.

    The TradingView script refits one static channel over the latest `length`
    bars. Its deviation loop intentionally compares `src[x]` to
    `slope * (len - x) + intercept`; keep that off-by-one expression literal
    for parity instead of replacing it with a corrected residual formula.
    """
    values = as_float_array(values)
    length = int(length)
    if length <= 0 or len(values) < length:
        empty = np.array([], dtype=float)
        return {
            "middle": empty,
            "upper": empty,
            "lower": empty,
            "deviation": NAN,
            "slope": NAN,
            "intercept": NAN,
            "end": NAN,
        }

    window = values[-length:]
    if np.any(~np.isfinite(window)):
        empty = np.array([], dtype=float)
        return {
            "middle": empty,
            "upper": empty,
            "lower": empty,
            "deviation": NAN,
            "slope": NAN,
            "intercept": NAN,
            "end": NAN,
        }

    x = np.arange(length, dtype=float)
    slope, _poly_intercept = np.polyfit(x, window, 1)
    mid = float(np.sum(window) / length)
    intercept = mid - slope * math.floor(length / 2) + ((1 - (length % 2)) / 2.0) * slope
    end = intercept + slope * (length - 1)

    deviation_sum = 0.0
    current_first = window[::-1]
    for offset, source_value in enumerate(current_first):
        fitted = slope * (length - offset) + intercept
        deviation_sum += (float(source_value) - fitted) ** 2
    deviation = math.sqrt(deviation_sum / length)

    middle = intercept + slope * x
    upper = middle + deviation * float(upper_dev)
    lower = middle - deviation * float(lower_dev)

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "deviation": deviation,
        "slope": float(slope),
        "intercept": float(intercept),
        "end": float(end),
    }


def _dw_period_series(size: int, length: int, periods: np.ndarray | None = None) -> np.ndarray:
    if periods is None:
        return np.full(size, max(1, int(length)), dtype=int)
    normalized = np.asarray(periods, dtype=int)
    if len(normalized) != size:
        raise ValueError("DW period series must align with source values")
    return np.maximum(normalized, 1)


def _dw_history_value(values: np.ndarray, index: int, offset: int) -> float:
    point_index = index - offset
    if point_index < 0:
        # Pine: nz(y[offset], y)
        return float(values[index])
    value = float(values[point_index])
    return value if np.isfinite(value) else float(values[index])


def _dw_filter_series(
    values: np.ndarray,
    periods: np.ndarray,
    filter_type: str,
    volumes: np.ndarray | None = None,
) -> np.ndarray:
    """Literal implementation of the custom filters in Regression Channel [DW].

    These are intentionally separate from the shared Pine helpers. The DW
    script fills unavailable historical offsets with the current series value
    (`nz(y[i], y)`) instead of producing a warm-up NaN.
    """
    values = as_float_array(values)
    normalized = str(filter_type or "SMA").strip().upper()
    output = np.full(len(values), NAN, dtype=float)
    volume_values = (
        as_float_array(volumes)
        if volumes is not None
        else np.ones(len(values), dtype=float)
    )

    for index, raw_period in enumerate(periods):
        period = max(1, int(raw_period))
        current = float(values[index])

        if normalized == "EMA":
            previous = output[index - 1] if index > 0 else NAN
            output[index] = (
                current
                if not np.isfinite(previous)
                else (current - previous) * (2.0 / (period + 1.0)) + previous
            )
            continue

        if normalized == "RMA":
            previous = output[index - 1] if index > 0 else NAN
            if np.isfinite(previous):
                output[index] = (previous * (period - 1) + current) / period
                continue

        if normalized == "ALMA":
            m = 0.85 * (period - 1)
            s = period / 6.0
            weighted_sum = 0.0
            weight_sum = 0.0
            for position in range(period):
                weight = math.exp(-pow(position - m, 2) / (2.0 * pow(s, 2)))
                offset = period - 1 - position
                weighted_sum += weight * _dw_history_value(values, index, offset)
                weight_sum += weight
            output[index] = weighted_sum / weight_sum
            continue

        if normalized == "LWMA":
            weighted_sum = 0.0
            weight_sum = 0.0
            for offset in range(period):
                weight = period - offset
                weighted_sum += weight * _dw_history_value(values, index, offset)
                weight_sum += weight
            output[index] = weighted_sum / weight_sum
            continue

        if normalized == "VWMA":
            current_volume = float(volume_values[index])
            if not np.isfinite(current_volume):
                current_volume = 1.0
            weighted_sum = 0.0
            volume_sum = 0.0
            for offset in range(period):
                point_index = index - offset
                if point_index < 0:
                    value = current
                    volume = current_volume
                else:
                    value = _dw_history_value(values, index, offset)
                    volume = float(volume_values[point_index])
                    if not np.isfinite(volume):
                        volume = current_volume
                weighted_sum += value * volume
                volume_sum += volume
            output[index] = weighted_sum / volume_sum if volume_sum else NAN
            continue

        # SMA is also the initial-state seed used by the script's RMA.
        total = sum(
            _dw_history_value(values, index, offset)
            for offset in range(period)
        )
        output[index] = total / period

    return output


def _dw_calculation_series(
    values: np.ndarray,
    bar_indices: np.ndarray,
    length: int,
    filter_type: str,
    width_coeff: float,
    volumes: np.ndarray | None = None,
    periods: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    values = as_float_array(values)
    bar_indices = as_float_array(bar_indices)
    period_series = _dw_period_series(len(values), length, periods)

    filtered = _dw_filter_series(values, period_series, filter_type, volumes)
    deviations = values - filtered
    squared_deviations = np.power(deviations, 2)
    filtered_squared = _dw_filter_series(
        squared_deviations,
        period_series,
        filter_type,
        volumes,
    )
    standard_deviation = (
        np.sqrt(np.maximum(filtered_squared, 0.0)) * float(width_coeff)
    )

    middle = np.full(len(values), NAN, dtype=float)
    correlations = np.full(len(values), NAN, dtype=float)
    slopes = np.full(len(values), NAN, dtype=float)

    for index, raw_period in enumerate(period_series):
        period = max(1, int(raw_period))
        # Pine round(t / 2), where positive .5 values round upward.
        x_deviation = (period + 1) // 2
        current_deviation = float(deviations[index])
        historical_deviations = [
            (
                float(deviations[index - offset])
                if index - offset >= 0 and np.isfinite(deviations[index - offset])
                else current_deviation
            )
            for offset in range(period)
        ]

        xy_sum = sum(x_deviation * value for value in historical_deviations)
        x2_sum = period * x_deviation * x_deviation
        y2_sum = sum(value * value for value in historical_deviations)
        denominator = math.sqrt(x2_sum * y2_sum)
        correlation = 0.0 if denominator == 0 else xy_sum / denominator
        correlations[index] = correlation

        slope = (
            0.0
            if period == 1 or x_deviation == 0
            else correlation * (float(standard_deviation[index]) / x_deviation)
        )
        slopes[index] = slope

        x_mean_index = index - x_deviation
        x_mean = float(bar_indices[x_mean_index]) if x_mean_index >= 0 else 0.0
        intercept = float(filtered[index]) - slope * x_mean
        middle[index] = intercept + slope * float(bar_indices[index])

    return {
        "middle": middle,
        "standard_deviation": standard_deviation,
        "correlation": correlations,
        "slope": slopes,
    }


def _dw_filtered_std(
    values: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    width_coeff: float,
    volumes: np.ndarray | None,
) -> float:
    bar_indices = np.arange(len(values), dtype=float)
    calculated = _dw_calculation_series(
        values,
        bar_indices,
        length,
        filter_type,
        width_coeff,
        volumes,
    )
    return float(calculated["standard_deviation"][index])


def _dw_correlation(
    values: np.ndarray,
    bar_indices: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    volumes: np.ndarray | None,
) -> float:
    calculated = _dw_calculation_series(
        values,
        bar_indices,
        length,
        filter_type,
        1.0,
        volumes,
    )
    return float(calculated["correlation"][index])


def dw_regression_point(
    values: np.ndarray,
    bar_indices: np.ndarray,
    index: int,
    length: int,
    filter_type: str,
    width_coeff: float,
    volumes: np.ndarray | None = None,
) -> tuple[float, float, float]:
    if length <= 0 or index < 0 or index >= len(values):
        return NAN, NAN, NAN
    calculated = _dw_calculation_series(
        values,
        bar_indices,
        length,
        filter_type,
        width_coeff,
        volumes,
    )
    return (
        float(calculated["middle"][index]),
        float(calculated["standard_deviation"][index]),
        float(calculated["slope"][index]),
    )


def dw_channel_series(
    values: np.ndarray,
    bar_indices: np.ndarray,
    length: int,
    filter_type: str = "SMA",
    width_coeff: float = 1.0,
    volumes: np.ndarray | None = None,
    periods: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    calculated = _dw_calculation_series(
        values,
        bar_indices,
        length,
        filter_type,
        width_coeff,
        volumes,
        periods,
    )
    middle = calculated["middle"]
    std_dev = calculated["standard_deviation"]
    upper = middle + std_dev
    lower = middle - std_dev
    q3 = middle + std_dev / 2.0
    q1 = middle - std_dev / 2.0

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

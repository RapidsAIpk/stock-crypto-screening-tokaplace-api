# services/regression_channel_dw.py
"""Donovan Wall Regression Channel [DW] indicator."""

from datetime import datetime, timezone

import numpy as np

from services.pine_math import dw_channel_series


def compute_dw_regression_channel(
    candles,
    length=200,
    width_coeff=1.0,
    window_type="continuous",
    interval_step=1,
    filter_type="SMA",
):
    interval_mode = str(window_type).lower() == "interval"
    step = max(1, int(interval_step or 1)) if interval_mode else 1

    if not candles or (not interval_mode and len(candles) < length):
        return None

    active_length = (
        len(_current_day_candles(candles))
        if interval_mode
        else int(length)
    )
    start_index = len(candles) - active_length
    periods = _interval_periods(candles) if interval_mode else None

    per = active_length if interval_mode else length
    closes = np.array([c["close"] for c in candles], dtype=float)
    volumes = np.array([float(c.get("volume", 0) or 0) for c in candles], dtype=float)
    bar_indices = np.arange(len(candles), dtype=float)

    series = dw_channel_series(
        closes,
        bar_indices,
        per,
        filter_type=str(filter_type or "SMA"),
        width_coeff=width_coeff,
        volumes=volumes,
        periods=periods,
    )

    if not np.any(np.isfinite(series["middle"])):
        return None

    active_series = {
        key: values[-active_length:]
        for key, values in series.items()
    }

    return {
        "middle": active_series["middle"],
        "upper": active_series["upper"],
        "lower": active_series["lower"],
        "q1": active_series["q1"],
        "q3": active_series["q3"],
        "length": active_length,
        "window_type": window_type,
        "interval_step": step,
        "filter_type": str(filter_type or "SMA"),
    }


def _current_day_candles(candles):
    if not candles:
        return []

    latest_day = _candle_utc_day(candles[-1])
    if latest_day is None:
        return []

    start_index = len(candles) - 1
    while start_index - 1 >= 0 and _candle_utc_day(candles[start_index - 1]) == latest_day:
        start_index -= 1

    return candles[start_index:]


def _interval_periods(candles):
    periods = np.ones(len(candles), dtype=int)
    previous_day = None
    current_period = 0

    for index, candle in enumerate(candles):
        candle_day = _candle_utc_day(candle)
        if candle_day is None or candle_day != previous_day:
            current_period = 1
        else:
            current_period += 1
        periods[index] = current_period
        previous_day = candle_day

    return periods


def _candle_utc_day(candle):
    try:
        timestamp = int(candle["time"])
    except (KeyError, TypeError, ValueError):
        return None

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()

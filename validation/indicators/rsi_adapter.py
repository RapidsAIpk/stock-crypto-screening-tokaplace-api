from __future__ import annotations

from typing import Any

from services.rsi import compute_rsi_series
from validation.indicators.common import calculation_row, insufficient_rows, is_validation_candle
from validation.spec import ValidationSpec


def calculate(candles: list[dict[str, Any]], spec: ValidationSpec) -> list[dict[str, Any]]:
    length = spec.indicators.rsi_length
    required = length + 1
    if len(candles) < required:
        return insufficient_rows(spec, "rsi", (("rsi", "rsi"),), required, len(candles))

    series = compute_rsi_series(candles, length=length)
    if series is None:
        return insufficient_rows(spec, "rsi", (("rsi", "rsi"),), required, len(candles))
    offset = len(candles) - len(series)
    return [
        calculation_row(spec, candles[index + offset], "rsi", "rsi", value, "rsi")
        for index, value in enumerate(series)
        if is_validation_candle(candles[index + offset], spec)
    ]

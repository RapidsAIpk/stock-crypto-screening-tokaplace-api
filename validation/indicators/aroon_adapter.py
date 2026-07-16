from __future__ import annotations

from typing import Any

from services.aroon_oscillator import compute_aroon_oscillator
from validation.indicators.common import calculation_row, insufficient_rows, is_validation_candle
from validation.spec import ValidationSpec


def calculate(candles: list[dict[str, Any]], spec: ValidationSpec) -> list[dict[str, Any]]:
    length = spec.indicators.aroon_length
    required = length + 1
    components = (("aroon_oscillator", "aroon"),)
    if len(candles) < required:
        return insufficient_rows(spec, "aroon", components, required, len(candles))

    series = compute_aroon_oscillator(candles, length=length)
    if series is None:
        return insufficient_rows(spec, "aroon", components, required, len(candles))
    offset = len(candles) - len(series)
    return [
        calculation_row(
            spec,
            candles[index + offset],
            "aroon",
            "aroon_oscillator",
            value,
            "aroon",
        )
        for index, value in enumerate(series)
        if is_validation_candle(candles[index + offset], spec)
    ]

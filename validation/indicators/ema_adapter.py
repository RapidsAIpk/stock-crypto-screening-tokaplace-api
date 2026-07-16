from __future__ import annotations

from typing import Any

import numpy as np

from services.ema import compute_ema
from validation.indicators.common import calculation_row, insufficient_rows, is_validation_candle
from validation.spec import ValidationSpec


def calculate(candles: list[dict[str, Any]], spec: ValidationSpec) -> list[dict[str, Any]]:
    length = spec.indicators.ema_length
    required = length + 1
    if len(candles) < required:
        return insufficient_rows(spec, "ema", (("ema", "ema"),), required, len(candles))

    closes = np.array([candle["close"] for candle in candles], dtype=float)
    series = compute_ema(closes, length)
    return [
        calculation_row(spec, candle, "ema", "ema", value, "ema")
        for candle, value in zip(candles, series)
        if is_validation_candle(candle, spec)
    ]

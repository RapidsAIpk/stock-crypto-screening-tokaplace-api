from __future__ import annotations

from typing import Any

from services.macd import compute_macd
from validation.indicators.common import calculation_row, insufficient_rows, is_validation_candle
from validation.spec import ValidationSpec


COMPONENTS = (
    ("macd", "macd.macd"),
    ("macd_signal", "macd.signal"),
    ("macd_hist", "macd.hist"),
)


def calculate(candles: list[dict[str, Any]], spec: ValidationSpec) -> list[dict[str, Any]]:
    parameters = spec.indicators
    required = max(parameters.macd_fast, parameters.macd_slow) + parameters.macd_signal + 2
    if len(candles) < required:
        return insufficient_rows(spec, "macd", COMPONENTS, required, len(candles))

    values = compute_macd(
        candles,
        fast=parameters.macd_fast,
        slow=parameters.macd_slow,
        signal=parameters.macd_signal,
    )
    series_by_component = {
        "macd": values["macd"],
        "macd_signal": values["signal"],
        "macd_hist": values["hist"],
    }
    rows: list[dict[str, Any]] = []
    for component, tolerance_key in COMPONENTS:
        series = series_by_component[component]
        offset = len(candles) - len(series)
        rows.extend(
            calculation_row(
                spec,
                candles[index + offset],
                "macd",
                component,
                value,
                tolerance_key,
            )
            for index, value in enumerate(series)
            if is_validation_candle(candles[index + offset], spec)
        )
    return rows

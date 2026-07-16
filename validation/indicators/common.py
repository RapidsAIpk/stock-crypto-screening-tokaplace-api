from __future__ import annotations

from typing import Any, Iterable

from validation.spec import ValidationSpec


def tolerance_for(spec: ValidationSpec, key: str) -> float:
    return float(spec.tolerance.get(key, spec.tolerance.get(key.split(".")[0], 0.0)))


def calculation_row(
    spec: ValidationSpec,
    candle: dict[str, Any],
    indicator: str,
    component: str,
    value: float,
    tolerance_key: str,
) -> dict[str, Any]:
    return {
        "timestamp": candle["datetime"],
        "segment": "validation",
        "indicator": indicator,
        "component": component,
        "reference_value": None,
        "backend_value": float(value),
        "absolute_difference": None,
        "relative_difference": None,
        "tolerance": tolerance_for(spec, tolerance_key),
        "status": "calculated",
    }


def insufficient_rows(
    spec: ValidationSpec,
    indicator: str,
    components: Iterable[tuple[str, str]],
    required_candles: int,
    available_candles: int,
) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": None,
            "segment": "validation",
            "indicator": indicator,
            "component": component,
            "reference_value": None,
            "backend_value": None,
            "absolute_difference": None,
            "relative_difference": None,
            "tolerance": tolerance_for(spec, tolerance_key),
            "status": "insufficient_data",
            "required_candles": required_candles,
            "available_candles": available_candles,
        }
        for component, tolerance_key in components
    ]


def is_validation_candle(candle: dict[str, Any], spec: ValidationSpec) -> bool:
    return spec.validation_start.isoformat() <= candle["date"] <= spec.validation_end.isoformat()

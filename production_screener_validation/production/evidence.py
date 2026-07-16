from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from models.filters import IndicatorConfig

from ..contracts import ScreenerCase
from ..fixture_store import FixtureStore, slice_candles_to_date
from services.indicators import evaluate_indicator_details


def _selected_indicators(case: ScreenerCase) -> list[IndicatorConfig]:
    return [
        IndicatorConfig(name=item.name, timeframe=item.timeframe, config=dict(item.config))
        for item in case.indicators
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def _format_sticker(sticker: Any) -> dict[str, Any] | None:
    if sticker is None:
        return None
    if isinstance(sticker, str):
        return {"value": sticker}
    if isinstance(sticker, dict):
        return _json_safe(dict(sticker))
    if hasattr(sticker, "model_dump"):
        return _json_safe(sticker.model_dump())
    if hasattr(sticker, "dict"):
        return _json_safe(sticker.dict())
    return {"value": str(sticker)}


def _latest_candle_summary(candle: dict[str, Any] | None) -> dict[str, Any]:
    if not candle:
        return {}
    return {
        "date": candle.get("date") or candle.get("datetime"),
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
        "volume": candle.get("volume"),
    }


def evaluate_case_production(case: ScreenerCase, store: FixtureStore) -> dict[str, Any]:
    """Evaluate every symbol with production indicator handlers (no oracle)."""
    timeframe = case.single_timeframe or "1day"
    selected = _selected_indicators(case)
    passing: list[str] = []
    symbol_evidence: dict[str, Any] = {}
    errors: list[str] = []

    for symbol in case.symbols:
        try:
            candles = slice_candles_to_date(
                store.load_candles(case.fixture_id, symbol, str(timeframe)),
                case.evaluation_date,
            )
            asset: dict[str, Any] = {
                "symbol": symbol,
                "channels": {},
                "stickers": [],
                "candles": candles,
            }
            details = evaluate_indicator_details(asset, selected, timeframe_scope="single")
            passed = bool(details) and all(item["passed"] for item in details)
            latest = candles[-1] if candles else None
            symbol_evidence[symbol] = {
                "passed": passed,
                "status": "evaluated",
                "evaluation_date": case.evaluation_date,
                "candle": _latest_candle_summary(latest),
                "indicators": [
                    {
                        "name": item["name"],
                        "passed": item["passed"],
                        "sticker": _format_sticker(item.get("sticker")),
                        "config": deepcopy(item.get("config") or {}),
                    }
                    for item in details
                ],
                "channels": _json_safe(deepcopy(asset.get("channels") or {})),
            }
            if passed:
                passing.append(symbol)
        except Exception as exc:
            errors.append(f"{symbol}: {type(exc).__name__}: {exc}")
            symbol_evidence[symbol] = {
                "passed": False,
                "status": "error",
                "error": str(exc),
            }

    status = "production_error" if errors and not passing else "evaluated"
    return {
        "status": status,
        "case_id": case.case_id,
        "fixture_id": case.fixture_id,
        "evaluation_date": case.evaluation_date,
        "passing_symbols": sorted(passing),
        "excluded_symbols": sorted(set(case.symbols) - set(passing)),
        "symbol_evidence": symbol_evidence,
        "errors": errors,
    }

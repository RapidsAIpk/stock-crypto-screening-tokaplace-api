from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from services import aroon_oscillator, ema, indicators, macd, rsi, screener
from services.utils import confirm_if_needed
from validation.indicators.pipeline import load_massive_candles
from validation.screener.cases import FilterCase, ScreenerCaseSuite
from validation.spec import ValidationSpec


def _config_with_periods(case: FilterCase, spec: ValidationSpec) -> dict[str, Any]:
    config = dict(case.config)
    if case.indicator == "rsi":
        config.setdefault("length", spec.indicators.rsi_length)
    elif case.indicator == "aroon":
        config.setdefault("length", spec.indicators.aroon_length)
    elif case.indicator == "ema":
        config.setdefault("length", spec.indicators.ema_length)
    elif case.indicator == "macd":
        config.setdefault("fast", spec.indicators.macd_fast)
        config.setdefault("slow", spec.indicators.macd_slow)
        config.setdefault("signal", spec.indicators.macd_signal)
    return config


def _trace_rsi(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    series = rsi.compute_rsi_series(candles, length=int(config["length"]))
    if series is None:
        return {"signal_timestamp": None, "evaluated_indexes": [], "values": {}}
    offset = len(candles) - len(series)
    window = max(1, int(config.get("window", 1) or 1))
    indexes = list(range(max(0, len(series) - window), len(series)))
    for index in indexes:
        if not rsi._rsi_location_matches(
            series,
            index,
            config.get("location"),
            float(config.get("tolerance_pct", 0) or 0),
        ):
            continue
        if not rsi._rsi_direction_matches(series, index, config.get("direction")):
            continue
        candle_index = index + offset
        if config.get("confirmation") and not confirm_if_needed(candles, candle_index, config):
            continue
        return {
            "signal_timestamp": candles[candle_index]["datetime"],
            "evaluated_indexes": [value + offset for value in indexes],
            "values": {"rsi": float(series[index])},
        }
    return {
        "signal_timestamp": candles[-1]["datetime"],
        "evaluated_indexes": [value + offset for value in indexes],
        "values": {"rsi": float(series[-1])},
    }


def _trace_aroon(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    series = aroon_oscillator.compute_aroon_oscillator(candles, length=int(config["length"]))
    if series is None:
        return {"signal_timestamp": None, "evaluated_indexes": [], "values": {}}
    offset = len(candles) - len(series)
    window = max(1, int(config.get("window", 1) or 1))
    indexes = list(range(max(0, len(series) - window), len(series)))
    extreme = aroon_oscillator._normalize_extreme_level(config)
    for index in indexes:
        if not aroon_oscillator._aroon_level_matches(
            series,
            index,
            config.get("level"),
            float(config.get("tolerance_pct", 0) or 0),
        ):
            continue
        if not aroon_oscillator._aroon_direction_matches(
            series,
            index,
            config.get("direction"),
            extreme,
        ):
            continue
        candle_index = index + offset
        if config.get("confirmation") and not confirm_if_needed(candles, candle_index, config):
            continue
        return {
            "signal_timestamp": candles[candle_index]["datetime"],
            "evaluated_indexes": [value + offset for value in indexes],
            "values": {"aroon_oscillator": float(series[index])},
        }
    return {
        "signal_timestamp": candles[-1]["datetime"],
        "evaluated_indexes": [value + offset for value in indexes],
        "values": {"aroon_oscillator": float(series[-1])},
    }


def _trace_latest(candles: list[dict[str, Any]], case: FilterCase, config: dict[str, Any]) -> dict[str, Any]:
    if case.indicator == "ema":
        closes = [candle["close"] for candle in candles]
        series = ema.compute_ema(closes, int(config["length"]))
        return {
            "signal_timestamp": candles[-1]["datetime"],
            "evaluated_indexes": [len(candles) - 1],
            "values": {"price": closes[-1], "ema": float(series[-1])},
        }
    values = macd.compute_macd(
        candles,
        fast=int(config["fast"]),
        slow=int(config["slow"]),
        signal=int(config["signal"]),
    )
    return {
        "signal_timestamp": candles[-1]["datetime"],
        "evaluated_indexes": [len(candles) - 2, len(candles) - 1],
        "values": {
            "previous_macd": float(values["macd"][-2]),
            "macd": float(values["macd"][-1]),
            "previous_signal": float(values["signal"][-2]),
            "signal": float(values["signal"][-1]),
            "histogram": float(values["hist"][-1]),
        },
    }


class BackendFilterRunner:
    def __init__(self, spec: ValidationSpec, massive_run_path: str) -> None:
        self.spec = spec
        self.candles = load_massive_candles(massive_run_path)

    def evaluate_suite(self, suite: ScreenerCaseSuite) -> dict[str, Any]:
        cases = {case.case_id: self.evaluate_case(case) for case in suite.cases}
        case_map = {case.case_id: case for case in suite.cases}
        combined: dict[str, Any] = {}
        for item in suite.combined:
            decisions = [cases[case_id] for case_id in item.case_ids]
            if any(decision["status"] != "evaluated" for decision in decisions):
                combined[item.case_id] = {
                    "status": "insufficient_data",
                    "actual_included": None,
                    "operator": item.operator,
                    "case_ids": list(item.case_ids),
                    "combination_path": "not_evaluated",
                }
                continue
            if item.operator == "all":
                selected = [
                    SimpleNamespace(
                        name=case_map[case_id].indicator,
                        config=_config_with_periods(case_map[case_id], self.spec),
                    )
                    for case_id in item.case_ids
                ]
                asset = {"symbol": self.spec.symbol, "candles": deepcopy(self.candles)}
                included = bool(indicators.apply_indicators([asset], selected))
                path = "services.indicators.apply_indicators"
            else:
                included = any(bool(decision["actual_pass"]) for decision in decisions)
                path = "any_over_independent_backend_results"
            combined[item.case_id] = {
                "status": "evaluated",
                "actual_included": included,
                "operator": item.operator,
                "case_ids": list(item.case_ids),
                "combination_path": path,
            }
        return {"cases": cases, "combined": combined}

    def evaluate_case(self, case: FilterCase) -> dict[str, Any]:
        config = _config_with_periods(case, self.spec)
        selected = SimpleNamespace(name=case.indicator, config=config)
        required = screener.required_candles_for_indicators([selected])
        if len(self.candles) < required:
            return {
                "status": "insufficient_data",
                "indicator": case.indicator,
                "config": config,
                "actual_pass": None,
                "screener_included": None,
                "required_candles": required,
                "available_candles": len(self.candles),
                "signal_timestamp": None,
                "evaluated_indexes": [],
                "values": {},
            }

        handler = indicators.INDICATOR_REGISTRY[case.indicator]
        asset = {"symbol": self.spec.symbol, "candles": deepcopy(self.candles), "channels": {}}
        passed, sticker = handler(asset, asset["candles"], config)
        screener_asset = {"symbol": self.spec.symbol, "candles": deepcopy(self.candles)}
        included = bool(indicators.apply_indicators([screener_asset], [selected]))
        if case.indicator == "rsi":
            trace = _trace_rsi(self.candles, config)
        elif case.indicator == "aroon":
            trace = _trace_aroon(self.candles, config)
        else:
            trace = _trace_latest(self.candles, case, config)
        return {
            "status": "evaluated",
            "indicator": case.indicator,
            "config": config,
            "actual_pass": bool(passed),
            "screener_included": included,
            "sticker": sticker,
            "confirmation_pass": bool(passed) if config.get("confirmation") else None,
            **trace,
        }

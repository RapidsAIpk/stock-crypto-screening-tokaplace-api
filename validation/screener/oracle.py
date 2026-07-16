from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from validation.screener.cases import FilterCase, ScreenerCaseSuite
from validation.spec import ValidationSpec, canonical_utc_timestamp


class ReferenceRuleError(ValueError):
    pass


def _timestamp_value(raw: Any) -> str:
    return canonical_utc_timestamp(raw)


def _load_values(path: Path, indicator: str) -> list[dict[str, Any]]:
    payload = json.loads((path / indicator / "indicator.raw.json").read_text("utf-8"))
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise ReferenceRuleError(f"{indicator} reference has no values")
    return sorted(values, key=lambda row: _timestamp_value(row["datetime"]))


def _load_candles(path: Path) -> list[dict[str, Any]]:
    payload = json.loads((path / "rsi" / "candles.raw.json").read_text("utf-8"))
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise ReferenceRuleError("Twelve candle reference has no values")
    return sorted(values, key=lambda row: _timestamp_value(row["datetime"]))


def _direction_matches(series: list[float], index: int, direction: str | None) -> bool:
    if not direction:
        return True
    if direction in {"rising", "falling"}:
        if index < 1:
            return False
        delta = series[index] - series[index - 1]
        return delta > 1e-9 if direction == "rising" else delta < -1e-9
    if direction in {"turning_up", "turning_down"}:
        if index < 2:
            return False
        previous = series[index - 1] - series[index - 2]
        current = series[index] - series[index - 1]
        return (
            previous <= 1e-9 and current > 1e-9
            if direction == "turning_up"
            else previous >= -1e-9 and current < -1e-9
        )
    return False


def _patterns(candles: list[dict[str, Any]], index: int) -> set[str]:
    current = candles[index]
    previous = candles[index - 1] if index > 0 else None
    open_value = float(current["open"])
    close = float(current["close"])
    high = float(current["high"])
    low = float(current["low"])
    body = abs(close - open_value)
    upper = high - max(open_value, close)
    lower = min(open_value, close) - low
    found: set[str] = set()
    if previous:
        previous_open = float(previous["open"])
        previous_close = float(previous["close"])
        if previous_close < previous_open and close > open_value:
            if open_value <= previous_close and close >= previous_open:
                found.add("bullish_engulfing")
        if previous_close > previous_open and close < open_value:
            if open_value >= previous_close and close <= previous_open:
                found.add("bearish_engulfing")
    candle_range = max(high - low, 1e-9)
    if lower >= body * 2 and upper <= max(body, candle_range * 0.15):
        found.update({"hammer", "bullish_pin_bar"})
    if upper >= body * 2 and lower <= max(body, candle_range * 0.15):
        found.update({"shooting_star", "bearish_pin_bar"})
    return found


def _confirmation_matches(
    candles: list[dict[str, Any]],
    signal_timestamp: str,
    config: dict[str, Any],
) -> tuple[bool, str | None]:
    if not config.get("confirmation"):
        return True, signal_timestamp
    types = list(config.get("confirmation_types") or [])
    single_type = config.get("confirmation_type")
    if single_type and single_type not in types:
        types.insert(0, single_type)
    patterns = list(config.get("confirmation_patterns") or [])
    supported_patterns = {
        "bullish_engulfing",
        "bearish_engulfing",
        "hammer",
        "shooting_star",
        "bullish_pin_bar",
        "bearish_pin_bar",
    }
    unsupported = set(patterns) - supported_patterns
    if unsupported:
        raise ReferenceRuleError(
            f"unsupported independent confirmation patterns: {sorted(unsupported)}"
        )
    if not types and not patterns:
        return True, signal_timestamp
    indexes = {
        _timestamp_value(candle["datetime"]): index
        for index, candle in enumerate(candles)
    }
    if signal_timestamp not in indexes:
        return False, None
    start = indexes[signal_timestamp]
    window = max(0, int(config.get("confirmation_window", 1) or 1))
    for index in range(start, min(len(candles), start + window + 1)):
        candle = candles[index]
        open_value = float(candle["open"])
        close = float(candle["close"])
        candle_range = max(float(candle["high"]) - float(candle["low"]), 1e-9)
        body = abs(close - open_value)
        type_match = any(
            (value == "bullish" and close > open_value)
            or (value == "bearish" and close < open_value)
            or (value == "strong_bullish" and close > open_value and body > candle_range * 0.6)
            or (value == "strong_bearish" and close < open_value and body > candle_range * 0.6)
            for value in types
        )
        if type_match or set(patterns) & _patterns(candles, index):
            return True, _timestamp_value(candle["datetime"])
    return False, None


class ReferenceFilterOracle:
    def __init__(self, spec: ValidationSpec, twelve_run_path: str | Path) -> None:
        self.spec = spec
        self.path = Path(twelve_run_path)
        self.candles = _load_candles(self.path)

    def evaluate_suite(self, suite: ScreenerCaseSuite) -> dict[str, Any]:
        cases = {case.case_id: self.evaluate_case(case) for case in suite.cases}
        combined: dict[str, Any] = {}
        for item in suite.combined:
            decisions = [cases[case_id] for case_id in item.case_ids]
            if any(decision["status"] != "evaluated" for decision in decisions):
                combined[item.case_id] = {
                    "status": "reference_error",
                    "expected_included": None,
                    "operator": item.operator,
                    "case_ids": list(item.case_ids),
                }
                continue
            values = [bool(decision["expected_pass"]) for decision in decisions]
            combined[item.case_id] = {
                "status": "evaluated",
                "expected_included": all(values) if item.operator == "all" else any(values),
                "operator": item.operator,
                "case_ids": list(item.case_ids),
            }
        return {"cases": cases, "combined": combined}

    def evaluate_case(self, case: FilterCase) -> dict[str, Any]:
        try:
            self._validate_periods(case)
            values = _load_values(self.path, case.indicator)
            result = self._evaluate(case, values)
            return {"status": "evaluated", **result}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return {
                "status": "reference_error",
                "expected_pass": None,
                "error": str(exc),
                "indicator": case.indicator,
                "config": case.config,
            }

    def _validate_periods(self, case: FilterCase) -> None:
        config = case.config
        expected: dict[str, int]
        if case.indicator == "rsi":
            expected = {"length": self.spec.indicators.rsi_length}
        elif case.indicator == "aroon":
            expected = {"length": self.spec.indicators.aroon_length}
        elif case.indicator == "ema":
            expected = {"length": self.spec.indicators.ema_length}
        else:
            expected = {
                "fast": self.spec.indicators.macd_fast,
                "slow": self.spec.indicators.macd_slow,
                "signal": self.spec.indicators.macd_signal,
            }
        mismatches = {
            key: {"expected": value, "actual": config[key]}
            for key, value in expected.items()
            if key in config and int(config[key]) != value
        }
        if mismatches:
            raise ReferenceRuleError(
                f"case periods do not match the frozen reference: {mismatches}"
            )

    def _evaluate(self, case: FilterCase, rows: list[dict[str, Any]]) -> dict[str, Any]:
        config = case.config
        timestamps = [_timestamp_value(row["datetime"]) for row in rows]
        indicator = case.indicator
        if indicator == "rsi":
            series = [float(row["rsi"]) for row in rows]
            location = config.get("location")
            tolerance = max(0.0, float(config.get("tolerance_pct", 0) or 0))
            def level(value: float) -> bool:
                if not location:
                    return True
                if location == "oversold":
                    return value <= 30 + tolerance
                if location == "neutral":
                    return 30 - tolerance <= value <= 70 + tolerance
                if location == "overbought":
                    return value >= 70 - tolerance
                return False
            match = lambda index: level(series[index]) and _direction_matches(
                series, index, config.get("direction")
            )
            trace_values = lambda index: {"rsi": series[index]}
        elif indicator == "aroon":
            series = [float(row["aroon_up"]) - float(row["aroon_down"]) for row in rows]
            rule = config.get("level")
            tolerance = max(0.0, float(config.get("tolerance_pct", 0) or 0))
            extreme = abs(float(config.get("extreme_level", 70) or 70))
            def match(index: int) -> bool:
                value = series[index]
                levels = {
                    "above_50": value >= 50 - tolerance,
                    "between_50_0": -tolerance < value <= 50 + tolerance,
                    "near_0": -10 - tolerance <= value <= 10 + tolerance,
                    "between_0_-50": -50 - tolerance <= value < tolerance,
                    "below_-50": value <= -50 + tolerance,
                }
                if not rule or not levels.get(rule, False):
                    return False
                direction = config.get("direction")
                if not _direction_matches(series, index, direction):
                    return False
                if direction == "turning_up":
                    return index > 0 and series[index - 1] <= -extreme
                if direction == "turning_down":
                    return index > 0 and series[index - 1] >= extreme
                return True
            trace_values = lambda index: {
                "aroon_up": float(rows[index]["aroon_up"]),
                "aroon_down": float(rows[index]["aroon_down"]),
                "aroon_oscillator": series[index],
            }
        elif indicator == "ema":
            if config.get("confirmation"):
                raise ReferenceRuleError("EMA confirmation is not supported by the backend evaluator")
            candle_by_timestamp = {
                _timestamp_value(row["datetime"]): row
                for row in self.candles
            }
            index = len(rows) - 1
            timestamp = timestamps[index]
            price = float(candle_by_timestamp[timestamp]["close"])
            ema = float(rows[index]["ema"])
            tolerance = abs(ema) * (max(0.0, float(config.get("tolerance_pct", 0) or 0)) / 100)
            rule = config.get("rule")
            passed = (
                price >= ema - tolerance
                if rule == "above"
                else price <= ema + tolerance
                if rule == "below"
                else abs(price - ema) <= max(abs(ema) * 0.002, tolerance)
                if rule == "touch"
                else False
            )
            return {
                "indicator": indicator,
                "config": config,
                "expected_pass": passed,
                "signal_timestamp": timestamp,
                "confirmation_pass": None,
                "confirmation_timestamp": None,
                "values": {"price": price, "ema": ema},
            }
        elif indicator == "macd":
            if config.get("confirmation"):
                raise ReferenceRuleError("MACD confirmation is not supported by the backend evaluator")
            if len(rows) < 2:
                raise ReferenceRuleError("MACD requires current and previous reference rows")
            previous, current = rows[-2], rows[-1]
            m1, m2 = float(previous["macd"]), float(current["macd"])
            s1, s2 = float(previous["macd_signal"]), float(current["macd_signal"])
            tolerance = abs(float(config.get("tolerance_pct", 0) or 0)) / 100
            rule = config.get("rule")
            passed = {
                "bullish_cross": m1 <= s1 + tolerance and m2 >= s2 - tolerance,
                "bearish_cross": m1 >= s1 - tolerance and m2 <= s2 + tolerance,
                "above_zero": m2 >= -tolerance,
                "below_zero": m2 <= tolerance,
            }.get(rule, False)
            return {
                "indicator": indicator,
                "config": config,
                "expected_pass": passed,
                "signal_timestamp": timestamps[-1],
                "confirmation_pass": None,
                "confirmation_timestamp": None,
                "values": {
                    "previous_macd": m1,
                    "macd": m2,
                    "previous_signal": s1,
                    "signal": s2,
                    "histogram": float(current["macd_hist"]),
                },
            }
        else:
            raise ReferenceRuleError(f"unsupported indicator '{indicator}'")

        window = max(1, int(config.get("window", 1) or 1))
        start = max(0, len(series) - window)
        for index in range(start, len(series)):
            if not match(index):
                continue
            confirmation_pass, confirmation_timestamp = _confirmation_matches(
                self.candles,
                timestamps[index],
                config,
            )
            if not confirmation_pass:
                continue
            return {
                "indicator": indicator,
                "config": config,
                "expected_pass": True,
                "signal_timestamp": timestamps[index],
                "confirmation_pass": confirmation_pass if config.get("confirmation") else None,
                "confirmation_timestamp": confirmation_timestamp if config.get("confirmation") else None,
                "values": trace_values(index),
            }
        return {
            "indicator": indicator,
            "config": config,
            "expected_pass": False,
            "signal_timestamp": timestamps[-1],
            "confirmation_pass": False if config.get("confirmation") else None,
            "confirmation_timestamp": None,
            "values": trace_values(len(series) - 1),
        }

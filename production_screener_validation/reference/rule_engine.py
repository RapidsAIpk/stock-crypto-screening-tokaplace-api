from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .confirmation_oracle import confirmation_matches
from .custom_engine import (
    linear_regression_candles,
    lrc,
    regression_channel,
    trend_channel,
    volatility,
    wavetrend,
)
from .talib_engine import calculate, finite_at, last_finite_index


class InsufficientReferenceData(ValueError):
    pass


def _dates(candles: list[dict[str, Any]]) -> list[str]:
    return [str(row.get("datetime") or row.get("date") or row.get("time")) for row in candles]


def _direction(series: np.ndarray, index: int, direction: str | None) -> bool:
    if not direction:
        return True
    if direction in {"rising", "falling"}:
        if index < 1:
            return False
        delta = float(series[index] - series[index - 1])
        return delta > 1e-9 if direction == "rising" else delta < -1e-9
    if direction in {"turning_up", "turning_down"}:
        if index < 2:
            return False
        previous = float(series[index - 1] - series[index - 2])
        current = float(series[index] - series[index - 1])
        return previous <= 1e-9 and current > 1e-9 if direction == "turning_up" else previous >= -1e-9 and current < -1e-9
    raise ValueError(f"unknown direction '{direction}'")


def _window_match(
    candles: list[dict[str, Any]],
    series: np.ndarray,
    config: dict[str, Any],
    predicate: Callable[[int], bool],
) -> tuple[bool, int | None]:
    last = last_finite_index(series)
    if last is None:
        raise InsufficientReferenceData("indicator has no finite output")
    start = max(0, last - max(1, int(config.get("window", 1))) + 1)
    for index in range(start, last + 1):
        if not np.isfinite(series[index]) or not predicate(index):
            continue
        confirmed, _ = confirmation_matches(candles, index, config)
        if confirmed:
            return True, index
    return False, last


def evaluate_standard(name: str, candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    output = calculate(name, candles, config)
    dates = _dates(candles)
    tolerance = abs(float(config.get("tolerance_pct", 0) or 0))
    if name == "rsi":
        series = output["rsi"]
        def predicate(index: int) -> bool:
            value = float(series[index])
            location = config.get("location")
            location_ok = (
                True if not location else
                value <= 30 + tolerance if location == "oversold" else
                30 - tolerance <= value <= 70 + tolerance if location == "neutral" else
                value >= 70 - tolerance if location == "overbought" else False
            )
            if location not in {None, "oversold", "neutral", "overbought"}:
                raise ValueError(f"unknown RSI location '{location}'")
            return location_ok and _direction(series, index, config.get("direction"))
        passed, index = _window_match(candles, series, config, predicate)
        return _evidence(name, passed, index, dates, {"rsi": finite_at(series, index or 0)})
    if name == "aroon":
        series = output["aroon_oscillator"]
        def predicate(index: int) -> bool:
            value = float(series[index]); level = config.get("level")
            level_ok = {
                "above_50": value >= 50 - tolerance,
                "between_50_0": -tolerance < value <= 50 + tolerance,
                "near_0": -10 - tolerance <= value <= 10 + tolerance,
                "between_0_-50": -50 - tolerance <= value < tolerance,
                "below_-50": value <= -50 + tolerance,
            }.get(level)
            if level_ok is None:
                raise ValueError(f"unknown Aroon level '{level}'")
            direction = config.get("direction")
            if not _direction(series, index, direction):
                return False
            extreme = abs(float(config.get("extreme_level", 70)))
            if direction == "turning_up": return index > 0 and series[index - 1] <= -extreme
            if direction == "turning_down": return index > 0 and series[index - 1] >= extreme
            return bool(level_ok)
        passed, index = _window_match(candles, series, config, predicate)
        return _evidence(name, passed, index, dates, {key: finite_at(value, index or 0) for key, value in output.items()})
    if name == "macd":
        macd, signal = output["macd"], output["signal"]
        index = last_finite_index(signal)
        if index is None or index < 1:
            raise InsufficientReferenceData("MACD requires current and previous finite values")
        m1, m2, s1, s2 = map(float, (macd[index - 1], macd[index], signal[index - 1], signal[index]))
        delta = tolerance / 100.0; rule = config.get("rule")
        passed = {
            "bullish_cross": m1 <= s1 + delta and m2 >= s2 - delta,
            "bearish_cross": m1 >= s1 - delta and m2 <= s2 + delta,
            "above_zero": m2 >= -delta,
            "below_zero": m2 <= delta,
        }.get(rule)
        if passed is None: raise ValueError(f"unknown MACD rule '{rule}'")
        return _evidence(name, passed, index, dates, {"previous_macd": m1, "macd": m2, "previous_signal": s1, "signal": s2, "histogram": float(output["histogram"][index])})
    if name in {"ema", "sma"}:
        key = name; series = output[key]; index = last_finite_index(series)
        if index is None: raise InsufficientReferenceData(f"{name.upper()} has no finite output")
        price, average = float(candles[index]["close"]), float(series[index]); rule = config.get("rule")
        amount = abs(average) * tolerance / 100.0
        passed = price >= average - amount if rule == "above" else price <= average + amount if rule == "below" else abs(price - average) <= max(abs(average) * 0.002, amount) if rule == "touch" else None
        if passed is None: raise ValueError(f"unknown {name.upper()} rule '{rule}'")
        return _evidence(name, passed, index, dates, {"price": price, key: average})
    if name == "adx":
        series = output["adx"]; index = last_finite_index(series)
        if index is None: raise InsufficientReferenceData("ADX has no finite output")
        value = float(series[index]); threshold = float(config.get("threshold", 25)); rule = config.get("rule")
        passed = value >= threshold - tolerance if rule == "above" else value <= threshold + tolerance if rule == "below" else _direction(series, index, rule) if rule in {"rising", "falling"} else None
        if passed is None: raise ValueError(f"unknown ADX rule '{rule}'")
        return _evidence(name, passed, index, dates, {"adx": value})
    if name == "stochrsi":
        k, d = output["k"], output["d"]; index = last_finite_index(d)
        if index is None or index < 1: raise InsufficientReferenceData("StochRSI has insufficient output")
        rule = config.get("rule"); lower = float(config.get("oversold", 20)); upper = float(config.get("overbought", 80))
        passed = float(k[index]) <= lower + tolerance if rule == "oversold" else float(k[index]) >= upper - tolerance if rule == "overbought" else float(k[index-1]) <= float(d[index-1]) and float(k[index]) >= float(d[index]) if rule == "bullish_cross" else float(k[index-1]) >= float(d[index-1]) and float(k[index]) <= float(d[index]) if rule == "bearish_cross" else None
        if passed is None: raise ValueError(f"unknown StochRSI rule '{rule}'")
        return _evidence(name, passed, index, dates, {"k": float(k[index]), "d": float(d[index])})
    raise ValueError(f"unsupported standard indicator '{name}'")


def _evidence(name: str, passed: bool, index: int | None, dates: list[str], values: dict[str, Any]) -> dict[str, Any]:
    return {"indicator": name, "passed": bool(passed), "signal_index": index, "signal_timestamp": dates[index] if index is not None else None, "values": values}


def _line_touch(candle: dict[str, Any], value: float, tolerance_pct: float, touch_type: str = "wick") -> bool:
    amount = abs(value) * tolerance_pct / 100.0
    low, high = float(candle["low"]), float(candle["high"])
    body_low, body_high = sorted((float(candle["open"]), float(candle["close"])))
    wick = low - amount <= value <= high + amount
    body = body_low - amount <= value <= body_high + amount
    return body if touch_type == "body" else wick and not body if touch_type == "wick" else wick


def evaluate_custom(name: str, candles: list[dict[str, Any]], metadata: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    dates = _dates(candles); latest = len(candles) - 1; tolerance = abs(float(config.get("tolerance_pct", 0) or 0))
    if name == "wavetrend":
        values = wavetrend(candles, config); wt1, wt2 = values["wt1"], values["wt2"]
        zone, direction = config.get("zone"), config.get("direction")
        def predicate(index: int) -> bool:
            value = float(wt1[index]); zone_ok = value <= float(config.get("oversold_level", -60)) + tolerance if zone == "oversold" else value >= float(config.get("overbought_level", 60)) - tolerance if zone == "overbought" else True if zone in {None, "any"} else False
            direction_ok = _direction(wt1, index, direction) if direction in {None, "rising", "falling", "turning_up", "turning_down"} else index > 0 and wt1[index-1] <= wt2[index-1] and wt1[index] >= wt2[index] if direction == "crossed_up" else index > 0 and wt1[index-1] >= wt2[index-1] and wt1[index] <= wt2[index] if direction == "crossed_down" else False
            return zone_ok and direction_ok
        passed, index = _window_match(candles, wt1, config, predicate)
        return _evidence(name, passed, index, dates, {"wt1": finite_at(wt1, index or 0), "wt2": finite_at(wt2, index or 0)})
    if name == "linreg_candles":
        eval_candles = candles[:-1] if candles and candles[-1].get("is_closed") is False else candles
        if not eval_candles:
            raise InsufficientReferenceData("linreg_candles has no closed candles")
        values = linear_regression_candles(eval_candles, config)
        line = values["line"]
        eval_dates = _dates(eval_candles)
        latest = len(eval_candles) - 1
        window = max(1, int(config.get("window", 1) or 1))
        position = str(config.get("price_position") or "").strip().lower()
        if position in {"", "any", "auto", "none"}:
            position = None
        if position in {"any_signals", "any_position_signal"}:
            position = "any_signal"
        close_location = str(config.get("close_location") or "").strip().lower()
        if close_location in {"", "any", "auto", "none"}:
            close_location = None

        def position_predicate(index: int) -> bool:
            value = float(line[index])
            if not np.isfinite(value):
                return False
            candle = {
                "open": float(values["bopen"][index]),
                "high": float(values["bhigh"][index]),
                "low": float(values["blow"][index]),
                "close": float(values["bclose"][index]),
            }
            if not all(np.isfinite(item) for item in candle.values()):
                return False
            amount = abs(value) * tolerance / 100.0
            body_low, body_high = sorted((candle["open"], candle["close"]))
            effective_position = position
            if effective_position == "any_signal":
                effective_position = str(config.get("_candidate_price_position") or "")
            return (
                True if effective_position is None else
                candle["low"] >= value - amount if effective_position == "above" else
                candle["high"] <= value + amount if effective_position == "below" else
                body_low <= value + amount and body_high >= value - amount if effective_position == "on" else
                candle["open"] <= value + amount and candle["close"] >= value - amount if effective_position == "piercing_from_below" else
                candle["open"] >= value - amount and candle["close"] <= value + amount if effective_position == "piercing_from_above" else
                False
            )

        def predicate(index: int) -> bool:
            if not position_predicate(index):
                return False
            value = float(line[index])
            candle_open = float(values["bopen"][index])
            candle_close = float(values["bclose"][index])
            amount = abs(value) * tolerance / 100.0
            location_ok = (
                True if close_location is None else
                candle_close >= value - amount if close_location == "close_above" else
                candle_close <= value + amount if close_location == "close_below" else
                abs(candle_close - value) <= amount if close_location == "close_on" else
                candle_close > candle_open if close_location == "bullish" else
                candle_close < candle_open if close_location == "bearish" else
                False
            )
            return location_ok

        index = None
        def evaluate_position(candidate_position: str | None) -> int | None:
            nonlocal position
            original_position = position
            position = candidate_position
            try:
                if candidate_position is None:
                    if predicate(latest):
                        confirmed, _ = confirmation_matches(eval_candles, latest, config)
                        if confirmed:
                            return latest
                    return None

                if candidate_position in {"piercing_from_below", "piercing_from_above"}:
                    candidate = latest - window + 1
                    if candidate >= 0 and predicate(candidate):
                        confirmed, _ = confirmation_matches(eval_candles, candidate, config)
                        if confirmed:
                            return candidate
                    return None

                if predicate(latest):
                    signal_start = latest
                    while signal_start > 0 and position_predicate(signal_start - 1):
                        signal_start -= 1
                    signal_age = latest - signal_start + 1
                    confirmed, _ = confirmation_matches(eval_candles, signal_start, config)
                    if signal_age == window and confirmed:
                        return latest
                return None
            finally:
                position = original_position

        if position == "any_signal":
            for candidate_position in (
                "above",
                "below",
                "piercing_from_below",
                "piercing_from_above",
                "on",
            ):
                index = evaluate_position(candidate_position)
                if index is not None:
                    break
        elif position is None:
            if predicate(latest):
                confirmed, _ = confirmation_matches(eval_candles, latest, config)
                if confirmed:
                    index = latest
        elif position in {"piercing_from_below", "piercing_from_above"}:
            candidate = latest - window + 1
            if candidate >= 0 and predicate(candidate):
                confirmed, _ = confirmation_matches(eval_candles, candidate, config)
                if confirmed:
                    index = candidate
        elif predicate(latest):
            signal_start = latest
            while signal_start > 0 and position_predicate(signal_start - 1):
                signal_start -= 1
            signal_age = latest - signal_start + 1
            confirmed, _ = confirmation_matches(eval_candles, signal_start, config)
            if signal_age == window and confirmed:
                index = latest

        passed = index is not None
        evidence_index = index if index is not None else latest
        return _evidence(
            name,
            passed,
            evidence_index,
            eval_dates,
            {
                "line": finite_at(line, evidence_index),
                "bopen": finite_at(values["bopen"], evidence_index),
                "bhigh": finite_at(values["bhigh"], evidence_index),
                "blow": finite_at(values["blow"], evidence_index),
                "bclose": finite_at(values["bclose"], evidence_index),
            },
        )
    if name in {"lrc", "regression", "trend"}:
        channel = lrc(candles, config) if name == "lrc" else regression_channel(candles, config) if name == "regression" else trend_channel(candles, config)
        middle_key = "middle" if name != "trend" else "middle_line"
        middle = channel[middle_key]
        if len(middle) == 0: raise InsufficientReferenceData(f"{name} has insufficient channel history")
        if name == "lrc":
            r_mode = config.get("r_mode", "ignore"); r = float(channel["r"])
            if r_mode == "min" and abs(r) < float(config.get("r_min", 0)): return _evidence(name, False, latest, dates, {"r": r})
            if r_mode == "range" and not float(config.get("r_min", 0)) <= abs(r) <= float(config.get("r_max", 1)): return _evidence(name, False, latest, dates, {"r": r})
        selected = config.get("areas") if name == "trend" else config.get("lines") or ["middle"]
        if isinstance(selected, list) and selected and isinstance(selected[0], dict):
            rule_blocks = selected
        else:
            rule_blocks = [{"area" if name == "trend" else "line": item, "action": config.get("action", "touched"), "window": config.get("window", 1), "touch_type": config.get("touch_type", "wick"), "tolerance_pct": tolerance} for item in selected]
        decisions = []
        for block in rule_blocks:
            key = block.get("area") if name == "trend" else block.get("line")
            aliases = {"upper": "upper", "middle": middle_key, "lower": "lower", "top_line": "top_line", "middle_line": "middle_line", "bottom_line": "bottom_line"}
            if key in {"top_zone", "bottom_zone"}: key = "top_line" if key == "top_zone" else "bottom_line"
            series = channel.get(aliases.get(key, key))
            if series is None: raise ValueError(f"unknown {name} line/area '{key}'")
            window = max(1, int(block.get("window", 1))); action = block.get("action", "touched"); matched = False
            for offset in range(min(window, len(series))):
                candle_index = len(candles) - 1 - offset; line_index = len(series) - 1 - offset; value = float(series[line_index]); candle = candles[candle_index]; amount = abs(value) * float(block.get("tolerance_pct", block.get("tolerance", tolerance))) / 100.0
                matched = _line_touch(candle, value, float(block.get("tolerance_pct", tolerance)), block.get("touch_type", "wick")) if action in {"touched", "on_line"} else float(candle["close"]) > value + amount if action in {"closed_above", "breach"} and block.get("breach_direction", "up") != "down" else float(candle["close"]) < value - amount if action == "closed_below" or block.get("breach_direction") == "down" else False
                if matched: break
            decisions.append({"rule": block, "passed": matched})
        return _evidence(name, all(item["passed"] for item in decisions), latest, dates, {"rules": decisions, "latest_middle": float(middle[-1])})
    volumes = np.asarray([float(item["volume"]) for item in candles], dtype=float)
    if name in {"volume", "relative_volume"}:
        length = int(config["length"])
        if len(volumes) < length + 1: raise InsufficientReferenceData(f"{name} requires {length + 1} candles")
        average = float(np.mean(volumes[-length-1:-1])); current = float(volumes[-1]); ratio = current / average if average > 0 else 0.0
        threshold = float(config.get("multiplier", config.get("min_ratio"))) * (1 - tolerance / 100.0)
        return _evidence(name, ratio > threshold if name == "volume" else ratio >= threshold, latest, dates, {"current": current, "average": average, "ratio": ratio})
    if name == "current_volume":
        value = float(volumes[-1]); minimum = config.get("min_value"); maximum = config.get("max_value")
        passed = (minimum is None or value >= float(minimum) * (1 - tolerance / 100)) and (maximum is None or value <= float(maximum) * (1 + tolerance / 100))
        return _evidence(name, passed, latest, dates, {"current_volume": value})
    if name in {"float", "shares_outstanding"}:
        key = "float_shares" if name == "float" else "shares_outstanding"; value = metadata.get(key)
        if value is None: raise InsufficientReferenceData(f"metadata is missing {key}")
        value = float(value); minimum = config.get("min_value"); maximum = config.get("max_value")
        passed = (minimum is None or value >= float(minimum) * (1 - tolerance / 100)) and (maximum is None or value <= float(maximum) * (1 + tolerance / 100))
        return _evidence(name, passed, latest, dates, {key: value})
    if name == "volatility":
        value = volatility(candles, config)
        if value is None: raise InsufficientReferenceData("volatility has insufficient history")
        minimum = float(config.get("min_pct", 0)); maximum = config.get("max_pct")
        passed = value >= max(0, minimum - tolerance) and (maximum is None or value <= float(maximum) + tolerance)
        return _evidence(name, passed, latest, dates, {"volatility_pct": value})
    raise ValueError(f"unsupported custom indicator '{name}'")

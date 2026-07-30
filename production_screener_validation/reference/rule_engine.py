from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .confirmation_oracle import confirmation_matches
from .custom_engine import (
    ema_wave,
    linear_regression_candles,
    lrc,
    regression_channel,
    trend_channel,
    volatility,
    wavetrend,
)
from .talib_engine import calculate, finite_at, last_finite_index
from services.volatility import compute_volatility as compute_backend_volatility
from services.trendy_adx import (
    compute_trendy_adx as compute_backend_trendy_adx,
    evaluate_trendy_adx_rules as evaluate_backend_trendy_adx_rules,
    trendy_adx_debug_trace as backend_trendy_adx_debug_trace,
)


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


def _current_volume_reference(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    volumes = np.array([float(row.get("volume", 0) or 0) for row in candles], dtype=float)
    highs = np.array([float(row.get("high", 0) or 0) for row in candles], dtype=float)
    lows = np.array([float(row.get("low", 0) or 0) for row in candles], dtype=float)
    closes = np.array([float(row.get("close", 0) or 0) for row in candles], dtype=float)
    if len(volumes) < 1:
        raise InsufficientReferenceData("current_volume requires at least 1 candle")

    avg_count = max(1, int(config.get("avg_count", config.get("avgCnt", config.get("average_length", 30))) or 30))
    atr_length = max(1, int(config.get("atr_length", config.get("length", 14)) or 14))
    atr_multiplier = float(config.get("atr_multiplier", config.get("atrmultiplier", 0.5)) or 0.5)
    smoothing = str(config.get("smoothing", "RMA") or "RMA").strip().upper()

    average = float(np.mean(volumes[-avg_count:])) if len(volumes) >= avg_count else None
    percent = float(np.floor((float(volumes[-1]) / average) * 100.0 + 0.5)) if average and average > 0 else None
    true_range = _true_range_reference(highs, lows, closes)
    atr_series = _smooth_reference(true_range, atr_length, smoothing)
    atr = float(atr_series[-1] * atr_multiplier) if len(atr_series) and np.isfinite(atr_series[-1]) else None
    return {
        "current_volume": float(volumes[-1]),
        "current_average_volume": average,
        "current_resolution_percent_avg": percent,
        "atr": atr,
    }


def _true_range_reference(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    output = np.full(len(highs), np.nan, dtype=float)
    for index in range(len(highs)):
        if index == 0:
            output[index] = highs[index] - lows[index]
            continue
        output[index] = max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
    return output


def _smooth_reference(values: np.ndarray, length: int, smoothing: str) -> np.ndarray:
    if smoothing == "SMA":
        return _sma_reference(values, length)
    if smoothing == "EMA":
        return _ema_reference(values, length)
    if smoothing == "WMA":
        return _wma_reference(values, length)
    return _rma_reference(values, length)


def _sma_reference(values: np.ndarray, length: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(length - 1, len(values)):
        output[index] = float(np.mean(values[index - length + 1:index + 1]))
    return output


def _ema_reference(values: np.ndarray, length: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    if not len(values):
        return output
    multiplier = 2.0 / (length + 1.0)
    output[0] = values[0]
    for index in range(1, len(values)):
        output[index] = (values[index] - output[index - 1]) * multiplier + output[index - 1]
    return output


def _rma_reference(values: np.ndarray, length: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    for index in range(len(values)):
        if index < length - 1:
            output[index] = float(np.mean(values[:index + 1]))
        elif index == length - 1:
            output[index] = float(np.mean(values[:length]))
        else:
            output[index] = (output[index - 1] * (length - 1) + values[index]) / length
    return output


def _wma_reference(values: np.ndarray, length: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=float)
    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = float(np.sum(weights))
    for index in range(length - 1, len(values)):
        output[index] = float(np.dot(values[index - length + 1:index + 1], weights) / weight_sum)
    return output


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
        rule = str(config.get("rule") or "").strip().lower()
        if rule in {"above_zero", "below_zero", "histogram_above_zero", "histogram_below_zero"}:
            series = output["histogram"] if rule.startswith("histogram") else macd
            index = last_finite_index(series)
            if index is None:
                raise InsufficientReferenceData("MACD has no finite output")
            value = float(series[index])
            amount = abs(value) * tolerance / 100.0
            passed = value >= -amount if rule in {"above_zero", "histogram_above_zero"} else value <= amount
            return _evidence(name, passed, index, dates, {
                "macd": finite_at(macd, index),
                "signal": finite_at(signal, index),
                "histogram": finite_at(output["histogram"], index),
            })

        pair_indexes = np.flatnonzero(np.isfinite(macd) & np.isfinite(signal))
        if pair_indexes.size < 2:
            raise InsufficientReferenceData("MACD requires current and previous finite values")
        previous = int(pair_indexes[-2])
        index = int(pair_indexes[-1])
        m1, m2, s1, s2 = map(float, (macd[previous], macd[index], signal[previous], signal[index]))
        previous_amount = max(abs(m1), abs(s1)) * tolerance / 100.0
        current_amount = max(abs(m2), abs(s2)) * tolerance / 100.0
        passed = {
            "bullish_cross": m1 <= s1 + previous_amount and m2 >= s2 - current_amount,
            "bearish_cross": m1 >= s1 - previous_amount and m2 <= s2 + current_amount,
            "above_signal": m2 >= s2 - current_amount,
            "macd_above_signal": m2 >= s2 - current_amount,
            "below_signal": m2 <= s2 + current_amount,
            "macd_below_signal": m2 <= s2 + current_amount,
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
        if config.get("mode") or config.get("conditions") or config.get("condition"):
            computed = compute_backend_trendy_adx(candles, length=config.get("length", 11))
            if computed is None:
                raise InsufficientReferenceData("Trendy ADX has insufficient history")
            passed = evaluate_backend_trendy_adx_rules(computed, candles, config)
            trace = backend_trendy_adx_debug_trace(computed, candles, config)
            return _evidence(name, passed, trace["latest_index"], dates, trace.get("latest", {}))
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
    if name == "ema_wave":
        values = ema_wave(candles, config)
        wave_a, wave_b, wave_c = values["wave_a"], values["wave_b"], values["wave_c"]
        finite = np.isfinite(wave_a) & np.isfinite(wave_b) & np.isfinite(wave_c)
        indexes = np.flatnonzero(finite)
        if not indexes.size:
            raise InsufficientReferenceData("EMA Wave has no finite output")
        rule = str(config.get("rule", "any_spike") or "any_spike").strip().lower()
        wave_name = str(config.get("wave", "wave_c") or "wave_c").strip().lower()
        threshold = float(config.get("threshold", 0) or 0)
        wave_map = {
            "a": wave_a, "wa": wave_a, "wavea": wave_a, "wave_a": wave_a,
            "b": wave_b, "wb": wave_b, "waveb": wave_b, "wave_b": wave_b,
            "c": wave_c, "wc": wave_c, "wavec": wave_c, "wave_c": wave_c,
        }
        series = wave_map.get(wave_name, wave_c)
        def predicate(index: int) -> bool:
            if rule == "any_spike":
                return bool(values["wave_b_spike"][index] or values["wave_c_spike"][index])
            if rule == "both_spikes":
                return bool(values["wave_b_spike"][index] and values["wave_c_spike"][index])
            if rule == "wave_b_spike":
                return bool(values["wave_b_spike"][index])
            if rule == "wave_c_spike":
                return bool(values["wave_c_spike"][index])
            amount = abs(threshold) * tolerance / 100.0
            current = float(series[index])
            if rule == "above":
                return current >= threshold - amount
            if rule == "below":
                return current <= threshold + amount
            if rule == "crossed_up":
                return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) <= threshold + amount and current >= threshold - amount
            if rule == "crossed_down":
                return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) >= threshold - amount and current <= threshold + amount
            raise ValueError(f"unknown EMA Wave rule '{rule}'")
        passed, index = _window_match(candles, series, config, predicate)
        return _evidence(name, passed, index, dates, {
            "wave_a": finite_at(wave_a, index or 0),
            "wave_b": finite_at(wave_b, index or 0),
            "wave_c": finite_at(wave_c, index or 0),
            "wave_b_spike": bool(values["wave_b_spike"][index]) if index is not None else False,
            "wave_c_spike": bool(values["wave_c_spike"][index]) if index is not None else False,
        })
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
        evidence = _current_volume_reference(candles, config)
        value = evidence["current_volume"]; minimum = config.get("min_value"); maximum = config.get("max_value")
        percent = evidence["current_resolution_percent_avg"]
        rule = str(config.get("rule", "value") or "value").strip().lower()
        if rule in {"above_average", "above_average_volume", "avg_100"}:
            passed = percent is not None and percent >= 100.0 * (1 - tolerance / 100)
        elif rule in {"above_average_percent", "percent", "percent_avg_above", "rvol_percent_above", "above_percent"}:
            threshold = float(config.get("min_percent_avg", 100.0) or 100.0) * (1 - tolerance / 100)
            passed = percent is not None and percent >= threshold
        elif rule in {"below_average_percent", "below_percent", "percent_avg_below"}:
            threshold = float(config.get("min_percent_avg", 100.0) or 100.0) * (1 + tolerance / 100)
            passed = percent is not None and percent <= threshold
        elif rule in {"between_average_percent", "between_percent", "percent_range"}:
            lower = float(config.get("min_percent_avg", 100.0) or 100.0) * (1 - tolerance / 100)
            upper = float(config.get("max_percent_avg")) * (1 + tolerance / 100)
            passed = percent is not None and lower <= percent <= upper
        else:
            passed = (minimum is None or value >= float(minimum) * (1 - tolerance / 100)) and (maximum is None or value <= float(maximum) * (1 + tolerance / 100))
        return _evidence(name, passed, latest, dates, evidence)
    if name in {"float", "shares_outstanding"}:
        key = "float_shares" if name == "float" else "shares_outstanding"; value = metadata.get(key)
        if value is None: raise InsufficientReferenceData(f"metadata is missing {key}")
        value = float(value); minimum = config.get("min_value"); maximum = config.get("max_value")
        passed = (minimum is None or value >= float(minimum) * (1 - tolerance / 100)) and (maximum is None or value <= float(maximum) * (1 + tolerance / 100))
        return _evidence(name, passed, latest, dates, {key: value})
    if name == "volatility":
        mode = str(config.get("mode", "range_avg") or "range_avg").strip().lower()
        if mode in {"vstop", "volatility_stop", "v-stop", "volatility_stop_mtf"}:
            result = compute_backend_volatility(candles, config)
            if result.get("config_error"):
                raise InsufficientReferenceData(result["config_error"])
            if result["latest_index"] < 0:
                raise InsufficientReferenceData("volatility has insufficient history")
            latest_evidence = dict(result.get("debug", {}).get("latest", {}))
            latest_evidence["matched_signal_index"] = result.get("matched_signal_index")
            latest_evidence["matched_signal_age"] = result.get("matched_signal_age")
            return _evidence(name, result.get("matched_signal_index") is not None, latest, dates, latest_evidence)
        value = volatility(candles, config)
        if value is None: raise InsufficientReferenceData("volatility has insufficient history")
        minimum = float(config.get("min_pct", 0)); maximum = config.get("max_pct")
        passed = value >= max(0, minimum - tolerance) and (maximum is None or value <= float(maximum) + tolerance)
        return _evidence(name, passed, latest, dates, {"volatility_pct": value})
    raise ValueError(f"unsupported custom indicator '{name}'")

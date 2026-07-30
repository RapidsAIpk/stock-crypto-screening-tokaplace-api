# services/volatility.py
"""Volatility filters, including TradingView's Volatility Stop MTF logic."""

import numpy as np

from services.pine_math import NAN, pine_daily_volatility, pine_range_volatility
from services.utils import build_indicator_sticker, format_decimal, humanize_token


DEFAULT_VOLATILITY_CONFIG = {
    "mode": "range_avg",
    "length": 20,
    "min_pct": 0.0,
    "max_pct": None,
    "tolerance_pct": 0.0,
    "source": "close",
    "atr_factor": 2.0,
    "htf_selection": "Multiple Of Current TF",
    "htf_multiple": 3.0,
    "fixed_timeframe": "1D",
    "detect_breaches": True,
    "repainting_htf": False,
    "trend_reversal_alert": False,
    "change_to_uptrend_alert": False,
    "change_to_downtrend_alert": False,
    "chart_breach_uptrend_alert": False,
    "chart_breach_downtrend_alert": False,
    "delay_minutes": 0.0,
    "alert_frequency": "once_per_bar",
    "rule": "threshold",
    "window": 1,
    "min_atr": None,
    "max_atr": None,
    "min_stop_distance_pct": None,
    "max_stop_distance_pct": None,
}

TRADINGVIEW_VSTOP_DEFAULTS = {
    "source": "close",
    "length": 20,
    "atr_factor": 2.0,
    "htf_selection": "Multiple Of Current TF",
    "htf_multiple": 3.0,
    "fixed_timeframe": "1D",
    "detect_breaches": True,
    "repainting_htf": False,
    "trend_reversal_alert": False,
    "change_to_uptrend_alert": False,
    "change_to_downtrend_alert": False,
    "chart_breach_uptrend_alert": False,
    "chart_breach_downtrend_alert": False,
    "delay_minutes": 0.0,
}

VOLATILITY_ALIAS_GROUPS = {
    "mode": ("mode", "calculation_mode"),
    "length": ("length", "lenInput", "atr_length"),
    "min_pct": ("min_pct", "minimum_pct"),
    "max_pct": ("max_pct", "maximum_pct"),
    "tolerance_pct": ("tolerance_pct", "tolerance"),
    "source": ("source", "srcInput"),
    "atr_factor": ("atr_factor", "atrInput", "atr_multiplier", "factor"),
    "htf_selection": ("htf_selection", "typeInput", "higher_timeframe_selection"),
    "htf_multiple": ("htf_multiple", "type2Input", "multiple_of_current_tf"),
    "fixed_timeframe": ("fixed_timeframe", "type3Input", "fixed_tf"),
    "detect_breaches": ("detect_breaches", "detectBreachesInput"),
    "repainting_htf": ("repainting_htf", "repaintsInput", "repainting"),
    "trend_reversal_alert": ("trend_reversal_alert", "revInput"),
    "change_to_uptrend_alert": ("change_to_uptrend_alert", "upInput"),
    "change_to_downtrend_alert": ("change_to_downtrend_alert", "dnInput"),
    "chart_breach_uptrend_alert": ("chart_breach_uptrend_alert", "eUpInput"),
    "chart_breach_downtrend_alert": ("chart_breach_downtrend_alert", "eDnInput"),
    "delay_minutes": ("delay_minutes", "delayInput"),
    "alert_frequency": ("alert_frequency", "freqInput"),
    "rule": ("rule", "condition", "signal"),
    "window": ("window", "signal_window", "lookback_candles"),
    "min_atr": ("min_atr", "minimum_atr"),
    "max_atr": ("max_atr", "maximum_atr"),
    "min_stop_distance_pct": ("min_stop_distance_pct", "minimum_stop_distance_pct"),
    "max_stop_distance_pct": ("max_stop_distance_pct", "maximum_stop_distance_pct"),
}

SUPPORTED_VOLATILITY_MODES = {"range_avg", "daily", "returns_std", "vstop"}
SUPPORTED_VOLATILITY_RULES = {
    "threshold",
    "trend_reversal",
    "change_to_uptrend",
    "change_to_downtrend",
    "uptrend",
    "downtrend",
    "price_cross_stop",
    "atr_above",
    "atr_below",
    "stop_distance_above_pct",
    "stop_distance_below_pct",
    "volatility_expansion",
    "volatility_contraction",
    "early_breach_uptrend",
    "early_breach_downtrend",
    "selected_alerts",
}


class VolatilityConfigError(ValueError):
    pass


def evaluate_volatility(candles, config):
    result = compute_volatility(candles, config)
    if result["config_error"]:
        raise VolatilityConfigError(result["config_error"])
    return result["matched_signal_index"] is not None


def compute_volatility(candles, config):
    requested_config = dict(config or {})
    normalized_config, config_error = normalize_volatility_config(requested_config)
    candles = _completed_sorted_candles(candles)
    mode = normalized_config["mode"]

    if mode == "vstop":
        return _compute_vstop_volatility(candles, requested_config, normalized_config, config_error)
    return _compute_legacy_volatility(candles, requested_config, normalized_config, config_error)


def build_volatility_sticker(candles, config):
    result = compute_volatility(candles, config)
    if result["config_error"]:
        raise VolatilityConfigError(result["config_error"])

    index = result["matched_signal_index"]
    if index is None:
        index = result["latest_index"]

    effective = result["effective_config"]
    if effective["mode"] == "vstop":
        stop = _finite_float_or_default(result["stop"][index], None) if index >= 0 else None
        atr = _finite_float_or_default(result["atr"][index], None) if index >= 0 else None
        trend = "Uptrend" if index >= 0 and bool(result["trend_up"][index]) else "Downtrend"
        age = result["matched_signal_age"]
        timing = "latest candle" if age in {None, 0} else f"{age} bars ago"
        parts = [f"{trend} stop {format_decimal(stop, 4) if stop is not None else 'n/a'} on {timing}"]
        if atr is not None:
            parts.append(f"ATR {format_decimal(atr, 4)}")
        condition = "; ".join(parts)
    else:
        value = _finite_float_or_default(result["volatility_pct"][index], None) if index >= 0 else None
        label = result["label"]
        condition = f"{label}: {format_decimal(value, 2)}%" if value is not None else f"{label}: n/a"

    return build_indicator_sticker(
        "Volatility",
        condition,
        {"window": int(effective["window"]), "confirmation": False},
        length=int(effective["length"]),
        window=int(effective["window"]),
        decision=_volatility_decision(effective, result),
    )


def normalize_volatility_config(config):
    requested = dict(config or {})
    normalized = dict(DEFAULT_VOLATILITY_CONFIG)

    try:
        for canonical, keys in VOLATILITY_ALIAS_GROUPS.items():
            present = [(key, requested[key]) for key in keys if key in requested and requested[key] is not None]
            if not present:
                continue
            coerced_values = [_coerce_volatility_config_value(canonical, value) for _key, value in present]
            first_value = coerced_values[0]
            conflicts = [
                f"{key}={value}"
                for (key, _raw), value in zip(present, coerced_values)
                if value != first_value
            ]
            if conflicts:
                all_values = ", ".join(f"{key}={_coerce_volatility_config_value(canonical, raw)}" for key, raw in present)
                raise VolatilityConfigError(f"Conflicting Volatility config aliases for {canonical}: {all_values}")
            normalized[canonical] = first_value

        if normalized["mode"] not in SUPPORTED_VOLATILITY_MODES:
            raise VolatilityConfigError(
                f"Unsupported Volatility mode '{normalized['mode']}'. Supported modes: {', '.join(sorted(SUPPORTED_VOLATILITY_MODES))}"
            )
        if normalized["rule"] not in SUPPORTED_VOLATILITY_RULES:
            raise VolatilityConfigError(
                f"Unsupported Volatility rule '{normalized['rule']}'. Supported rules: {', '.join(sorted(SUPPORTED_VOLATILITY_RULES))}"
            )
        if normalized["mode"] == "vstop" and int(normalized["length"]) < 2:
            raise VolatilityConfigError("Volatility Stop length must be at least 2")
        if float(normalized["atr_factor"]) < 0.25:
            raise VolatilityConfigError("Volatility Stop ATR factor must be at least 0.25")

        return normalized, None
    except (TypeError, ValueError) as exc:
        return normalized, str(exc)


def required_volatility_candles(config):
    normalized, error = normalize_volatility_config(config)
    if error:
        normalized = dict(DEFAULT_VOLATILITY_CONFIG)
    length = int(normalized["length"])
    window = int(normalized.get("window", 1) or 1)
    if normalized["mode"] == "returns_std":
        length += 1
    return max(2, length) + max(0, window - 1)


def volatility_config_warnings(config):
    requested = dict(config or {})
    normalized, error = normalize_volatility_config(requested)
    warnings = []

    if error:
        warnings.append({
            "code": "VOLATILITY_CONFIG_ERROR",
            "message": error,
            "requested_config": requested,
            "effective_config": normalized,
        })
        return warnings

    if normalized["mode"] == "vstop":
        differing_defaults = {
            key: {
                "backend": normalized.get(key),
                "tradingview_default": value,
            }
            for key, value in TRADINGVIEW_VSTOP_DEFAULTS.items()
            if normalized.get(key) != value
        }
        if differing_defaults:
            warnings.append({
                "code": "VOLATILITY_VSTOP_TV_DEFAULT_MISMATCH_RISK",
                "message": (
                    "Volatility Stop effective config differs from the TradingView script defaults. "
                    "TradingView validation must use the same input values."
                ),
                "differences": differing_defaults,
                "requested_config": requested,
                "effective_config": normalized,
            })

        if _htf_on(normalized):
            warnings.append({
                "code": "VOLATILITY_VSTOP_HTF_REQUEST_SECURITY_LIMITATION",
                "message": (
                    "The TradingView script can request a separate higher-timeframe series. "
                    "This backend path evaluates the selected chart timeframe candles unless a "
                    "separate HTF candle fetch is added to the screener pipeline."
                ),
                "requested_htf_selection": normalized["htf_selection"],
                "effective_config": normalized,
            })

    return warnings


def volatility_signal_warnings(candles, config):
    result = compute_volatility(candles, config)
    if result["config_error"]:
        return []

    if result["matched_signal_index"] is not None and result["matched_signal_age"] and result["matched_signal_age"] > 0:
        return [{
            "code": "VOLATILITY_SIGNAL_WITHIN_WINDOW_NOT_LATEST",
            "message": (
                "Volatility passed because a matching signal exists inside the configured "
                "window, but it was not created by the latest completed candle."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["matched_signal_age"],
            "effective_config": result["effective_config"],
        }]

    if result["matched_signal_index"] is None and result["most_recent_signal_index"] is not None:
        return [{
            "code": "VOLATILITY_STALE_SIGNAL_OUTSIDE_WINDOW",
            "message": (
                "TradingView may show an older Volatility condition, but the backend did not pass "
                "because the most recent matching signal is outside the configured window."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["most_recent_signal_age"],
            "effective_config": result["effective_config"],
        }]

    return []


def volatility_debug_trace(candles, config, symbol=None, timeframe=None):
    result = compute_volatility(candles, config)
    trace = dict(result["debug"])
    trace["symbol"] = symbol
    trace["timeframe"] = timeframe
    trace["candle_count"] = len(result["candles"])
    trace["latest_index"] = result["latest_index"]
    trace["matched_signal_index"] = result["matched_signal_index"]
    trace["matched_signal_age"] = result["matched_signal_age"]
    trace["most_recent_signal_index"] = result["most_recent_signal_index"]
    trace["most_recent_signal_age"] = result["most_recent_signal_age"]
    trace["signal_warnings"] = volatility_signal_warnings(candles, config)
    return trace


def _compute_legacy_volatility(candles, requested_config, normalized_config, config_error):
    length = int(normalized_config["length"])
    latest_index = len(candles) - 1
    values = np.full(len(candles), NAN, dtype=float)
    label = f"Range volatility over {length} bars"

    if len(candles) >= max(2, length):
        mode = normalized_config["mode"]
        if mode == "daily":
            for index in range(1, len(candles)):
                latest = dict(candles[index])
                latest["previous_close"] = float(candles[index - 1]["close"])
                values[index] = pine_daily_volatility(latest)
            label = "Daily true-range volatility"
        elif mode == "returns_std":
            closes = np.array([c.get("close", NAN) for c in candles], dtype=float)
            for index in range(length, len(closes)):
                returns = _safe_percent_returns(closes[index - length:index + 1])
                if returns.size:
                    values[index] = float(np.std(returns) * 100.0)
            label = f"Realized vol over {length} bars"
        else:
            for index in range(length - 1, len(candles)):
                values[index] = pine_range_volatility(candles[:index + 1], length)

    signal = _legacy_signal_series(values, normalized_config)
    matched_signal_index = _matching_boolean_index(signal, latest_index, int(normalized_config["window"]))
    most_recent_signal_index = _matching_boolean_index(signal, latest_index, None)
    return _build_result(
        candles,
        requested_config,
        normalized_config,
        config_error,
        signal,
        matched_signal_index,
        most_recent_signal_index,
        {
            "volatility_pct": values,
            "label": label,
            "debug": {
                "latest": {
                    "time": candles[latest_index].get("time") if latest_index >= 0 else None,
                    "volatility_pct": _finite_float_or_default(values[latest_index], None) if latest_index >= 0 else None,
                    "final_signal": bool(signal[latest_index]) if latest_index >= 0 else False,
                },
            },
        },
    )


def _compute_vstop_volatility(candles, requested_config, normalized_config, config_error):
    latest_index = len(candles) - 1
    source = _source_series(candles, normalized_config["source"])
    highs = np.array([float(c.get("high", NAN)) for c in candles], dtype=float)
    lows = np.array([float(c.get("low", NAN)) for c in candles], dtype=float)
    closes = np.array([float(c.get("close", NAN)) for c in candles], dtype=float)
    true_range = _true_range(highs, lows, closes)
    atr = _pine_atr(true_range, int(normalized_config["length"]))
    stop, trend_up, atr_distance = _vstop_series(source, true_range, atr, float(normalized_config["atr_factor"]))
    trend_reversal = _trend_reversal_series(trend_up)
    trend_change_to_up = trend_reversal & trend_up
    trend_change_to_down = trend_reversal & ~trend_up
    price_cross_stop = _cross_series(closes, stop)
    in_limbo, early_breach_up, early_breach_down = _breach_series(
        price_cross_stop,
        trend_reversal,
        trend_up,
        _htf_on(normalized_config) and bool(normalized_config["detect_breaches"]),
    )
    seconds_reversal = _seconds_since(candles, trend_reversal)
    seconds_up = _seconds_since(candles, trend_change_to_up)
    seconds_down = _seconds_since(candles, trend_change_to_down)
    seconds_early_up = _seconds_since(candles, early_breach_up)
    seconds_early_down = _seconds_since(candles, early_breach_down)
    delay_seconds = float(normalized_config["delay_minutes"]) * 60.0
    alert_reversal = seconds_reversal >= delay_seconds
    alert_up = seconds_up >= delay_seconds
    alert_down = seconds_down >= delay_seconds
    alert_early_up = seconds_early_up >= delay_seconds
    alert_early_down = seconds_early_down >= delay_seconds
    stop_distance_pct = np.divide(
        np.abs(closes - stop),
        np.abs(closes),
        out=np.full(len(closes), NAN, dtype=float),
        where=np.isfinite(closes) & (np.abs(closes) > 0) & np.isfinite(stop),
    ) * 100.0

    signal = _vstop_signal_series(
        normalized_config,
        atr,
        stop_distance_pct,
        trend_up,
        trend_reversal,
        trend_change_to_up,
        trend_change_to_down,
        price_cross_stop,
        early_breach_up,
        early_breach_down,
        alert_reversal,
        alert_up,
        alert_down,
        alert_early_up,
        alert_early_down,
    )
    matched_signal_index = _matching_boolean_index(signal, latest_index, int(normalized_config["window"]))
    most_recent_signal_index = _matching_boolean_index(signal, latest_index, None)
    return _build_result(
        candles,
        requested_config,
        normalized_config,
        config_error,
        signal,
        matched_signal_index,
        most_recent_signal_index,
        {
            "source": source,
            "true_range": true_range,
            "atr": atr,
            "atr_distance": atr_distance,
            "stop": stop,
            "trend_up": trend_up,
            "trend_reversal": trend_reversal,
            "trend_change_to_up": trend_change_to_up,
            "trend_change_to_down": trend_change_to_down,
            "price_cross_stop": price_cross_stop,
            "in_limbo": in_limbo,
            "early_breach_up": early_breach_up,
            "early_breach_down": early_breach_down,
            "seconds_since_reversal": seconds_reversal,
            "seconds_since_change_to_uptrend": seconds_up,
            "seconds_since_change_to_downtrend": seconds_down,
            "seconds_since_early_breach_uptrend": seconds_early_up,
            "seconds_since_early_breach_downtrend": seconds_early_down,
            "alert_reversal": alert_reversal,
            "alert_change_to_uptrend": alert_up,
            "alert_change_to_downtrend": alert_down,
            "alert_early_breach_uptrend": alert_early_up,
            "alert_early_breach_downtrend": alert_early_down,
            "stop_distance_pct": stop_distance_pct,
            "label": "Volatility Stop",
            "debug": {
                "latest": _vstop_latest_trace(
                    candles,
                    source,
                    atr,
                    atr_distance,
                    stop,
                    trend_up,
                    trend_reversal,
                    trend_change_to_up,
                    trend_change_to_down,
                    price_cross_stop,
                    in_limbo,
                    early_breach_up,
                    early_breach_down,
                    alert_reversal,
                    alert_up,
                    alert_down,
                    alert_early_up,
                    alert_early_down,
                    stop_distance_pct,
                    signal,
                    latest_index,
                ),
            },
        },
    )


def _build_result(candles, requested_config, normalized_config, config_error, signal, matched_index, recent_index, payload):
    latest_index = len(candles) - 1
    matched_age = latest_index - matched_index if matched_index is not None else None
    recent_age = latest_index - recent_index if recent_index is not None else None
    debug_payload = dict(payload.pop("debug", {}))
    debug_payload.update({
        "requested_config": requested_config,
        "normalized_config": normalized_config,
        "effective_config": normalized_config,
        "config_error": config_error,
        "config_warnings": volatility_config_warnings(requested_config),
    })
    return {
        **payload,
        "signal": signal,
        "requested_config": requested_config,
        "normalized_config": normalized_config,
        "effective_config": normalized_config,
        "config_error": config_error,
        "candles": candles,
        "latest_index": latest_index,
        "matched_signal_index": matched_index,
        "matched_signal_age": matched_age,
        "most_recent_signal_index": recent_index,
        "most_recent_signal_age": recent_age,
        "debug": debug_payload,
    }


def _legacy_signal_series(values, config):
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    minimum = float(config.get("min_pct", 0) or 0)
    maximum = config.get("max_pct")
    signal = np.isfinite(values) & (values >= max(0.0, minimum - tolerance_pct))
    if maximum is not None:
        signal &= values <= float(maximum) + tolerance_pct
    return signal


def _vstop_signal_series(
    config,
    atr,
    stop_distance_pct,
    trend_up,
    trend_reversal,
    trend_change_to_up,
    trend_change_to_down,
    price_cross_stop,
    early_breach_up,
    early_breach_down,
    alert_reversal,
    alert_up,
    alert_down,
    alert_early_up,
    alert_early_down,
):
    rule = config["rule"]
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    if rule == "trend_reversal":
        return trend_reversal
    if rule == "change_to_uptrend":
        return trend_change_to_up
    if rule == "change_to_downtrend":
        return trend_change_to_down
    if rule == "uptrend":
        return trend_up
    if rule == "downtrend":
        return ~trend_up
    if rule == "price_cross_stop":
        return price_cross_stop
    if rule == "early_breach_uptrend":
        return early_breach_up
    if rule == "early_breach_downtrend":
        return early_breach_down
    if rule == "selected_alerts":
        signal = np.zeros(len(atr), dtype=bool)
        if config.get("trend_reversal_alert"):
            signal |= alert_reversal
        if config.get("change_to_uptrend_alert"):
            signal |= alert_up
        if config.get("change_to_downtrend_alert"):
            signal |= alert_down
        if config.get("chart_breach_uptrend_alert"):
            signal |= alert_early_up
        if config.get("chart_breach_downtrend_alert"):
            signal |= alert_early_down
        return signal
    if rule == "atr_above":
        minimum = float(config.get("min_atr") or 0.0) * (1 - tolerance_pct / 100.0)
        return np.isfinite(atr) & (atr >= minimum)
    if rule == "atr_below":
        maximum = float(config.get("max_atr") if config.get("max_atr") is not None else config.get("min_atr") or 0.0)
        return np.isfinite(atr) & (atr <= maximum * (1 + tolerance_pct / 100.0))
    if rule == "stop_distance_above_pct":
        minimum = float(config.get("min_stop_distance_pct") or 0.0) * (1 - tolerance_pct / 100.0)
        return np.isfinite(stop_distance_pct) & (stop_distance_pct >= minimum)
    if rule == "stop_distance_below_pct":
        maximum = float(config.get("max_stop_distance_pct") if config.get("max_stop_distance_pct") is not None else config.get("min_stop_distance_pct") or 0.0)
        return np.isfinite(stop_distance_pct) & (stop_distance_pct <= maximum * (1 + tolerance_pct / 100.0))
    if rule == "volatility_expansion":
        return _rising(atr)
    if rule == "volatility_contraction":
        return _falling(atr)
    return np.isfinite(atr)


def _vstop_series(source, true_range, atr, atr_factor):
    stop = np.full(len(source), NAN, dtype=float)
    trend_up = np.ones(len(source), dtype=bool)
    atr_distance = np.full(len(source), NAN, dtype=float)
    if len(source) == 0:
        return stop, trend_up, atr_distance

    max_source = NAN
    min_source = NAN
    for index, value in enumerate(source):
        if not np.isfinite(value):
            trend_up[index] = trend_up[index - 1] if index > 0 else True
            continue

        distance = atr[index] * atr_factor if np.isfinite(atr[index]) else true_range[index]
        atr_distance[index] = distance
        if not np.isfinite(distance):
            distance = 0.0

        if index == 0 or not np.isfinite(stop[index - 1]):
            max_source = value
            min_source = value
            stop[index] = value
            trend_up[index] = True
            continue

        previous_stop = stop[index - 1]
        previous_trend = bool(trend_up[index - 1])
        max_source = max(max_source, value) if np.isfinite(max_source) else value
        min_source = min(min_source, value) if np.isfinite(min_source) else value
        candidate_stop = max(previous_stop, max_source - distance) if previous_trend else min(previous_stop, min_source + distance)
        current_trend = value - candidate_stop >= 0.0

        if current_trend != previous_trend:
            max_source = value
            min_source = value
            candidate_stop = max_source - distance if current_trend else min_source + distance

        stop[index] = candidate_stop
        trend_up[index] = current_trend

    return stop, trend_up, atr_distance


def _pine_atr(true_range, length):
    values = np.asarray(true_range, dtype=float)
    output = np.full(len(values), NAN, dtype=float)
    if length <= 0 or len(values) < length:
        return output
    for index in range(length - 1, len(values)):
        if index == length - 1:
            window = values[:length]
            if np.any(~np.isfinite(window)):
                continue
            output[index] = float(np.mean(window))
            continue
        previous = output[index - 1]
        current = values[index]
        if not np.isfinite(previous) or not np.isfinite(current):
            continue
        output[index] = (previous * (length - 1) + current) / length
    return output


def _true_range(highs, lows, closes):
    output = np.full(len(highs), NAN, dtype=float)
    for index in range(len(highs)):
        high = highs[index]
        low = lows[index]
        if not np.isfinite(high) or not np.isfinite(low):
            continue
        if index == 0 or not np.isfinite(closes[index - 1]):
            output[index] = high - low
            continue
        previous_close = closes[index - 1]
        output[index] = max(high - low, abs(high - previous_close), abs(low - previous_close))
    return output


def _source_series(candles, source):
    opens = np.array([float(c.get("open", NAN)) for c in candles], dtype=float)
    highs = np.array([float(c.get("high", NAN)) for c in candles], dtype=float)
    lows = np.array([float(c.get("low", NAN)) for c in candles], dtype=float)
    closes = np.array([float(c.get("close", NAN)) for c in candles], dtype=float)
    normalized = str(source or "close").strip().lower()
    if normalized == "open":
        return opens
    if normalized == "high":
        return highs
    if normalized == "low":
        return lows
    if normalized == "hl2":
        return (highs + lows) / 2.0
    if normalized == "hlc3":
        return (highs + lows + closes) / 3.0
    if normalized == "ohlc4":
        return (opens + highs + lows + closes) / 4.0
    if normalized == "hlcc4":
        return (highs + lows + closes + closes) / 4.0
    return closes


def _safe_percent_returns(closes):
    series = np.asarray(closes, dtype=float)
    if series.size < 2:
        return np.array([], dtype=float)
    previous = series[:-1]
    current = series[1:]
    valid = np.isfinite(previous) & np.isfinite(current) & (previous != 0)
    if not np.any(valid):
        return np.array([], dtype=float)
    returns = (current[valid] - previous[valid]) / previous[valid]
    return returns[np.isfinite(returns)]


def _trend_reversal_series(trend_up):
    output = np.zeros(len(trend_up), dtype=bool)
    for index in range(1, len(trend_up)):
        output[index] = bool(trend_up[index] != trend_up[index - 1])
    return output


def _cross_series(left, right):
    output = np.zeros(len(left), dtype=bool)
    for index in range(1, len(left)):
        if not all(np.isfinite(value) for value in (left[index - 1], left[index], right[index - 1], right[index])):
            continue
        output[index] = (left[index - 1] <= right[index - 1] and left[index] > right[index]) or (
            left[index - 1] >= right[index - 1] and left[index] < right[index]
        )
    return output


def _breach_series(price_cross_stop, trend_reversal, trend_up, detect_breaches):
    in_limbo = np.zeros(len(price_cross_stop), dtype=bool)
    early_up = np.zeros(len(price_cross_stop), dtype=bool)
    early_down = np.zeros(len(price_cross_stop), dtype=bool)
    if not detect_breaches:
        return in_limbo, early_up, early_down

    for index in range(len(price_cross_stop)):
        previous_limbo = bool(in_limbo[index - 1]) if index > 0 else False
        previous_trend = bool(trend_up[index - 1]) if index > 0 else bool(trend_up[index])
        htf_breach = not previous_limbo and bool(price_cross_stop[index])
        early_up[index] = htf_breach and not bool(trend_reversal[index]) and bool(trend_up[index])
        early_down[index] = htf_breach and not bool(trend_reversal[index]) and not bool(trend_up[index])
        in_limbo[index] = (previous_limbo or htf_breach) and bool(trend_up[index]) == previous_trend
    return in_limbo, early_up, early_down


def _rising(values):
    output = np.zeros(len(values), dtype=bool)
    for index in range(1, len(values)):
        output[index] = np.isfinite(values[index]) and np.isfinite(values[index - 1]) and values[index] > values[index - 1]
    return output


def _falling(values):
    output = np.zeros(len(values), dtype=bool)
    for index in range(1, len(values)):
        output[index] = np.isfinite(values[index]) and np.isfinite(values[index - 1]) and values[index] < values[index - 1]
    return output


def _seconds_since(candles, condition):
    output = np.full(len(condition), NAN, dtype=float)
    last_time = None
    for index, active in enumerate(condition):
        current_time = _time_seconds(candles[index], index) if index < len(candles) else float(index)
        if bool(active):
            last_time = current_time
        if last_time is not None:
            output[index] = max(0.0, current_time - last_time)
    return output


def _time_seconds(candle, index):
    value = candle.get("time") or candle.get("datetime") or candle.get("date")
    if value is None:
        return float(index)
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric / 1000.0 if numeric > 10_000_000_000 else numeric
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float(index)


def _matching_boolean_index(series, latest_index, window):
    if latest_index < 0:
        return None
    start_index = 0 if window is None else max(0, latest_index - int(window) + 1)
    values = np.asarray(series, dtype=bool)
    for index in range(latest_index, start_index - 1, -1):
        if bool(values[index]):
            return index
    return None


def _completed_sorted_candles(candles):
    completed = []
    for candle in candles or []:
        if candle.get("is_closed") is False or candle.get("closed") is False or candle.get("complete") is False:
            continue
        completed.append(candle)
    return sorted(completed, key=lambda c: c.get("time") or c.get("datetime") or c.get("date") or 0)


def _to_bool(value):
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off"}
    return bool(value)


def _coerce_volatility_config_value(canonical, value):
    if canonical in {"length", "window"}:
        return max(1, int(value))
    if canonical in {
        "min_pct",
        "max_pct",
        "tolerance_pct",
        "atr_factor",
        "htf_multiple",
        "min_atr",
        "max_atr",
        "min_stop_distance_pct",
        "max_stop_distance_pct",
    }:
        if value is None and canonical in {"max_pct", "min_atr", "max_atr", "min_stop_distance_pct", "max_stop_distance_pct"}:
            return None
        return float(value)
    if canonical in {
        "detect_breaches",
        "repainting_htf",
        "trend_reversal_alert",
        "change_to_uptrend_alert",
        "change_to_downtrend_alert",
        "chart_breach_uptrend_alert",
        "chart_breach_downtrend_alert",
    }:
        return _to_bool(value)
    if canonical == "delay_minutes":
        return max(0.0, float(value))
    if canonical == "mode":
        return _normalize_mode(value)
    if canonical == "rule":
        return _normalize_rule(value)
    if canonical == "source":
        normalized = str(value or "close").strip().lower()
        if normalized not in {"open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4"}:
            raise VolatilityConfigError("Volatility source must be one of open, high, low, close, hl2, hlc3, ohlc4, hlcc4")
        return normalized
    return str(value or "").strip()


def _normalize_mode(value):
    normalized = str(value or "range_avg").strip().lower()
    aliases = {
        "range": "range_avg",
        "range_average": "range_avg",
        "daily_true_range": "daily",
        "realized": "returns_std",
        "returns": "returns_std",
        "volatility_stop": "vstop",
        "v-stop": "vstop",
        "volatility_stop_mtf": "vstop",
    }
    return aliases.get(normalized, normalized)


def _normalize_rule(value):
    normalized = str(value or "threshold").strip().lower()
    aliases = {
        "above": "threshold",
        "below": "threshold",
        "trend": "threshold",
        "reversal": "trend_reversal",
        "change_up": "change_to_uptrend",
        "up": "change_to_uptrend",
        "change_down": "change_to_downtrend",
        "down": "change_to_downtrend",
        "cross": "price_cross_stop",
        "cross_stop": "price_cross_stop",
        "expansion": "volatility_expansion",
        "contraction": "volatility_contraction",
        "chart_breach_of_htf_uptrend": "early_breach_uptrend",
        "chart_breach_of_htf_downtrend": "early_breach_downtrend",
        "alerts": "selected_alerts",
        "selected_alert_conditions": "selected_alerts",
    }
    return aliases.get(normalized, normalized)


def _htf_on(config):
    return str(config.get("htf_selection") or "").strip().lower() not in {"none", ""}


def _finite_float_or_default(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if np.isfinite(value) else default


def _volatility_decision(config, result):
    mode = config["mode"]
    if mode != "vstop":
        max_pct = config.get("max_pct")
        min_pct = config.get("min_pct")
        if max_pct is None and float(min_pct or 0) > 0:
            return "Range Expansion"
        if max_pct is not None and float(min_pct or 0) <= 0:
            return "Controlled Volatility"
        if max_pct is not None:
            return "Volatility Band Match"
        return "Volatility Match"

    rule = config["rule"]
    if rule == "trend_reversal":
        return "Volatility Stop Reversal"
    if rule == "change_to_uptrend":
        return "Change To Uptrend"
    if rule == "change_to_downtrend":
        return "Change To Downtrend"
    if rule == "uptrend":
        return "Uptrend State"
    if rule == "downtrend":
        return "Downtrend State"
    if rule == "price_cross_stop":
        return "Price Crossed Stop"
    if rule == "volatility_expansion":
        return "Volatility Expansion"
    if rule == "volatility_contraction":
        return "Volatility Contraction"
    return humanize_token(rule)


def _vstop_latest_trace(
    candles,
    source,
    atr,
    atr_distance,
    stop,
    trend_up,
    trend_reversal,
    trend_change_to_up,
    trend_change_to_down,
    price_cross_stop,
    in_limbo,
    early_breach_up,
    early_breach_down,
    alert_reversal,
    alert_up,
    alert_down,
    alert_early_up,
    alert_early_down,
    stop_distance_pct,
    signal,
    latest_index,
):
    if latest_index < 0:
        return {}
    return {
        "time": candles[latest_index].get("time") if candles else None,
        "source": _finite_float_or_default(source[latest_index], None),
        "atr": _finite_float_or_default(atr[latest_index], None),
        "atr_distance": _finite_float_or_default(atr_distance[latest_index], None),
        "stop": _finite_float_or_default(stop[latest_index], None),
        "trend_up": bool(trend_up[latest_index]),
        "trend_reversal": bool(trend_reversal[latest_index]),
        "trend_change_to_up": bool(trend_change_to_up[latest_index]),
        "trend_change_to_down": bool(trend_change_to_down[latest_index]),
        "price_cross_stop": bool(price_cross_stop[latest_index]),
        "in_limbo": bool(in_limbo[latest_index]),
        "early_breach_up": bool(early_breach_up[latest_index]),
        "early_breach_down": bool(early_breach_down[latest_index]),
        "alert_reversal": bool(alert_reversal[latest_index]),
        "alert_change_to_uptrend": bool(alert_up[latest_index]),
        "alert_change_to_downtrend": bool(alert_down[latest_index]),
        "alert_early_breach_uptrend": bool(alert_early_up[latest_index]),
        "alert_early_breach_downtrend": bool(alert_early_down[latest_index]),
        "stop_distance_pct": _finite_float_or_default(stop_distance_pct[latest_index], None),
        "final_signal": bool(signal[latest_index]),
    }

# services/volume.py

from datetime import datetime, timedelta, timezone

import math

import numpy as np
from services.pine_math import NAN, pine_alma, pine_ema, pine_rma, pine_sma, rolling_linreg
from services.utils import build_indicator_sticker, format_compact_number, format_decimal

DEFAULT_VOLUME_SPIKE_CONFIG = {
    "vol_ma": 100,
    "vol_x": 1.5,
    "only_valid_hl": True,
    "only_hammers_shooters": True,
    "only_same_color": False,
    "session": "0000-0000",
    "rule": "either",
    "window": 1,
    "tolerance_pct": 0.0,
}

VOLUME_SPIKE_ALIAS_GROUPS = {
    "vol_ma": ("vol_ma", "volume_sma_length", "length"),
    "vol_x": ("vol_x", "volume_multiplier", "multiplier"),
    "only_valid_hl": ("only_valid_hl", "only_valid_high_low"),
    "only_hammers_shooters": ("only_hammers_shooters", "only_hammers_and_shooters"),
    "only_same_color": ("only_same_color", "same_color"),
    "session": ("session",),
    "rule": ("rule", "action", "direction"),
    "window": ("window", "signal_window", "lookback"),
    "tolerance_pct": ("tolerance_pct",),
}

SUPPORTED_VOLUME_SPIKE_RULES = {"bullish", "bearish", "either"}
LEGACY_VOLUME_SPIKE_ALIAS_KEYS = {"length", "multiplier"}
LEGACY_VOLUME_SPIKE_ALIAS_FLAGS = {"allow_legacy_aliases", "use_legacy_aliases"}
TRADINGVIEW_VOLUME_SPIKE_DEFAULTS = {
    "vol_ma": DEFAULT_VOLUME_SPIKE_CONFIG["vol_ma"],
    "vol_x": DEFAULT_VOLUME_SPIKE_CONFIG["vol_x"],
    "only_valid_hl": DEFAULT_VOLUME_SPIKE_CONFIG["only_valid_hl"],
    "only_hammers_shooters": DEFAULT_VOLUME_SPIKE_CONFIG["only_hammers_shooters"],
    "only_same_color": DEFAULT_VOLUME_SPIKE_CONFIG["only_same_color"],
    "session": DEFAULT_VOLUME_SPIKE_CONFIG["session"],
}


class VolumeSpikeConfigError(ValueError):
    pass


DEFAULT_RELATIVE_VOLUME_CONFIG = {
    "lsma_length": 50,
    "avg_length": 30,
    "vol_alert": 200000000,
    "show_lsma_21": True,
    "show_lsma_6": True,
    "show_anomalies": True,
    "rule": "above",
    "min_ratio": 1.0,
    "max_ratio": None,
    "threshold": None,
    "window": 1,
    "tolerance_pct": 0.0,
}

RELATIVE_VOLUME_ALIAS_GROUPS = {
    "lsma_length": ("lsma_length", "lsmalength", "lsmaLength"),
    "avg_length": ("avg_length", "avglength", "average_length", "length", "lookback"),
    "vol_alert": ("vol_alert", "volalert", "volume_alert"),
    "show_lsma_21": ("show_lsma_21", "showlsma21"),
    "show_lsma_6": ("show_lsma_6", "showlsma6"),
    "show_anomalies": ("show_anomalies", "showanom"),
    "rule": ("rule", "condition", "signal"),
    "min_ratio": ("min_ratio", "ratio", "threshold"),
    "max_ratio": ("max_ratio",),
    "window": ("window", "signal_window", "lookback_candles"),
    "tolerance_pct": ("tolerance_pct", "tolerance"),
}

SUPPORTED_RELATIVE_VOLUME_RULES = {
    "above",
    "below",
    "between",
    "crossed_above",
    "crossed_below",
    "highest",
    "volume_alert",
    "increased_volume",
    "anomaly",
    "entry",
}

TRADINGVIEW_RELATIVE_VOLUME_DEFAULTS = {
    "lsma_length": DEFAULT_RELATIVE_VOLUME_CONFIG["lsma_length"],
    "avg_length": DEFAULT_RELATIVE_VOLUME_CONFIG["avg_length"],
    "vol_alert": DEFAULT_RELATIVE_VOLUME_CONFIG["vol_alert"],
    "show_lsma_21": DEFAULT_RELATIVE_VOLUME_CONFIG["show_lsma_21"],
    "show_lsma_6": DEFAULT_RELATIVE_VOLUME_CONFIG["show_lsma_6"],
    "show_anomalies": DEFAULT_RELATIVE_VOLUME_CONFIG["show_anomalies"],
}


class RelativeVolumeConfigError(ValueError):
    pass


DEFAULT_CURRENT_VOLUME_CONFIG = {
    "atr_length": 14,
    "smoothing": "RMA",
    "atr_multiplier": 0.5,
    "avg_count": 30,
    "enable_percentage_on_chart": True,
    "rule": "value",
    "min_value": None,
    "max_value": None,
    "min_percent_avg": None,
    "max_percent_avg": None,
    "window": 1,
    "tolerance_pct": 0.0,
}

CURRENT_VOLUME_ALIAS_GROUPS = {
    "atr_length": ("atr_length", "atr_period", "length"),
    "smoothing": ("smoothing",),
    "atr_multiplier": ("atr_multiplier", "atrmultiplier"),
    "avg_count": ("avg_count", "avgCnt", "average_length", "average_bars"),
    "enable_percentage_on_chart": ("enable_percentage_on_chart", "enablePercentageOnChart"),
    "rule": ("rule", "condition", "signal"),
    "min_value": ("min_value", "minimum_volume"),
    "max_value": ("max_value", "maximum_volume"),
    "min_percent_avg": ("min_percent_avg", "minimum_percent_avg", "min_rvol_percent"),
    "max_percent_avg": ("max_percent_avg", "maximum_percent_avg", "max_rvol_percent"),
    "window": ("window", "signal_window", "lookback_candles"),
    "tolerance_pct": ("tolerance_pct", "tolerance"),
}

SUPPORTED_CURRENT_VOLUME_RULES = {
    "value",
    "above_average_percent",
    "below_average_percent",
    "between_average_percent",
    "above_average",
}

TRADINGVIEW_CURRENT_VOLUME_DEFAULTS = {
    "atr_length": DEFAULT_CURRENT_VOLUME_CONFIG["atr_length"],
    "smoothing": DEFAULT_CURRENT_VOLUME_CONFIG["smoothing"],
    "atr_multiplier": DEFAULT_CURRENT_VOLUME_CONFIG["atr_multiplier"],
    "avg_count": DEFAULT_CURRENT_VOLUME_CONFIG["avg_count"],
    "enable_percentage_on_chart": DEFAULT_CURRENT_VOLUME_CONFIG["enable_percentage_on_chart"],
}


class CurrentVolumeConfigError(ValueError):
    pass


# =========================================================
# VOLUME SPIKE
# =========================================================

def evaluate_volume_spike(candles, config):
    result = compute_volume_spikes(candles, config)
    if result["config_error"]:
        raise VolumeSpikeConfigError(result["config_error"])

    return result["matched_signal_index"] is not None


def compute_volume_spikes(candles, config):
    requested_config = dict(config or {})
    normalized_config, config_error = normalize_volume_spike_config(requested_config)
    candles = _completed_sorted_candles(candles)
    volumes = np.array([float(c.get("volume", 0) or 0) for c in candles], dtype=float)
    opens = np.array([float(c.get("open", 0) or 0) for c in candles], dtype=float)
    highs = np.array([float(c.get("high", 0) or 0) for c in candles], dtype=float)
    lows = np.array([float(c.get("low", 0) or 0) for c in candles], dtype=float)
    closes = np.array([float(c.get("close", 0) or 0) for c in candles], dtype=float)

    length = int(normalized_config["vol_ma"])
    multiplier = float(normalized_config["vol_x"])

    volume_sma = pine_sma(volumes, length)
    in_session = np.array([_in_session(candle, normalized_config) for candle in candles], dtype=bool)
    vol_check = np.isfinite(volume_sma) & (volumes > volume_sma * multiplier) & in_session

    distance_hl = highs - lows
    valid_hammer = (opens > lows + distance_hl / 2.0) & (closes > lows + distance_hl / 2.0)
    valid_shooter = (opens < lows + distance_hl / 2.0) & (closes < lows + distance_hl / 2.0)

    result_bullish = np.zeros(len(candles), dtype=bool)
    result_bearish = np.zeros(len(candles), dtype=bool)
    candidate_bullish = np.zeros(len(candles), dtype=bool)
    candidate_bearish = np.zeros(len(candles), dtype=bool)

    only_valid_hl = bool(normalized_config["only_valid_hl"])
    only_hammers_shooters = bool(normalized_config["only_hammers_shooters"])
    only_same_color = bool(normalized_config["only_same_color"])

    candidate_trace = {}
    for index in range(2, len(candles)):
        candidate = index - 1

        valid_high = highs[candidate] > highs[candidate - 1] and highs[candidate] > highs[index] if only_valid_hl else True
        valid_low = lows[candidate] < lows[candidate - 1] and lows[candidate] < lows[index] if only_valid_hl else True
        base_valid_high = bool(valid_high)
        base_valid_low = bool(valid_low)
        same_color_bearish = closes[candidate] < opens[candidate]
        same_color_bullish = closes[candidate] > opens[candidate]

        if only_hammers_shooters:
            valid_high = valid_high and bool(valid_shooter[candidate])
            valid_low = valid_low and bool(valid_hammer[candidate])

        if only_same_color:
            valid_high = valid_high and same_color_bearish
            valid_low = valid_low and same_color_bullish

        candidate_bearish[candidate] = bool(valid_high and vol_check[candidate])
        candidate_bullish[candidate] = bool(valid_low and vol_check[candidate])
        result_bearish[index] = candidate_bearish[candidate]
        result_bullish[index] = candidate_bullish[candidate]
        if index == len(candles) - 1:
            threshold = float(volume_sma[candidate] * multiplier) if np.isfinite(volume_sma[candidate]) else float("nan")
            candidate_trace = {
                "index_2_time": candles[candidate - 1].get("time"),
                "index_1_time": candles[candidate].get("time"),
                "index_0_time": candles[index].get("time"),
                "sma": _finite_float(volume_sma[candidate]),
                "spike_volume": float(volumes[candidate]) if len(volumes) > candidate else None,
                "volume_threshold": _finite_float(threshold),
                "vol_check": bool(vol_check[candidate]),
                "valid_high": base_valid_high,
                "valid_low": base_valid_low,
                "valid_hammer": bool(valid_hammer[candidate]),
                "valid_shooter": bool(valid_shooter[candidate]),
                "same_color_bullish": bool(same_color_bullish),
                "same_color_bearish": bool(same_color_bearish),
                "session": bool(in_session[candidate]),
                "bullish_result": bool(result_bullish[index]),
                "bearish_result": bool(result_bearish[index]),
                "selected_rule": normalized_config["rule"],
                "final_result": _rule_result(
                    normalized_config["rule"],
                    bool(result_bullish[index]),
                    bool(result_bearish[index]),
                ),
            }

    rule = normalized_config["rule"]
    window = int(normalized_config["window"])
    latest_index = len(candles) - 1
    matched_signal_index = _matching_signal_index(result_bullish, result_bearish, rule, latest_index, window)
    most_recent_signal_index = _matching_signal_index(result_bullish, result_bearish, rule, latest_index, None)
    matched_signal_age = latest_index - matched_signal_index if matched_signal_index is not None else None
    most_recent_signal_age = latest_index - most_recent_signal_index if most_recent_signal_index is not None else None

    if candidate_trace:
        candidate_trace.update({
            "window": window,
            "matched_signal_index": matched_signal_index,
            "matched_signal_age": matched_signal_age,
            "most_recent_signal_index": most_recent_signal_index,
            "most_recent_signal_age": most_recent_signal_age,
        })

    return {
        "volume_sma": volume_sma,
        "vol_check": vol_check,
        "valid_hammer": valid_hammer,
        "valid_shooter": valid_shooter,
        "candidate_bullish": candidate_bullish,
        "candidate_bearish": candidate_bearish,
        "result_bullish": result_bullish,
        "result_bearish": result_bearish,
        "length": length,
        "multiplier": multiplier,
        "adjusted_multiplier": multiplier,
        "requested_config": requested_config,
        "normalized_config": normalized_config,
        "effective_config": normalized_config,
        "config_error": config_error,
        "candles": candles,
        "latest_index": latest_index,
        "matched_signal_index": matched_signal_index,
        "matched_signal_age": matched_signal_age,
        "most_recent_signal_index": most_recent_signal_index,
        "most_recent_signal_age": most_recent_signal_age,
        "debug": {
            "requested_config": requested_config,
            "normalized_config": normalized_config,
            "effective_config": normalized_config,
            "config_error": config_error,
            "config_warnings": volume_spike_config_warnings(requested_config),
            "candidate": candidate_trace,
        },
    }


# =========================================================
# STICKER
# =========================================================

def build_volume_sticker(candles, config):
    result = compute_volume_spikes(candles, config)
    if result["config_error"]:
        raise VolumeSpikeConfigError(result["config_error"])
    volumes = np.array([float(c.get("volume", 0) or 0) for c in result["candles"]], dtype=float)
    length = result["length"]
    matched_index = result["matched_signal_index"]
    signal_index = matched_index - 1 if matched_index is not None else len(volumes) - 2
    average = float(result["volume_sma"][signal_index]) if signal_index >= 0 and np.isfinite(result["volume_sma"][signal_index]) else 0.0
    current = float(volumes[signal_index]) if signal_index >= 0 and len(volumes) else 0.0
    ratio = (current / average) if average > 0 else 0.0
    window = int(result["effective_config"]["window"])
    age = result["matched_signal_age"]
    timing = "latest confirmed spike" if age == 0 else f"confirmed spike {age} bars ago"
    return build_indicator_sticker(
        "Volume",
        f"{format_decimal(ratio, 2)}x SMA({length}) on {timing} ({format_compact_number(current)} vs {format_compact_number(average)})",
        {"window": window, "confirmation": False},
        length=length,
        window=window,
        decision="Volume Expansion",
    )


def normalize_volume_spike_config(config):
    requested = dict(config or {})
    normalized = dict(DEFAULT_VOLUME_SPIKE_CONFIG)

    try:
        for canonical, keys in VOLUME_SPIKE_ALIAS_GROUPS.items():
            present = [(key, requested[key]) for key in keys if key in requested and requested[key] is not None]
            if not present:
                continue
            coerced_values = [_coerce_config_value(canonical, value) for _key, value in present]
            first_value = coerced_values[0]
            conflicts = [
                f"{key}={value}"
                for (key, raw), value in zip(present, coerced_values)
                if value != first_value
            ]
            if conflicts:
                all_values = ", ".join(f"{key}={_coerce_config_value(canonical, raw)}" for key, raw in present)
                raise VolumeSpikeConfigError(f"Conflicting Volume Spikes config aliases for {canonical}: {all_values}")
            normalized[canonical] = first_value

        if normalized["rule"] not in SUPPORTED_VOLUME_SPIKE_RULES:
            raise VolumeSpikeConfigError(
                f"Unsupported Volume Spikes rule '{normalized['rule']}'. Supported rules: bullish, bearish, either"
            )

        return normalized, None
    except (TypeError, ValueError) as exc:
        return normalized, str(exc)


def required_volume_spike_candles(config):
    normalized, error = normalize_volume_spike_config(config)
    if error:
        return int(DEFAULT_VOLUME_SPIKE_CONFIG["vol_ma"]) + 2
    return int(normalized["vol_ma"]) + 2 + max(0, int(normalized.get("window", 1)) - 1)


def volume_spike_config_warnings(config):
    requested = dict(config or {})
    normalized, error = normalize_volume_spike_config(requested)
    warnings = []

    if error:
        warnings.append({
            "code": "VOLUME_SPIKES_CONFIG_ERROR",
            "message": error,
            "requested_config": requested,
            "effective_config": normalized,
        })
        return warnings

    legacy_keys = sorted(
        key
        for key in ("length", "multiplier")
        if key in requested and requested[key] is not None
    )
    if legacy_keys:
        warnings.append({
            "code": "VOLUME_SPIKES_LEGACY_ALIASES",
            "message": (
                "Volume Spikes request used generic aliases. The backend normalized them to the "
                "canonical TFO schema; compare TradingView using the effective vol_x/vol_ma values."
            ),
            "legacy_keys": legacy_keys,
            "requested_config": requested,
            "effective_config": normalized,
        })

    differing_defaults = {
        key: {
            "backend": normalized.get(key),
            "tradingview_default": value,
        }
        for key, value in TRADINGVIEW_VOLUME_SPIKE_DEFAULTS.items()
        if normalized.get(key) != value
    }
    if differing_defaults:
        warnings.append({
            "code": "VOLUME_SPIKES_TV_DEFAULT_MISMATCH_RISK",
            "message": (
                "Volume Spikes effective config differs from the TradingView TFO default inputs. "
                "This is valid for custom scans, but TradingView validation must use the same values."
            ),
            "differences": differing_defaults,
            "requested_config": requested,
            "effective_config": normalized,
        })

    return warnings


def volume_spike_signal_warnings(candles, config):
    result = compute_volume_spikes(candles, config)
    if result["config_error"]:
        return []

    window = int(result["effective_config"]["window"])
    matched_index = result["matched_signal_index"]
    most_recent_index = result["most_recent_signal_index"]
    most_recent_age = result["most_recent_signal_age"]

    if matched_index is not None and result["matched_signal_age"] and result["matched_signal_age"] > 0:
        return [{
            "code": "VOLUME_SPIKES_SIGNAL_WITHIN_WINDOW_NOT_LATEST",
            "message": (
                "Volume Spikes passed because a matching confirmed signal exists inside the "
                "configured window, but it was not created by the latest completed candle."
            ),
            "window": window,
            "signal_age": result["matched_signal_age"],
            "effective_config": result["effective_config"],
        }]

    if matched_index is None and most_recent_index is not None:
        return [{
            "code": "VOLUME_SPIKES_STALE_SIGNAL_OUTSIDE_WINDOW",
            "message": (
                "TradingView may show an older Volume Spikes marker, but the backend did not pass "
                "because the most recent matching signal is outside the configured window."
            ),
            "window": window,
            "signal_age": most_recent_age,
            "effective_config": result["effective_config"],
        }]

    return []


def volume_spike_debug_trace(candles, config, symbol=None, timeframe=None):
    result = compute_volume_spikes(candles, config)
    trace = dict(result["debug"])
    trace["symbol"] = symbol
    trace["timeframe"] = timeframe
    trace["candle_count"] = len(result["candles"])
    trace["latest_index"] = result["latest_index"]
    trace["matched_signal_index"] = result["matched_signal_index"]
    trace["matched_signal_age"] = result["matched_signal_age"]
    trace["most_recent_signal_index"] = result["most_recent_signal_index"]
    trace["most_recent_signal_age"] = result["most_recent_signal_age"]
    trace["signal_warnings"] = volume_spike_signal_warnings(candles, config)
    return trace


# =========================================================
# RELATIVE VOLUME (veryfid TradingView RVOL)
# =========================================================

def evaluate_relative_volume(candles, config):
    result = compute_relative_volume(candles, config)
    if result["config_error"]:
        raise RelativeVolumeConfigError(result["config_error"])
    return result["matched_signal_index"] is not None


def compute_relative_volume(candles, config):
    requested_config = dict(config or {})
    normalized_config, config_error = normalize_relative_volume_config(requested_config)
    candles = _completed_sorted_candles(candles)
    volumes = np.array([float(c.get("volume", 0) or 0) for c in candles], dtype=float)

    avg_length = int(normalized_config["avg_length"])
    lsma_length = int(normalized_config["lsma_length"])
    vol_alert = float(normalized_config["vol_alert"])
    window = int(normalized_config["window"])
    rule = normalized_config["rule"]
    latest_index = len(candles) - 1

    ma1 = pine_sma(volumes, 20)
    ma2 = rolling_linreg(volumes, lsma_length, offset=0)
    ma3 = rolling_linreg(volumes, 21, offset=0)
    ma4 = rolling_linreg(volumes, 6, offset=0)
    lsma2 = rolling_linreg(ma2, 20, offset=0)
    zlsma = ma2 + (ma2 - lsma2)
    trend_delta = zlsma - ma2
    std_dev = _pine_stdev(volumes, 21)
    hull_ma = _pine_hma(volumes, 21)
    alma = pine_alma(volumes, 9)

    previous_average = _previous_average_series(volumes, avg_length)
    rvol = np.full(len(volumes), NAN, dtype=float)
    valid_avg = np.isfinite(previous_average) & (previous_average > 0)
    rvol[valid_avg] = volumes[valid_avg] / previous_average[valid_avg]

    entry_signal = _relative_volume_entry_signal(
        ma2,
        ma3,
        ma4,
        show_lsma_21=bool(normalized_config["show_lsma_21"]),
        show_lsma_6=bool(normalized_config["show_lsma_6"]),
    )
    volume_alert = _crossed_above(volumes, vol_alert)
    increased_volume = np.isfinite(ma2) & (volumes > ma2)
    anomaly = bool(normalized_config["show_anomalies"]) & np.isfinite(ma2) & np.isfinite(std_dev) & ((volumes - ma2) > std_dev)

    signal = _relative_volume_signal_series(
        rule,
        rvol,
        volumes,
        entry_signal,
        volume_alert,
        increased_volume,
        anomaly,
        normalized_config,
    )
    matched_signal_index = _matching_boolean_index(signal, latest_index, window)
    most_recent_signal_index = _matching_boolean_index(signal, latest_index, None)
    matched_signal_age = latest_index - matched_signal_index if matched_signal_index is not None else None
    most_recent_signal_age = latest_index - most_recent_signal_index if most_recent_signal_index is not None else None

    return {
        "rvol": rvol,
        "previous_average": previous_average,
        "ma1": ma1,
        "ma2": ma2,
        "ma3": ma3,
        "ma4": ma4,
        "lsma2": lsma2,
        "zlsma": zlsma,
        "trend_delta": trend_delta,
        "std_dev": std_dev,
        "hull_ma": hull_ma,
        "alma": alma,
        "entry_signal": entry_signal,
        "volume_alert": volume_alert,
        "increased_volume": increased_volume,
        "anomaly": anomaly,
        "signal": signal,
        "requested_config": requested_config,
        "normalized_config": normalized_config,
        "effective_config": normalized_config,
        "config_error": config_error,
        "candles": candles,
        "latest_index": latest_index,
        "matched_signal_index": matched_signal_index,
        "matched_signal_age": matched_signal_age,
        "most_recent_signal_index": most_recent_signal_index,
        "most_recent_signal_age": most_recent_signal_age,
        "debug": {
            "requested_config": requested_config,
            "normalized_config": normalized_config,
            "effective_config": normalized_config,
            "config_error": config_error,
            "config_warnings": relative_volume_config_warnings(requested_config),
            "latest": _relative_volume_latest_trace(
                candles,
                volumes,
                rvol,
                previous_average,
                ma2,
                std_dev,
                trend_delta,
                entry_signal,
                volume_alert,
                increased_volume,
                anomaly,
                signal,
                latest_index,
            ),
        },
    }


def build_relative_volume_sticker(candles, config):
    result = compute_relative_volume(candles, config)
    if result["config_error"]:
        raise RelativeVolumeConfigError(result["config_error"])

    index = result["matched_signal_index"]
    if index is None:
        index = result["latest_index"]

    rvol = _finite_float_or_default(result["rvol"][index], 0.0) if index >= 0 else 0.0
    average = _finite_float_or_default(result["previous_average"][index], 0.0) if index >= 0 else 0.0
    current = float((result["candles"][index] or {}).get("volume", 0) or 0) if index >= 0 and result["candles"] else 0.0
    age = result["matched_signal_age"]
    timing = "latest candle" if age in {None, 0} else f"{age} bars ago"
    cfg = result["effective_config"]
    return build_indicator_sticker(
        "Relative Volume",
        f"{format_decimal(rvol, 2)}x average on {timing} ({format_compact_number(current)} vs {format_compact_number(average)})",
        {"window": int(cfg["window"]), "confirmation": False},
        length=int(cfg["avg_length"]),
        window=int(cfg["window"]),
        decision=_relative_volume_decision(cfg["rule"]),
    )


def normalize_relative_volume_config(config):
    requested = dict(config or {})
    normalized = dict(DEFAULT_RELATIVE_VOLUME_CONFIG)

    try:
        for canonical, keys in RELATIVE_VOLUME_ALIAS_GROUPS.items():
            present = [(key, requested[key]) for key in keys if key in requested and requested[key] is not None]
            if not present:
                continue
            coerced_values = [_coerce_relative_volume_config_value(canonical, value) for _key, value in present]
            first_value = coerced_values[0]
            conflicts = [
                f"{key}={value}"
                for (key, raw), value in zip(present, coerced_values)
                if value != first_value
            ]
            if conflicts:
                all_values = ", ".join(f"{key}={_coerce_relative_volume_config_value(canonical, raw)}" for key, raw in present)
                raise RelativeVolumeConfigError(f"Conflicting Relative Volume config aliases for {canonical}: {all_values}")
            normalized[canonical] = first_value

        if normalized["threshold"] is not None:
            normalized["min_ratio"] = float(normalized["threshold"])

        if normalized["rule"] not in SUPPORTED_RELATIVE_VOLUME_RULES:
            raise RelativeVolumeConfigError(
                f"Unsupported Relative Volume rule '{normalized['rule']}'. Supported rules: {', '.join(sorted(SUPPORTED_RELATIVE_VOLUME_RULES))}"
            )

        if normalized["rule"] == "between" and normalized["max_ratio"] is None:
            raise RelativeVolumeConfigError("Relative Volume rule 'between' requires max_ratio")

        return normalized, None
    except (TypeError, ValueError) as exc:
        return normalized, str(exc)


def required_relative_volume_candles(config):
    normalized, error = normalize_relative_volume_config(config)
    if error:
        normalized = dict(DEFAULT_RELATIVE_VOLUME_CONFIG)

    avg_length = int(normalized["avg_length"])
    lsma_length = int(normalized["lsma_length"])
    window = max(1, int(normalized["window"]))
    return max(
        avg_length + 1,
        lsma_length + 20,
        21 + int(math.floor(math.sqrt(21))),
        21,
    ) + window - 1


def relative_volume_config_warnings(config):
    requested = dict(config or {})
    normalized, error = normalize_relative_volume_config(requested)
    warnings = []

    if error:
        warnings.append({
            "code": "RELATIVE_VOLUME_CONFIG_ERROR",
            "message": error,
            "requested_config": requested,
            "effective_config": normalized,
        })
        return warnings

    differing_defaults = {
        key: {
            "backend": normalized.get(key),
            "tradingview_default": value,
        }
        for key, value in TRADINGVIEW_RELATIVE_VOLUME_DEFAULTS.items()
        if normalized.get(key) != value
    }
    if differing_defaults:
        warnings.append({
            "code": "RELATIVE_VOLUME_TV_DEFAULT_MISMATCH_RISK",
            "message": (
                "Relative Volume effective config differs from the TradingView script defaults. "
                "TradingView validation must use the same input values."
            ),
            "differences": differing_defaults,
            "requested_config": requested,
            "effective_config": normalized,
        })

    return warnings


def relative_volume_signal_warnings(candles, config):
    result = compute_relative_volume(candles, config)
    if result["config_error"]:
        return []

    if result["matched_signal_index"] is not None and result["matched_signal_age"] and result["matched_signal_age"] > 0:
        return [{
            "code": "RELATIVE_VOLUME_SIGNAL_WITHIN_WINDOW_NOT_LATEST",
            "message": (
                "Relative Volume passed because a matching signal exists inside the configured "
                "window, but it was not created by the latest completed candle."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["matched_signal_age"],
            "effective_config": result["effective_config"],
        }]

    if result["matched_signal_index"] is None and result["most_recent_signal_index"] is not None:
        return [{
            "code": "RELATIVE_VOLUME_STALE_SIGNAL_OUTSIDE_WINDOW",
            "message": (
                "TradingView may show an older Relative Volume signal, but the backend did not pass "
                "because the most recent matching signal is outside the configured window."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["most_recent_signal_age"],
            "effective_config": result["effective_config"],
        }]

    return []


def relative_volume_debug_trace(candles, config, symbol=None, timeframe=None):
    result = compute_relative_volume(candles, config)
    trace = dict(result["debug"])
    trace["symbol"] = symbol
    trace["timeframe"] = timeframe
    trace["candle_count"] = len(result["candles"])
    trace["latest_index"] = result["latest_index"]
    trace["matched_signal_index"] = result["matched_signal_index"]
    trace["matched_signal_age"] = result["matched_signal_age"]
    trace["most_recent_signal_index"] = result["most_recent_signal_index"]
    trace["most_recent_signal_age"] = result["most_recent_signal_age"]
    trace["signal_warnings"] = relative_volume_signal_warnings(candles, config)
    return trace


# =========================================================
# CURRENT VOLUME (dalozification TradingView table)
# =========================================================

def evaluate_current_volume(candles, config):
    result = compute_current_volume(candles, config)
    if result["config_error"]:
        raise CurrentVolumeConfigError(result["config_error"])
    return result["matched_signal_index"] is not None


def compute_current_volume(candles, config):
    requested_config = dict(config or {})
    normalized_config, config_error = normalize_current_volume_config(requested_config)
    candles = _completed_sorted_candles(candles)
    volumes = np.array([float(c.get("volume", 0) or 0) for c in candles], dtype=float)
    highs = np.array([float(c.get("high", 0) or 0) for c in candles], dtype=float)
    lows = np.array([float(c.get("low", 0) or 0) for c in candles], dtype=float)
    closes = np.array([float(c.get("close", 0) or 0) for c in candles], dtype=float)

    atr_length = int(normalized_config["atr_length"])
    avg_count = int(normalized_config["avg_count"])
    atr_multiplier = float(normalized_config["atr_multiplier"])
    smoothing = str(normalized_config["smoothing"])
    window = int(normalized_config["window"])
    latest_index = len(candles) - 1

    true_range = _true_range(highs, lows, closes)
    catr = _current_volume_ma_function(true_range, atr_length, smoothing)
    atr_value = catr * atr_multiplier
    current_avg_volume = pine_sma(volumes, avg_count)
    percent_avg = np.full(len(volumes), NAN, dtype=float)
    valid_avg = np.isfinite(current_avg_volume) & (current_avg_volume > 0)
    percent_avg[valid_avg] = _round_half_up((volumes[valid_avg] / current_avg_volume[valid_avg]) * 100.0)
    color_state = _current_volume_color_state(percent_avg)
    codiff = np.isfinite(percent_avg) & (percent_avg >= 100.0)

    signal = _current_volume_signal_series(
        volumes,
        percent_avg,
        normalized_config,
    )
    matched_signal_index = _matching_boolean_index(signal, latest_index, window)
    most_recent_signal_index = _matching_boolean_index(signal, latest_index, None)
    matched_signal_age = latest_index - matched_signal_index if matched_signal_index is not None else None
    most_recent_signal_age = latest_index - most_recent_signal_index if most_recent_signal_index is not None else None

    return {
        "current_volume": volumes,
        "current_avg_volume": current_avg_volume,
        "current_resolution_percent_avg": percent_avg,
        "true_range": true_range,
        "catr": catr,
        "atr_value": atr_value,
        "color_state": color_state,
        "codiff": codiff,
        "signal": signal,
        "requested_config": requested_config,
        "normalized_config": normalized_config,
        "effective_config": normalized_config,
        "config_error": config_error,
        "candles": candles,
        "latest_index": latest_index,
        "matched_signal_index": matched_signal_index,
        "matched_signal_age": matched_signal_age,
        "most_recent_signal_index": most_recent_signal_index,
        "most_recent_signal_age": most_recent_signal_age,
        "debug": {
            "requested_config": requested_config,
            "normalized_config": normalized_config,
            "effective_config": normalized_config,
            "config_error": config_error,
            "config_warnings": current_volume_config_warnings(requested_config),
            "latest": _current_volume_latest_trace(
                candles,
                volumes,
                current_avg_volume,
                percent_avg,
                atr_value,
                color_state,
                codiff,
                signal,
                latest_index,
            ),
        },
    }


def build_current_volume_sticker(candles, config):
    result = compute_current_volume(candles, config)
    if result["config_error"]:
        raise CurrentVolumeConfigError(result["config_error"])

    index = result["matched_signal_index"]
    if index is None:
        index = result["latest_index"]

    current = _finite_float_or_default(result["current_volume"][index], 0.0) if index >= 0 else 0.0
    average = _finite_float_or_default(result["current_avg_volume"][index], None) if index >= 0 else None
    percent = _finite_float_or_default(result["current_resolution_percent_avg"][index], None) if index >= 0 else None
    atr_value = _finite_float_or_default(result["atr_value"][index], None) if index >= 0 else None
    age = result["matched_signal_age"]
    timing = "latest candle" if age in {None, 0} else f"{age} bars ago"
    parts = [f"{format_compact_number(current)} traded on {timing}"]
    if average is not None and percent is not None:
        parts.append(f"{format_decimal(percent, 0)}% of {format_compact_number(average)} average")
    if atr_value is not None:
        parts.append(f"ATR {format_decimal(atr_value, 2)}")

    return build_indicator_sticker(
        "Current Volume",
        "; ".join(parts),
        {"window": int(result["effective_config"]["window"]), "confirmation": False},
        window=int(result["effective_config"]["window"]),
        decision=_current_volume_decision(result["effective_config"]["rule"]),
    )


def normalize_current_volume_config(config):
    requested = dict(config or {})
    normalized = dict(DEFAULT_CURRENT_VOLUME_CONFIG)

    try:
        for canonical, keys in CURRENT_VOLUME_ALIAS_GROUPS.items():
            present = [(key, requested[key]) for key in keys if key in requested and requested[key] is not None]
            if not present:
                continue
            coerced_values = [_coerce_current_volume_config_value(canonical, value) for _key, value in present]
            first_value = coerced_values[0]
            conflicts = [
                f"{key}={value}"
                for (key, raw), value in zip(present, coerced_values)
                if value != first_value
            ]
            if conflicts:
                all_values = ", ".join(f"{key}={_coerce_current_volume_config_value(canonical, raw)}" for key, raw in present)
                raise CurrentVolumeConfigError(f"Conflicting Current Volume config aliases for {canonical}: {all_values}")
            normalized[canonical] = first_value

        if normalized["rule"] not in SUPPORTED_CURRENT_VOLUME_RULES:
            raise CurrentVolumeConfigError(
                f"Unsupported Current Volume rule '{normalized['rule']}'. Supported rules: {', '.join(sorted(SUPPORTED_CURRENT_VOLUME_RULES))}"
            )

        if normalized["rule"] == "between_average_percent" and normalized["max_percent_avg"] is None:
            raise CurrentVolumeConfigError("Current Volume rule 'between_average_percent' requires max_percent_avg")

        return normalized, None
    except (TypeError, ValueError) as exc:
        return normalized, str(exc)


def required_current_volume_candles(config):
    normalized, error = normalize_current_volume_config(config)
    if error:
        normalized = dict(DEFAULT_CURRENT_VOLUME_CONFIG)
    return max(
        1,
        int(normalized["avg_count"]),
        int(normalized["atr_length"]),
    ) + max(0, int(normalized.get("window", 1) or 1) - 1)


def current_volume_config_warnings(config):
    requested = dict(config or {})
    normalized, error = normalize_current_volume_config(requested)
    warnings = []

    if error:
        warnings.append({
            "code": "CURRENT_VOLUME_CONFIG_ERROR",
            "message": error,
            "requested_config": requested,
            "effective_config": normalized,
        })
        return warnings

    differing_defaults = {
        key: {
            "backend": normalized.get(key),
            "tradingview_default": value,
        }
        for key, value in TRADINGVIEW_CURRENT_VOLUME_DEFAULTS.items()
        if normalized.get(key) != value
    }
    if differing_defaults:
        warnings.append({
            "code": "CURRENT_VOLUME_TV_DEFAULT_MISMATCH_RISK",
            "message": (
                "Current Volume effective config differs from the TradingView script defaults. "
                "TradingView validation must use the same input values."
            ),
            "differences": differing_defaults,
            "requested_config": requested,
            "effective_config": normalized,
        })

    return warnings


def current_volume_signal_warnings(candles, config):
    result = compute_current_volume(candles, config)
    if result["config_error"]:
        return []

    if result["matched_signal_index"] is not None and result["matched_signal_age"] and result["matched_signal_age"] > 0:
        return [{
            "code": "CURRENT_VOLUME_SIGNAL_WITHIN_WINDOW_NOT_LATEST",
            "message": (
                "Current Volume passed because a matching signal exists inside the configured "
                "window, but it was not created by the latest completed candle."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["matched_signal_age"],
            "effective_config": result["effective_config"],
        }]

    if result["matched_signal_index"] is None and result["most_recent_signal_index"] is not None:
        return [{
            "code": "CURRENT_VOLUME_STALE_SIGNAL_OUTSIDE_WINDOW",
            "message": (
                "TradingView may show an older Current Volume condition, but the backend did not pass "
                "because the most recent matching signal is outside the configured window."
            ),
            "window": int(result["effective_config"]["window"]),
            "signal_age": result["most_recent_signal_age"],
            "effective_config": result["effective_config"],
        }]

    return []


def current_volume_debug_trace(candles, config, symbol=None, timeframe=None):
    result = compute_current_volume(candles, config)
    trace = dict(result["debug"])
    trace["symbol"] = symbol
    trace["timeframe"] = timeframe
    trace["candle_count"] = len(result["candles"])
    trace["latest_index"] = result["latest_index"]
    trace["matched_signal_index"] = result["matched_signal_index"]
    trace["matched_signal_age"] = result["matched_signal_age"]
    trace["most_recent_signal_index"] = result["most_recent_signal_index"]
    trace["most_recent_signal_age"] = result["most_recent_signal_age"]
    trace["signal_warnings"] = current_volume_signal_warnings(candles, config)
    return trace


def _coerce_config_value(canonical, value):
    if canonical == "vol_ma":
        return max(1, int(value))
    if canonical == "vol_x":
        return float(value)
    if canonical in {"only_valid_hl", "only_hammers_shooters", "only_same_color"}:
        return _to_bool(value)
    if canonical == "rule":
        return _normalize_rule(value)
    if canonical == "window":
        return max(1, int(value))
    if canonical == "tolerance_pct":
        return float(value or 0)
    if canonical == "session":
        return str(value or DEFAULT_VOLUME_SPIKE_CONFIG["session"]).strip()
    return value


def _normalize_rule(value):
    normalized = str(value or "either").strip().lower()
    aliases = {
        "long": "bullish",
        "bullish_spike": "bullish",
        "short": "bearish",
        "bearish_spike": "bearish",
        "any": "either",
        "both": "either",
    }
    return aliases.get(normalized, normalized)


def _legacy_aliases_enabled(config):
    return any(_to_bool(config.get(key)) for key in LEGACY_VOLUME_SPIKE_ALIAS_FLAGS if key in config)


def _config_bool(config, key, default):
    value = config.get(key, default)
    return _to_bool(value)


def _to_bool(value):
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off"}
    return bool(value)


def _completed_sorted_candles(candles):
    selected = []
    for candle in candles or []:
        if not isinstance(candle, dict):
            continue
        if (
            candle.get("is_closed") is False
            or candle.get("is_complete") is False
            or candle.get("complete") is False
            or candle.get("closed") is False
            or candle.get("is_live") is True
        ):
            continue
        selected.append(dict(candle))

    if all("time" in candle and candle.get("time") is not None for candle in selected):
        selected.sort(key=lambda candle: float(candle.get("time") or 0))

    return selected


def _rule_result(rule, bullish, bearish):
    if rule == "bullish":
        return bullish
    if rule == "bearish":
        return bearish
    return bullish or bearish


def _finite_float(value):
    value = float(value)
    return value if np.isfinite(value) else None


def _last_finite_bool_index(series):
    indexes = np.flatnonzero(np.asarray(series, dtype=bool))
    return int(indexes[-1]) if indexes.size else None


def _matching_signal_index(result_bullish, result_bearish, rule, latest_index, window):
    if latest_index < 0:
        return None

    start_index = 0 if window is None else max(0, latest_index - int(window) + 1)
    for index in range(latest_index, start_index - 1, -1):
        bullish = bool(result_bullish[index])
        bearish = bool(result_bearish[index])
        if _rule_result(rule, bullish, bearish):
            return index
    return None


def _in_session(candle, config):
    session = str(config.get("session", "0000-0000") or "0000-0000").strip()
    if session in {"", "0000-0000", "0000-0000:1234567"}:
        return True

    if "time" not in candle:
        return True

    try:
        start_text, end_text = session.split(":", 1)[0].split("-", 1)
        start_minutes = _session_minutes(start_text)
        end_minutes = _session_minutes(end_text)
    except ValueError:
        return True

    timestamp = float(candle.get("time") or 0)
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000.0

    offset_minutes = int(config.get("session_tz_offset_minutes", config.get("timezone_offset_minutes", 0)) or 0)
    moment = datetime.fromtimestamp(timestamp, tz=timezone.utc) + timedelta(minutes=offset_minutes)
    current_minutes = moment.hour * 60 + moment.minute

    if start_minutes == end_minutes:
        return True
    if start_minutes < end_minutes:
        return start_minutes <= current_minutes < end_minutes
    return current_minutes >= start_minutes or current_minutes < end_minutes


def _session_minutes(value):
    value = str(value or "").strip()
    if len(value) != 4 or not value.isdigit():
        raise ValueError("invalid session value")
    hours = int(value[:2])
    minutes = int(value[2:])
    if hours > 23 or minutes > 59:
        raise ValueError("invalid session value")
    return hours * 60 + minutes


def _coerce_relative_volume_config_value(canonical, value):
    if canonical in {"lsma_length", "avg_length", "window"}:
        return max(1, int(value))
    if canonical in {"vol_alert", "min_ratio", "max_ratio", "threshold", "tolerance_pct"}:
        if value is None and canonical in {"max_ratio", "threshold"}:
            return None
        return float(value)
    if canonical in {"show_lsma_21", "show_lsma_6", "show_anomalies"}:
        return _to_bool(value)
    if canonical == "rule":
        return _normalize_relative_volume_rule(value)
    return value


def _normalize_relative_volume_rule(value):
    normalized = str(value or "above").strip().lower()
    aliases = {
        "ratio_above": "above",
        "rvol_above": "above",
        "greater_than": "above",
        "gt": "above",
        "ratio_below": "below",
        "rvol_below": "below",
        "less_than": "below",
        "lt": "below",
        "range": "between",
        "within": "between",
        "cross_above": "crossed_above",
        "crossover": "crossed_above",
        "rvol_crossed_above": "crossed_above",
        "cross_below": "crossed_below",
        "crossunder": "crossed_below",
        "rvol_crossed_below": "crossed_below",
        "highest_relative_volume": "highest",
        "highest_rvol": "highest",
        "alert": "volume_alert",
        "vol_alert": "volume_alert",
        "increased": "increased_volume",
        "volume_above_lsma": "increased_volume",
        "anomalies": "anomaly",
        "entry_signal": "entry",
        "lsma_entry": "entry",
    }
    return aliases.get(normalized, normalized)


def _previous_average_series(values, length):
    output = np.full(len(values), NAN, dtype=float)
    if length <= 0 or len(values) < length + 1:
        return output

    for index in range(length, len(values)):
        window = values[index - length:index]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.mean(window))
    return output


def _pine_wma(values, length):
    values = np.asarray(values, dtype=float)
    output = np.full(len(values), NAN, dtype=float)
    length = int(length)
    if length <= 0 or len(values) < length:
        return output

    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = float(np.sum(weights))
    for index in range(length - 1, len(values)):
        window = values[index - length + 1:index + 1]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.dot(window, weights) / weight_sum)
    return output


def _pine_hma(values, length):
    length = int(length)
    if length <= 0:
        return np.full(len(values), NAN, dtype=float)
    half_length = max(1, int(length / 2))
    sqrt_length = max(1, int(math.floor(math.sqrt(length))))
    return _pine_wma(2 * _pine_wma(values, half_length) - _pine_wma(values, length), sqrt_length)


def _pine_stdev(values, length):
    values = np.asarray(values, dtype=float)
    output = np.full(len(values), NAN, dtype=float)
    length = int(length)
    if length <= 0 or len(values) < length:
        return output

    for index in range(length - 1, len(values)):
        window = values[index - length + 1:index + 1]
        if np.any(~np.isfinite(window)):
            continue
        output[index] = float(np.std(window, ddof=0))
    return output


def _crossed_above(series, threshold):
    values = np.asarray(series, dtype=float)
    output = np.zeros(len(values), dtype=bool)
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if not np.isfinite(previous) or not np.isfinite(current):
            continue
        output[index] = bool(previous <= threshold and current > threshold)
    return output


def _crossed_below(series, threshold):
    values = np.asarray(series, dtype=float)
    output = np.zeros(len(values), dtype=bool)
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if not np.isfinite(previous) or not np.isfinite(current):
            continue
        output[index] = bool(previous >= threshold and current < threshold)
    return output


def _relative_volume_entry_signal(ma2, ma3, ma4, *, show_lsma_21, show_lsma_6):
    signal = _crossed_above(ma2, 0.0)
    if show_lsma_21 and not show_lsma_6:
        signal = signal | _crossed_above(ma3, 0.0)
    elif show_lsma_6 and not show_lsma_21:
        signal = signal | _crossed_above(ma4, 0.0)
    elif show_lsma_6 and show_lsma_21:
        signal = signal | _crossed_above(ma3, 0.0) | _crossed_above(ma4, 0.0)
    return signal


def _relative_volume_signal_series(
    rule,
    rvol,
    volumes,
    entry_signal,
    volume_alert,
    increased_volume,
    anomaly,
    config,
):
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    min_ratio = float(config.get("min_ratio", 1.0) or 1.0)
    max_ratio = config.get("max_ratio")
    threshold = max(0.0, min_ratio * (1 - tolerance_pct / 100.0))
    upper_threshold = None if max_ratio is None else float(max_ratio) * (1 + tolerance_pct / 100.0)

    if rule == "above":
        return np.isfinite(rvol) & (rvol >= threshold)
    if rule == "below":
        return np.isfinite(rvol) & (rvol <= min_ratio * (1 + tolerance_pct / 100.0))
    if rule == "between":
        return np.isfinite(rvol) & (rvol >= threshold) & (rvol <= upper_threshold)
    if rule == "crossed_above":
        return _crossed_above(rvol, min_ratio)
    if rule == "crossed_below":
        return _crossed_below(rvol, min_ratio)
    if rule == "highest":
        return _highest_relative_volume_signal(rvol, int(config.get("window", 1) or 1))
    if rule == "volume_alert":
        return volume_alert
    if rule == "increased_volume":
        return increased_volume
    if rule == "anomaly":
        return anomaly
    if rule == "entry":
        return entry_signal
    return np.zeros(len(volumes), dtype=bool)


def _highest_relative_volume_signal(rvol, window):
    output = np.zeros(len(rvol), dtype=bool)
    normalized_window = max(1, int(window))
    for index in range(len(rvol)):
        value = rvol[index]
        if not np.isfinite(value):
            continue
        start = max(0, index - normalized_window + 1)
        window_values = rvol[start:index + 1]
        finite = window_values[np.isfinite(window_values)]
        if finite.size and value >= float(np.max(finite)):
            output[index] = True
    return output


def _matching_boolean_index(series, latest_index, window):
    if latest_index < 0:
        return None
    start_index = 0 if window is None else max(0, latest_index - int(window) + 1)
    values = np.asarray(series, dtype=bool)
    for index in range(latest_index, start_index - 1, -1):
        if bool(values[index]):
            return index
    return None


def _relative_volume_latest_trace(
    candles,
    volumes,
    rvol,
    previous_average,
    ma2,
    std_dev,
    trend_delta,
    entry_signal,
    volume_alert,
    increased_volume,
    anomaly,
    signal,
    latest_index,
):
    if latest_index < 0:
        return {}
    return {
        "time": candles[latest_index].get("time") if candles else None,
        "volume": float(volumes[latest_index]) if latest_index < len(volumes) else None,
        "rvol": _finite_float_or_default(rvol[latest_index], None),
        "previous_average": _finite_float_or_default(previous_average[latest_index], None),
        "lsma": _finite_float_or_default(ma2[latest_index], None),
        "std_dev": _finite_float_or_default(std_dev[latest_index], None),
        "trend_delta": _finite_float_or_default(trend_delta[latest_index], None),
        "entry_signal": bool(entry_signal[latest_index]) if latest_index < len(entry_signal) else False,
        "volume_alert": bool(volume_alert[latest_index]) if latest_index < len(volume_alert) else False,
        "increased_volume": bool(increased_volume[latest_index]) if latest_index < len(increased_volume) else False,
        "anomaly": bool(anomaly[latest_index]) if latest_index < len(anomaly) else False,
        "final_signal": bool(signal[latest_index]) if latest_index < len(signal) else False,
    }


def _relative_volume_decision(rule):
    if rule in {"above", "crossed_above", "highest"}:
        return "High Relative Volume"
    if rule == "below":
        return "Low Relative Volume"
    if rule == "between":
        return "Relative Volume Range"
    if rule == "volume_alert":
        return "Volume Alert"
    if rule == "increased_volume":
        return "Increased Volume"
    if rule == "anomaly":
        return "Volume Anomaly"
    if rule == "entry":
        return "RVOL Entry Signal"
    return "Relative Volume Match"


def _finite_float_or_default(value, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if np.isfinite(value) else default


def _coerce_current_volume_config_value(canonical, value):
    if canonical in {"atr_length", "avg_count", "window"}:
        return max(1, int(value))
    if canonical in {"atr_multiplier", "min_value", "max_value", "min_percent_avg", "max_percent_avg", "tolerance_pct"}:
        if value is None and canonical in {"min_value", "max_value", "min_percent_avg", "max_percent_avg"}:
            return None
        return float(value)
    if canonical == "enable_percentage_on_chart":
        return _to_bool(value)
    if canonical == "smoothing":
        normalized = str(value or "RMA").strip().upper()
        if normalized not in {"RMA", "SMA", "EMA", "WMA"}:
            raise CurrentVolumeConfigError("Current Volume smoothing must be one of RMA, SMA, EMA, WMA")
        return normalized
    if canonical == "rule":
        return _normalize_current_volume_rule(value)
    return value


def _normalize_current_volume_rule(value):
    normalized = str(value or "value").strip().lower()
    aliases = {
        "current": "value",
        "current_volume": "value",
        "volume": "value",
        "threshold": "value",
        "percent": "above_average_percent",
        "percent_avg_above": "above_average_percent",
        "rvol_percent_above": "above_average_percent",
        "above_percent": "above_average_percent",
        "below_percent": "below_average_percent",
        "percent_avg_below": "below_average_percent",
        "between_percent": "between_average_percent",
        "percent_range": "between_average_percent",
        "above_average_volume": "above_average",
        "avg_100": "above_average",
    }
    return aliases.get(normalized, normalized)


def _true_range(highs, lows, closes):
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    output = np.full(len(highs), NAN, dtype=float)
    if len(highs) == 0:
        return output

    for index in range(len(highs)):
        high = highs[index]
        low = lows[index]
        if not np.isfinite(high) or not np.isfinite(low):
            continue
        if index == 0 or not np.isfinite(closes[index - 1]):
            output[index] = high - low
            continue
        previous_close = closes[index - 1]
        output[index] = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )
    return output


def _current_volume_ma_function(source, length, smoothing):
    normalized = str(smoothing or "RMA").strip().upper()
    if normalized == "SMA":
        return pine_sma(source, length)
    if normalized == "EMA":
        return pine_ema(source, length)
    if normalized == "WMA":
        return _pine_wma(source, length)
    return pine_rma(source, length)


def _round_half_up(values):
    values = np.asarray(values, dtype=float)
    return np.floor(values + 0.5)


def _current_volume_color_state(percent_avg):
    states = np.full(len(percent_avg), "white", dtype=object)
    finite = np.isfinite(percent_avg)
    states[finite & (percent_avg >= 100.0)] = "orange"
    states[finite & (percent_avg >= 200.0)] = "green"
    return states


def _current_volume_signal_series(volumes, percent_avg, config):
    rule = config["rule"]
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if rule == "value":
        minimum = config.get("min_value")
        maximum = config.get("max_value")
        signal = np.ones(len(volumes), dtype=bool)
        if minimum is not None:
            signal &= volumes >= float(minimum) * (1 - tolerance_pct / 100.0)
        if maximum is not None:
            signal &= volumes <= float(maximum) * (1 + tolerance_pct / 100.0)
        return signal

    minimum_percent = config.get("min_percent_avg")
    if minimum_percent is None:
        minimum_percent = 100.0
    maximum_percent = config.get("max_percent_avg")
    lower = float(minimum_percent) * (1 - tolerance_pct / 100.0)

    if rule == "above_average":
        lower = 100.0 * (1 - tolerance_pct / 100.0)
        return np.isfinite(percent_avg) & (percent_avg >= lower)
    if rule == "above_average_percent":
        return np.isfinite(percent_avg) & (percent_avg >= lower)
    if rule == "below_average_percent":
        upper = float(minimum_percent) * (1 + tolerance_pct / 100.0)
        return np.isfinite(percent_avg) & (percent_avg <= upper)
    if rule == "between_average_percent":
        upper = float(maximum_percent) * (1 + tolerance_pct / 100.0)
        return np.isfinite(percent_avg) & (percent_avg >= lower) & (percent_avg <= upper)

    return np.zeros(len(volumes), dtype=bool)


def _current_volume_latest_trace(
    candles,
    volumes,
    current_avg_volume,
    percent_avg,
    atr_value,
    color_state,
    codiff,
    signal,
    latest_index,
):
    if latest_index < 0:
        return {}
    return {
        "time": candles[latest_index].get("time") if candles else None,
        "current_volume": float(volumes[latest_index]) if latest_index < len(volumes) else None,
        "current_average_volume": _finite_float_or_default(current_avg_volume[latest_index], None),
        "current_resolution_percent_avg": _finite_float_or_default(percent_avg[latest_index], None),
        "atr": _finite_float_or_default(atr_value[latest_index], None),
        "color_state": str(color_state[latest_index]) if latest_index < len(color_state) else None,
        "codiff": bool(codiff[latest_index]) if latest_index < len(codiff) else False,
        "final_signal": bool(signal[latest_index]) if latest_index < len(signal) else False,
    }


def _current_volume_decision(rule):
    if rule == "value":
        return "Liquidity Threshold Met"
    if rule in {"above_average", "above_average_percent"}:
        return "Above Average Volume"
    if rule == "below_average_percent":
        return "Below Average Volume"
    if rule == "between_average_percent":
        return "Average Volume Range"
    return "Current Volume Match"

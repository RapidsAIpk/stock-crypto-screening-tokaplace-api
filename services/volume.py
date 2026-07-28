# services/volume.py

from datetime import datetime, timedelta, timezone

import numpy as np
from services.pine_math import pine_sma
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

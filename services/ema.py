# services/ema.py

import numpy as np
from services.candle_utils import completed_candles
from services.pine_math import pine_ema, pine_sma
from services.range_utils import candles_since_in_range, selection_mode_pass
from services.utils import build_indicator_sticker, format_price_value


# =========================================================
# EMA
# =========================================================

TRADINGVIEW_STANDARD_EMA_PERIODS = [20, 50, 100, 200]
EMA_WARMUP_MULTIPLIER = 5
EMA_MAX_HISTORY_REQUIREMENT = 500
TRADINGVIEW_STANDARD_EMA_PRESETS = {
    "ema_20_50_100_200",
    "ema20_50_100_200",
    "ema_20/50/100/200",
    "ema 20/50/100/200",
    "tradingview_ema_20_50_100_200",
    "tv_ema_20_50_100_200",
}


def required_ema_history(period):
    try:
        normalized_period = int(period)
    except (TypeError, ValueError):
        normalized_period = 1
    normalized_period = max(1, normalized_period)
    return min(EMA_MAX_HISTORY_REQUIREMENT, normalized_period * EMA_WARMUP_MULTIPLIER)


def compute_ema(series, length):

    series = np.asarray(series)

    ema = np.zeros_like(series)

    multiplier = 2 / (length + 1)

    ema[0] = series[0]

    for i in range(1, len(series)):
        ema[i] = (series[i] - ema[i-1]) * multiplier + ema[i-1]

    return ema


def compute_ema_wave(
    candles,
    wave_a_length=5,
    wave_b_length=25,
    wave_c_length=50,
    wave_sma_length=4,
    cutoff=10,
    source="hlc3",
):
    """EMA Wave Indicator [LazyBear] port.

    Pine:
      wa = sma(src - ema(src, alength), lengthMA)
      wb = sma(src - ema(src, blength), lengthMA)
      wc = sma(src - ema(src, clength), lengthMA)
      wcf = wb != 0 ? wc / wb > cutoff : false
      wbf = wa != 0 ? wb / wa > cutoff : false
    """
    if not candles:
        return None

    source_values = _candle_source(candles, source)
    a_length = int(wave_a_length)
    b_length = int(wave_b_length)
    c_length = int(wave_c_length)
    sma_length = int(wave_sma_length)
    cutoff_value = float(cutoff)

    if min(a_length, b_length, c_length, sma_length) <= 0:
        return None

    wave_a = pine_sma(source_values - pine_ema(source_values, a_length), sma_length)
    wave_b = pine_sma(source_values - pine_ema(source_values, b_length), sma_length)
    wave_c = pine_sma(source_values - pine_ema(source_values, c_length), sma_length)

    wave_c_spike = np.zeros(len(source_values), dtype=bool)
    wave_b_spike = np.zeros(len(source_values), dtype=bool)

    finite_c = np.isfinite(wave_c) & np.isfinite(wave_b) & (wave_b != 0)
    finite_b = np.isfinite(wave_b) & np.isfinite(wave_a) & (wave_a != 0)
    wave_c_spike[finite_c] = (wave_c[finite_c] / wave_b[finite_c]) > cutoff_value
    wave_b_spike[finite_b] = (wave_b[finite_b] / wave_a[finite_b]) > cutoff_value

    return {
        "wave_a": wave_a,
        "wave_b": wave_b,
        "wave_c": wave_c,
        "wave_b_spike": wave_b_spike,
        "wave_c_spike": wave_c_spike,
        "source": str(source or "hlc3").strip().lower(),
        "wave_a_length": a_length,
        "wave_b_length": b_length,
        "wave_c_length": c_length,
        "wave_sma_length": sma_length,
        "cutoff": cutoff_value,
    }


def price_matches_ema_rule(price, ema_value, rule, tolerance_pct=0):

    tolerance_pct = max(0.0, float(tolerance_pct or 0))
    tolerance = abs(float(ema_value)) * (tolerance_pct / 100.0)

    if rule == "above":
        return float(price) >= (float(ema_value) - tolerance)

    if rule == "below":
        return float(price) <= (float(ema_value) + tolerance)

    if rule == "touch":
        base_tolerance = abs(float(ema_value)) * 0.002
        return abs(float(price) - float(ema_value)) <= max(base_tolerance, tolerance)

    return False


EMA_CONDITION_ALIASES = {
    "touch_from_above": "touch_from_above",
    "touch_above": "touch_from_above",
    "touch": "touch_from_above",
    "piercing_from_below": "piercing_from_below",
    "pierce_from_below": "piercing_from_below",
    "piercing": "piercing_from_below",
    "close_above": "close_above",
    "above": "close_above",
    "touched_or_pierced_and_closed_above": "touched_or_pierced_and_closed_above",
    "touch_or_pierce_close_above": "touched_or_pierced_and_closed_above",
    "touch_pierce_close_above": "touched_or_pierced_and_closed_above",
    "below": "legacy_below",
}

EMA_DEFAULT_CONDITIONS = {
    "touch_from_above": {
        "enabled": False,
        "candles_since_min": 0,
        "candles_since_max": 5,
    },
    "piercing_from_below": {
        "enabled": False,
        "candles_since_min": 0,
        "candles_since_max": 5,
    },
    "close_above": {
        "enabled": True,
        "candles_since_min": 0,
        "candles_since_max": 0,
    },
    "touched_or_pierced_and_closed_above": {
        "enabled": False,
        "candles_since_min": 0,
        "candles_since_max": 5,
        "require_still_above_now": True,
    },
}


def _uses_tradingview_standard_ema_periods(config):
    if config.get("ema_20_50_100_200") is True:
        return True
    if config.get("standard_ema_periods") is True:
        return True
    if config.get("tradingview_standard_emas") is True:
        return True

    raw_preset = (
        config.get("preset")
        or config.get("ema_preset")
        or config.get("study")
        or config.get("title")
    )
    preset = str(raw_preset or "").strip().lower()
    return preset in TRADINGVIEW_STANDARD_EMA_PRESETS


def normalize_ema_periods(config):
    raw = config.get("periods") or config.get("ema_periods") or config.get("lengths")
    if raw is None and config.get("length") is not None:
        raw = config.get("length")
    if raw is None and _uses_tradingview_standard_ema_periods(config):
        return list(TRADINGVIEW_STANDARD_EMA_PERIODS)
    if raw is None:
        raw = 9

    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]

    periods = []
    for value in raw:
        try:
            period = int(value)
        except (TypeError, ValueError):
            continue
        if period > 0 and period not in periods:
            periods.append(period)

    return periods or [9]


def normalize_ema_conditions(config):
    raw_conditions = config.get("conditions")
    normalized = {
        name: dict(defaults)
        for name, defaults in EMA_DEFAULT_CONDITIONS.items()
    }
    explicit_conditions = False

    if isinstance(raw_conditions, dict):
        explicit_conditions = True
        for condition_config in normalized.values():
            condition_config["enabled"] = False
        for raw_name, raw_value in raw_conditions.items():
            condition_name = EMA_CONDITION_ALIASES.get(str(raw_name or "").strip().lower())
            if condition_name is None or condition_name == "legacy_below":
                continue
            if isinstance(raw_value, dict):
                normalized[condition_name].update(raw_value)
                normalized[condition_name]["enabled"] = bool(raw_value.get("enabled", True))
            else:
                normalized[condition_name]["enabled"] = bool(raw_value)

    elif isinstance(raw_conditions, (list, tuple, set)):
        explicit_conditions = True
        for condition_config in normalized.values():
            condition_config["enabled"] = False
        for raw_name in raw_conditions:
            condition_name = EMA_CONDITION_ALIASES.get(str(raw_name or "").strip().lower())
            if condition_name is not None and condition_name != "legacy_below":
                normalized[condition_name]["enabled"] = True

    if not explicit_conditions:
        for item in normalized.values():
            item["enabled"] = False

        rule = EMA_CONDITION_ALIASES.get(str(config.get("rule", "above") or "above").strip().lower())
        if rule in normalized:
            normalized[rule]["enabled"] = True
            normalized[rule]["candles_since_min"] = config.get("candles_since_min", config.get("window_min", 0))
            normalized[rule]["candles_since_max"] = config.get("candles_since_max", config.get("window_max", 0))
        elif rule == "legacy_below":
            normalized["legacy_below"] = {
                "enabled": True,
                "candles_since_min": config.get("candles_since_min", 0),
                "candles_since_max": config.get("candles_since_max", 0),
            }

    return normalized


def normalize_ema_config(config):
    config = dict(config or {})
    return {
        **config,
        "periods": normalize_ema_periods(config),
        "selection_mode": str(config.get("selection_mode", "all") or "all").strip().lower(),
        "conditions": normalize_ema_conditions(config),
    }


def _finite_at(series, index):
    if index < 0 or index >= len(series):
        return None
    value = float(series[index])
    return value if np.isfinite(value) else None


def _ema_touch_from_above(candles, ema_series, index):
    if index <= 0:
        return False
    candle = candles[index]
    prev_close = float(candles[index - 1]["close"])
    prev_ema = _finite_at(ema_series, index - 1)
    ema_value = _finite_at(ema_series, index)
    if prev_ema is None or ema_value is None:
        return False
    return (
        prev_close > prev_ema
        and float(candle["low"]) <= ema_value
        and float(candle["high"]) >= ema_value
        and float(candle["close"]) > ema_value
    )


def _ema_piercing_from_below(candles, ema_series, index):
    if index <= 0:
        return False
    candle = candles[index]
    prev_close = float(candles[index - 1]["close"])
    prev_ema = _finite_at(ema_series, index - 1)
    ema_value = _finite_at(ema_series, index)
    if prev_ema is None or ema_value is None:
        return False
    return (
        prev_close < prev_ema
        and float(candle["low"]) < ema_value
        and float(candle["high"]) >= ema_value
        and float(candle["close"]) > ema_value
    )


def _ema_close_above(candles, ema_series, index):
    ema_value = _finite_at(ema_series, index)
    return ema_value is not None and float(candles[index]["close"]) > ema_value


def _ema_legacy_below(candles, ema_series, index):
    ema_value = _finite_at(ema_series, index)
    return ema_value is not None and float(candles[index]["close"]) < ema_value


def _find_latest_ema_event(candles, ema_series, predicate):
    for index in range(len(candles) - 1, -1, -1):
        if predicate(candles, ema_series, index):
            return index
    return None


def _condition_range(config):
    return (
        config.get("candles_since_min", config.get("min_candles_since")),
        config.get("candles_since_max", config.get("max_candles_since")),
    )


def _evaluate_period_condition(candles, ema_series, condition_name, condition_config):
    if not condition_config.get("enabled"):
        return False, None

    latest_index = len(candles) - 1
    min_candles, max_candles = _condition_range(condition_config)

    if condition_name == "touch_from_above":
        event_index = _find_latest_ema_event(candles, ema_series, _ema_touch_from_above)
    elif condition_name == "piercing_from_below":
        event_index = _find_latest_ema_event(candles, ema_series, _ema_piercing_from_below)
    elif condition_name == "close_above":
        event_index = _find_latest_ema_event(candles, ema_series, _ema_close_above)
    elif condition_name == "legacy_below":
        event_index = _find_latest_ema_event(candles, ema_series, _ema_legacy_below)
    elif condition_name == "touched_or_pierced_and_closed_above":
        event_index = _find_latest_ema_event(
            candles,
            ema_series,
            lambda rows, series, index: (
                _ema_touch_from_above(rows, series, index)
                or _ema_piercing_from_below(rows, series, index)
            ),
        )
        if condition_config.get("require_still_above_now", True) and not _ema_close_above(candles, ema_series, latest_index):
            return False, event_index
    else:
        return False, None

    return (
        candles_since_in_range(event_index, latest_index, min_candles, max_candles),
        event_index,
    )


def evaluate_ema_period(candles, period, config):
    closes = np.array([c["close"] for c in candles], dtype=float)
    required_candles = required_ema_history(period)
    if len(closes) < required_candles:
        latest_close = float(closes[-1]) if len(closes) else None
        return {
            "period": period,
            "passed": False,
            "conditions": {},
            "ema": None,
            "close": latest_close,
            "failure_reason": "insufficient_history",
            "required_candles": int(required_candles),
            "available_candles": int(len(closes)),
        }

    ema_series = compute_ema(closes, period)
    conditions = config["conditions"]
    active_conditions = [
        (name, condition_config)
        for name, condition_config in conditions.items()
        if isinstance(condition_config, dict) and condition_config.get("enabled")
    ]

    if not active_conditions:
        return {
            "period": period,
            "passed": False,
            "conditions": {},
            "ema": float(ema_series[-1]),
            "close": float(closes[-1]),
            "failure_reason": "no_active_conditions",
        }

    condition_results = {}
    for condition_name, condition_config in active_conditions:
        passed, event_index = _evaluate_period_condition(
            candles,
            ema_series,
            condition_name,
            condition_config,
        )
        condition_results[condition_name] = {
            "passed": bool(passed),
            "event_index": event_index,
            "candles_since": (len(candles) - 1 - event_index) if event_index is not None else None,
        }

    return {
        "period": period,
        "passed": all(item["passed"] for item in condition_results.values()),
        "conditions": condition_results,
        "ema": float(ema_series[-1]),
        "close": float(closes[-1]),
        "failure_reason": None,
    }


def evaluate_ema_rules_detail(candles, config):
    if _is_ema_wave_config(config):
        return {
            "passed": evaluate_ema_wave_rules(candles, config),
            "mode": "ema_wave",
            "period_results": [],
            "config": dict(config or {}),
        }

    closed = completed_candles(candles)
    if len(closed) < 2:
        return {
            "passed": False,
            "mode": "ema",
            "period_results": [],
            "config": normalize_ema_config(config),
        }

    normalized = normalize_ema_config(config)
    period_results = [
        evaluate_ema_period(closed, period, normalized)
        for period in normalized["periods"]
    ]

    return {
        "passed": selection_mode_pass(
            [item["passed"] for item in period_results],
            normalized.get("selection_mode", "all"),
        ),
        "mode": "ema",
        "period_results": period_results,
        "config": normalized,
    }


# =========================================================
# RULES
# =========================================================

def evaluate_ema_rules(candles, config):
    if _is_ema_wave_config(config):
        return evaluate_ema_wave_rules(completed_candles(candles), config)

    return bool(evaluate_ema_rules_detail(candles, config)["passed"])


def evaluate_ema_wave_rules(candles, config):
    computed = compute_ema_wave_from_config(candles, config)
    if computed is None:
        return False

    index = _latest_finite_wave_index(computed)
    if index is None:
        return False

    rule = str(config.get("rule", "any_spike") or "any_spike").strip().lower()
    tolerance = float(config.get("tolerance", config.get("tolerance_pct", 0)) or 0)
    wave_name = str(config.get("wave", "wave_c") or "wave_c").strip().lower()
    threshold = float(config.get("threshold", 0) or 0)

    if rule == "any_spike":
        return bool(computed["wave_b_spike"][index] or computed["wave_c_spike"][index])
    if rule == "both_spikes":
        return bool(computed["wave_b_spike"][index] and computed["wave_c_spike"][index])
    if rule == "wave_b_spike":
        return bool(computed["wave_b_spike"][index])
    if rule == "wave_c_spike":
        return bool(computed["wave_c_spike"][index])

    series = _wave_series(computed, wave_name)
    if series is None or not np.isfinite(series[index]):
        return False
    value = float(series[index])
    amount = abs(threshold) * tolerance / 100.0

    if rule == "above":
        return value >= threshold - amount
    if rule == "below":
        return value <= threshold + amount
    if rule == "crossed_up":
        return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) <= threshold + amount and value >= threshold - amount
    if rule == "crossed_down":
        return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) >= threshold - amount and value <= threshold + amount

    return False


def build_moving_average_sticker(label, length, rule, price, ma_value):
    condition = f"Price {format_price_value(price)} vs {label} @ {format_price_value(ma_value)}"
    return build_indicator_sticker(
        label,
        condition,
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision=_moving_average_decision(rule),
    )


def build_ema_sticker(candles, config):
    if _is_ema_wave_config(config):
        return build_ema_wave_sticker(completed_candles(candles), config)

    detail = evaluate_ema_rules_detail(candles, config)
    normalized = detail["config"]
    periods = [item["period"] for item in detail["period_results"] if item["passed"]]
    display_periods = periods or normalized["periods"]
    length = display_periods[0] if len(display_periods) == 1 else None
    condition_names = [
        name.replace("_", " ")
        for name, value in normalized["conditions"].items()
        if isinstance(value, dict) and value.get("enabled")
    ]
    condition = (
        f"Periods {', '.join(str(period) for period in display_periods)} | "
        f"{' + '.join(condition_names) if condition_names else 'EMA condition'}"
    )
    return build_indicator_sticker(
        "EMA",
        condition,
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision="EMA Phase 1 Match",
    )


def build_ema_wave_sticker(candles, config):
    computed = compute_ema_wave_from_config(candles, config)
    index = _latest_finite_wave_index(computed) if computed is not None else None
    wave_a = computed["wave_a"][index] if computed is not None and index is not None else np.nan
    wave_b = computed["wave_b"][index] if computed is not None and index is not None else np.nan
    wave_c = computed["wave_c"][index] if computed is not None and index is not None else np.nan
    condition = (
        f"WaveA {format_price_value(wave_a)} / "
        f"WaveB {format_price_value(wave_b)} / "
        f"WaveC {format_price_value(wave_c)}"
    )
    return build_indicator_sticker(
        "EMA Wave",
        condition,
        {"window": 1, "confirmation": False},
        length=computed["wave_c_length"] if computed is not None else config.get("wave_c_length", 50),
        window=1,
        decision=_ema_wave_decision(config.get("rule", "any_spike")),
    )


def _moving_average_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "above":
        return "Bullish Trend Filter"
    if normalized == "below":
        return "Bearish Trend Filter"
    if normalized == "touch":
        return "Retest Watch"
    return "Moving Average Match"


def compute_ema_wave_from_config(candles, config):
    return compute_ema_wave(
        candles,
        wave_a_length=config.get("wave_a_length", config.get("alength", 5)),
        wave_b_length=config.get("wave_b_length", config.get("blength", 25)),
        wave_c_length=config.get("wave_c_length", config.get("clength", 50)),
        wave_sma_length=config.get("wave_sma_length", config.get("lengthMA", config.get("length_ma", 4))),
        cutoff=config.get("cutoff", 10),
        source=config.get("source", "hlc3"),
    )


def _is_ema_wave_config(config):
    mode = str(config.get("mode", config.get("type", "")) or "").strip().lower()
    if mode in {"price", "simple", "simple_ema", "ema_price", "moving_average"}:
        return False
    if config.get("simple_ema") is True:
        return False
    return mode in {"wave", "ema_wave", "ewi", "ewi_lb"} or _has_ema_wave_config(config)


def _has_ema_wave_config(config):
    mode = str(config.get("mode", config.get("type", "")) or "").strip().lower()
    return mode in {"wave", "ema_wave", "ewi", "ewi_lb"} or any(
        key in config
        for key in (
            "wave_a_length",
            "wave_b_length",
            "wave_c_length",
            "wave_sma_length",
            "alength",
            "blength",
            "clength",
            "lengthMA",
            "mse",
            "cutoff",
        )
    )


def _candle_source(candles, source):
    normalized = str(source or "hlc3").strip().lower()
    values = np.zeros(len(candles), dtype=float)

    for index, candle in enumerate(candles):
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        if normalized == "open":
            values[index] = open_
        elif normalized == "high":
            values[index] = high
        elif normalized == "low":
            values[index] = low
        elif normalized == "close":
            values[index] = close
        elif normalized == "hl2":
            values[index] = (high + low) / 2.0
        elif normalized == "ohlc4":
            values[index] = (open_ + high + low + close) / 4.0
        else:
            values[index] = (high + low + close) / 3.0

    return values


def _latest_finite_wave_index(computed):
    if computed is None:
        return None
    finite = (
        np.isfinite(computed["wave_a"])
        & np.isfinite(computed["wave_b"])
        & np.isfinite(computed["wave_c"])
    )
    indexes = np.flatnonzero(finite)
    return int(indexes[-1]) if indexes.size else None


def _wave_series(computed, wave_name):
    normalized = str(wave_name or "wave_c").strip().lower()
    aliases = {
        "a": "wave_a",
        "wa": "wave_a",
        "wavea": "wave_a",
        "wave_a": "wave_a",
        "b": "wave_b",
        "wb": "wave_b",
        "waveb": "wave_b",
        "wave_b": "wave_b",
        "c": "wave_c",
        "wc": "wave_c",
        "wavec": "wave_c",
        "wave_c": "wave_c",
    }
    return computed.get(aliases.get(normalized, normalized))


def _ema_wave_decision(rule):
    normalized = str(rule or "").strip().lower()
    if "spike" in normalized:
        return "Spike / Exhaustion"
    if normalized in {"above", "crossed_up"}:
        return "Positive Wave"
    if normalized in {"below", "crossed_down"}:
        return "Negative Wave"
    return "EMA Wave Match"

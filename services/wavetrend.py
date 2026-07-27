# services/wavetrend.py
import numpy as np

from services.pine_math import NAN, pine_ema, pine_sma
from services.utils import build_indicator_sticker, confirm_if_needed, format_decimal, series_direction_matches

DEFAULT_ZONE_THRESHOLD = 60.0
DEFAULT_ZONE_THRESHOLD_SECONDARY = 53.0
LAZYBEAR_OB_LEVEL_1 = 60.0
LAZYBEAR_OB_LEVEL_2 = 53.0
LAZYBEAR_OS_LEVEL_1 = -60.0
LAZYBEAR_OS_LEVEL_2 = -53.0
LAZYBEAR_MODES = {"lazybear", "lazybear_cross", "wt_cross_lb", "wavetrend_cross_lazybear"}
CUSTOM_MODES = {"custom", "legacy", "threshold", "backend"}
LAZYBEAR_ZONE_LEVEL_1 = {"level_1", "level1", "1", "outer", "deep"}
LAZYBEAR_CONDITION_ALIASES = {
    "any": "zone_only",
    "none": "zone_only",
    "zone_only": "zone_only",
    "no_cross_filter": "zone_only",
    "watch": "zone_only",
    "oversold": "oversold_watch",
    "oversold_watch": "oversold_watch",
    "overbought": "overbought_watch",
    "overbought_watch": "overbought_watch",
    "cross": "cross_any",
    "crossed": "cross_any",
    "cross_any": "cross_any",
    "both": "cross_any",
    "cross_up": "cross_up",
    "crossed_up": "cross_up",
    "bullish": "cross_up",
    "bullish_cross": "cross_up",
    "cross_down": "cross_down",
    "crossed_down": "cross_down",
    "bearish": "cross_down",
    "bearish_cross": "cross_down",
    "oversold_cross": "oversold_cross_up",
    "oversold_cross_up": "oversold_cross_up",
    "bullish_oversold_cross": "oversold_cross_up",
    "turning_up_from_oversold": "turning_up_from_oversold",
    "oversold_turning_up": "turning_up_from_oversold",
    "overbought_cross": "overbought_cross_down",
    "overbought_cross_down": "overbought_cross_down",
    "bearish_overbought_cross": "overbought_cross_down",
    "turning_down_from_overbought": "turning_down_from_overbought",
    "overbought_turning_down": "turning_down_from_overbought",
    "rising": "rising",
    "falling": "falling",
    "turning_up": "turning_up",
    "turning_down": "turning_down",
}
LAZYBEAR_CROSS_CONDITIONS = {
    "cross_any",
    "cross_up",
    "cross_down",
    "oversold_cross_up",
    "overbought_cross_down",
}
LAZYBEAR_DIRECTION_CONDITIONS = {
    "rising",
    "falling",
    "turning_up",
    "turning_down",
    "turning_up_from_oversold",
    "turning_down_from_overbought",
}
LAZYBEAR_BUILTIN_CONDITIONS = {
    "zone_only": [{"type": "zone", "line": "wt1"}],
    "oversold_watch": [{"type": "zone", "line": "wt1"}],
    "overbought_watch": [{"type": "zone", "line": "wt1"}],
    "cross_any": [{"type": "cross", "direction": "any"}],
    "cross_up": [{"type": "cross", "direction": "up"}],
    "cross_down": [{"type": "cross", "direction": "down"}],
    "oversold_cross_up": [
        {"type": "cross", "direction": "up"},
        {"type": "zone", "line": "wt2"},
    ],
    "overbought_cross_down": [
        {"type": "cross", "direction": "down"},
        {"type": "zone", "line": "wt2"},
    ],
    "rising": [{"type": "direction", "line": "wt1", "direction": "rising"}],
    "falling": [{"type": "direction", "line": "wt1", "direction": "falling"}],
    "turning_up": [{"type": "direction", "line": "wt1", "direction": "turning_up"}],
    "turning_down": [{"type": "direction", "line": "wt1", "direction": "turning_down"}],
    "turning_up_from_oversold": [
        {"type": "direction", "line": "wt1", "direction": "turning_up"},
        {"type": "zone", "line": "wt1"},
    ],
    "turning_down_from_overbought": [
        {"type": "direction", "line": "wt1", "direction": "turning_down"},
        {"type": "zone", "line": "wt1"},
    ],
}


def compute_wavetrend(
    candles,
    channel_length=10,
    average_length=21,
    signal_length=4,
):
    n = len(candles)

    if n < average_length + signal_length:
        return None

    hlc3 = np.array([
        (c["high"] + c["low"] + c["close"]) / 3
        for c in candles
    ], dtype=float)

    esa = pine_ema(hlc3, channel_length)
    deviation = pine_ema(np.abs(hlc3 - esa), channel_length)

    ci = np.full(n, NAN, dtype=float)
    valid = np.isfinite(deviation) & (deviation > 0)
    ci[valid] = (hlc3[valid] - esa[valid]) / (0.015 * deviation[valid])

    wt1 = pine_ema(ci, average_length)
    wt2 = pine_sma(wt1, signal_length)

    return {
        "wt1": wt1,
        "wt2": wt2,
    }


def ema(series, length):
    return pine_ema(np.asarray(series, dtype=float), length)


def sma(series, length):
    return pine_sma(np.asarray(series, dtype=float), length)


def evaluate_wavetrend_rules(
    wt,
    candles,
    config
):
    if _uses_lazybear_mode(config):
        return evaluate_lazybear_wavetrend_rules(wt, candles, config)

    wt1 = wt["wt1"]
    wt2 = wt["wt2"]

    window = int(config.get("window", 1) or 1)
    zone_rule = config.get("zone")
    direction_rule = config.get("direction")
    tolerance_pct = float(config.get("tolerance_pct", 0) or 0)
    threshold = float(config.get("threshold", DEFAULT_ZONE_THRESHOLD) or DEFAULT_ZONE_THRESHOLD)

    if window <= 0:
        window = 1

    if len(wt1) < window:
        return False

    start = len(wt1) - window

    for idx in range(start, len(wt1)):
        if not _wavetrend_zone_matches(wt1, idx, zone_rule, tolerance_pct, threshold):
            continue

        if not _wavetrend_direction_matches(wt1, wt2, idx, direction_rule):
            continue

        if config.get("confirmation"):
            if idx >= len(candles):
                continue

            if not confirm_if_needed(candles, idx, config):
                continue

        return True

    return False


def evaluate_lazybear_wavetrend_rules(wt, candles, config):
    wt1 = wt["wt1"]
    wt2 = wt["wt2"]
    window = max(1, int(config.get("window", 1) or 1))

    if len(wt1) < window:
        return False

    start = max(0, len(wt1) - window)
    condition = _resolve_lazybear_condition(config)
    for idx in range(start, len(wt1)):
        if not _lazybear_condition_matches(wt1, wt2, idx, config, condition):
            continue

        if config.get("confirmation"):
            if idx >= len(candles):
                continue
            if not confirm_if_needed(candles, idx, config):
                continue

        return True

    return False


def _wavetrend_zone_matches(wt1, idx, zone_rule, tolerance_pct=0, threshold=None):
    if not zone_rule:
        return True

    value = float(wt1[idx])
    if not np.isfinite(value):
        return False

    tolerance = max(0.0, float(tolerance_pct))
    th = DEFAULT_ZONE_THRESHOLD if threshold is None else float(threshold)

    if zone_rule == "oversold":
        return value <= (-th + tolerance)
    if zone_rule == "neutral":
        return (-th - tolerance) <= value <= (th + tolerance)
    if zone_rule == "overbought":
        return value >= (th - tolerance)

    return False


def _wavetrend_direction_matches(wt1, wt2, idx, direction_rule):
    if direction_rule in {"rising", "falling", "turning_up", "turning_down"}:
        return series_direction_matches(wt1, idx, direction_rule)

    if direction_rule in {"crossed_up", "crossed_down"}:
        if idx - 1 < 0:
            return False
        prev_delta = float(wt1[idx - 1]) - float(wt2[idx - 1])
        cur_delta = float(wt1[idx]) - float(wt2[idx])
        return (prev_delta <= 0 and cur_delta > 0) if direction_rule == "crossed_up" else (prev_delta >= 0 and cur_delta < 0)

    return False


def _uses_lazybear_mode(config):
    mode = str(config.get("mode") or config.get("compatibility") or "").strip().lower()
    if mode in CUSTOM_MODES:
        return False
    return not mode or mode in LAZYBEAR_MODES


def _lazybear_level(config, key, default):
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _lazybear_levels(config):
    return {
        "ob1": _lazybear_level(config, "overbought_level_1", LAZYBEAR_OB_LEVEL_1),
        "ob2": _lazybear_level(config, "overbought_level_2", LAZYBEAR_OB_LEVEL_2),
        "os1": _lazybear_level(config, "oversold_level_1", LAZYBEAR_OS_LEVEL_1),
        "os2": _lazybear_level(config, "oversold_level_2", LAZYBEAR_OS_LEVEL_2),
    }


def _lazybear_zone_matches(wt1, idx, config):
    zone = _lazybear_zone_for_condition(config, None)
    return _lazybear_value_in_zone(_series_value(wt1, idx), zone, config)


def _lazybear_value_in_zone(value, zone, config):
    zone = str(zone or "any").strip().lower()
    if zone in {"", "any", "all", "none"}:
        return True

    if not np.isfinite(value):
        return False

    tolerance = max(0.0, float(config.get("tolerance_pct", 0) or 0))
    levels = _lazybear_levels(config)

    if zone in {"oversold", "oversold_level_2", "os2"}:
        return value <= levels["os2"] + tolerance
    if zone in {"oversold_level_1", "os1", "deep_oversold"}:
        return value <= levels["os1"] + tolerance
    if zone in {"overbought", "overbought_level_2", "ob2"}:
        return value >= levels["ob2"] - tolerance
    if zone in {"overbought_level_1", "ob1", "deep_overbought"}:
        return value >= levels["ob1"] - tolerance
    if zone == "neutral":
        return levels["os2"] - tolerance <= value <= levels["ob2"] + tolerance

    return False


def _lazybear_condition_matches(wt1, wt2, idx, config, condition=None):
    condition = condition or _resolve_lazybear_condition(config)
    clauses, logic = _lazybear_condition_clauses(config, condition)
    if not clauses:
        return False

    matches = [
        _lazybear_clause_matches(wt1, wt2, idx, config, clause, condition)
        for clause in clauses
    ]
    return any(matches) if logic == "any" else all(matches)


def _lazybear_condition_clauses(config, condition):
    configured = config.get("conditions")
    if isinstance(configured, list) and configured:
        clauses = [clause for clause in configured if isinstance(clause, dict)]
        return clauses, _lazybear_condition_logic(config)

    return LAZYBEAR_BUILTIN_CONDITIONS.get(condition, []), "all"


def _lazybear_condition_logic(config):
    logic = str(config.get("condition_logic") or config.get("logic") or "all").strip().lower()
    return "any" if logic in {"any", "or"} else "all"


def _lazybear_clause_matches(wt1, wt2, idx, config, clause, parent_condition):
    clause_type = str(clause.get("type") or clause.get("kind") or clause.get("id") or "").strip().lower()
    if clause_type in {"zone", "in_zone"}:
        line = str(clause.get("line") or clause.get("source") or "wt1").strip().lower()
        zone = str(clause.get("zone") or _lazybear_zone_for_condition(config, parent_condition)).strip().lower()
        return _lazybear_value_in_zone(_lazybear_line_value(wt1, wt2, idx, line), zone, config)

    if clause_type in {"cross", "crossover"}:
        direction = str(clause.get("direction") or "any").strip().lower()
        return _lazybear_cross_matches_clause(wt1, wt2, idx, direction)

    if clause_type in {"direction", "slope", "momentum"}:
        line = str(clause.get("line") or clause.get("source") or "wt1").strip().lower()
        direction = str(clause.get("direction") or "").strip().lower()
        return _lazybear_direction_matches_clause(wt1, wt2, idx, line, direction)

    if clause_type in {"compare", "comparison"}:
        return _lazybear_compare_matches_clause(wt1, wt2, idx, clause)

    named_condition = _normalize_lazybear_condition(clause_type)
    nested_clauses = LAZYBEAR_BUILTIN_CONDITIONS.get(named_condition)
    if nested_clauses:
        return all(
            _lazybear_clause_matches(wt1, wt2, idx, config, nested_clause, named_condition)
            for nested_clause in nested_clauses
        )

    return False


def _lazybear_cross_matches_clause(wt1, wt2, idx, direction):
    cross_state = _lazybear_cross_state(wt1, wt2, idx)
    if not cross_state["valid"]:
        return False

    if direction in {"", "any", "both", "cross_any"}:
        return cross_state["crossed_up"] or cross_state["crossed_down"]
    if direction in {"up", "bullish", "cross_up", "crossed_up"}:
        return cross_state["crossed_up"]
    if direction in {"down", "bearish", "cross_down", "crossed_down"}:
        return cross_state["crossed_down"]
    return False


def _lazybear_direction_matches_clause(wt1, wt2, idx, line, direction):
    series = _lazybear_line_series(wt1, wt2, line)
    if series is None:
        return False
    return series_direction_matches(series, idx, direction)


def _lazybear_compare_matches_clause(wt1, wt2, idx, clause):
    left_value = _lazybear_line_value(wt1, wt2, idx, clause.get("left") or clause.get("line") or "wt1")
    right_value = _lazybear_compare_right_value(wt1, wt2, idx, clause)
    if not np.isfinite(left_value) or not np.isfinite(right_value):
        return False

    operator = str(clause.get("operator") or clause.get("op") or "above").strip().lower()
    tolerance = max(0.0, float(clause.get("tolerance") or config_tolerance_fallback(clause) or 0))
    if operator in {"above", "gt", ">"}:
        return left_value > right_value - tolerance
    if operator in {"below", "lt", "<"}:
        return left_value < right_value + tolerance
    if operator in {"gte", ">=", "above_or_equal"}:
        return left_value >= right_value - tolerance
    if operator in {"lte", "<=", "below_or_equal"}:
        return left_value <= right_value + tolerance
    if operator in {"equal", "eq", "near"}:
        return abs(left_value - right_value) <= tolerance
    return False


def config_tolerance_fallback(clause):
    return clause.get("tolerance_pct")


def _lazybear_compare_right_value(wt1, wt2, idx, clause):
    if "value" in clause:
        try:
            return float(clause.get("value"))
        except (TypeError, ValueError):
            return NAN
    return _lazybear_line_value(wt1, wt2, idx, clause.get("right") or "wt2")


def _lazybear_line_series(wt1, wt2, line):
    line = str(line or "wt1").strip().lower()
    if line in {"wt1", "green", "main"}:
        return wt1
    if line in {"wt2", "red", "signal"}:
        return wt2
    if line in {"hist", "histogram", "area"}:
        return np.asarray(wt1, dtype=float) - np.asarray(wt2, dtype=float)
    return None


def _lazybear_line_value(wt1, wt2, idx, line):
    series = _lazybear_line_series(wt1, wt2, line)
    if series is None:
        return NAN
    return _series_value(series, idx)


def _series_value(series, idx):
    try:
        return float(series[idx])
    except (TypeError, ValueError, IndexError):
        return NAN


def _lazybear_cross_state(wt1, wt2, idx):
    if idx - 1 < 0:
        return {
            "valid": False,
            "crossed_up": False,
            "crossed_down": False,
            "hist": NAN,
        }

    prev_wt1 = _series_value(wt1, idx - 1)
    prev_wt2 = _series_value(wt2, idx - 1)
    cur_wt1 = _series_value(wt1, idx)
    cur_wt2 = _series_value(wt2, idx)
    if not all(np.isfinite(v) for v in (prev_wt1, prev_wt2, cur_wt1, cur_wt2)):
        return {
            "valid": False,
            "crossed_up": False,
            "crossed_down": False,
            "hist": NAN,
        }

    prev_delta = prev_wt1 - prev_wt2
    cur_delta = cur_wt1 - cur_wt2
    return {
        "valid": True,
        "crossed_up": prev_delta <= 0 and cur_delta > 0,
        "crossed_down": prev_delta >= 0 and cur_delta < 0,
        "hist": cur_delta,
    }


def build_wavetrend_sticker(wt, config):
    if _uses_lazybear_mode(config):
        return build_lazybear_wavetrend_sticker(wt, config)

    zone = config.get("zone")
    direction = config.get("direction")
    idx = _latest_matching_wavetrend_index(wt, config)
    wt1 = float(wt["wt1"][idx]) if len(wt["wt1"]) else 0.0
    wt2 = float(wt["wt2"][idx]) if len(wt["wt2"]) else 0.0
    zone_text = _zone_text(zone)
    direction_text = direction.replace("_", " ").title() if direction else None
    condition_parts = [f"WT1 {format_decimal(wt1, 1, signed=True)} vs WT2 {format_decimal(wt2, 1, signed=True)}"]
    if zone_text:
        condition_parts.append(zone_text.lower())
    if direction_text:
        condition_parts.append(direction_text.lower())

    return build_indicator_sticker(
        "WaveTrend",
        "; ".join([condition_parts[0], ", ".join(condition_parts[1:])]) if len(condition_parts) > 1 else condition_parts[0],
        config,
        length=config.get("average_length", 21),
        decision=_wavetrend_decision(zone, direction),
    )


def build_lazybear_wavetrend_sticker(wt, config):
    idx = _latest_matching_lazybear_index(wt, config)
    wt1 = float(wt["wt1"][idx]) if len(wt["wt1"]) else 0.0
    wt2 = float(wt["wt2"][idx]) if len(wt["wt2"]) else 0.0
    hist = wt1 - wt2
    cross_text = _lazybear_cross_text(wt["wt1"], wt["wt2"], idx)
    condition_name = _resolve_lazybear_condition(config).replace("_", " ").title()
    levels = _lazybear_levels(config)
    condition = (
        f"{condition_name}; {cross_text}; WT1 {format_decimal(wt1, 1, signed=True)} vs "
        f"WT2 {format_decimal(wt2, 1, signed=True)}; Hist {format_decimal(hist, 1, signed=True)}; "
        f"Levels {format_decimal(levels['ob1'], 0)}/{format_decimal(levels['ob2'], 0)}/"
        f"{format_decimal(levels['os1'], 0)}/{format_decimal(levels['os2'], 0)}"
    )

    return build_indicator_sticker(
        "WaveTrend Cross LazyBear",
        condition,
        config,
        length=config.get("average_length", 21),
        decision=_lazybear_decision(cross_text),
    )


def _zone_text(zone):
    zone_map = {
        "oversold": "Oversold",
        "neutral": "Neutral",
        "overbought": "Overbought",
    }
    return zone_map.get(zone, str(zone or "").strip().title()) if zone else None


def _latest_matching_wavetrend_index(wt, config):
    wt1 = wt["wt1"]
    if len(wt1) == 0:
        return 0

    window = max(1, int(config.get("window", 1) or 1))
    start = max(0, len(wt1) - window)
    latest_match = None

    for idx in range(start, len(wt1)):
        if not _wavetrend_zone_matches(
            wt1,
            idx,
            config.get("zone"),
            float(config.get("tolerance_pct", 0) or 0),
            float(config.get("threshold", DEFAULT_ZONE_THRESHOLD) or DEFAULT_ZONE_THRESHOLD),
        ):
            continue
        if not _wavetrend_direction_matches(wt["wt1"], wt["wt2"], idx, config.get("direction")):
            continue
        latest_match = idx

    return latest_match if latest_match is not None else len(wt1) - 1


def _latest_matching_lazybear_index(wt, config):
    wt1 = wt["wt1"]
    if len(wt1) == 0:
        return 0

    window = max(1, int(config.get("window", 1) or 1))
    start = max(0, len(wt1) - window)
    latest_match = None
    condition = _resolve_lazybear_condition(config)

    for idx in range(start, len(wt1)):
        if not _lazybear_condition_matches(wt["wt1"], wt["wt2"], idx, config, condition):
            continue
        latest_match = idx

    return latest_match if latest_match is not None else len(wt1) - 1


def _lazybear_cross_text(wt1, wt2, idx):
    cross_state = _lazybear_cross_state(wt1, wt2, idx)
    if not cross_state["valid"]:
        return "No Cross"

    if cross_state["crossed_up"]:
        return "Bullish Cross"
    if cross_state["crossed_down"]:
        return "Bearish Cross"
    return "No Cross"


def _resolve_lazybear_condition(config):
    explicit = _first_config_value(
        config,
        "condition",
        "condition_type",
        "lazybear_condition",
        "rule",
        "signal",
        "cross",
        "cross_direction",
    )
    if explicit is not None:
        condition = _normalize_lazybear_condition(explicit)
        if condition != "zone_only":
            return _compose_zone_condition(config, condition)
        return _compose_zone_watch_condition(config)

    legacy_direction = config.get("direction")
    if legacy_direction is not None:
        condition = _normalize_lazybear_legacy_direction(legacy_direction)
        return _compose_zone_condition(config, condition)

    return _compose_zone_condition(config, "cross_any")


def _first_config_value(config, *keys):
    for key in keys:
        if key in config and config.get(key) is not None:
            value = str(config.get(key)).strip().lower()
            if value:
                return value
    return None


def _normalize_lazybear_condition(value):
    normalized = str(value or "").strip().lower()
    return LAZYBEAR_CONDITION_ALIASES.get(normalized, normalized)


def _normalize_lazybear_legacy_direction(value):
    normalized = str(value or "").strip().lower()
    if normalized == "turning_up":
        return "cross_up"
    if normalized == "turning_down":
        return "cross_down"
    if normalized in {"rising", "falling"}:
        return "cross_any"
    return _normalize_lazybear_condition(normalized)


def _compose_zone_condition(config, condition):
    zone = _lazybear_zone_for_condition(config, condition)
    if zone.startswith("oversold") and condition in {"cross_up", "turning_up"}:
        return "oversold_cross_up" if condition == "cross_up" else "turning_up_from_oversold"
    if zone.startswith("overbought") and condition in {"cross_down", "turning_down"}:
        return "overbought_cross_down" if condition == "cross_down" else "turning_down_from_overbought"
    return condition


def _compose_zone_watch_condition(config):
    zone = _lazybear_zone_for_condition(config, "zone_only")
    if zone.startswith("oversold"):
        return "oversold_watch"
    if zone.startswith("overbought"):
        return "overbought_watch"
    return "zone_only"


def _lazybear_zone_for_condition(config, condition):
    configured_zone = str(config.get("zone") or "").strip().lower()
    if configured_zone:
        return configured_zone

    if condition in {"oversold_watch", "oversold_cross_up", "turning_up_from_oversold"}:
        return _lazybear_oversold_zone(config)
    if condition in {"overbought_watch", "overbought_cross_down", "turning_down_from_overbought"}:
        return _lazybear_overbought_zone(config)
    return "any"


def _lazybear_oversold_zone(config):
    level = str(config.get("zone_level") or config.get("level") or "").strip().lower()
    if level in LAZYBEAR_ZONE_LEVEL_1:
        return "oversold_level_1"
    return "oversold"


def _lazybear_overbought_zone(config):
    level = str(config.get("zone_level") or config.get("level") or "").strip().lower()
    if level in LAZYBEAR_ZONE_LEVEL_1:
        return "overbought_level_1"
    return "overbought"


def _lazybear_decision(cross_text):
    if cross_text == "Bullish Cross":
        return "LazyBear Bullish Cross"
    if cross_text == "Bearish Cross":
        return "LazyBear Bearish Cross"
    return "LazyBear WaveTrend Match"


def _wavetrend_decision(zone, direction):
    normalized_zone = str(zone or "").strip().lower()
    normalized_direction = str(direction or "").strip().lower()

    if normalized_zone == "oversold":
        if normalized_direction in {"crossed_up", "turning_up", "rising"}:
            return "Bullish Reversal"
        return "Oversold Watch"

    if normalized_zone == "overbought":
        if normalized_direction in {"crossed_down", "turning_down", "falling"}:
            return "Bearish Reversal"
        return "Overbought Watch"

    if normalized_direction in {"crossed_up", "turning_up", "rising"}:
        return "Bullish Momentum"
    if normalized_direction in {"crossed_down", "turning_down", "falling"}:
        return "Bearish Momentum"
    return "WaveTrend Match"

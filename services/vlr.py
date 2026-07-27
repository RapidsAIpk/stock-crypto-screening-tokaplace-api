# services/vlr.py
#
# VLR Precision Filter — site update/variable linear regression/Variable linear regression.pdf
#
# Oscillator source: "Variable Linear Regression With Pearsons R" + its companion "...Oscillator"
# script, both (c) x11joe / Gentleman-Goat, published open-source on TradingView and pasted in full
# by the client. The Red/Green/Blue lines are the Pearson correlation coefficient between bar
# position (x=0 at the current bar, increasing going backward in time) and price, computed over
# windows of increasing length (default 12, 24, 36) — naturally bounded to [-1, 1].
#
# Sign convention (verified against the source, not assumed): in an uptrend, price is lower further
# back in time (higher x) -> x and y move opposite ways -> negative R. In a downtrend, price is
# higher further back -> positive R. This matches the spec's own wording exactly ("Exact Bullish
# Reversal: Market was trending down ... Red line reaches +0.80 to +1.00").
#
# "Deviation(s)" is computed in the source's createLinReg() but never read by the oscillator (only
# PearsonsR is pushed into the plotted array) — kept here as an inert, editable setting for parity.

import numpy as np

from services.pine_math import pine_relative_volume_ratio
from services.utils import (
    build_indicator_sticker,
    detect_candlestick_patterns,
    format_decimal,
    series_direction_matches,
)

DEFAULT_SOURCE = "close"
DEFAULT_NUM_REGRESSIONS = 3
DEFAULT_START_PERIOD = 12
DEFAULT_PERIOD_INCREMENT = 12
MAX_REGRESSIONS = 10  # matches the source script's input maxval

LINE_NAMES = ["Red", "Green", "Blue"]
LINE_KEYS = {
    "red": 0,
    "r1": 0,
    "fast": 0,
    "green": 1,
    "r2": 1,
    "middle": 1,
    "blue": 2,
    "r3": 2,
    "slow": 2,
}
CONDITION_PRESETS = {
    "bullish_extreme": {
        "logic": "all",
        "conditions": [
            {"type": "zone", "line": "red", "zone": "positive_extreme"},
            {"type": "zone", "line": "green", "zone": "positive_extreme"},
            {"type": "zone", "line": "blue", "zone": "positive"},
        ],
    },
    "bearish_extreme": {
        "logic": "all",
        "conditions": [
            {"type": "zone", "line": "red", "zone": "negative_extreme"},
            {"type": "zone", "line": "green", "zone": "negative_extreme"},
            {"type": "zone", "line": "blue", "zone": "negative"},
        ],
    },
    "extreme_watch": {
        "logic": "any",
        "conditions": [
            {"type": "preset", "name": "bullish_extreme"},
            {"type": "preset", "name": "bearish_extreme"},
        ],
    },
    "bullish_order": {
        "logic": "all",
        "conditions": [
            {"type": "line_order", "direction": "bullish", "lines": ["red", "green", "blue"]},
        ],
    },
    "bearish_order": {
        "logic": "all",
        "conditions": [
            {"type": "line_order", "direction": "bearish", "lines": ["red", "green", "blue"]},
        ],
    },
    "order_watch": {
        "logic": "any",
        "conditions": [
            {"type": "preset", "name": "bullish_order"},
            {"type": "preset", "name": "bearish_order"},
        ],
    },
    "legacy_reversal": {
        "logic": "all",
        "conditions": [
            {"type": "reversal", "reversal_type": "both", "direction": "both"},
        ],
    },
}

BULLISH_PAIR_IDS = ["red_below_green", "red_below_blue", "green_below_blue", "red_below_both"]
BEARISH_PAIR_IDS = ["red_above_green", "red_above_blue", "green_above_blue", "red_above_both"]

PAIR_TAGS = {
    "red_below_green": ["Red Crossed Green"],
    "red_above_green": ["Red Crossed Green"],
    "red_below_blue": ["Red Crossed Blue"],
    "red_above_blue": ["Red Crossed Blue"],
    "green_below_blue": ["Green Crossed Blue"],
    "green_above_blue": ["Green Crossed Blue"],
    "red_below_both": ["Red Crossed Green", "Red Crossed Blue"],
    "red_above_both": ["Red Crossed Green", "Red Crossed Blue"],
}


# =========================================================
# COMPUTE
# =========================================================

def _closed_candles(candles):
    if candles and candles[-1].get("is_closed") is False:
        return candles[:-1]
    return candles


def _source_series(candles, source):
    source = str(source or DEFAULT_SOURCE).strip().lower()
    values = np.zeros(len(candles), dtype=float)
    for i, candle in enumerate(candles):
        o = float(candle["open"])
        h = float(candle["high"])
        l = float(candle["low"])
        c = float(candle["close"])
        if source == "open":
            values[i] = o
        elif source == "high":
            values[i] = h
        elif source == "low":
            values[i] = l
        elif source == "hl2":
            values[i] = (h + l) / 2.0
        elif source == "hlc3":
            values[i] = (h + l + c) / 3.0
        elif source == "ohlc4":
            values[i] = (o + h + l + c) / 4.0
        else:
            values[i] = c
    return values


def _rolling_pearson_r(values, period):
    n = len(values)
    output = np.full(n, np.nan, dtype=float)
    if period < 2 or n < period:
        return output

    ex = float(sum(range(period)))
    ex2 = float(sum(i * i for i in range(period)))
    ex_sq = ex * ex

    for idx in range(period - 1, n):
        window = values[idx - period + 1: idx + 1][::-1]  # window[0] = current (x=0), window[-1] = oldest
        ey = 0.0
        ey2 = 0.0
        exy = 0.0
        for i, y in enumerate(window):
            ey += y
            ey2 += y * y
            exy += y * i
        denom = (ex2 - ex_sq / period) * (ey2 - (ey * ey) / period)
        if denom <= 0:
            continue
        output[idx] = (exy - (ex * ey) / period) / (denom ** 0.5)

    return output


def compute_vlr(
    candles,
    source=DEFAULT_SOURCE,
    num_regressions=DEFAULT_NUM_REGRESSIONS,
    start_period=DEFAULT_START_PERIOD,
    period_increment=DEFAULT_PERIOD_INCREMENT,
):
    candles = _closed_candles(candles)
    num_regressions = max(1, min(MAX_REGRESSIONS, int(num_regressions or DEFAULT_NUM_REGRESSIONS)))
    start_period = max(2, int(start_period or DEFAULT_START_PERIOD))
    period_increment = int(period_increment if period_increment is not None else DEFAULT_PERIOD_INCREMENT)

    longest_period = start_period + (num_regressions - 1) * period_increment
    if len(candles) < longest_period:
        return None

    values = _source_series(candles, source)

    r_series_list = []
    for reg_index in range(num_regressions):
        period = start_period + reg_index * period_increment
        r_series_list.append(_rolling_pearson_r(values, period))

    return {"r": r_series_list}


# =========================================================
# VALUE HELPERS
# =========================================================

def _v(series, idx):
    if idx < 0 or idx >= len(series):
        return None
    value = float(series[idx])
    return value if np.isfinite(value) else None


def _crossed_below(a, b, idx):
    if idx <= 0:
        return False
    a_prev, b_prev = _v(a, idx - 1), _v(b, idx - 1)
    a_cur, b_cur = _v(a, idx), _v(b, idx)
    if None in (a_prev, b_prev, a_cur, b_cur):
        return False
    return a_prev >= b_prev and a_cur < b_cur


def _crossed_above(a, b, idx):
    if idx <= 0:
        return False
    a_prev, b_prev = _v(a, idx - 1), _v(b, idx - 1)
    a_cur, b_cur = _v(a, idx), _v(b, idx)
    if None in (a_prev, b_prev, a_cur, b_cur):
        return False
    return a_prev <= b_prev and a_cur > b_cur


def _resolve_window(config, key="timing_candles", default=1):
    value = (config or {}).get(key)
    if value is None:
        return default
    try:
        window = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, window)


def _event_within_window(n, window, predicate):
    start = max(1, n - window)
    for idx in range(start, n):
        if predicate(idx):
            return True
    return False


def _configured_conditions(config):
    conditions = config.get("vlr_conditions")
    if conditions is None:
        conditions = config.get("conditions")
    if isinstance(conditions, dict):
        return conditions
    if not isinstance(conditions, list):
        preset_conditions, _ = _conditions_from_preset(config)
        return preset_conditions
    return [condition for condition in conditions if isinstance(condition, dict)]


def _condition_logic(config):
    _, preset_logic = _conditions_from_preset(config)
    if preset_logic and not (config.get("condition_logic") or config.get("logic")):
        return preset_logic
    logic = str(config.get("condition_logic") or config.get("logic") or "all").strip().lower()
    return "any" if logic in {"any", "or"} else "all"


def _condition_operator(condition, default="all"):
    logic = str(
        condition.get("operator")
        or condition.get("condition_logic")
        or condition.get("logic")
        or condition.get("mode")
        or default
    ).strip().lower()
    if logic in {"any", "or"}:
        return "any"
    if logic in {"not", "none"}:
        return "not"
    return "all"


def _condition_rules(condition):
    rules = condition.get("rules")
    if rules is None:
        rules = condition.get("conditions")
    if rules is None:
        rules = condition.get("clauses")
    if isinstance(rules, dict):
        return [rules]
    if isinstance(rules, list):
        return [rule for rule in rules if isinstance(rule, dict)]
    return []


def _is_condition_group(condition):
    if not isinstance(condition, dict):
        return False
    if str(condition.get("type") or condition.get("kind") or condition.get("id") or "").strip():
        return False
    return bool(_condition_rules(condition))


def _extend_unique(target, source):
    for tag in source:
        if tag not in target:
            target.append(tag)


def _conditions_from_preset(config):
    preset_name = str(
        config.get("condition_preset")
        or config.get("vlr_preset")
        or config.get("setup")
        or config.get("strategy")
        or ""
    ).strip().lower()
    preset = CONDITION_PRESETS.get(preset_name)
    if not preset:
        return [], None
    return list(preset["conditions"]), preset.get("logic", "all")


def _line_index(line):
    if isinstance(line, int):
        return line
    text = str(line or "red").strip().lower()
    if text.startswith("r") and text[1:].isdigit():
        return int(text[1:]) - 1
    return LINE_KEYS.get(text)


def _line_series(r_series_list, line):
    idx = _line_index(line)
    if idx is None or idx < 0 or idx >= len(r_series_list):
        return None
    return r_series_list[idx]


def _line_value(r_series_list, line, idx):
    series = _line_series(r_series_list, line)
    if series is None:
        return None
    return _v(series, idx)


def _clause_window(config, clause, default_window):
    if "window" in clause:
        try:
            return max(1, int(clause.get("window")))
        except (TypeError, ValueError):
            return default_window
    if "candles_since" in clause:
        return _resolve_window(clause, key="candles_since", default=default_window)
    if "timing_candles" in clause:
        return _resolve_window(clause, key="timing_candles", default=default_window)
    return default_window


# =========================================================
# REVERSAL SETUP
# =========================================================

def _exact_bullish_reversal(red_r, idx):
    peak = _v(red_r, idx - 1)
    if peak is None or not (0.80 <= peak <= 1.00):
        return False
    return series_direction_matches(red_r, idx, "turning_down")


def _early_bullish_reversal(red_r, idx):
    peak = _v(red_r, idx - 1)
    if peak is None or not (0.70 <= peak < 0.80):
        return False
    return series_direction_matches(red_r, idx, "turning_down")


def _exact_bearish_reversal(red_r, idx):
    trough = _v(red_r, idx - 1)
    if trough is None or not (-1.00 <= trough <= -0.80):
        return False
    return series_direction_matches(red_r, idx, "turning_up")


def _early_bearish_reversal(red_r, idx):
    trough = _v(red_r, idx - 1)
    if trough is None or not (-0.80 < trough <= -0.70):
        return False
    return series_direction_matches(red_r, idx, "turning_up")


def _evaluate_reversal(red_r, reversal_type, direction, n, window, matched_tags):
    check_bullish = direction in ("bullish", "both")
    check_bearish = direction in ("bearish", "both")
    check_exact = reversal_type in ("exact", "both")
    check_early = reversal_type in ("early", "both")

    matched = False

    if check_bullish and check_exact and _event_within_window(n, window, lambda i: _exact_bullish_reversal(red_r, i)):
        matched_tags.append("Exact Bullish Reversal Watch")
        matched = True
    if check_bullish and check_early and _event_within_window(n, window, lambda i: _early_bullish_reversal(red_r, i)):
        matched_tags.append("Early Bullish Reversal Watch")
        matched = True
    if check_bearish and check_exact and _event_within_window(n, window, lambda i: _exact_bearish_reversal(red_r, i)):
        matched_tags.append("Exact Bearish Reversal Watch")
        matched = True
    if check_bearish and check_early and _event_within_window(n, window, lambda i: _early_bearish_reversal(red_r, i)):
        matched_tags.append("Early Bearish Reversal Watch")
        matched = True

    return matched


def _reversal_matches_at(red_r, reversal_type, direction, idx, matched_tags=None):
    check_bullish = direction in ("bullish", "both")
    check_bearish = direction in ("bearish", "both")
    check_exact = reversal_type in ("exact", "both")
    check_early = reversal_type in ("early", "both")

    if check_bullish and check_exact and _exact_bullish_reversal(red_r, idx):
        if matched_tags is not None:
            matched_tags.append("Exact Bullish Reversal Watch")
        return True
    if check_bullish and check_early and _early_bullish_reversal(red_r, idx):
        if matched_tags is not None:
            matched_tags.append("Early Bullish Reversal Watch")
        return True
    if check_bearish and check_exact and _exact_bearish_reversal(red_r, idx):
        if matched_tags is not None:
            matched_tags.append("Exact Bearish Reversal Watch")
        return True
    if check_bearish and check_early and _early_bearish_reversal(red_r, idx):
        if matched_tags is not None:
            matched_tags.append("Early Bearish Reversal Watch")
        return True

    return False


def _line_order_matches(r_series_list, idx, clause):
    direction = str(clause.get("direction") or "").strip().lower()
    if direction == "bullish":
        lines = clause.get("lines") or ["red", "green", "blue"]
        operator = str(clause.get("operator") or "above").strip().lower()
    elif direction == "bearish":
        lines = clause.get("lines") or ["red", "green", "blue"]
        operator = str(clause.get("operator") or "below").strip().lower()
    else:
        lines = clause.get("lines") or ["red", "green", "blue"]
        operator = str(clause.get("operator") or clause.get("op") or "above").strip().lower()

    values = [_line_value(r_series_list, line, idx) for line in lines]
    if len(values) < 2 or any(value is None for value in values):
        return False

    tolerance = max(0.0, float(clause.get("tolerance") or clause.get("tolerance_pct") or 0))
    pairs = zip(values, values[1:])
    if operator in {"above", "gt", ">", "descending"}:
        return all(left > right - tolerance for left, right in pairs)
    if operator in {"below", "lt", "<", "ascending"}:
        return all(left < right + tolerance for left, right in pairs)
    return False


def _compare_right_value(r_series_list, idx, clause):
    if "value" in clause:
        try:
            return float(clause.get("value"))
        except (TypeError, ValueError):
            return None
    return _line_value(r_series_list, clause.get("right") or "green", idx)


def _compare_matches(r_series_list, idx, clause):
    left = _line_value(r_series_list, clause.get("left") or clause.get("line") or "red", idx)
    right = _compare_right_value(r_series_list, idx, clause)
    if left is None or right is None:
        return False

    operator = str(clause.get("operator") or clause.get("op") or "above").strip().lower()
    tolerance = max(0.0, float(clause.get("tolerance") or clause.get("tolerance_pct") or 0))
    if operator in {"above", "gt", ">"}:
        return left > right - tolerance
    if operator in {"below", "lt", "<"}:
        return left < right + tolerance
    if operator in {"gte", ">=", "above_or_equal"}:
        return left >= right - tolerance
    if operator in {"lte", "<=", "below_or_equal"}:
        return left <= right + tolerance
    if operator in {"near", "equal", "eq"}:
        return abs(left - right) <= tolerance
    return False


def _zone_matches(r_series_list, idx, clause):
    value = _line_value(r_series_list, clause.get("line") or "red", idx)
    if value is None:
        return False

    zone = str(clause.get("zone") or "").strip().lower()
    tolerance = max(0.0, float(clause.get("tolerance") or clause.get("tolerance_pct") or 0))
    exact_level = float(clause.get("exact_level", 0.80) or 0.80)
    early_level = float(clause.get("early_level", 0.70) or 0.70)

    if zone in {"bullish_exact", "positive_extreme", "downtrend_extreme"}:
        return value >= exact_level - tolerance
    if zone in {"bullish_early", "positive_early"}:
        return early_level - tolerance <= value < exact_level + tolerance
    if zone in {"bearish_exact", "negative_extreme", "uptrend_extreme"}:
        return value <= -exact_level + tolerance
    if zone in {"bearish_early", "negative_early"}:
        return -exact_level - tolerance < value <= -early_level + tolerance
    if zone in {"positive", "above_zero"}:
        return value > 0 - tolerance
    if zone in {"negative", "below_zero"}:
        return value < 0 + tolerance
    if zone in {"neutral", "near_zero"}:
        return abs(value) <= tolerance
    return False


def _direction_matches(r_series_list, idx, clause):
    series = _line_series(r_series_list, clause.get("line") or "red")
    if series is None:
        return False
    direction = str(clause.get("direction") or "").strip().lower()
    return series_direction_matches(series, idx, direction)


def _cross_matches(r_series_list, idx, clause):
    pair_id = clause.get("pair_id")
    if pair_id:
        return _crossing_pair_matches(r_series_list, str(pair_id), idx)

    left = _line_series(r_series_list, clause.get("left") or "red")
    right_line = clause.get("right")
    if "value" in clause:
        try:
            right = np.full(len(left), float(clause.get("value"))) if left is not None else None
        except (TypeError, ValueError):
            return False
    else:
        right = _line_series(r_series_list, right_line or "green")
    if left is None or right is None:
        return False

    direction = str(clause.get("direction") or "any").strip().lower()
    if direction in {"below", "down", "bearish", "crossed_below"}:
        return _crossed_below(left, right, idx)
    if direction in {"above", "up", "bullish", "crossed_above"}:
        return _crossed_above(left, right, idx)
    return _crossed_below(left, right, idx) or _crossed_above(left, right, idx)


def _vlr_clause_matches_at(r_series_list, idx, clause, matched_tags=None):
    clause_type = str(clause.get("type") or clause.get("kind") or clause.get("id") or "").strip().lower()

    if clause_type == "preset":
        preset_name = str(clause.get("name") or clause.get("preset") or "").strip().lower()
        preset = CONDITION_PRESETS.get(preset_name)
        if not preset:
            matched = False
        else:
            preset_matches = [
                _vlr_clause_matches_at(r_series_list, idx, preset_clause, matched_tags)
                for preset_clause in preset["conditions"]
            ]
            matched = any(preset_matches) if preset.get("logic") == "any" else all(preset_matches)
    elif clause_type == "reversal":
        reversal_type = str(clause.get("reversal_type") or "both").strip().lower()
        direction = str(clause.get("direction") or "both").strip().lower()
        matched = _reversal_matches_at(r_series_list[0], reversal_type, direction, idx, matched_tags)
    elif clause_type in {"line_order", "order", "alignment"}:
        matched = _line_order_matches(r_series_list, idx, clause)
        if matched and matched_tags is not None:
            matched_tags.append("Line Order Match")
    elif clause_type in {"compare", "comparison"}:
        matched = _compare_matches(r_series_list, idx, clause)
        if matched and matched_tags is not None:
            matched_tags.append("Line Comparison Match")
    elif clause_type in {"zone", "level", "range"}:
        matched = _zone_matches(r_series_list, idx, clause)
        if matched and matched_tags is not None:
            matched_tags.append("Line Zone Match")
    elif clause_type in {"direction", "slope", "momentum"}:
        matched = _direction_matches(r_series_list, idx, clause)
        if matched and matched_tags is not None:
            matched_tags.append("Line Direction Match")
    elif clause_type in {"cross", "crossover"}:
        matched = _cross_matches(r_series_list, idx, clause)
        if matched and matched_tags is not None:
            matched_tags.append("Line Cross Match")
    else:
        matched = False

    return matched


def _vlr_clause_matches_within_window(r_series_list, n, default_window, config, clause, matched_tags):
    window = _clause_window(config, clause, default_window)
    start = max(1, n - window)
    for idx in range(start, n):
        local_tags = []
        if _vlr_clause_matches_at(r_series_list, idx, clause, local_tags):
            for tag in local_tags:
                if tag not in matched_tags:
                    matched_tags.append(tag)
            return True
    return False


def _vlr_condition_matches(r_series_list, n, default_window, config, condition, matched_tags):
    if not isinstance(condition, dict):
        return False

    if _is_condition_group(condition):
        rules = _condition_rules(condition)
        operator = _condition_operator(condition, default=_condition_logic(config))
        group_window = _clause_window(config, condition, default_window)

        if operator == "not":
            local_tags = []
            matched = any(
                _vlr_condition_matches(r_series_list, n, group_window, config, rule, local_tags)
                for rule in rules
            )
            return not matched

        if operator == "any":
            for rule in rules:
                local_tags = []
                if _vlr_condition_matches(r_series_list, n, group_window, config, rule, local_tags):
                    _extend_unique(matched_tags, local_tags)
                    return True
            return False

        collected_tags = []
        for rule in rules:
            local_tags = []
            if not _vlr_condition_matches(r_series_list, n, group_window, config, rule, local_tags):
                return False
            _extend_unique(collected_tags, local_tags)
        _extend_unique(matched_tags, collected_tags)
        return True

    return _vlr_clause_matches_within_window(r_series_list, n, default_window, config, condition, matched_tags)


def _evaluate_dynamic_vlr_conditions(r_series_list, candles, config, n, window, matched_tags):
    conditions = _configured_conditions(config)
    if not conditions:
        return None

    if isinstance(conditions, dict):
        return _vlr_condition_matches(r_series_list, n, window, config, conditions, matched_tags)

    logic = _condition_logic(config)
    if logic == "any":
        for condition in conditions:
            local_tags = []
            if _vlr_condition_matches(r_series_list, n, window, config, condition, local_tags):
                _extend_unique(matched_tags, local_tags)
                return True
        return False

    collected_tags = []
    for condition in conditions:
        local_tags = []
        if not _vlr_condition_matches(r_series_list, n, window, config, condition, local_tags):
            return False
        _extend_unique(collected_tags, local_tags)
    _extend_unique(matched_tags, collected_tags)
    return True


# =========================================================
# CROSSING CONFIRMATION
# =========================================================

def _below_both(red, green, blue, idx):
    r, g, b = _v(red, idx), _v(green, idx), _v(blue, idx)
    if None in (r, g, b):
        return False
    return r < g and r < b


def _above_both(red, green, blue, idx):
    r, g, b = _v(red, idx), _v(green, idx), _v(blue, idx)
    if None in (r, g, b):
        return False
    return r > g and r > b


def _crossing_pair_matches(r_series_list, pair_id, idx):
    if idx < 1 or len(r_series_list) < 2:
        return False
    red, green = r_series_list[0], r_series_list[1]
    blue = r_series_list[2] if len(r_series_list) > 2 else None

    if pair_id == "red_below_green":
        return _crossed_below(red, green, idx)
    if pair_id == "red_above_green":
        return _crossed_above(red, green, idx)
    if pair_id == "red_below_blue":
        return blue is not None and _crossed_below(red, blue, idx)
    if pair_id == "red_above_blue":
        return blue is not None and _crossed_above(red, blue, idx)
    if pair_id == "green_below_blue":
        return blue is not None and _crossed_below(green, blue, idx)
    if pair_id == "green_above_blue":
        return blue is not None and _crossed_above(green, blue, idx)
    if pair_id == "red_below_both":
        return blue is not None and _below_both(red, green, blue, idx) and not _below_both(red, green, blue, idx - 1)
    if pair_id == "red_above_both":
        return blue is not None and _above_both(red, green, blue, idx) and not _above_both(red, green, blue, idx - 1)
    return False


def _pair_crossed_within_window(r_series_list, pair_id, n, window):
    start = max(1, n - window)
    for idx in range(start, n):
        if _crossing_pair_matches(r_series_list, pair_id, idx):
            return True
    return False


def _multiple_crossings_within_window(r_series_list, pair_ids, n, window):
    matched_pairs = [p for p in pair_ids if _pair_crossed_within_window(r_series_list, p, n, window)]
    return len(matched_pairs) >= 2


def _line_zero_cross_index(r_series, direction, n, window):
    start = max(1, n - window)
    zero = np.zeros(n)
    latest = None
    for idx in range(start, n):
        crossed = _crossed_below(r_series, zero, idx) if direction == "bullish" else _crossed_above(r_series, zero, idx)
        if crossed:
            latest = idx if latest is None else min(latest, idx)
    return latest


def _sequence_matches(r_series_list, sequence, direction, n, window):
    if sequence == "any" or len(r_series_list) < 3:
        return True
    if direction == "both":
        return True  # ordering across two directions at once isn't well-defined; don't gate on it

    red_idx = _line_zero_cross_index(r_series_list[0], direction, n, window)
    green_idx = _line_zero_cross_index(r_series_list[1], direction, n, window)
    blue_idx = _line_zero_cross_index(r_series_list[2], direction, n, window)

    if sequence == "red_first":
        return red_idx is not None and (green_idx is None or red_idx <= green_idx) and (blue_idx is None or red_idx <= blue_idx)
    if sequence == "green_first":
        return green_idx is not None and (red_idx is None or green_idx <= red_idx) and (blue_idx is None or green_idx <= blue_idx)
    if sequence == "blue_first":
        return blue_idx is not None and (red_idx is None or blue_idx <= red_idx) and (green_idx is None or blue_idx <= green_idx)
    if sequence == "sequential":
        return red_idx is not None and green_idx is not None and blue_idx is not None and red_idx <= green_idx <= blue_idx
    return True


def _evaluate_crossing_confirmation(r_series_list, direction, config, n, window, matched_tags):
    selected_bullish = list(config.get("bullish_crossings") or [])
    selected_bearish = list(config.get("bearish_crossings") or [])

    if direction == "bullish":
        selected_bearish = []
    elif direction == "bearish":
        selected_bullish = []

    all_selected = selected_bullish + selected_bearish
    if not all_selected:
        return True

    results = {}
    for pair_id in selected_bullish:
        if pair_id == "multiple_bullish":
            matched = _multiple_crossings_within_window(r_series_list, BULLISH_PAIR_IDS[:3], n, window)
            if matched:
                matched_tags.append("Multiple Bullish Crossings")
        else:
            matched = _pair_crossed_within_window(r_series_list, pair_id, n, window)
            if matched:
                for tag in PAIR_TAGS.get(pair_id, []):
                    if tag not in matched_tags:
                        matched_tags.append(tag)
        results[pair_id] = matched

    for pair_id in selected_bearish:
        if pair_id == "multiple_bearish":
            matched = _multiple_crossings_within_window(r_series_list, BEARISH_PAIR_IDS[:3], n, window)
            if matched:
                matched_tags.append("Multiple Bearish Crossings")
        else:
            matched = _pair_crossed_within_window(r_series_list, pair_id, n, window)
            if matched:
                for tag in PAIR_TAGS.get(pair_id, []):
                    if tag not in matched_tags:
                        matched_tags.append(tag)
        results[pair_id] = matched

    requirement = config.get("multiple_crossing_requirement", "at_least_1")
    matched_count = sum(1 for v in results.values() if v)

    if requirement == "at_least_2":
        passed = matched_count >= 2
    elif requirement == "all_selected":
        passed = matched_count == len(all_selected)
    else:
        passed = matched_count >= 1

    if not passed:
        return False

    sequence = config.get("crossing_sequence", "any")
    sequence_direction = direction if direction in ("bullish", "bearish") else ("bullish" if selected_bullish else "bearish")
    if not _sequence_matches(r_series_list, sequence, sequence_direction, n, window):
        return False
    if sequence == "sequential":
        matched_tags.append("Sequential Confirmation")

    return True


# =========================================================
# OPTIONAL CONFIRMATIONS
# =========================================================

def _evaluate_volume_confirmation(candles, config, n, window, matched_tags):
    min_ratio = float(config.get("volume_min_ratio", 1.5) or 1.5)
    length = int(config.get("volume_length", 10) or 10)
    volumes = np.array([float(c.get("volume") or 0.0) for c in candles], dtype=float)

    start = max(0, n - window)
    for idx in range(start, n):
        ratio = pine_relative_volume_ratio(volumes[: idx + 1], length)
        if np.isfinite(ratio) and ratio >= min_ratio:
            matched_tags.append("Volume Confirmed")
            return True
    return False


def _evaluate_candle_confirmation(candles, config, n, window, matched_tags):
    selected_patterns = config.get("candle_confirmation_patterns") or []
    if not selected_patterns:
        return False

    start = max(0, n - window)
    for idx in range(start, n):
        patterns = detect_candlestick_patterns(candles, idx)
        if any(pattern in patterns for pattern in selected_patterns):
            matched_tags.append("Candle Confirmed")
            return True
    return False


# =========================================================
# TOP-LEVEL RULE EVALUATION
# =========================================================

def evaluate_vlr_rules(computed, candles, config):
    candles = _closed_candles(candles)
    n = len(candles)
    r_series_list = computed["r"]
    if n == 0 or not r_series_list:
        return False, []

    reversal_type = str(config.get("reversal_type") or "both").strip().lower()
    direction = str(config.get("direction") or "both").strip().lower()
    window = _resolve_window(config)

    matched_tags = []

    dynamic_result = _evaluate_dynamic_vlr_conditions(r_series_list, candles, config, n, window, matched_tags)
    if dynamic_result is None:
        if not _evaluate_reversal(r_series_list[0], reversal_type, direction, n, window, matched_tags):
            return False, []
    elif not dynamic_result:
        return False, []

    if config.get("crossing_confirmation"):
        if not _evaluate_crossing_confirmation(r_series_list, direction, config, n, window, matched_tags):
            return False, []

    if config.get("volume_confirmation"):
        if not _evaluate_volume_confirmation(candles, config, n, window, matched_tags):
            return False, []

    if config.get("candle_confirmation"):
        if not _evaluate_candle_confirmation(candles, config, n, window, matched_tags):
            return False, []

    return True, matched_tags


# =========================================================
# STICKER
# =========================================================

def build_vlr_sticker(computed, candles, config, matched_tags):
    candles = _closed_candles(candles)
    r_series_list = computed["r"]
    n = len(candles)
    window = _resolve_window(config)

    values_text = " / ".join(
        f"{LINE_NAMES[i] if i < len(LINE_NAMES) else f'R{i+1}'} {format_decimal(_v(series, n - 1) or 0.0, 2, signed=True)}"
        for i, series in enumerate(r_series_list)
    )

    condition_text = f"{', '.join(matched_tags)} | {values_text}" if matched_tags else values_text

    return build_indicator_sticker(
        "VLR Precision",
        condition_text,
        {"window": window, "confirmation": False},
        length=config.get("start_period", DEFAULT_START_PERIOD),
        window=window,
        decision=None,
    )

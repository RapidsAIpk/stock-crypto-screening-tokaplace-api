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
        candles_ago = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, candles_ago + 1)


def _event_within_window(n, window, predicate):
    start = max(1, n - window)
    for idx in range(start, n):
        if predicate(idx):
            return True
    return False


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

    if not _evaluate_reversal(r_series_list[0], reversal_type, direction, n, window, matched_tags):
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

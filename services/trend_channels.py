# services/trend_channels.py

import math
from collections import defaultdict

import numpy as np

from services.market_data import MAX_CANDLES
from services.utils import detect_touch, confirm_if_needed


MIN_TREND_HISTORY = 40
VOLUME_BREAK_MULTIPLIER = 1.15
RANGE_BREAK_MULTIPLIER = 1.2

LINE_KEYS = (
    "top",
    "bottom",
    "middle",
    "top_zone_upper",
    "top_zone_lower",
    "bottom_zone_upper",
    "bottom_zone_lower",
)
# Matches the ChartPrime Pine source: atr_10 = ta.atr(10) * 6, and each
# boundary line sits offset/7 to either side of its anchor (pivot) line.
ATR_PERIOD = 10
ATR_MULTIPLIER = 6
ZONE_OFFSET_FRACTION = 1.0 / 7.0


# =========================================================
# COMPUTE TREND CHANNEL

# =========================================================

def _slope_non_positive(delta_y: float, delta_x: float) -> bool:
    if delta_x == 0:
        return delta_y <= 0
    return math.atan2(delta_y, delta_x) <= 0


def _slope_non_negative(delta_y: float, delta_x: float) -> bool:
    if delta_x == 0:
        return delta_y >= 0
    return math.atan2(delta_y, delta_x) >= 0


def required_trend_channel_history(length=8):
    # ChartPrime Pine replays pivot/channel state from the first bar on the chart.
    # Truncating history changes which pivots exist, which channels break, and which
    # channel is active on the latest bar — always fetch the full screening budget.
    _ = max(2, int(length or 8))
    return MAX_CANDLES


def compute_trend_channel(candles, length=8, wait_for_break=True, show_last_channel=True):
    normalized_length = max(2, int(length or 8))
    confirmed_pivots = _collect_confirmed_pivots(candles, normalized_length)

    pivot_channel = _compute_pivot_liquidity_channel(
        candles,
        normalized_length,
        confirmed_pivots=confirmed_pivots,
        wait_for_break=bool(wait_for_break),
        show_last_channel=bool(show_last_channel),
    )
    if pivot_channel is not None:
        return pivot_channel

    # ChartPrime Pine never synthesizes a fallback channel. When pivot logic
    # cannot form or retain a channel, there is simply no active channel.
    return None


# =========================================================
# PIVOT-BASED CHANNEL (ChartPrime port)
#
# Reference (Pine): a down-channel is built from the two most recent
# confirmed pivot highs only, sharing one slope; an up-channel is the
# mirror, built from the two most recent confirmed pivot lows only.
# Both lines of a channel share that single slope and are separated by
# a fixed width atr_10 = ta.atr(10) * 6, captured once at the bar the
# channel is created. Only the two most recent pivots per type are ever
# tracked (prev/last) - no combinatorial search, no "flat" channel state.
# A channel breaks on price alone (candle low above the top line, or
# candle high below the bottom line) - volume/range are never part of
# that decision, only informational metadata about the break bar.
# =========================================================

def _compute_pivot_liquidity_channel(
    candles,
    length,
    confirmed_pivots=None,
    wait_for_break=True,
    show_last_channel=True,
):
    if len(candles) < max(length * 2 + 1, 5):
        return None

    pivots_by_confirm_index = defaultdict(list)
    for pivot in confirmed_pivots or _collect_confirmed_pivots(candles, length):
        pivots_by_confirm_index[pivot["confirm_index"]].append(pivot)

    atr = _wilder_atr(candles, ATR_PERIOD)

    prev_high = None
    last_high = None
    prev_low = None
    last_low = None

    down_state = None
    up_state = None
    last_channel = None

    for current_index in range(len(candles)):

        high_just_updated = False
        low_just_updated = False

        for pivot in pivots_by_confirm_index.get(current_index, []):
            if pivot["type"] == "high":
                if last_high is not None:
                    prev_high = last_high
                    high_just_updated = True
                last_high = pivot
            else:
                if last_low is not None:
                    prev_low = last_low
                    low_just_updated = True
                last_low = pivot

        if (
            high_just_updated
            and down_state is None
            and (up_state is None if wait_for_break else True)
            and _slope_non_positive(
                last_high["price"] - prev_high["price"],
                last_high["index"] - prev_high["index"],
            )
        ):
            candidate = _build_channel_state(
                "down", prev_high, last_high, current_index, atr
            )
            if candidate is not None:
                down_state = candidate
                last_channel = dict(candidate)
                if not show_last_channel:
                    up_state = None

        if (
            low_just_updated
            and up_state is None
            and (down_state is None if wait_for_break else True)
            and _slope_non_negative(
                last_low["price"] - prev_low["price"],
                last_low["index"] - prev_low["index"],
            )
        ):
            candidate = _build_channel_state(
                "up", prev_low, last_low, current_index, atr
            )
            if candidate is not None:
                up_state = candidate
                last_channel = dict(candidate)
                if not show_last_channel:
                    down_state = None

        if down_state is not None:
            _advance_channel_line_endpoints(down_state, current_index)
            break_direction = _check_channel_break(down_state, candles[current_index])
            if break_direction is not None:
                down_state["broken"] = True
                down_state["break_index"] = current_index
                down_state["break_direction"] = break_direction
                down_state["liquidity_break"] = _is_liquidity_elevated(candles, current_index, length)
                last_channel = dict(down_state)
                down_state = None

        if up_state is not None:
            _advance_channel_line_endpoints(up_state, current_index)
            break_direction = _check_channel_break(up_state, candles[current_index])
            if break_direction is not None:
                up_state["broken"] = True
                up_state["break_index"] = current_index
                up_state["break_direction"] = break_direction
                up_state["liquidity_break"] = _is_liquidity_elevated(candles, current_index, length)
                last_channel = dict(up_state)
                up_state = None

    channel_state = down_state or up_state or (last_channel if show_last_channel else None)
    if channel_state is None:
        return None

    return _build_rendered_channel(channel_state, len(candles) - 1)


def _collect_confirmed_pivots(candles, pivot_span):
    pivots = []

    if len(candles) < pivot_span * 2 + 1:
        return pivots

    for index in range(pivot_span, len(candles) - pivot_span):
        if _is_pivot_high(candles, index, pivot_span):
            pivots.append(
                {
                    "type": "high",
                    "index": index,
                    "price": float(candles[index]["high"]),
                    "confirm_index": index + pivot_span,
                }
            )
        if _is_pivot_low(candles, index, pivot_span):
            pivots.append(
                {
                    "type": "low",
                    "index": index,
                    "price": float(candles[index]["low"]),
                    "confirm_index": index + pivot_span,
                }
            )

    return sorted(
        pivots,
        key=lambda pivot: (
            pivot["confirm_index"],
            pivot["index"],
            0 if pivot["type"] == "low" else 1,
        ),
    )


def _is_pivot_high(candles, index, span):
    highs = [float(candle["high"]) for candle in candles[index - span:index + span + 1]]
    current = highs[span]
    left = highs[:span]
    right = highs[span + 1:]

    return (
        current == max(highs)
        and current > max(left)
        and current >= max(right)
    )


def _is_pivot_low(candles, index, span):
    lows = [float(candle["low"]) for candle in candles[index - span:index + span + 1]]
    current = lows[span]
    left = lows[:span]
    right = lows[span + 1:]

    return (
        current == min(lows)
        and current < min(left)
        and current <= min(right)
    )


def _build_channel_state(direction, first_pivot, second_pivot, current_index, atr_series):
    first_index = first_pivot["index"]
    second_index = second_pivot["index"]
    span = second_index - first_index
    if span <= 0:
        return None

    slope = (second_pivot["price"] - first_pivot["price"]) / float(span)
    intercept = first_pivot["price"] - slope * first_index

    offset = float(atr_series[current_index]) * ATR_MULTIPLIER
    if offset <= 1e-9:
        return None

    state = {
        "direction": direction,
        "slope": slope,
        "anchor_intercept": intercept,
        "offset": offset,
        "start_index": first_index,
        "anchor_end_index": second_index,
        "created_at": current_index,
        "broken": False,
        "break_index": None,
        "break_direction": None,
        "liquidity_break": False,
    }
    _initialize_channel_line_endpoints(state)
    return state


def _initialize_channel_line_endpoints(channel_state):
    """Seed Pine line anchors at the actual pivot bar indexes.

    Pine stores `last_pivot_high_index := bar_index` at the *confirmation*
    bar (bar_index = actual_pivot_index + length), then builds the line with
    `last_pivot_high_index - length`, which lands back on the actual pivot
    bar. Python's pivot dicts already separate "index" (actual pivot bar)
    from "confirm_index" (index + length), and `_build_channel_state` seeds
    start_index/anchor_end_index from the actual pivot bar directly - so no
    further `- length` belongs here. Subtracting length again would anchor
    the line `length` bars before the pivot it's supposed to pass through.
    """
    x1 = channel_state["start_index"]
    x2 = channel_state["anchor_end_index"]
    channel_state["line_x1"] = x1
    channel_state["line_x2"] = x2

    lines_x1 = _channel_line_values(channel_state, x1)
    lines_x2 = _channel_line_values(channel_state, x2)
    for key in LINE_KEYS:
        channel_state[f"line_y1_{key}"] = lines_x1[key]
        channel_state[f"line_y2_{key}"] = lines_x2[key]


def _advance_channel_line_endpoints(channel_state, bar_index):
    """Mirror Pine's per-bar extrapolation when extend=false (y2 += dydx, x2 = bar_index)."""
    dydx = channel_state["slope"]
    channel_state["line_x2"] = bar_index
    for key in LINE_KEYS:
        channel_state[f"line_y2_{key}"] = channel_state[f"line_y2_{key}"] + dydx


def _line_values_from_endpoints(channel_state, x_values):
    x1 = channel_state["line_x1"]
    x2 = channel_state["line_x2"]
    x_arr = np.asarray(x_values, dtype=float)
    if x2 == x1:
        ratio = np.zeros_like(x_arr)
    else:
        ratio = (x_arr - x1) / float(x2 - x1)

    return {
        key: channel_state[f"line_y1_{key}"]
        + (channel_state[f"line_y2_{key}"] - channel_state[f"line_y1_{key}"]) * ratio
        for key in LINE_KEYS
    }


def _channel_line_values(channel_state, x):
    anchor = channel_state["anchor_intercept"] + channel_state["slope"] * x
    offset = channel_state["offset"]
    zone = offset * ZONE_OFFSET_FRACTION

    if channel_state["direction"] == "down":
        top = anchor + zone
        bottom = anchor - offset - zone
        middle = anchor - offset / 2.0
        top_zone_lower = anchor - zone
        bottom_zone_upper = anchor - offset + zone
    else:
        top = anchor + offset + zone
        bottom = anchor - zone
        middle = anchor + offset / 2.0
        top_zone_lower = anchor + offset - zone
        bottom_zone_upper = anchor + zone

    return {
        "top": top,
        "bottom": bottom,
        "middle": middle,
        "top_zone_upper": top,
        "top_zone_lower": top_zone_lower,
        "bottom_zone_upper": bottom_zone_upper,
        "bottom_zone_lower": bottom,
    }


def _check_channel_break(channel_state, candle):
    # After _advance_channel_line_endpoints, x2 is the current bar and y2 holds
    # the extrapolated boundary prices Pine uses for break checks.
    top = channel_state["line_y2_top"]
    bottom = channel_state["line_y2_bottom"]
    low = float(candle["low"])
    high = float(candle["high"])

    if low > top:
        return "up"
    if high < bottom:
        return "down"
    return None


def _is_liquidity_elevated(candles, current_index, length):
    return (
        _volume_is_elevated(candles, current_index, window=max(length * 2, 10))
        or _range_is_elevated(candles, current_index, window=max(length, 5))
    )


def _volume_is_elevated(candles, current_index, window):
    current_volume = _candle_float(candles[current_index], "volume")
    if current_volume is None or current_volume <= 0:
        return False

    volumes = [
        volume
        for volume in (
            _candle_float(candle, "volume")
            for candle in candles[max(0, current_index - window):current_index]
        )
        if volume is not None and volume > 0
    ]
    if len(volumes) < 3:
        return False

    average_volume = sum(volumes) / float(len(volumes))
    return current_volume >= average_volume * VOLUME_BREAK_MULTIPLIER


def _range_is_elevated(candles, current_index, window):
    current_range = _candle_range(candles[current_index])
    historical_ranges = [
        _candle_range(candle)
        for candle in candles[max(0, current_index - window):current_index]
    ]
    if len(historical_ranges) < 3:
        return False

    average_range = sum(historical_ranges) / float(len(historical_ranges))
    return current_range >= average_range * RANGE_BREAK_MULTIPLIER


def _candle_range(candle):
    return max(float(candle["high"]) - float(candle["low"]), 1e-9)


def _candle_float(candle, key):
    try:
        return float(candle[key])
    except (KeyError, TypeError, ValueError):
        return None


def _build_rendered_channel(channel_state, current_index):
    start_index = channel_state["start_index"]
    x = np.arange(start_index, current_index + 1, dtype=float)
    lines = _line_values_from_endpoints(channel_state, x)

    return {
        "middle": lines["middle"],
        "top": lines["top"],
        "bottom": lines["bottom"],
        "top_zone_upper": lines["top_zone_upper"],
        "top_zone_lower": lines["top_zone_lower"],
        "bottom_zone_upper": lines["bottom_zone_upper"],
        "bottom_zone_lower": lines["bottom_zone_lower"],
        "length": len(x),
        "model": "pivot_liquidity",
        "direction": channel_state["direction"],
        "start_index": start_index,
        "broken": bool(channel_state.get("broken")),
        "break_index": channel_state.get("break_index"),
        "break_direction": channel_state.get("break_direction"),
        "liquidity_break": bool(channel_state.get("liquidity_break")),
        "line_x1": channel_state.get("line_x1"),
        "line_x2": channel_state.get("line_x2"),
    }


# =========================================================
# ATR (WILDER), USED FOR THE CHANNEL WIDTH OFFSET
# =========================================================

def _true_range_series(candles):
    n = len(candles)
    tr = np.zeros(n, dtype=float)
    if n == 0:
        return tr

    prev_close = float(candles[0]["close"])
    for i in range(n):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        if i == 0:
            tr[i] = high - low
        else:
            tr[i] = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close),
            )
        prev_close = float(candles[i]["close"])

    return tr


def _wilder_atr(candles, period=10):
    n = len(candles)
    tr = _true_range_series(candles)
    atr = np.zeros(n, dtype=float)
    if n == 0:
        return atr

    if n <= period:
        running_sum = 0.0
        for i in range(n):
            running_sum += tr[i]
            atr[i] = running_sum / (i + 1)
        return atr

    seed = float(np.mean(tr[:period]))
    atr[:period - 1] = seed
    atr[period - 1] = seed
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


# =========================================================
# EVALUATE RULES
# =========================================================

def _channel_last_signal_index(tc):
    """Last absolute candle index eligible for screener rules.

    When a channel is broken, only bars at or before the break bar may
    generate signals. Post-break extrapolated line values are retained for
    rendering only and must not drive rule evaluation.
    """
    if not tc.get("broken"):
        return None

    break_index = tc.get("break_index")
    if break_index is None:
        return None

    return int(break_index)


def _candle_index_eligible_for_signal(tc, candle_index):
    last_signal_index = _channel_last_signal_index(tc)
    if last_signal_index is None:
        return True
    return int(candle_index) <= last_signal_index


def evaluate_trend_channel_rules(candles, tc, config, evidence=None):

    selected_areas = config.get("areas", [])

    if not selected_areas:
        return False

    all_passed = True

    for area_rule in selected_areas:

        if not evaluate_single_area(
            candles,
            tc,
            area_rule,
            evidence=evidence,
        ):
            all_passed = False
            # Short-circuit on the hot screening path (evidence=None); keep
            # evaluating every configured area when evidence collection was
            # requested so the caller gets a full picture of what failed.
            if evidence is None:
                return False

    return all_passed


# =========================================================
# SINGLE AREA EVALUATION
# =========================================================

def evaluate_single_area(candles, tc, rule, evidence=None):
    result = _evaluate_single_area_core(candles, tc, rule)

    if evidence is not None:
        evidence.append(_build_area_evidence(candles, tc, rule, result))

    return result["matched"]


# Area -> (line series key, break-eligibility direction) used by both the
# window-scan and the closed/on_line "run" evaluators, and by evidence.
_LINE_AREA_SERIES_KEY = {"top_line": "top", "bottom_line": "bottom", "middle_line": "middle"}
_LINE_AREA_DIRECTION = {"top_line": "up", "bottom_line": "down", "middle_line": None}
_ZONE_AREA_KEYS = {
    "top_zone": ("top_zone_lower", "top_zone_upper", "up"),
    "bottom_zone": ("bottom_zone_lower", "bottom_zone_upper", "down"),
}


def _base_candidate_info(candle, candle_index):
    """Per-candidate diagnostic scaffold shared by every evaluation path -
    see the `checked_candidates` schema in evaluate_single_area's evidence.
    """
    open_ = float(candle["open"])
    close = float(candle["close"])
    return {
        "candle_index": candle_index,
        "candle_time": candle.get("time"),
        "is_closed": candle.get("is_closed", True) is not False,
        "open": open_,
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": close,
        "body_low": min(open_, close),
        "body_high": max(open_, close),
        "line_value": None,
        "zone_low": None,
        "zone_high": None,
        "geometry_overlap": False,
        "wick_overlap": False,
        "signal_eligible": True,
        "failure_reason": "",
    }


def _evaluate_area_geometry(tc, rule, area, candle, regression_index):
    """Evaluate one candle against one area's configured action.

    Returns (matched, line_value, zone_low, zone_high, wick_overlap).
    `matched` is exactly the touch_type/action-aware result that decides
    pass/fail (identical to what evaluate_line_action/evaluate_zone_action
    already compute) - `wick_overlap` is a separate, touch_type-independent
    diagnostic showing whether the candle's raw high/low range reaches the
    target at all, useful for explaining near-misses in evidence.
    """
    low = float(candle["low"])
    high = float(candle["high"])

    if area in _LINE_AREA_SERIES_KEY:
        line_series = tc.get(_LINE_AREA_SERIES_KEY[area])
        if line_series is None or regression_index >= len(line_series):
            return False, None, None, None, False
        line_value = float(line_series[regression_index])
        wick_overlap = low <= line_value <= high
        matched = evaluate_line_action(candle, line_value, rule, _LINE_AREA_DIRECTION[area])
        return matched, line_value, None, None, wick_overlap

    if area in _ZONE_AREA_KEYS:
        lower_key, upper_key, direction = _ZONE_AREA_KEYS[area]
        lower_series = tc.get(lower_key)
        upper_series = tc.get(upper_key)
        if lower_series is None or upper_series is None or regression_index >= len(lower_series):
            return False, None, None, None, False
        lower_value = float(lower_series[regression_index])
        upper_value = float(upper_series[regression_index])
        zone_low = min(lower_value, upper_value)
        zone_high = max(lower_value, upper_value)
        wick_overlap = low <= zone_high and high >= zone_low
        matched = evaluate_zone_action(candle, lower_value, upper_value, rule, direction)
        return matched, None, zone_low, zone_high, wick_overlap

    return False, None, None, None, False


def _finalize_area_result(candidates, matched_index, empty_reason="no_candidates_checked"):
    matched = matched_index is not None
    failure_reason = None
    if not matched:
        if not candidates:
            failure_reason = empty_reason
        elif all(not c["signal_eligible"] for c in candidates):
            failure_reason = "channel_broken_before_window"
        else:
            failure_reason = "no_candidate_matched"
    return {
        "matched": matched,
        "matched_index": matched_index,
        "candidates": candidates,
        "failure_reason": failure_reason,
    }


def _evaluate_window_area(candles, tc, rule, area, window, start_index, length):
    """touched/breach (line areas) and entered/rejected/breach (zone areas):
    scan every candle in the trailing `window`, oldest to newest, first
    match wins - identical priority to the pre-fix implementation, but now
    every candidate examined is recorded so evidence can report exactly
    which one (if any) actually matched instead of assuming the latest.
    """
    candidates = []
    matched_index = None
    window = max(1, window)
    first_checked_index = max(0, len(candles) - window)

    for candle_index in range(first_checked_index, len(candles)):
        candle = candles[candle_index]
        candidate = _base_candidate_info(candle, candle_index)

        if not _candle_index_eligible_for_signal(tc, candle_index):
            candidate["signal_eligible"] = False
            candidate["failure_reason"] = "candle_after_channel_break"
            candidates.append(candidate)
            continue

        regression_index = candle_index - start_index
        if regression_index < 0 or regression_index >= length:
            candidate["failure_reason"] = "outside_channel_range"
            candidates.append(candidate)
            continue

        matched, line_value, zone_low, zone_high, wick_overlap = _evaluate_area_geometry(
            tc, rule, area, candle, regression_index,
        )
        candidate["line_value"] = line_value
        candidate["zone_low"] = zone_low
        candidate["zone_high"] = zone_high
        candidate["geometry_overlap"] = matched
        candidate["wick_overlap"] = wick_overlap

        if not matched:
            candidate["failure_reason"] = "no_geometry_overlap"
            candidates.append(candidate)
            continue

        if not confirm_if_needed(candles, candle_index, rule):
            candidate["failure_reason"] = "confirmation_failed"
            candidates.append(candidate)
            continue

        candidates.append(candidate)
        matched_index = candle_index
        break

    return _finalize_area_result(candidates, matched_index)


def _evaluate_run_area(candles, tc, rule, area, window, start_index):
    """closed_above/closed_below/on_line: requires an unbroken run of
    matching candles ending at the LATEST candle, with the run's start
    falling within `window` bars of it (mirrors the pre-fix backward walk
    in _current_line_signal_start_index exactly, one candidate at a time).
    """
    latest_index = len(candles) - 1
    if latest_index < 0:
        return _finalize_area_result([], None, empty_reason="no_candles")

    line_series, direction = _line_series_for_area(tc, area)
    if line_series is None:
        return _finalize_area_result([], None, empty_reason="unsupported_area_for_action")

    last_signal_index = _channel_last_signal_index(tc)
    candidates = []
    signal_start_index = None
    candle_index = latest_index

    while candle_index >= 0:
        candle = candles[candle_index]
        candidate = _base_candidate_info(candle, candle_index)

        eligible = last_signal_index is None or candle_index <= last_signal_index
        if not eligible:
            candidate["signal_eligible"] = False
            candidate["failure_reason"] = "candle_after_channel_break"
            candidates.append(candidate)
            break

        regression_index = candle_index - start_index
        if regression_index < 0 or regression_index >= len(line_series):
            candidate["failure_reason"] = "outside_channel_range"
            candidates.append(candidate)
            break

        line_value = float(line_series[regression_index])
        candidate["line_value"] = line_value
        candidate["wick_overlap"] = float(candle["low"]) <= line_value <= float(candle["high"])
        matched = evaluate_line_action(candle, line_value, rule, direction)
        candidate["geometry_overlap"] = matched

        if not matched:
            candidate["failure_reason"] = "no_geometry_overlap"
            candidates.append(candidate)
            break

        candidates.append(candidate)
        signal_start_index = candle_index
        candle_index -= 1

    if signal_start_index is None:
        return _finalize_area_result(candidates, None)

    if (len(candles) - signal_start_index) > window:
        for candidate in candidates:
            if candidate["candle_index"] == signal_start_index:
                candidate["failure_reason"] = "outside_window"
        return {"matched": False, "matched_index": None, "candidates": candidates, "failure_reason": "outside_window"}

    if not confirm_if_needed(candles, signal_start_index, rule):
        for candidate in candidates:
            if candidate["candle_index"] == signal_start_index:
                candidate["failure_reason"] = "confirmation_failed"
        return {"matched": False, "matched_index": None, "candidates": candidates, "failure_reason": "confirmation_failed"}

    return {"matched": True, "matched_index": signal_start_index, "candidates": candidates, "failure_reason": None}


def _evaluate_single_area_core(candles, tc, rule):
    """Evaluate `rule` and return full diagnostics:
    {"matched": bool, "matched_index": int|None, "candidates": [...],
     "failure_reason": str|None}. See _evaluate_window_area/_evaluate_run_
    area for the two matching strategies this dispatches to.
    """
    area = rule.get("area")
    window = int(rule.get("window", 1) or 1)
    length = tc["length"]
    start_index = len(candles) - length
    action = str(rule.get("action") or "").strip().lower()

    if action in {"closed_above", "closed_below", "on_line"}:
        return _evaluate_run_area(candles, tc, rule, area, window, start_index)

    return _evaluate_window_area(candles, tc, rule, area, window, start_index, length)


def _build_area_evidence(candles, tc, rule, result):
    """Diagnostic snapshot of every candidate candle examined for this area
    rule (see the `checked_candidates` schema), reporting the candle that
    actually matched - or a clear per-candidate failure reason when none
    did - instead of always assuming the latest candle in `candles`.
    """
    area = rule.get("area")
    action = str(rule.get("action") or "").strip().lower()
    matched = result["matched"]
    matched_index = result.get("matched_index")
    candidates = result.get("candidates") or []

    matched_candle_time = None
    if matched_index is not None and 0 <= matched_index < len(candles):
        matched_candle_time = candles[matched_index].get("time")

    info = {
        "area": area,
        "action": action,
        "touch_type": rule.get("touch_type"),
        "window": int(rule.get("window", 1) or 1),
        "matched": bool(matched),
        "channel_direction": tc.get("direction"),
        "channel_start_index": tc.get("start_index"),
        "channel_break_index": tc.get("break_index"),
        "channel_broken": bool(tc.get("broken")),
        "break_index": tc.get("break_index"),
        "checked_candidates": candidates,
        "matched_candle_index": matched_index,
        "matched_candle_time": matched_candle_time,
        "failure_reason": "" if matched else (result.get("failure_reason") or "no_candidate_matched"),
    }

    # Legacy single-candle summary fields, sourced from the candle that
    # actually decided the result (the match when one exists, otherwise the
    # most recently examined candidate) rather than always `candles[-1]`.
    reference_candidate = None
    if matched_index is not None:
        reference_candidate = next((c for c in candidates if c["candle_index"] == matched_index), None)
    if reference_candidate is None and candidates:
        reference_candidate = candidates[-1]

    if reference_candidate is not None:
        info["checked_candle_index"] = reference_candidate["candle_index"]
        info["checked_candle_time"] = reference_candidate["candle_time"]
        info["checked_candle_closed"] = reference_candidate["is_closed"]
        info["candle_low"] = reference_candidate["low"]
        info["candle_high"] = reference_candidate["high"]
        info["body_low"] = reference_candidate["body_low"]
        info["body_high"] = reference_candidate["body_high"]
        if reference_candidate["line_value"] is not None:
            info["line_value"] = reference_candidate["line_value"]
        if reference_candidate["zone_low"] is not None:
            info["zone_low"] = reference_candidate["zone_low"]
            info["zone_high"] = reference_candidate["zone_high"]
        if area in _LINE_AREA_SERIES_KEY or area in _ZONE_AREA_KEYS:
            default_pct = 0.1 if action == "on_line" else 0.0
            raw_tolerance = rule.get("tolerance")
            info["tolerance_pct"] = default_pct if raw_tolerance is None else float(raw_tolerance)

    return info


def _line_series_for_area(tc, area):
    if area == "top_line":
        return tc.get("top"), "up"

    if area == "bottom_line":
        return tc.get("bottom"), "down"

    if area == "middle_line":
        return tc.get("middle"), None

    return None, None


# =========================================================
# LINE ACTIONS
# =========================================================

def evaluate_line_action(candle, line_value, rule, direction=None):

    action = rule.get("action")
    lower_tol, upper_tol = _line_tolerance_bounds(line_value, rule)

    if action == "touched":
        return detect_touch(candle, lower_tol, upper_tol, rule, direction=direction)

    if action == "closed_above":
        return candle["close"] > upper_tol

    if action == "closed_below":
        return candle["close"] < lower_tol

    if action == "on_line":
        on_line_lower, on_line_upper = _line_tolerance_bounds(line_value, rule, default_pct=0.1)
        return on_line_lower <= candle["close"] <= on_line_upper

    if action == "breach":
        return detect_breach(candle, line_value, rule, direction)

    return False


def _line_tolerance_bounds(line_value, rule, default_pct=0.0):
    raw_tolerance = rule.get("tolerance")
    tolerance_pct = default_pct if raw_tolerance is None else float(raw_tolerance)
    tolerance = abs(float(line_value)) * (tolerance_pct / 100.0)
    return float(line_value) - tolerance, float(line_value) + tolerance


# =========================================================
# ZONE ACTIONS
# =========================================================

def _body_bounds_candle(candle):
    return min(candle["open"], candle["close"]), max(candle["open"], candle["close"])


def _zone_tolerance_bounds(zone_low, zone_high, rule):
    """Expand a normalized zone symmetrically by `tolerance` percent per edge.

    Unlike `_line_tolerance_bounds` (which tightens a directional pass/fail
    threshold, e.g. closed_above/closed_below), this widens the target area -
    the same convention already used by `touched`'s tolerance band for lines.
    tolerance=None is treated as 0.0; tolerance=0 is preserved as exactly
    zero (no `or default` fallback that would silently replace a real zero).
    """
    raw_tolerance = rule.get("tolerance")
    tolerance_pct = 0.0 if raw_tolerance is None else float(raw_tolerance)
    low_tolerance = abs(float(zone_low)) * (tolerance_pct / 100.0)
    high_tolerance = abs(float(zone_high)) * (tolerance_pct / 100.0)
    return zone_low - low_tolerance, zone_high + high_tolerance


def _zone_geometry_overlaps(candle, zone_low, zone_high, touch_type):
    wick_overlap = candle["low"] <= zone_high and candle["high"] >= zone_low

    if touch_type == "wick":
        return wick_overlap

    body_low, body_high = _body_bounds_candle(candle)
    body_overlap = body_low <= zone_high and body_high >= zone_low

    if touch_type == "body":
        return body_overlap

    # "both": either the wick or the body overlapping the zone counts.
    return wick_overlap or body_overlap


def evaluate_zone_action(candle, lower, upper, rule, direction=None):

    action = rule.get("action")
    zone_low = min(float(lower), float(upper))
    zone_high = max(float(lower), float(upper))
    tol_zone_low, tol_zone_high = _zone_tolerance_bounds(zone_low, zone_high, rule)
    touch_type = rule.get("touch_type", "wick")

    if action == "entered":
        return _zone_geometry_overlaps(candle, tol_zone_low, tol_zone_high, touch_type)

    if action == "rejected":

        if not _zone_geometry_overlaps(candle, tol_zone_low, tol_zone_high, touch_type):
            return False

        if direction == "up":
            return candle["close"] < zone_low

        if direction == "down":
            return candle["close"] > zone_high

        return False

    if action == "breach":
        breach_direction = rule.get("breach_direction", "any")
        if breach_direction == "up":
            direction = "up"
        elif breach_direction == "down":
            direction = "down"

        breach_type = rule.get("breach_type", rule.get("touch_type", "wick"))
        # Breach uses the zone's outer boundary only, with the same
        # stricter-buffer tolerance convention as closed_above/closed_below.
        _, top_tol = _line_tolerance_bounds(zone_high, rule)
        bottom_tol, _ = _line_tolerance_bounds(zone_low, rule)
        body_low, body_high = _body_bounds_candle(candle)

        def _breached_up():
            if breach_type in {"body", "both"} and body_high > top_tol:
                return True
            if breach_type in {"wick", "both"} and candle["high"] > top_tol:
                return True
            return False

        def _breached_down():
            if breach_type in {"body", "both"} and body_low < bottom_tol:
                return True
            if breach_type in {"wick", "both"} and candle["low"] < bottom_tol:
                return True
            return False

        if direction == "up":
            return _breached_up()
        if direction == "down":
            return _breached_down()
        return _breached_up() or _breached_down()

    return False


# =========================================================
# BREACH DETECTION
# =========================================================

def detect_breach(candle, line_value, rule, direction=None):
    breach_type = rule.get("breach_type", rule.get("touch_type", "wick"))
    breach_direction = rule.get("breach_direction", "any")

    if breach_direction == "up":
        direction = "up"
    elif breach_direction == "down":
        direction = "down"

    wick_up = candle["high"] > line_value
    wick_down = candle["low"] < line_value
    body_up = max(candle["open"], candle["close"]) > line_value
    body_down = min(candle["open"], candle["close"]) < line_value

    if breach_type == "body":
        if direction == "up":
            return body_up
        if direction == "down":
            return body_down
        return body_up or body_down

    if breach_type == "both":
        if direction == "up":
            return wick_up or body_up
        if direction == "down":
            return wick_down or body_down
        return wick_up or wick_down or body_up or body_down

    if direction == "up":
        return wick_up
    if direction == "down":
        return wick_down
    return wick_up or wick_down

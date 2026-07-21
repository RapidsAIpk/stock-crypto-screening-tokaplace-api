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
                "down", prev_high, last_high, current_index, atr, length
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
                "up", prev_low, last_low, current_index, atr, length
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


def _build_channel_state(direction, first_pivot, second_pivot, current_index, atr_series, pivot_length):
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
    _initialize_channel_line_endpoints(state, pivot_length)
    return state


def _initialize_channel_line_endpoints(channel_state, pivot_length):
    """Seed Pine line anchors at pivot_index - length (see trend_channel.md)."""
    x1 = channel_state["start_index"] - pivot_length
    x2 = channel_state["anchor_end_index"] - pivot_length
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


def evaluate_trend_channel_rules(candles, tc, config):

    selected_areas = config.get("areas", [])

    if not selected_areas:
        return False

    for area_rule in selected_areas:

        if not evaluate_single_area(
            candles,
            tc,
            area_rule
        ):
            return False

    return True


# =========================================================
# SINGLE AREA EVALUATION
# =========================================================

def evaluate_single_area(candles, tc, rule):

    area = rule.get("area")
    window = int(rule.get("window", 1) or 1)

    length = tc["length"]
    start_index = len(candles) - length
    action = str(rule.get("action") or "").strip().lower()
    latest_index = len(candles) - 1

    if action in {"closed_above", "closed_below", "on_line"}:
        if not _candle_index_eligible_for_signal(tc, latest_index):
            return False

        line_series, direction = _line_series_for_area(tc, area)
        if line_series is None:
            return False

        signal_start_index = _current_line_signal_start_index(
            candles,
            line_series,
            start_index,
            rule,
            direction,
            tc=tc,
        )
        if signal_start_index is None:
            return False

        if (len(candles) - signal_start_index) > window:
            return False

        return confirm_if_needed(candles, signal_start_index, rule)

    recent_candles = candles[-window:]

    for i in range(window):

        candle = recent_candles[i]

        candle_index = len(candles) - window + i
        if not _candle_index_eligible_for_signal(tc, candle_index):
            continue

        regression_index = candle_index - start_index

        if regression_index < 0 or regression_index >= length:
            continue

        # -----------------------------
        # LINE AREAS
        # -----------------------------

        if area == "top_line":

            line_value = tc["top"][regression_index]

            if evaluate_line_action(candle, line_value, rule, "up"):
                if confirm_if_needed(candles, candle_index, rule):
                    return True

        elif area == "bottom_line":

            line_value = tc["bottom"][regression_index]

            if evaluate_line_action(candle, line_value, rule, "down"):
                if confirm_if_needed(candles, candle_index, rule):
                    return True

        elif area == "middle_line":

            line_value = tc["middle"][regression_index]

            if evaluate_line_action(candle, line_value, rule):
                if confirm_if_needed(candles, candle_index, rule):
                    return True

        # -----------------------------
        # ZONE AREAS
        # -----------------------------

        elif area == "top_zone":

            lower = tc["top_zone_lower"][regression_index]
            upper = tc["top_zone_upper"][regression_index]

            if evaluate_zone_action(candle, lower, upper, rule, "up"):
                if confirm_if_needed(candles, candle_index, rule):
                    return True

        elif area == "bottom_zone":

            lower = tc["bottom_zone_lower"][regression_index]
            upper = tc["bottom_zone_upper"][regression_index]

            if evaluate_zone_action(candle, lower, upper, rule, "down"):
                if confirm_if_needed(candles, candle_index, rule):
                    return True

    return False


def _line_series_for_area(tc, area):
    if area == "top_line":
        return tc.get("top"), "up"

    if area == "bottom_line":
        return tc.get("bottom"), "down"

    if area == "middle_line":
        return tc.get("middle"), None

    return None, None


def _current_line_signal_start_index(
    candles,
    line_series,
    start_index,
    rule,
    direction=None,
    tc=None,
):
    latest_index = len(candles) - 1

    if latest_index < 0:
        return None

    if tc is not None and not _candle_index_eligible_for_signal(tc, latest_index):
        return None

    if not _line_action_matches_index(
        candles,
        line_series,
        latest_index,
        start_index,
        rule,
        direction,
    ):
        return None

    signal_start_index = latest_index
    last_signal_index = _channel_last_signal_index(tc) if tc is not None else None

    while signal_start_index - 1 >= 0:
        previous_index = signal_start_index - 1
        if last_signal_index is not None and previous_index > last_signal_index:
            break
        if not _line_action_matches_index(
            candles,
            line_series,
            previous_index,
            start_index,
            rule,
            direction,
        ):
            break
        signal_start_index = previous_index

    return signal_start_index


def _line_action_matches_index(
    candles,
    line_series,
    candle_index,
    start_index,
    rule,
    direction=None,
):
    regression_index = candle_index - start_index

    if regression_index < 0 or regression_index >= len(line_series):
        return False

    return evaluate_line_action(
        candles[candle_index],
        line_series[regression_index],
        rule,
        direction,
    )


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
    tolerance_pct = float(rule.get("tolerance", default_pct) or default_pct)
    tolerance = abs(float(line_value)) * (tolerance_pct / 100.0)
    return float(line_value) - tolerance, float(line_value) + tolerance


# =========================================================
# ZONE ACTIONS
# =========================================================

def evaluate_zone_action(candle, lower, upper, rule, direction=None):

    action = rule.get("action")

    # candle intersects zone
    wick_entry = candle["low"] <= upper and candle["high"] >= lower

    if action == "entered":
        return wick_entry

    if action == "rejected":

        if not wick_entry:
            return False

        if direction == "up":
            return candle["close"] < lower

        if direction == "down":
            return candle["close"] > upper

    if action == "breach":
        breach_direction = rule.get("breach_direction", "any")
        if breach_direction == "up":
            direction = "up"
        elif breach_direction == "down":
            direction = "down"

        breach_type = rule.get("breach_type", rule.get("touch_type", "wick"))
        if breach_type in {"body", "both"}:
            if direction == "up":
                body_high = max(candle["open"], candle["close"])
                if body_high > upper:
                    return True
            if direction == "down":
                body_low = min(candle["open"], candle["close"])
                if body_low < lower:
                    return True
            if direction is None and (
                max(candle["open"], candle["close"]) > upper
                or min(candle["open"], candle["close"]) < lower
            ):
                return True

        if breach_type in {"wick", "both"}:
            if direction == "up":
                return candle["high"] > upper
            if direction == "down":
                return candle["low"] < lower
            return candle["high"] > upper or candle["low"] < lower

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

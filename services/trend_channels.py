# services/trend_channels.py

import math
from collections import defaultdict

import numpy as np

from services.utils import detect_touch, confirm_if_needed


MIN_TREND_HISTORY = 40
VOLUME_BREAK_MULTIPLIER = 1.15
RANGE_BREAK_MULTIPLIER = 1.2

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
    normalized_length = max(2, int(length or 8))
    # Pivot channels need enough runway to confirm swings before evaluating the latest bar.
    return min(500, max(normalized_length * 9, normalized_length * 2 + 5, MIN_TREND_HISTORY))


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
            candidate = _build_channel_state("down", prev_high, last_high, current_index, atr)
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
            candidate = _build_channel_state("up", prev_low, last_low, current_index, atr)
            if candidate is not None:
                up_state = candidate
                last_channel = dict(candidate)
                if not show_last_channel:
                    down_state = None

        if down_state is not None:
            break_direction = _check_channel_break(down_state, candles[current_index], current_index)
            if break_direction is not None:
                down_state["broken"] = True
                down_state["break_index"] = current_index
                down_state["break_direction"] = break_direction
                down_state["liquidity_break"] = _is_liquidity_elevated(candles, current_index, length)
                last_channel = dict(down_state)
                down_state = None

        if up_state is not None:
            break_direction = _check_channel_break(up_state, candles[current_index], current_index)
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

    return {
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


def _check_channel_break(channel_state, candle, current_index):
    lines = _channel_line_values(channel_state, current_index)
    low = float(candle["low"])
    high = float(candle["high"])

    if low > lines["top"]:
        return "up"
    if high < lines["bottom"]:
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
    x = np.arange(channel_state["start_index"], current_index + 1, dtype=float)
    lines = _channel_line_values(channel_state, x)

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
        "start_index": channel_state["start_index"],
        "broken": bool(channel_state.get("broken")),
        "break_index": channel_state.get("break_index"),
        "break_direction": channel_state.get("break_direction"),
        "liquidity_break": bool(channel_state.get("liquidity_break")),
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

    if action in {"closed_above", "closed_below", "on_line"}:
        line_series, direction = _line_series_for_area(tc, area)
        if line_series is None:
            return False

        signal_start_index = _current_line_signal_start_index(
            candles,
            line_series,
            start_index,
            rule,
            direction,
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
):
    latest_index = len(candles) - 1

    if latest_index < 0:
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

    while signal_start_index - 1 >= 0:
        previous_index = signal_start_index - 1
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

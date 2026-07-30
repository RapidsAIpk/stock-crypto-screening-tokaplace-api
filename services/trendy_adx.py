# services/trendy_adx.py
#
# Trendy ADX DI+/DI- Trend (TradingView Pine v6)
#
# The Pine script uses a 0-seeded recursive accumulator:
# smoothed := nz(smoothed[1]) - nz(smoothed[1]) / length + current
# Keep that literal instead of replacing it with a conventional SMA-seeded RMA.

import numpy as np

from services.pine_math import NAN, pine_sma
from services.utils import build_indicator_sticker, format_decimal

DEFAULT_LENGTH = 11
DEFAULT_THRESHOLD = 20.0
DEFAULT_TOP_LEVEL = 19.0
DEFAULT_RISING_LEVEL = 10.0
DEFAULT_UP_LEVEL = 4.0
DEFAULT_DOWN_LEVEL = -4.0
DEFAULT_FALLING_LEVEL = -10.0
DEFAULT_BOTTOM_LEVEL = -19.0
STRONG_ADX = 25.0
EXHAUSTION_ADX = 40.0

# Internal constants for conditions the spec describes qualitatively but never
# gives a number for (see the plan's "flagged assumptions" — kept as named
# constants, not buried literals, so they're easy to find and adjust).
DIRECTIONAL_TREND_LOOKBACK = 3     # "separating" / "falling away" comparison window
COMPRESSION_TOUCH_TOLERANCE = 0.1  # "touching" epsilon, indicator points
WEAK_LOOKBACK = 10                 # "mixed/changing too often", "no clean cross", "no confirmation"
WEAK_FALLING_LOOKBACK = 5          # "ADX falling" / "ADX flat" comparison window
WEAK_FLAT_TOLERANCE = 0.5          # "ADX flat" tolerance, indicator points
WEAK_FLIP_THRESHOLD = 3            # background flips within WEAK_LOOKBACK to call it "mixed"


# =========================================================
# COMPUTE
# =========================================================

def _closed_candles(candles):
    selected = []
    for candle in candles or []:
        if (
            candle.get("is_closed") is False
            or candle.get("is_complete") is False
            or candle.get("complete") is False
            or candle.get("closed") is False
            or candle.get("is_live") is True
        ):
            continue
        selected.append(candle)
    return selected


def compute_trendy_adx(candles, length=DEFAULT_LENGTH):
    candles = _closed_candles(candles)
    n = len(candles)
    length = max(1, int(length or DEFAULT_LENGTH))

    if n < length + 1:
        return None

    high = np.array([float(c["high"]) for c in candles], dtype=float)
    low = np.array([float(c["low"]) for c in candles], dtype=float)
    close = np.array([float(c["close"]) for c in candles], dtype=float)

    prev_high = np.concatenate(([0.0], high[:-1]))
    prev_low = np.concatenate(([0.0], low[:-1]))
    prev_close = np.concatenate(([0.0], close[:-1]))

    true_range = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )

    up_move = high - prev_high
    down_move = prev_low - low

    dm_plus = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    smoothed_tr = _pine_recursive_sum(true_range, length)
    smoothed_dm_plus = _pine_recursive_sum(dm_plus, length)
    smoothed_dm_minus = _pine_recursive_sum(dm_minus, length)

    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus = np.where(smoothed_tr != 0.0, smoothed_dm_plus / smoothed_tr * 100.0, 0.0)
        di_minus = np.where(smoothed_tr != 0.0, smoothed_dm_minus / smoothed_tr * 100.0, 0.0)

        di_sum = di_plus + di_minus
        dx = np.where(di_sum != 0.0, np.abs(di_plus - di_minus) / di_sum * 100.0, 0.0)

    adx = pine_sma(dx, length)
    trend_value = di_plus - di_minus
    buy_signal = _crossed_above_series(di_plus, di_minus)
    sell_signal = _crossed_above_series(di_minus, di_plus)

    return {
        "true_range": true_range,
        "dm_plus": dm_plus,
        "dm_minus": dm_minus,
        "smoothed_true_range": smoothed_tr,
        "smoothed_dm_plus": smoothed_dm_plus,
        "smoothed_dm_minus": smoothed_dm_minus,
        "di_plus": di_plus,
        "di_minus": di_minus,
        "dx": dx,
        "adx": adx,
        "trend_value": trend_value,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def _pine_recursive_sum(values, length):
    output = np.full(len(values), NAN, dtype=float)
    previous = 0.0
    for index, value in enumerate(values):
        current = float(value) if np.isfinite(value) else 0.0
        previous = previous - previous / length + current
        output[index] = previous
    return output


# =========================================================
# VALUE / EVENT HELPERS
# =========================================================

def _v(series, idx):
    if idx < 0 or idx >= len(series):
        return None
    value = float(series[idx])
    return value if np.isfinite(value) else None


def _crossed_above(a, b, idx):
    if idx <= 0:
        return False
    a_prev, b_prev = _v(a, idx - 1), _v(b, idx - 1)
    a_cur, b_cur = _v(a, idx), _v(b, idx)
    if None in (a_prev, b_prev, a_cur, b_cur):
        return False
    return a_prev <= b_prev and a_cur > b_cur


def _crossed_below(a, b, idx):
    if idx <= 0:
        return False
    a_prev, b_prev = _v(a, idx - 1), _v(b, idx - 1)
    a_cur, b_cur = _v(a, idx), _v(b, idx)
    if None in (a_prev, b_prev, a_cur, b_cur):
        return False
    return a_prev >= b_prev and a_cur < b_cur


def _crossed_above_series(a, b):
    output = np.zeros(len(a), dtype=bool)
    for idx in range(1, len(a)):
        output[idx] = _crossed_above(a, b, idx)
    return output


def _crossed_above_both(adx, dominant, opposing, idx):
    if idx <= 0:
        return False
    v_dom_prev, v_opp_prev = _v(dominant, idx - 1), _v(opposing, idx - 1)
    v_dom_cur, v_opp_cur = _v(dominant, idx), _v(opposing, idx)
    v_adx_prev, v_adx_cur = _v(adx, idx - 1), _v(adx, idx)
    if None in (v_dom_prev, v_opp_prev, v_dom_cur, v_opp_cur, v_adx_prev, v_adx_cur):
        return False
    return v_adx_prev <= max(v_dom_prev, v_opp_prev) and v_adx_cur > max(v_dom_cur, v_opp_cur)


def _find_recent_event(n, window, predicate):
    """Latest index (within the last `window` candles) satisfying predicate.
    Returns (found, candles_since) — candles_since counts back from the latest candle."""
    start = max(0, n - window)
    latest = None
    for idx in range(start, n):
        if predicate(idx):
            latest = idx
    if latest is None:
        return False, None
    return True, (n - 1) - latest


def _resolve_window(condition_cfg, default=1):
    """'Candles since event' preset -> maximum lookback window, matching this
    platform's existing 'within the last N candles' convention (RSI/WaveTrend/Aroon)."""
    value = (condition_cfg or {}).get("candles_since")
    if value is None:
        return default
    try:
        candles_ago = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, candles_ago + 1)


def _resolve_distance(condition_cfg, default=1.0):
    value = (condition_cfg or {}).get("distance")
    if value is None:
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _latest_index(candles, computed):
    return min(len(_closed_candles(candles)), len(computed.get("adx", []))) - 1


def _trend_value(computed):
    if "trend_value" in computed:
        return computed["trend_value"]
    return np.asarray(computed["di_plus"], dtype=float) - np.asarray(computed["di_minus"], dtype=float)


def _level_config(config):
    return {
        "top_level": float(config.get("top_level", DEFAULT_TOP_LEVEL) or DEFAULT_TOP_LEVEL),
        "rising_level": float(config.get("rising_level", DEFAULT_RISING_LEVEL) or DEFAULT_RISING_LEVEL),
        "up_level": float(config.get("up_level", DEFAULT_UP_LEVEL) or DEFAULT_UP_LEVEL),
        "down_level": float(config.get("down_level", DEFAULT_DOWN_LEVEL) or DEFAULT_DOWN_LEVEL),
        "falling_level": float(config.get("falling_level", DEFAULT_FALLING_LEVEL) or DEFAULT_FALLING_LEVEL),
        "bottom_level": float(config.get("bottom_level", DEFAULT_BOTTOM_LEVEL) or DEFAULT_BOTTOM_LEVEL),
    }


def trend_state_series(computed, config=None):
    levels = _level_config(config or {})
    trend = _trend_value(computed)
    states = np.full(len(trend), "neutral", dtype=object)
    finite = np.isfinite(trend)
    states[finite & (trend >= levels["up_level"])] = "up"
    states[finite & (trend >= levels["rising_level"])] = "rising"
    states[finite & (trend >= levels["top_level"])] = "top"
    states[finite & (trend <= levels["down_level"])] = "down"
    states[finite & (trend <= levels["falling_level"])] = "falling"
    states[finite & (trend <= levels["bottom_level"])] = "bottom"
    return states


def _background_condition(condition_id, computed, config, idx):
    state = trend_state_series(computed, config)
    if idx < 0 or idx >= len(state):
        return False
    current = str(state[idx])
    if condition_id == "bullish_trend":
        return current in {"up", "rising", "top"}
    if condition_id == "bearish_trend":
        return current in {"down", "falling", "bottom"}
    if condition_id == "strong_bullish_trend":
        return current == "top"
    if condition_id == "strong_bearish_trend":
        return current == "bottom"
    if condition_id == "compression":
        return current == "neutral"
    return False


def _evaluate_simple_rule(computed, candles, config):
    n = len(_closed_candles(candles))
    idx = min(n, len(computed["adx"])) - 1
    if idx < 0:
        return False

    rule = str(config.get("rule") or config.get("condition") or "").strip().lower()
    threshold = float(config.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
    window = max(1, int(config.get("window", config.get("candles_since", 1)) or 1))
    adx = computed["adx"]
    di_plus = computed["di_plus"]
    di_minus = computed["di_minus"]
    trend_value = _trend_value(computed)

    if rule in {"above", "adx_above", "strong_trend"}:
        value = _v(adx, idx)
        return value is not None and value > threshold
    if rule in {"below", "adx_below", "weak_trend"}:
        value = _v(adx, idx)
        return value is not None and value < threshold
    if rule in {"adx_rising", "rising"}:
        return idx > 0 and _v(adx, idx) is not None and _v(adx, idx - 1) is not None and _v(adx, idx) > _v(adx, idx - 1)
    if rule in {"adx_falling", "falling"}:
        return idx > 0 and _v(adx, idx) is not None and _v(adx, idx - 1) is not None and _v(adx, idx) < _v(adx, idx - 1)
    if rule in {"di_plus_above", "di_plus_above_di_minus", "bullish"}:
        plus, minus = _v(di_plus, idx), _v(di_minus, idx)
        return plus is not None and minus is not None and plus > minus
    if rule in {"di_minus_above", "di_minus_above_di_plus", "bearish"}:
        plus, minus = _v(di_plus, idx), _v(di_minus, idx)
        return plus is not None and minus is not None and minus > plus
    if rule in {"buy_signal", "di_plus_crossed_above", "di_plus_cross_above_di_minus", "bullish_cross"}:
        return _find_recent_event(n, window, lambda i: _crossed_above(di_plus, di_minus, i))[0]
    if rule in {"sell_signal", "di_minus_crossed_above", "di_minus_cross_above_di_plus", "bearish_cross"}:
        return _find_recent_event(n, window, lambda i: _crossed_above(di_minus, di_plus, i))[0]
    if rule in {"trend_strength_increasing", "trend_value_rising"}:
        return idx > 0 and np.isfinite(trend_value[idx]) and np.isfinite(trend_value[idx - 1]) and trend_value[idx] > trend_value[idx - 1]
    if rule in {"trend_strength_decreasing", "trend_value_falling"}:
        return idx > 0 and np.isfinite(trend_value[idx]) and np.isfinite(trend_value[idx - 1]) and trend_value[idx] < trend_value[idx - 1]
    if rule in {"bullish_trend", "bearish_trend", "strong_bullish_trend", "strong_bearish_trend", "compression"}:
        return _background_condition(rule, computed, config, idx)
    if rule in {"trend_reversal", "di_crossover"}:
        return _find_recent_event(
            n,
            window,
            lambda i: _crossed_above(di_plus, di_minus, i) or _crossed_above(di_minus, di_plus, i),
        )[0]
    return False
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


# =========================================================
# BULLISH / BEARISH — shared evaluator, parameterized by which
# DI line is "dominant" (Pink for bullish, Blue for bearish)
# =========================================================

def _evaluate_directional_condition(condition_id, sub_cfg, computed, candles, dominant, opposing, threshold):
    n = len(candles)
    if n == 0:
        return False, None

    adx = computed["adx"]

    if condition_id == "di_crossed_above":
        window = _resolve_window(sub_cfg)
        return _find_recent_event(n, window, lambda i: _crossed_above(dominant, opposing, i))

    if condition_id == "di_already_above":
        v_dom, v_opp = _v(dominant, n - 1), _v(opposing, n - 1)
        return (v_dom is not None and v_opp is not None and v_dom > v_opp), None

    if condition_id == "di_near_cross":
        distance = _resolve_distance(sub_cfg)
        v_dom, v_opp = _v(dominant, n - 1), _v(opposing, n - 1)
        if v_dom is None or v_opp is None:
            return False, None
        return (v_dom < v_opp) and (v_opp - v_dom) <= distance, None

    if condition_id == "di_touched_bounced":
        window = _resolve_window(sub_cfg, default=3)
        v_dom_latest, v_opp_latest = _v(dominant, n - 1), _v(opposing, n - 1)
        if v_dom_latest is None or v_opp_latest is None or v_dom_latest <= v_opp_latest:
            return False, None
        start = max(0, n - window)
        for i in range(start, n - 1):
            v_dom_i, v_opp_i = _v(dominant, i), _v(opposing, i)
            if v_dom_i is None or v_opp_i is None:
                continue
            if v_dom_i - v_opp_i <= COMPRESSION_TOUCH_TOLERANCE:
                return True, (n - 1) - i
        return False, None

    if condition_id == "di_separating":
        lookback = DIRECTIONAL_TREND_LOOKBACK
        if n - 1 - lookback < 0:
            return False, None
        v_dom_now, v_opp_now = _v(dominant, n - 1), _v(opposing, n - 1)
        v_dom_then, v_opp_then = _v(dominant, n - 1 - lookback), _v(opposing, n - 1 - lookback)
        if None in (v_dom_now, v_opp_now, v_dom_then, v_opp_then):
            return False, None
        gap_now = v_dom_now - v_opp_now
        gap_then = v_dom_then - v_opp_then
        return gap_now > 0 and gap_now > gap_then, None

    if condition_id == "di_opposite_falling_away":
        lookback = DIRECTIONAL_TREND_LOOKBACK
        if n - 1 - lookback < 0:
            return False, None
        v_opp_now = _v(opposing, n - 1)
        v_opp_then = _v(opposing, n - 1 - lookback)
        if v_opp_now is None or v_opp_then is None:
            return False, None
        return v_opp_now < v_opp_then, None

    if condition_id == "adx_below_20":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx < threshold), None

    if condition_id == "adx_near_20":
        distance = _resolve_distance(sub_cfg)
        v_adx = _v(adx, n - 1)
        if v_adx is None:
            return False, None
        return abs(v_adx - threshold) <= distance, None

    if condition_id == "adx_crossed_above_20":
        window = _resolve_window(sub_cfg)
        level = np.full(n, threshold, dtype=float)
        return _find_recent_event(n, window, lambda i: _crossed_above(adx, level, i))

    if condition_id == "adx_above_20":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx > threshold), None

    if condition_id == "adx_above_25":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx > STRONG_ADX), None

    if condition_id == "adx_above_40":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx > EXHAUSTION_ADX), None

    if condition_id in ("adx_below_dominant", "adx_above_dominant", "adx_near_dominant", "adx_crossed_above_dominant"):
        return _evaluate_adx_vs_line(condition_id, sub_cfg, adx, dominant, n, window_default=1)

    if condition_id in ("adx_below_opposing", "adx_above_opposing", "adx_near_opposing", "adx_crossed_above_opposing"):
        return _evaluate_adx_vs_line(condition_id, sub_cfg, adx, opposing, n, window_default=1)

    if condition_id == "adx_below_both":
        v_adx, v_dom, v_opp = _v(adx, n - 1), _v(dominant, n - 1), _v(opposing, n - 1)
        if None in (v_adx, v_dom, v_opp):
            return False, None
        return v_adx < min(v_dom, v_opp), None

    if condition_id == "adx_between_both":
        v_adx, v_dom, v_opp = _v(adx, n - 1), _v(dominant, n - 1), _v(opposing, n - 1)
        if None in (v_adx, v_dom, v_opp):
            return False, None
        lower, upper = min(v_dom, v_opp), max(v_dom, v_opp)
        return lower < v_adx < upper, None

    if condition_id == "adx_crossed_above_both":
        window = _resolve_window(sub_cfg)
        return _find_recent_event(n, window, lambda i: _crossed_above_both(adx, dominant, opposing, i))

    if condition_id == "adx_above_both":
        v_adx, v_dom, v_opp = _v(adx, n - 1), _v(dominant, n - 1), _v(opposing, n - 1)
        if None in (v_adx, v_dom, v_opp):
            return False, None
        return v_adx > max(v_dom, v_opp), None

    if condition_id in ("bg_just_started", "bg_active", "bg_active_for_x"):
        return _evaluate_background_condition(condition_id, sub_cfg, dominant, opposing, n)

    return False, None


def _evaluate_adx_vs_line(condition_id, sub_cfg, adx, line, n, window_default):
    if condition_id.startswith("adx_below"):
        v_adx, v_line = _v(adx, n - 1), _v(line, n - 1)
        if v_adx is None or v_line is None:
            return False, None
        return v_adx < v_line, None

    if condition_id.startswith("adx_above"):
        v_adx, v_line = _v(adx, n - 1), _v(line, n - 1)
        if v_adx is None or v_line is None:
            return False, None
        return v_adx > v_line, None

    if condition_id.startswith("adx_near"):
        distance = _resolve_distance(sub_cfg)
        v_adx, v_line = _v(adx, n - 1), _v(line, n - 1)
        if v_adx is None or v_line is None:
            return False, None
        return abs(v_adx - v_line) <= distance, None

    if condition_id.startswith("adx_crossed_above"):
        window = _resolve_window(sub_cfg, default=window_default)
        return _find_recent_event(n, window, lambda i: _crossed_above(adx, line, i))

    return False, None


def _evaluate_background_condition(condition_id, sub_cfg, dominant, opposing, n):
    zone_series = dominant > opposing
    if n == 0 or not bool(zone_series[n - 1]):
        return False, None

    if condition_id == "bg_active":
        return True, None

    consecutive = 0
    for i in range(n - 1, -1, -1):
        if zone_series[i]:
            consecutive += 1
        else:
            break

    if condition_id == "bg_just_started":
        window = _resolve_window(sub_cfg)
        return (consecutive <= window), (consecutive - 1)

    if condition_id == "bg_active_for_x":
        threshold_x = _resolve_window(sub_cfg, default=1)
        return (consecutive >= threshold_x), (consecutive - 1)

    return False, None


# =========================================================
# COMPRESSION / WATCH
# =========================================================

def _evaluate_compression_condition(condition_id, sub_cfg, computed, candles, threshold):
    n = len(candles)
    di_plus, di_minus, adx = computed["di_plus"], computed["di_minus"], computed["adx"]

    if condition_id == "di_close_together":
        distance = _resolve_distance(sub_cfg)
        v_plus, v_minus = _v(di_plus, n - 1), _v(di_minus, n - 1)
        if v_plus is None or v_minus is None:
            return False, None
        return abs(v_plus - v_minus) <= distance, None

    if condition_id == "di_touching":
        v_plus, v_minus = _v(di_plus, n - 1), _v(di_minus, n - 1)
        if v_plus is None or v_minus is None:
            return False, None
        return abs(v_plus - v_minus) <= COMPRESSION_TOUCH_TOLERANCE, None

    if condition_id in ("di_pink_toward_blue", "di_blue_toward_pink"):
        lookback = DIRECTIONAL_TREND_LOOKBACK
        if n - 1 - lookback < 0:
            return False, None
        v_plus_now, v_minus_now = _v(di_plus, n - 1), _v(di_minus, n - 1)
        v_plus_then, v_minus_then = _v(di_plus, n - 1 - lookback), _v(di_minus, n - 1 - lookback)
        if None in (v_plus_now, v_minus_now, v_plus_then, v_minus_then):
            return False, None
        gap_now = abs(v_plus_now - v_minus_now)
        gap_then = abs(v_plus_then - v_minus_then)
        if gap_now >= gap_then:
            return False, None
        # Attribute the narrowing to whichever line's own movement closed more of the
        # gap, holding the other line fixed at its earlier value (a simple sensitivity
        # decomposition — avoids assuming which side started above the other).
        pink_contribution = gap_then - abs(v_plus_now - v_minus_then)
        blue_contribution = gap_then - abs(v_plus_then - v_minus_now)
        if condition_id == "di_pink_toward_blue":
            return pink_contribution > blue_contribution, None
        return blue_contribution > pink_contribution, None

    if condition_id == "adx_below_20":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx < threshold), None

    if condition_id == "adx_turning_up":
        if n < 2:
            return False, None
        v_now, v_prev = _v(adx, n - 1), _v(adx, n - 2)
        if v_now is None or v_prev is None:
            return False, None
        return v_now > v_prev, None

    if condition_id == "adx_close_to_20":
        distance = _resolve_distance(sub_cfg)
        v_adx = _v(adx, n - 1)
        if v_adx is None:
            return False, None
        return abs(v_adx - threshold) <= distance, None

    if condition_id == "bg_changed_recently":
        window = _resolve_window(sub_cfg)
        zone_series = di_plus > di_minus
        return _find_recent_event(n, window, lambda i: i > 0 and bool(zone_series[i]) != bool(zone_series[i - 1]))

    return False, None


# =========================================================
# WEAK / AVOID
# =========================================================

def _evaluate_weak_condition(condition_id, sub_cfg, computed, candles, threshold):
    n = len(candles)
    di_plus, di_minus, adx = computed["di_plus"], computed["di_minus"], computed["adx"]

    if condition_id == "adx_below_20":
        v_adx = _v(adx, n - 1)
        return (v_adx is not None and v_adx < threshold), None

    if condition_id == "adx_below_both_di":
        v_adx, v_plus, v_minus = _v(adx, n - 1), _v(di_plus, n - 1), _v(di_minus, n - 1)
        if None in (v_adx, v_plus, v_minus):
            return False, None
        return v_adx < min(v_plus, v_minus), None

    if condition_id == "adx_falling":
        if n - 1 - WEAK_FALLING_LOOKBACK < 0:
            return False, None
        v_now, v_then = _v(adx, n - 1), _v(adx, n - 1 - WEAK_FALLING_LOOKBACK)
        if v_now is None or v_then is None:
            return False, None
        return v_now < v_then, None

    if condition_id == "adx_flat":
        if n - 1 - WEAK_FALLING_LOOKBACK < 0:
            return False, None
        v_now, v_then = _v(adx, n - 1), _v(adx, n - 1 - WEAK_FALLING_LOOKBACK)
        if v_now is None or v_then is None:
            return False, None
        return abs(v_now - v_then) <= WEAK_FLAT_TOLERANCE, None

    if condition_id == "di_close_no_separation":
        distance = _resolve_distance(sub_cfg, default=1.0)
        v_plus, v_minus = _v(di_plus, n - 1), _v(di_minus, n - 1)
        if v_plus is None or v_minus is None:
            return False, None
        return abs(v_plus - v_minus) <= distance, None

    if condition_id == "bg_mixed_or_changing":
        start = max(1, n - WEAK_LOOKBACK)
        zone_series = di_plus > di_minus
        flips = sum(
            1 for i in range(start, n) if bool(zone_series[i]) != bool(zone_series[i - 1])
        )
        return flips >= WEAK_FLIP_THRESHOLD, None

    if condition_id == "no_clean_di_cross":
        found, _ = _find_recent_event(
            n, WEAK_LOOKBACK,
            lambda i: _crossed_above(di_plus, di_minus, i) or _crossed_above(di_minus, di_plus, i),
        )
        return (not found), None

    if condition_id == "no_adx_confirmation":
        v_adx = _v(adx, n - 1)
        if v_adx is not None and v_adx > threshold:
            return False, None  # currently above threshold: confirmed, regardless of when it crossed
        level = np.full(n, threshold, dtype=float)
        found, _ = _find_recent_event(n, WEAK_LOOKBACK, lambda i: _crossed_above(adx, level, i))
        return (not found), None

    return False, None


# =========================================================
# TOP-LEVEL RULE EVALUATION (AND across selected conditions,
# same convention as Trend Channel's `areas` list)
# =========================================================

def evaluate_trendy_adx_rules(computed, candles, config):
    candles = _closed_candles(candles)
    mode = str(config.get("mode") or "").strip().lower()
    conditions = config.get("conditions") or []
    threshold = float(config.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)

    if not conditions and (config.get("rule") or config.get("condition")):
        return _evaluate_simple_rule(computed, candles, config)

    if not mode or not conditions:
        return False

    if mode in ("bullish", "bearish"):
        dominant = computed["di_plus"] if mode == "bullish" else computed["di_minus"]
        opposing = computed["di_minus"] if mode == "bullish" else computed["di_plus"]
        for condition in conditions:
            matched, _ = _evaluate_directional_condition(
                condition.get("id"), condition, computed, candles, dominant, opposing, threshold
            )
            if not matched:
                return False
        return True

    if mode == "compression":
        for condition in conditions:
            matched, _ = _evaluate_compression_condition(condition.get("id"), condition, computed, candles, threshold)
            if not matched:
                return False
        return True

    if mode == "weak":
        for condition in conditions:
            matched, _ = _evaluate_weak_condition(condition.get("id"), condition, computed, candles, threshold)
            if not matched:
                return False
        return True

    return False


# =========================================================
# FINAL LABEL + STICKER
# =========================================================

def _directional_final_label(mode, computed, n, threshold):
    dominant = computed["di_plus"] if mode == "bullish" else computed["di_minus"]
    opposing = computed["di_minus"] if mode == "bullish" else computed["di_plus"]
    prefix = "Bullish" if mode == "bullish" else "Bearish"

    v_adx = _v(computed["adx"], n - 1)
    v_dom = _v(dominant, n - 1)
    v_opp = _v(opposing, n - 1)

    if v_adx is None:
        return f"Early {prefix} / Weak Strength"
    if v_adx > EXHAUSTION_ADX:
        return f"{prefix} Exhaustion Warning"
    if v_adx > STRONG_ADX and v_dom is not None and v_opp is not None and v_adx > v_dom and v_adx > v_opp:
        return f"Strong {prefix} Confirmed"
    if v_adx > threshold and v_dom is not None and v_adx > v_dom:
        return f"{prefix} Confirmed"
    if v_adx >= threshold:
        return f"{prefix} Strength Building"
    return f"Early {prefix} / Weak Strength"


def _final_label(mode, computed, candles, matched_ids, threshold):
    n = len(candles)

    if mode in ("bullish", "bearish"):
        return _directional_final_label(mode, computed, n, threshold)

    if mode == "compression":
        if "di_pink_toward_blue" in matched_ids:
            return "Possible Bearish Interaction Soon"
        if "di_blue_toward_pink" in matched_ids:
            return "Possible Bullish Interaction Soon"
        return "Compression Watch"

    if mode == "weak":
        v_adx = _v(computed["adx"], n - 1)
        v_plus = _v(computed["di_plus"], n - 1)
        v_minus = _v(computed["di_minus"], n - 1)
        if v_adx is not None and v_plus is not None and v_minus is not None and v_adx < threshold and v_adx < min(v_plus, v_minus):
            return "Avoid"
        if "no_clean_di_cross" in matched_ids or "no_adx_confirmation" in matched_ids:
            return "No Confirmation"
        return "Weak Trend"

    return None


def build_trendy_adx_sticker(computed, candles, config):
    candles = _closed_candles(candles)
    n = len(candles)
    mode = str(config.get("mode") or "").strip().lower()
    threshold = float(config.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
    conditions = config.get("conditions") or []
    matched_ids = {condition.get("id") for condition in conditions}

    label = _final_label(mode, computed, candles, matched_ids, threshold)

    v_plus = _v(computed["di_plus"], n - 1) or 0.0
    v_minus = _v(computed["di_minus"], n - 1) or 0.0
    v_adx = _v(computed["adx"], n - 1) or 0.0

    condition_text = (
        f"DI+ {format_decimal(v_plus, 1)} / DI- {format_decimal(v_minus, 1)} / ADX {format_decimal(v_adx, 1)}"
    )

    return build_indicator_sticker(
        "Trendy ADX",
        condition_text,
        {"window": 1, "confirmation": False},
        length=config.get("length", DEFAULT_LENGTH),
        window=1,
        decision=label,
    )


def trendy_adx_debug_trace(computed, candles, config, symbol=None, timeframe=None):
    candles = _closed_candles(candles)
    idx = _latest_index(candles, computed)
    states = trend_state_series(computed, config)
    trend = _trend_value(computed)
    latest = {}
    if idx >= 0:
        latest = {
            "time": candles[idx].get("time") if idx < len(candles) and isinstance(candles[idx], dict) else None,
            "true_range": _v(computed.get("true_range", []), idx),
            "directional_movement_plus": _v(computed.get("dm_plus", []), idx),
            "directional_movement_minus": _v(computed.get("dm_minus", []), idx),
            "smoothed_true_range": _v(computed.get("smoothed_true_range", []), idx),
            "smoothed_directional_movement_plus": _v(computed.get("smoothed_dm_plus", []), idx),
            "smoothed_directional_movement_minus": _v(computed.get("smoothed_dm_minus", []), idx),
            "di_plus": _v(computed["di_plus"], idx),
            "di_minus": _v(computed["di_minus"], idx),
            "dx": _v(computed.get("dx", []), idx),
            "adx": _v(computed["adx"], idx),
            "trend_value": _v(trend, idx),
            "buy_signal": bool(computed.get("buy_signal", np.zeros(len(computed["adx"]), dtype=bool))[idx]),
            "sell_signal": bool(computed.get("sell_signal", np.zeros(len(computed["adx"]), dtype=bool))[idx]),
            "trend_state": str(states[idx]) if idx < len(states) else None,
            "final_signal": evaluate_trendy_adx_rules(computed, candles, config),
        }
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "latest_index": idx,
        "requested_config": dict(config or {}),
        "effective_config": {
            "length": int(config.get("length", DEFAULT_LENGTH) or DEFAULT_LENGTH),
            "threshold": float(config.get("threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD),
            **_level_config(config or {}),
        },
        "latest": latest,
    }

# services/trendy_adx.py
#
# Trendy ADX DI+/DI- Trend (Bonavest reference) — site update/indicator trendy ADX/Indicator Trendy ADX.pdf
#
# DI+/DI-/ADX formula sourced from the open "ADX and DI" script (c) BeikabuOyaji, which the closed-source
# Bonavest indicator's own description credits as a shared origin ("based off of the original code from
# @MasaNakamura"). Smoothing uses this codebase's existing pine_rma (SMA-seeded Wilder smoothing, the
# same convention already used correctly for RSI) instead of the source script's 0-seeded accumulator —
# mathematically the same Wilder-smoothing family, just seeded consistently with every other Wilder-based
# indicator here. The final ADX = SMA(DX, length) step is taken exactly as sourced (SMA, not RMA).

import numpy as np

from services.pine_math import NAN, pine_rma, pine_sma
from services.utils import build_indicator_sticker, format_decimal

DEFAULT_LENGTH = 11
DEFAULT_THRESHOLD = 20.0
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
    if candles and candles[-1].get("is_closed") is False:
        return candles[:-1]
    return candles


def compute_trendy_adx(candles, length=DEFAULT_LENGTH):
    candles = _closed_candles(candles)
    n = len(candles)
    length = max(1, int(length or DEFAULT_LENGTH))

    if n < length + 1:
        return None

    high = np.array([float(c["high"]) for c in candles], dtype=float)
    low = np.array([float(c["low"]) for c in candles], dtype=float)
    close = np.array([float(c["close"]) for c in candles], dtype=float)

    prev_high = np.concatenate(([high[0]], high[:-1]))
    prev_low = np.concatenate(([low[0]], low[:-1]))
    prev_close = np.concatenate(([close[0]], close[:-1]))

    true_range = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )

    up_move = high - prev_high
    down_move = prev_low - low

    dm_plus = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    smoothed_tr = pine_rma(true_range, length)
    smoothed_dm_plus = pine_rma(dm_plus, length)
    smoothed_dm_minus = pine_rma(dm_minus, length)

    with np.errstate(divide="ignore", invalid="ignore"):
        di_plus = np.where(smoothed_tr > 0, smoothed_dm_plus / smoothed_tr * 100.0, NAN)
        di_minus = np.where(smoothed_tr > 0, smoothed_dm_minus / smoothed_tr * 100.0, NAN)

        di_sum = di_plus + di_minus
        dx = np.where(np.isfinite(di_sum) & (di_sum > 0), np.abs(di_plus - di_minus) / di_sum * 100.0, 0.0)

    adx = pine_sma(dx, length)

    return {"di_plus": di_plus, "di_minus": di_minus, "adx": adx}


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

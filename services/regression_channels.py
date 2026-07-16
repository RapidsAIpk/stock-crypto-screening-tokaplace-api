# services/regression_channels.py
from datetime import datetime, timezone

import numpy as np

from services.pine_math import dw_channel_series, jwammo12_channel
from services.utils import detect_touch, confirm_if_needed, humanize_token


# =========================================================
# BASE REGRESSION
# =========================================================

def compute_regression_base(prices):

    length = len(prices)

    if length < 2:
        return None, None

    x = np.arange(length)

    try:
        slope, intercept = np.polyfit(x, prices, 1)
    except Exception:
        return None, None

    regression = intercept + slope * x

    residuals = prices - regression
    std = np.std(residuals)

    return regression, std


# =========================================================
# LINEAR REGRESSION CHANNEL (LRC)
# =========================================================

def compute_lrc_channel(
    candles,
    length=100,
    upper_dev=2.0,
    lower_dev=2.0,
):
    if len(candles) < length:
        return None

    closes = np.array([c["close"] for c in candles], dtype=float)
    channel = jwammo12_channel(closes, length, upper_dev)

    middle = channel["middle"][-length:]
    upper = channel["upper"][-length:]
    lower = channel["lower"][-length:]

    if not np.any(np.isfinite(middle)):
        return None

    try:
        r = np.corrcoef(np.arange(length), closes[-length:])[0, 1]
    except Exception:
        r = None

    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "r": r,
        "length": length,
    }


# =========================================================
# DONOVAN WALL REGRESSION CHANNEL
# =========================================================

def compute_dw_regression_channel(
    candles,
    length=200,
    width_coeff=1.0,
    window_type="continuous",
    interval_step=1,
    filter_type="SMA",
):
    interval_mode = str(window_type).lower() == "interval"
    step = max(1, int(interval_step or 1)) if interval_mode else 1

    if interval_mode:
        selected = _current_day_candles(candles)
        start_index = len(candles) - len(selected)
    else:
        if len(candles) < length:
            return None
        selected = candles[-length:]
        start_index = len(candles) - length

    if not selected:
        return None

    active_length = len(selected)
    per = active_length if interval_mode else length
    closes = np.array([c["close"] for c in selected], dtype=float)
    volumes = np.array([float(c.get("volume", 0) or 0) for c in selected], dtype=float)
    bar_indices = np.arange(start_index, start_index + active_length, dtype=float)

    series = dw_channel_series(
        closes,
        bar_indices,
        per,
        filter_type=str(filter_type or "SMA"),
        width_coeff=width_coeff,
        volumes=volumes,
    )

    if not np.any(np.isfinite(series["middle"])):
        return None

    return {
        "middle": series["middle"],
        "upper": series["upper"],
        "lower": series["lower"],
        "q1": series["q1"],
        "q3": series["q3"],
        "length": active_length,
        "window_type": window_type,
        "interval_step": step,
        "filter_type": str(filter_type or "SMA"),
    }


def _current_day_candles(candles):
    if not candles:
        return []

    latest_day = _candle_utc_day(candles[-1])
    if latest_day is None:
        return []

    start_index = len(candles) - 1
    while start_index - 1 >= 0 and _candle_utc_day(candles[start_index - 1]) == latest_day:
        start_index -= 1

    return candles[start_index:]


def _candle_utc_day(candle):
    try:
        timestamp = int(candle["time"])
    except (KeyError, TypeError, ValueError):
        return None

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()


# =========================================================
# REGRESSION RULE EVALUATION
# =========================================================

def evaluate_regression_lines(
    candles,
    channel,
    config
):

    selected_lines = config.get("lines", [])
    window = int(config.get("window", 1) or 1)
    tolerance_pct = float(config.get("tolerance", 0) or 0)

    if not selected_lines:
        return False

    length = channel.get("length")

    if not length:
        return False

    start_index = len(candles) - length
    recent_candles = candles[-window:]
    action = str(config.get("action") or "").strip().lower()

    for line_name in selected_lines:

        line_series = channel.get(line_name)
        touch_direction = _line_touch_direction(line_name)

        if line_series is None:
            return False

        if action in {"close_above", "close_below", "stay_above", "stay_below"}:
            signal_start_index = _current_signal_start_index(
                candles,
                line_series,
                start_index,
                config,
                touch_direction,
            )
            if signal_start_index is None:
                return False

            if (len(candles) - signal_start_index) > window:
                return False

            if not confirm_if_needed(candles, signal_start_index, config):
                return False

            continue

        matched_this_line = False

        for i in range(window):

            candle = recent_candles[i]

            candle_index = len(candles) - window + i
            regression_index = candle_index - start_index

            if regression_index < 0 or regression_index >= len(line_series):
                continue

            line_value = line_series[regression_index]

            tolerance = abs(line_value) * (tolerance_pct / 100)

            tol_upper = line_value + tolerance
            tol_lower = line_value - tolerance

            if evaluate_line_rule(
                candle,
                tol_lower,
                tol_upper,
                config,
                touch_direction=touch_direction,
            ):

                if confirm_if_needed(
                    candles,
                    candle_index,
                    config
                ):
                    matched_this_line = True
                    break

        if not matched_this_line:
            return False

    return True


def _current_signal_start_index(
    candles,
    line_series,
    start_index,
    config,
    touch_direction=None,
):
    latest_index = len(candles) - 1

    if latest_index < 0:
        return None

    if not _line_rule_matches_index(
        candles,
        line_series,
        latest_index,
        start_index,
        config,
        touch_direction,
    ):
        return None

    signal_start_index = latest_index

    while signal_start_index - 1 >= 0:
        previous_index = signal_start_index - 1
        if not _line_rule_matches_index(
            candles,
            line_series,
            previous_index,
            start_index,
            config,
            touch_direction,
        ):
            break
        signal_start_index = previous_index

    return signal_start_index


def _line_rule_matches_index(
    candles,
    line_series,
    candle_index,
    start_index,
    config,
    touch_direction=None,
):
    regression_index = candle_index - start_index

    if regression_index < 0 or regression_index >= len(line_series):
        return False

    line_value = line_series[regression_index]
    tolerance_pct = float(config.get("tolerance", 0) or 0)
    tolerance = abs(line_value) * (tolerance_pct / 100)

    return evaluate_line_rule(
        candles[candle_index],
        line_value - tolerance,
        line_value + tolerance,
        config,
        touch_direction=touch_direction,
    )


def _line_touch_direction(line_name):
    normalized = str(line_name or "").strip().lower()

    if normalized in {"upper", "top", "q3"}:
        return "up"

    if normalized in {"lower", "bottom", "q1"}:
        return "down"

    return None


# =========================================================
# LINE ACTION RULE
# =========================================================

def evaluate_line_rule(
    candle,
    lower_tol,
    upper_tol,
    config,
    touch_direction=None,
):

    action = config.get("action")

    if action == "touch":
        return detect_touch(
            candle,
            lower_tol,
            upper_tol,
            config,
            direction=touch_direction,
        )

    if action == "close_above":
        return candle["close"] > upper_tol

    if action == "close_below":
        return candle["close"] < lower_tol

    if action == "stay_above":
        return candle["close"] > lower_tol

    if action == "stay_below":
        return candle["close"] < upper_tol

    return False


def build_regression_sticker(indicator_name, channel, config):
    lines = config.get("lines") or []
    action = config.get("action") or "touch"
    touch_type = config.get("touch_type")

    def _line_label(line_name):
        if not line_name:
            return ""
        if str(line_name).lower() in {"q1", "q3"}:
            return str(line_name).upper()
        return f"{humanize_token(line_name)} Line"

    action_map = {
        "touch": f"{humanize_token(touch_type)} Touch" if touch_type else "Touched",
        "close_above": "Closed Above",
        "close_below": "Closed Below",
        "stay_above": "Stayed Above",
        "stay_below": "Stayed Below",
    }

    line_label = "/".join(_line_label(line) for line in lines)
    interaction = action_map.get(action, humanize_token(action))
    condition = f"{line_label}: {interaction}" if line_label else interaction

    return {
        "name": indicator_name,
        "length": channel.get("length"),
        "condition": condition.strip(),
        "decision": _regression_decision(lines, action),
        "window": int(config.get("window", 1) or 1),
    }


def _regression_decision(lines, action):
    normalized_lines = {str(line or "").strip().lower() for line in (lines or [])}
    normalized_action = str(action or "").strip().lower()

    has_upper = bool(normalized_lines.intersection({"upper", "top"}))
    has_lower = bool(normalized_lines.intersection({"lower", "bottom"}))
    has_middle = "middle" in normalized_lines

    if normalized_action == "touch":
        if has_upper and not has_lower and not has_middle:
            return "Resistance Test"
        if has_lower and not has_upper and not has_middle:
            return "Support Test"
        if has_middle and len(normalized_lines) == 1:
            return "Mean Reversion Test"
        return "Channel Reaction"

    if normalized_action == "close_above":
        if has_upper:
            return "Bullish Breakout"
        return "Bullish Reclaim"

    if normalized_action == "close_below":
        if has_lower:
            return "Bearish Breakdown"
        return "Bearish Weakness"

    if normalized_action == "stay_above":
        if has_upper:
            return "Breakout Holding"
        return "Support Holding"

    if normalized_action == "stay_below":
        if has_lower:
            return "Breakdown Holding"
        return "Resistance Holding"

    return "Channel Match"


# =========================================================
# PEARSON R FILTER
# =========================================================

def passes_r_filter(r_value, config):

    if r_value is None:
        return False

    preset = str(config.get("r_filter", "") or "").strip().lower()
    strength = abs(float(r_value))

    if preset == "ignore":
        return True

    if preset == "strong":
        return strength >= 0.70

    if preset == "balanced":
        return 0.50 <= strength <= 0.80

    mode = config.get("r_mode", "ignore")
    r_min = config.get("r_min")
    r_max = config.get("r_max")

    # Auto-mode fallback: if bounds are provided but mode was not set,
    # infer expected behavior from available values.
    if mode == "ignore":
        if r_min is not None and r_max is not None:
            mode = "range"
        elif r_min is not None:
            mode = "min"
        elif r_max is not None:
            mode = "max"

    if mode == "ignore":
        return True

    if mode == "min":
        threshold = float(r_min if r_min is not None else 0)
        return strength >= threshold

    if mode == "range":
        if r_min is None or r_max is None:
            return False

        return float(r_min) <= strength <= float(r_max)

    if mode == "max":
        if r_max is None:
            return False
        return strength <= float(r_max)

    return True

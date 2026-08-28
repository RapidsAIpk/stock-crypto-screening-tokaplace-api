# services/channel_line_rules.py
"""Shared screener rule evaluation for LRC and Donovan Wall regression channels."""

import math

from services.channel_interactions import (
    channel_interaction_stages,
    evaluate_channel_interaction,
    is_channel_interaction_action,
    normalize_channel_interaction_action,
)
from services.range_utils import selection_mode_pass
from services.utils import confirm_if_needed, detect_touch, humanize_token


def evaluate_regression_lines(candles, channel, config, evidence=None):
    selected_lines = config.get("lines", [])
    window = max(1, int(config.get("window", 1) or 1))

    if not selected_lines:
        return False

    length = channel.get("length")

    if not length:
        return False

    start_index = len(candles) - length
    action = str(config.get("action") or "").strip().lower()
    latest_index = len(candles) - 1

    line_results = []

    for line_name in selected_lines:
        line_series = channel.get(line_name)

        if line_series is None:
            return False

        if is_channel_interaction_action(action):
            target_values = _target_values_for_line(line_series, config, line_name, start_index)
            interaction_result = evaluate_channel_interaction(
                candles,
                target_values,
                action,
                config,
            )
            line_results.append(bool(interaction_result["passed"]))
            if evidence is not None:
                evidence.append({
                    "line": line_name,
                    "action": normalize_channel_interaction_action(action),
                    "matched": bool(interaction_result["passed"]),
                    "candles_since": interaction_result.get("candles_since"),
                    "stages": channel_interaction_stages(
                        candles,
                        target_values,
                        action,
                        config,
                        interaction_result.get("event_index"),
                    ),
                })
            continue

        if action in {"touch", "close_above", "close_below", "stay_above", "stay_below"}:
            signal_start_index = _current_signal_start_index(
                candles,
                line_series,
                start_index,
                config,
                line_name,
                None,
            )
            if signal_start_index is None:
                return False

            signal_age = latest_index - signal_start_index + 1
            if signal_age != window:
                return False

            if not confirm_if_needed(candles, signal_start_index, config):
                return False

            line_results.append(True)
            continue

        return False

    return selection_mode_pass(line_results, config.get("selection_mode", "all"))


def _target_values_for_line(line_series, config, line_name=None, start_index=0):
    return [None for _ in range(max(0, int(start_index or 0)))] + [
        _evaluation_line_value(value, config, line_name)
        for value in line_series
    ]


def _current_signal_start_index(
    candles,
    line_series,
    start_index,
    config,
    line_name=None,
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
        line_name,
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
            line_name,
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
    line_name=None,
    touch_direction=None,
):
    regression_index = candle_index - start_index

    if regression_index < 0 or regression_index >= len(line_series):
        return False

    line_value = _evaluation_line_value(line_series[regression_index], config, line_name)
    tolerance_pct = float(config.get("tolerance", 0) or 0)
    tolerance = abs(line_value) * (tolerance_pct / 100)

    return evaluate_line_rule(
        candles[candle_index],
        line_value - tolerance,
        line_value + tolerance,
        config,
        touch_direction=touch_direction,
    )


def _normalize_mintick(config):
    for key in ("mintick", "tick_size", "price_tick_size"):
        if key not in config:
            continue
        try:
            value = float(config.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            return value
    return None


def _round_to_mintick(value, mintick):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return numeric
    scaled = numeric / mintick
    if scaled >= 0:
        return math.floor(scaled + 0.5) * mintick
    return math.ceil(scaled - 0.5) * mintick


def _round_line_to_mintick(value, mintick, line_name=None):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return numeric

    normalized_line = str(line_name or "").strip().lower()
    scaled = numeric / mintick
    if normalized_line in {"upper", "top", "q3"}:
        return math.ceil(scaled) * mintick
    if normalized_line in {"lower", "bottom", "q1"}:
        return math.floor(scaled) * mintick
    return _round_to_mintick(numeric, mintick)


def _evaluation_line_value(value, config, line_name=None):
    mintick = _normalize_mintick(config or {})
    if mintick is None:
        return value
    return _round_line_to_mintick(value, mintick, line_name)


def evaluate_line_rule(candle, lower_tol, upper_tol, config, touch_direction=None):
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
        return candle["low"] > lower_tol

    if action == "stay_below":
        return candle["high"] < upper_tol

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
        "piercing_from_below": "Piercing From Below",
        "reclaimed_from_below_bullish": "Reclaimed From Below",
        "rejected_from_above_bullish": "Rejected From Above",
        "rejected_from_below_bearish": "Rejected From Below",
    }

    line_label = "/".join(_line_label(line) for line in lines)
    canonical_action = normalize_channel_interaction_action(action)
    interaction = action_map.get(canonical_action, action_map.get(action, humanize_token(action)))
    condition = f"{line_label}: {interaction}" if line_label else interaction

    return {
        "name": indicator_name,
        "length": channel.get("length"),
        "condition": condition.strip(),
        "decision": _regression_decision(lines, action),
        "window": int(config.get("window", 1) or 1),
    }


# Decisions for the Phase 2 multi-stage interactions. These are the only
# actions that actually verify a reclaim or a rejection, so they are the only
# ones allowed to claim one - see M3-ISS-02.
CHANNEL_INTERACTION_DECISIONS = {
    "piercing_from_below": "Bullish Piercing",
    "reclaimed_from_below_bullish": "Bullish Reclaim",
    "rejected_from_above_bullish": "Bullish Support Rejection",
    "rejected_from_below_bearish": "Bearish Resistance Rejection",
}


def _regression_decision(lines, action):
    normalized_lines = {str(line or "").strip().lower() for line in (lines or [])}
    normalized_action = str(action or "").strip().lower()

    interaction_action = normalize_channel_interaction_action(normalized_action)
    if interaction_action in CHANNEL_INTERACTION_DECISIONS:
        return CHANNEL_INTERACTION_DECISIONS[interaction_action]

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
        # NOT a reclaim: `close_above` is a single-candle state check that
        # never verifies price previously closed below the line. Calling it
        # "Bullish Reclaim" is what made rejections and reclaims look
        # identical in results (M3-ISS-02).
        return "Bullish Close Above"

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

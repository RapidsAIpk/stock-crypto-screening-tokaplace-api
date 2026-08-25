"""Phase 2 channel line/zone interaction rules.

The helpers in this module evaluate candle-vs-channel interactions at the
same historical index. Callers provide one target value per candle, so the
logic works for flat, regression, and sloped trend-channel lines.
"""

from services.range_utils import candles_since_in_range


CHANNEL_INTERACTION_ACTIONS = {
    "piercing_from_below",
    "reclaimed_from_below_bullish",
    "reclaim_from_below_bullish",
    "rejected_from_above_bullish",
    "rejected_from_above_bullish_support",
    "rejected_from_below_bearish",
    "rejected_from_below_bearish_resistance",
}


def normalize_channel_interaction_action(action):
    normalized = str(action or "").strip().lower()
    aliases = {
        "pierce_from_below": "piercing_from_below",
        "piercing": "piercing_from_below",
        "reclaim_from_below_bullish": "reclaimed_from_below_bullish",
        "reclaim_bullish": "reclaimed_from_below_bullish",
        "rejected_from_above_bullish_support": "rejected_from_above_bullish",
        "bullish_support_rejection": "rejected_from_above_bullish",
        "rejected_from_below_bearish_resistance": "rejected_from_below_bearish",
        "bearish_resistance_rejection": "rejected_from_below_bearish",
    }
    return aliases.get(normalized, normalized)


def is_channel_interaction_action(action):
    return normalize_channel_interaction_action(action) in {
        "piercing_from_below",
        "reclaimed_from_below_bullish",
        "rejected_from_above_bullish",
        "rejected_from_below_bearish",
    }


def _finite_target(target_values, index):
    if index < 0 or index >= len(target_values):
        return None
    try:
        value = float(target_values[index])
    except (TypeError, ValueError):
        return None
    return value


def _close(candles, index):
    return float(candles[index]["close"])


def _overlaps_target(candle, target):
    return float(candle["low"]) <= target <= float(candle["high"])


def _piercing_from_below(candles, target_values, index):
    if index <= 0:
        return False
    target = _finite_target(target_values, index)
    previous_target = _finite_target(target_values, index - 1)
    if target is None or previous_target is None:
        return False
    candle = candles[index]
    return (
        _close(candles, index - 1) < previous_target
        and float(candle["low"]) < target
        and float(candle["high"]) >= target
        and float(candle["close"]) > target
    )


def _rejected_from_above_bullish(candles, target_values, index):
    if index <= 0:
        return False
    target = _finite_target(target_values, index)
    previous_target = _finite_target(target_values, index - 1)
    if target is None or previous_target is None:
        return False
    candle = candles[index]
    return (
        _close(candles, index - 1) > previous_target
        and _overlaps_target(candle, target)
        and float(candle["close"]) > target
    )


def _rejected_from_below_bearish(candles, target_values, index):
    if index <= 0:
        return False
    target = _finite_target(target_values, index)
    previous_target = _finite_target(target_values, index - 1)
    if target is None or previous_target is None:
        return False
    candle = candles[index]
    return (
        _close(candles, index - 1) < previous_target
        and _overlaps_target(candle, target)
        and float(candle["close"]) < target
    )


def _consecutive_below_before(candles, target_values, index):
    count = 0
    cursor = index - 1
    while cursor >= 0:
        target = _finite_target(target_values, cursor)
        if target is None or _close(candles, cursor) >= target:
            break
        count += 1
        cursor -= 1
    return count


def _reclaimed_from_below_bullish(candles, target_values, index, config):
    target = _finite_target(target_values, index)
    if target is None or index <= 0:
        return False
    minimum_below = config.get(
        "below_candles_min",
        config.get("min_consecutive_below", config.get("consecutive_below_min", 1)),
    )
    maximum_below = config.get("below_candles_max", config.get("consecutive_below_max"))
    below_count = _consecutive_below_before(candles, target_values, index)
    if below_count < int(minimum_below or 1):
        return False
    if maximum_below is not None and below_count > int(maximum_below):
        return False
    return float(candles[index]["close"]) > target


def _still_above_now(candles, target_values):
    latest = len(candles) - 1
    target = _finite_target(target_values, latest)
    return target is not None and float(candles[latest]["close"]) > target


def _condition_matches(candles, target_values, index, action, config):
    normalized = normalize_channel_interaction_action(action)
    if normalized == "piercing_from_below":
        return _piercing_from_below(candles, target_values, index)
    if normalized == "reclaimed_from_below_bullish":
        return _reclaimed_from_below_bullish(candles, target_values, index, config)
    if normalized == "rejected_from_above_bullish":
        return _rejected_from_above_bullish(candles, target_values, index)
    if normalized == "rejected_from_below_bearish":
        return _rejected_from_below_bearish(candles, target_values, index)
    return False


def latest_channel_interaction_event(candles, target_values, action, config):
    for index in range(len(candles) - 1, -1, -1):
        if _condition_matches(candles, target_values, index, action, config):
            return index
    return None


def evaluate_channel_interaction(candles, target_values, action, config):
    if not candles or not target_values:
        return {
            "passed": False,
            "event_index": None,
            "candles_since": None,
        }

    normalized = normalize_channel_interaction_action(action)
    latest_index = len(candles) - 1
    event_index = latest_channel_interaction_event(candles, target_values, normalized, config)

    if (
        normalized == "reclaimed_from_below_bullish"
        and config.get("require_still_above_now", True)
        and not _still_above_now(candles, target_values)
    ):
        return {
            "passed": False,
            "event_index": event_index,
            "candles_since": latest_index - event_index if event_index is not None else None,
        }

    passed = candles_since_in_range(
        event_index,
        latest_index,
        config.get("candles_since_min", config.get("min_candles_since")),
        config.get("candles_since_max", config.get("max_candles_since", config.get("window_max"))),
    )
    return {
        "passed": bool(passed),
        "event_index": event_index,
        "candles_since": latest_index - event_index if event_index is not None else None,
    }

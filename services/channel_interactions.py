"""Phase 2 channel line/zone interaction rules.

The helpers in this module evaluate candle-vs-channel interactions at the
same historical index. Callers provide one target value per candle, so the
logic works for flat, regression, and sloped trend-channel lines.
"""

from services.range_utils import candles_since_in_range, consecutive_count_in_range


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


def _consecutive_below_indexes_before(candles, target_values, index):
    """Indexes of the unbroken run of closes below the line ending at
    `index - 1`, oldest first."""
    indexes = []
    cursor = index - 1
    while cursor >= 0:
        target = _finite_target(target_values, cursor)
        if target is None or _close(candles, cursor) >= target:
            break
        indexes.append(cursor)
        cursor -= 1
    indexes.reverse()
    return indexes


def _consecutive_below_before(candles, target_values, index):
    return len(_consecutive_below_indexes_before(candles, target_values, index))


def _reclaimed_from_below_bullish(candles, target_values, index, config):
    target = _finite_target(target_values, index)
    if target is None or index <= 0:
        return False
    min_consecutive_below = config.get("min_consecutive_below", config.get("consecutive_below_min", 1))
    minimum_below = config.get("below_candles_min", config.get("consecutive_below_min", 1))
    maximum_below = config.get("below_candles_max", config.get("consecutive_below_max"))
    below_count = _consecutive_below_before(candles, target_values, index)
    if below_count < int(min_consecutive_below or 1):
        return False
    if not consecutive_count_in_range(below_count, minimum_below, maximum_below):
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


# =========================================================
# EVIDENCE — per-stage breakdown for the detail chart
# =========================================================

def _stage(candles, target_values, index, stage, note):
    if index is None or index < 0 or index >= len(candles):
        return None
    candle = candles[index]
    return {
        "stage": stage,
        "note": note,
        "candle_index": index,
        "candle_time": candle.get("time"),
        "line_value": _finite_target(target_values, index),
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
    }


def channel_interaction_stages(candles, target_values, action, config, event_index):
    """The individual candles that make up one interaction, so the detail
    chart can show *why* it qualified rather than just that it did.

    This is what makes a Reclaim distinguishable from a Rejection on screen:
    a reclaim shows the run of closes below the line before it, a rejection
    shows that price only touched the line and never closed below (M3-ISS-02).
    """
    normalized = normalize_channel_interaction_action(action)
    if event_index is None or not candles:
        return []

    stages = []
    latest_index = len(candles) - 1

    if normalized == "reclaimed_from_below_bullish":
        below_indexes = _consecutive_below_indexes_before(candles, target_values, event_index)
        for position, index in enumerate(below_indexes, start=1):
            stages.append(_stage(
                candles, target_values, index, "closed_below",
                f"Closed below the line ({position} of {len(below_indexes)} consecutive).",
            ))
        stages.append(_stage(
            candles, target_values, event_index, "reclaim_close_above",
            "Reclaim: first candle to close back above the line after that run.",
        ))
        if latest_index != event_index:
            stages.append(_stage(
                candles, target_values, latest_index, "still_above_now",
                "Newest completed candle - still holding above the line.",
            ))

    elif normalized == "rejected_from_above_bullish":
        stages.append(_stage(
            candles, target_values, event_index - 1, "came_from_above",
            "Previous candle closed above the line - price approached from above.",
        ))
        stages.append(_stage(
            candles, target_values, event_index, "rejected_close_above",
            "Touched/pierced the line intraday but closed back above it. "
            "No close below the line is required for a rejection.",
        ))

    elif normalized == "rejected_from_below_bearish":
        stages.append(_stage(
            candles, target_values, event_index - 1, "came_from_below",
            "Previous candle closed below the line - price approached from below.",
        ))
        stages.append(_stage(
            candles, target_values, event_index, "rejected_close_below",
            "Touched/pierced the line intraday but closed back below it.",
        ))

    elif normalized == "piercing_from_below":
        stages.append(_stage(
            candles, target_values, event_index - 1, "closed_below",
            "Previous candle closed below the line.",
        ))
        stages.append(_stage(
            candles, target_values, event_index, "pierced_close_above",
            "Broke up through the line and closed above it.",
        ))

    return [item for item in stages if item is not None]

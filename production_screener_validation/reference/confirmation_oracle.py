from __future__ import annotations

from typing import Any


def _number(candle: dict[str, Any], key: str) -> float:
    return float(candle[key])


def _bullish(candle: dict[str, Any]) -> bool:
    return _number(candle, "close") > _number(candle, "open")


def _bearish(candle: dict[str, Any]) -> bool:
    return _number(candle, "close") < _number(candle, "open")


def patterns(candles: list[dict[str, Any]], index: int) -> set[str]:
    if index < 0 or index >= len(candles):
        return set()
    current = candles[index]
    previous = candles[index - 1] if index else None
    body = abs(_number(current, "close") - _number(current, "open"))
    span = max(_number(current, "high") - _number(current, "low"), 1e-12)
    upper = _number(current, "high") - max(_number(current, "open"), _number(current, "close"))
    lower = min(_number(current, "open"), _number(current, "close")) - _number(current, "low")
    found: set[str] = set()
    if previous and _bearish(previous) and _bullish(current):
        if _number(current, "open") <= _number(previous, "close") and _number(current, "close") >= _number(previous, "open"):
            found.add("bullish_engulfing")
    if previous and _bullish(previous) and _bearish(current):
        if _number(current, "open") >= _number(previous, "close") and _number(current, "close") <= _number(previous, "open"):
            found.add("bearish_engulfing")
    if lower >= body * 2 and upper <= max(body, span * 0.15):
        found.update(("hammer", "bullish_pin_bar"))
    if upper >= body * 2 and lower <= max(body, span * 0.15):
        found.update(("shooting_star", "bearish_pin_bar"))
    if body / span >= 0.85:
        found.add("bullish_marubozu" if _bullish(current) else "bearish_marubozu")
    if body / span >= 0.70:
        if _bullish(current) and upper <= span * 0.15:
            found.add("strong_breakout_candle")
        if _bearish(current) and lower <= span * 0.15:
            found.add("strong_breakdown_candle")
    return found


def confirmation_matches(candles: list[dict[str, Any]], signal_index: int, config: dict[str, Any]) -> tuple[bool, int | None]:
    if not config.get("confirmation", False):
        return True, None
    types = list(config.get("confirmation_types") or [])
    if config.get("confirmation_type") and config["confirmation_type"] not in types:
        types.insert(0, config["confirmation_type"])

    bullish_types = {"bullish", "strong_bullish"}
    bearish_types = {"bearish", "strong_bearish"}
    allowed_patterns: set[str] | None = None
    if types:
        allowed_patterns = set()
        for item in types:
            if item in bullish_types:
                allowed_patterns.update(
                    {
                        "bullish_engulfing",
                        "hammer",
                        "bullish_pin_bar",
                        "bullish_marubozu",
                        "strong_breakout_candle",
                    }
                )
            elif item in bearish_types:
                allowed_patterns.update(
                    {
                        "bearish_engulfing",
                        "shooting_star",
                        "bearish_pin_bar",
                        "bearish_marubozu",
                        "strong_breakdown_candle",
                    }
                )

    requested_patterns = set(config.get("confirmation_patterns") or [])
    if allowed_patterns is not None:
        requested_patterns = {pattern for pattern in requested_patterns if pattern in allowed_patterns}

    has_types = bool(types)
    has_patterns = bool(requested_patterns)
    if not has_types and not has_patterns:
        return False, None

    allowed_types = {"bullish", "bearish", "strong_bullish", "strong_bearish"}
    if any(item not in allowed_types for item in types):
        raise ValueError("unknown confirmation type")
    for index in range(signal_index, min(len(candles), signal_index + int(config.get("confirmation_window", 1)) + 1)):
        candle = candles[index]
        if any(candle.get(flag) is False for flag in ("closed", "complete", "is_closed", "is_complete")):
            continue
        found = patterns(candles, index)
        span = max(_number(candle, "high") - _number(candle, "low"), 1e-12)
        body_ratio = abs(_number(candle, "close") - _number(candle, "open")) / span
        type_match = False
        if has_types:
            type_match = any(
                (item == "bullish" and _bullish(candle))
                or (item == "bearish" and _bearish(candle))
                or (item == "strong_bullish" and _bullish(candle) and body_ratio > 0.6)
                or (item == "strong_bearish" and _bearish(candle) and body_ratio > 0.6)
                for item in types
            )
        pattern_match = bool(has_patterns and requested_patterns.intersection(found))
        if type_match or pattern_match:
            return True, index
    return False, None

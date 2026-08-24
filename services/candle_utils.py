"""Shared candle filtering helpers.

Scanner rules that represent confirmed signals must ignore a live/forming
bar. Providers use a few different flags for that state, so keep the policy
in one place and reuse it from indicator handlers.
"""


def is_completed_candle(candle):
    if not isinstance(candle, dict):
        return False
    if candle.get("is_closed") is False:
        return False
    if candle.get("is_complete") is False:
        return False
    if candle.get("complete") is False:
        return False
    if candle.get("closed") is False:
        return False
    if candle.get("is_live") is True:
        return False
    return True


def completed_candles(candles):
    return [candle for candle in candles or [] if is_completed_candle(candle)]

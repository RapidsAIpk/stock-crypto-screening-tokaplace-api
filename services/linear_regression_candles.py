# services/linear_regression_candles.py
import numpy as np

from services.pine_math import NAN, pine_ema, pine_sma, rolling_linreg
from services.utils import build_indicator_sticker, confirm_if_needed, format_price_value


def compute_linreg_candles(
    candles,
    lr_length=11,
    signal_smoothing=11,
    sma_signal=True,
    lin_reg=True,
):
    n = len(candles)
    min_history = lr_length + (signal_smoothing if sma_signal else 1)

    if n < min_history:
        return None

    def _field_series(field: str) -> np.ndarray:
        values = np.array([float(c[field]) for c in candles], dtype=float)
        if lin_reg:
            return rolling_linreg(values, lr_length, offset=0)
        return values

    bopen = _field_series("open")
    bhigh = _field_series("high")
    blow = _field_series("low")
    bclose = _field_series("close")

    if sma_signal:
        signal = pine_sma(bclose, signal_smoothing)
    else:
        signal = pine_ema(bclose, signal_smoothing)

    return {
        "signal": signal,
        "bopen": bopen,
        "bhigh": bhigh,
        "blow": blow,
        "bclose": bclose,
    }


def _signal_series(lr_result):
    if isinstance(lr_result, dict):
        return lr_result["signal"]
    return lr_result


def _linreg_context(lr_result, candle_idx: int) -> dict:
    if not isinstance(lr_result, dict):
        return {}

    context = {}
    for key in ("bopen", "bclose"):
        series = lr_result.get(key)
        if series is None or candle_idx < 0 or candle_idx >= len(series):
            continue
        value = float(series[candle_idx])
        if np.isfinite(value):
            context[key] = value
    return context


def evaluate_linreg_candle_rules(candles, lr_result, config):
    lr_line = _signal_series(lr_result)
    window = int(config.get("window", 1) or 1)

    if window <= 0:
        window = 1

    if len(lr_line) < window:
        return False

    position_rule = config.get("price_position")
    if not position_rule:
        return False

    close_rule = config.get("close_location")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    start_idx = len(lr_line) - window

    for candle_idx in range(start_idx, len(lr_line)):
        line = float(lr_line[candle_idx])
        if not np.isfinite(line):
            continue

        if isinstance(lr_result, dict) and "bopen" in lr_result:
            virtual_candle = {
                "open": float(lr_result["bopen"][candle_idx]),
                "high": float(lr_result["bhigh"][candle_idx]),
                "low": float(lr_result["blow"][candle_idx]),
                "close": float(lr_result["bclose"][candle_idx]),
            }
        else:
            virtual_candle = candles[candle_idx]
        linreg_context = _linreg_context(lr_result, candle_idx)

        if not check_price_position(virtual_candle, line, position_rule, tolerance_pct):
            continue

        if close_rule and not check_close_location(virtual_candle, line, close_rule, tolerance_pct, linreg_context):
            continue

        if config.get("confirmation") and not confirm_if_needed(candles, candle_idx, config):
            continue

        return True

    return False


def check_price_position(candle, line, rule, tolerance_pct=0):
    tolerance = abs(line) * (float(tolerance_pct) / 100.0)

    if rule == "above":
        return candle["low"] >= (line - tolerance)

    if rule == "below":
        return candle["high"] <= (line + tolerance)

    if rule == "on":
        body_low = min(candle["open"], candle["close"])
        body_high = max(candle["open"], candle["close"])
        return body_low <= (line + tolerance) and body_high >= (line - tolerance)

    if rule == "piercing_from_below":
        return candle["open"] <= (line + tolerance) and candle["close"] >= (line - tolerance)

    if rule == "piercing_from_above":
        return candle["open"] >= (line - tolerance) and candle["close"] <= (line + tolerance)

    return False


def check_close_location(candle, line, rule, tolerance_pct=0, linreg_context=None):
    configured_tolerance = abs(line) * (float(tolerance_pct) / 100.0)
    normalized = str(rule or "").strip().lower()
    linreg_context = linreg_context or {}

    if normalized in {"bullish", "bearish"}:
        bopen = linreg_context.get("bopen")
        bclose = linreg_context.get("bclose")
        if bopen is None or bclose is None:
            bopen = float(candle.get("open", 0.0) or 0.0)
            bclose = float(candle.get("close", 0.0) or 0.0)
        if normalized == "bullish":
            return bopen < bclose
        return bopen > bclose

    if rule == "close_above":
        return candle["close"] >= (line - configured_tolerance)

    if rule == "close_below":
        return candle["close"] <= (line + configured_tolerance)

    if rule == "close_on":
        return abs(candle["close"] - line) <= configured_tolerance

    return False


def build_linreg_candle_sticker(candles, lr_result, config):
    lr_line = _signal_series(lr_result)
    match = _latest_matching_linreg_index(candles, lr_result, config)
    candle_idx = match["candle_idx"]
    candle = candles[candle_idx] if candles and candle_idx < len(candles) else {}
    line_value = float(lr_line[candle_idx]) if len(lr_line) else 0.0
    pos = config.get("price_position")
    close = config.get("close_location")
    linreg_context = _linreg_context(lr_result, candle_idx)

    if close in {"close_above", "close_below", "close_on"}:
        bclose = linreg_context.get("bclose")
        if bclose is not None:
            candle_close = float(bclose)
        elif isinstance(lr_result, dict) and "bclose" in lr_result:
            candle_close = float(lr_result["bclose"][candle_idx])
        else:
            candle_close = float(candles[candle_idx]["close"]) if candles and candle_idx < len(candles) else 0.0
    else:
        candle_close = float(candles[candle_idx]["close"]) if candles and candle_idx < len(candles) else 0.0

    return build_indicator_sticker(
        "LinReg Candles",
        f"Close {format_price_value(candle_close)} vs line {format_price_value(line_value)}",
        config,
        length=config.get("lr_length", 11),
        decision=_linreg_decision(candle, pos, close, linreg_context),
    )


def _latest_matching_linreg_index(candles, lr_result, config):
    lr_line = _signal_series(lr_result)
    if not candles or len(lr_line) == 0:
        return {"candle_idx": 0, "lr_idx": 0}

    window = max(1, int(config.get("window", 1) or 1))
    start_idx = max(0, len(lr_line) - window)
    latest_match = None
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    for candle_idx in range(start_idx, len(lr_line)):
        line = float(lr_line[candle_idx])
        if not np.isfinite(line):
            continue

        if isinstance(lr_result, dict) and "bopen" in lr_result:
            virtual_candle = {
                "open": float(lr_result["bopen"][candle_idx]),
                "high": float(lr_result["bhigh"][candle_idx]),
                "low": float(lr_result["blow"][candle_idx]),
                "close": float(lr_result["bclose"][candle_idx]),
            }
        else:
            virtual_candle = candles[candle_idx]
        linreg_context = _linreg_context(lr_result, candle_idx)

        if not check_price_position(virtual_candle, line, config.get("price_position"), tolerance_pct):
            continue
        close_rule = config.get("close_location")
        if close_rule and not check_close_location(virtual_candle, line, close_rule, tolerance_pct, linreg_context):
            continue

        latest_match = {"candle_idx": candle_idx, "lr_idx": candle_idx}

    if latest_match is not None:
        return latest_match

    last_idx = len(lr_line) - 1
    return {"candle_idx": max(0, last_idx), "lr_idx": last_idx}


def _linreg_decision(candle, position_rule, close_rule, linreg_context=None):
    bias = _linreg_candle_bias_label(candle, linreg_context)
    rule_labels = []

    position_label = _linreg_rule_label(position_rule)
    close_label = _linreg_rule_label(close_rule)

    if position_label:
        rule_labels.append(position_label)
    if close_label:
        rule_labels.append(close_label)

    if rule_labels:
        return f"{bias} Candle {' + '.join(rule_labels)}"

    return f"{bias} Candle Match"


def _linreg_candle_bias_label(candle, linreg_context=None):
    linreg_context = linreg_context or {}
    bopen = linreg_context.get("bopen")
    bclose = linreg_context.get("bclose")
    if bopen is not None and bclose is not None:
        if bclose > bopen:
            return "Bullish"
        if bclose < bopen:
            return "Bearish"
        return "Neutral"

    open_price = float(candle.get("open", 0.0) or 0.0)
    close_price = float(candle.get("close", 0.0) or 0.0)

    if close_price > open_price:
        return "Bullish"
    if close_price < open_price:
        return "Bearish"
    return "Neutral"


def _linreg_rule_label(rule):
    normalized = str(rule or "").strip().lower()
    mapping = {
        "above": "Above Line",
        "below": "Below Line",
        "on": "On Line",
        "piercing_from_below": "Piercing From Below",
        "piercing_from_above": "Piercing From Above",
        "close_above": "Close Above Line",
        "close_below": "Close Below Line",
        "close_on": "Close On Line",
        "bullish": "Bullish LinReg Body",
        "bearish": "Bearish LinReg Body",
    }
    return mapping.get(normalized)

# services/indicators.py
import logging

import numpy as np

logger = logging.getLogger(__name__)

from services.regression_channels import (
    compute_lrc_channel,
    compute_dw_regression_channel,
    evaluate_regression_lines,
    passes_r_filter,
    build_regression_sticker,
)

from services.rsi import (
    compute_rsi_series,
    evaluate_rsi_rules,
    build_rsi_sticker
)

from services.trend_channels import (
    compute_trend_channel,
    evaluate_trend_channel_rules
)

from services.linear_regression_candles import (
    _closed_candles as linreg_closed_candles,
    compute_linreg_candles,
    evaluate_linreg_candle_rules,
    build_linreg_candle_sticker,
    build_linreg_evidence,
)

from services.aroon_oscillator import (
    compute_aroon_oscillator,
    evaluate_aroon_rules,
    build_aroon_sticker
)

from services.wavetrend import (
    compute_wavetrend,
    evaluate_wavetrend_rules,
    build_wavetrend_sticker
)

from services.trendy_adx import (
    compute_trendy_adx,
    evaluate_trendy_adx_rules,
    build_trendy_adx_sticker,
    trendy_adx_debug_trace,
)

from services.vlr import (
    compute_vlr,
    evaluate_vlr_rules,
    build_vlr_sticker
)

from services.ema import evaluate_ema_rules, build_ema_sticker, build_moving_average_sticker, price_matches_ema_rule
from services.macd import compute_macd, evaluate_macd_rules, build_macd_sticker
from services.volume import (
    evaluate_volume_spike,
    build_volume_sticker,
    volume_spike_config_warnings,
    volume_spike_signal_warnings,
    volume_spike_debug_trace,
    VolumeSpikeConfigError,
    evaluate_relative_volume,
    build_relative_volume_sticker,
    relative_volume_config_warnings,
    relative_volume_signal_warnings,
    relative_volume_debug_trace,
    RelativeVolumeConfigError,
    evaluate_current_volume,
    build_current_volume_sticker,
    current_volume_config_warnings,
    current_volume_signal_warnings,
    current_volume_debug_trace,
    CurrentVolumeConfigError,
)
from services.volatility import (
    evaluate_volatility,
    build_volatility_sticker,
    volatility_config_warnings,
    volatility_signal_warnings,
    volatility_debug_trace,
    VolatilityConfigError,
)
from services.utils import (
    build_indicator_sticker,
    format_compact_number,
    format_decimal,
    humanize_token,
)


# =========================================================
# UTILITIES
# =========================================================

def extract_price_arrays(candles):

    close = np.array([c["close"] for c in candles])
    high = np.array([c["high"] for c in candles])
    low = np.array([c["low"] for c in candles])
    volume = np.array([c["volume"] for c in candles])

    return close, high, low, volume


def _trend_area_condition(area_rule):
    area = humanize_token(area_rule.get("area"))
    action = str(area_rule.get("action") or "").strip().lower()
    touch_type = area_rule.get("touch_type")
    breach_type = area_rule.get("breach_type")
    breach_direction = area_rule.get("breach_direction")

    if action == "touched":
        interaction = f"{humanize_token(touch_type)} Touch" if touch_type else "Touched"
    elif action == "entered":
        interaction = "Entered Zone"
    elif action == "rejected":
        interaction = "Rejected from Zone"
    elif action == "breach":
        breach_parts = ["Breached"]
        if breach_type:
            breach_parts.append(humanize_token(breach_type))
        if breach_direction and breach_direction != "any":
            breach_parts.append(humanize_token(breach_direction))
        interaction = " ".join(breach_parts)
    else:
        interaction = humanize_token(action)

    return f"{area}: {interaction}".strip()


def _trend_sticker_config(area_rules):
    sticker_config = {
        "confirmation": False,
        "window": 1,
    }

    for area_rule in area_rules or []:
        if not isinstance(area_rule, dict):
            continue

        sticker_config["window"] = max(
            int(sticker_config["window"] or 1),
            int(area_rule.get("window", 1) or 1),
        )

        has_confirmation_rule = (
            bool(area_rule.get("confirmation_type"))
            or bool(area_rule.get("confirmation_types"))
            or bool(area_rule.get("confirmation_patterns"))
        )

        if area_rule.get("confirmation") and has_confirmation_rule and not sticker_config["confirmation"]:
            sticker_config["confirmation"] = True
            if area_rule.get("confirmation_type"):
                sticker_config["confirmation_type"] = area_rule.get("confirmation_type")
            if area_rule.get("confirmation_types"):
                sticker_config["confirmation_types"] = area_rule.get("confirmation_types")
            if area_rule.get("confirmation_patterns"):
                sticker_config["confirmation_patterns"] = area_rule.get("confirmation_patterns")

    return sticker_config


def _trend_rule_bias(area_rule):
    area = str(area_rule.get("area") or "").strip().lower()
    action = str(area_rule.get("action") or "").strip().lower()
    breach_direction = str(area_rule.get("breach_direction") or "any").strip().lower()

    if area == "top_line":
        if action == "closed_above":
            return "bullish"
        if action in {"touched", "on_line"}:
            return "neutral"
        if action == "closed_below":
            return "bearish"

    if area == "bottom_line":
        if action == "closed_below":
            return "bearish"
        if action in {"touched", "on_line"}:
            return "neutral"
        if action == "closed_above":
            return "bullish"

    if area == "middle_line":
        if action == "closed_above":
            return "bullish"
        if action == "closed_below":
            return "bearish"
        return "neutral"

    if area == "top_zone":
        if action == "rejected":
            return "bearish"
        if action == "breach" and breach_direction in {"any", "up"}:
            return "bullish"
        return "neutral"

    if area == "bottom_zone":
        if action == "rejected":
            return "bullish"
        if action == "breach" and breach_direction in {"any", "down"}:
            return "bearish"
        return "neutral"

    return "neutral"


def _trend_decision(area_rules):
    biases = [_trend_rule_bias(area_rule) for area_rule in area_rules or [] if isinstance(area_rule, dict)]
    bullish = sum(1 for bias in biases if bias == "bullish")
    bearish = sum(1 for bias in biases if bias == "bearish")

    if bullish and not bearish:
        return "Bullish Channel Setup"
    if bearish and not bullish:
        return "Bearish Channel Setup"
    if any(bias == "neutral" for bias in biases):
        return "Channel Reaction"
    return "Channel Structure Match"


def _adx_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "above":
        return "Strong Trend"
    if normalized == "below":
        return "Weak Trend"
    if normalized == "rising":
        return "Trend Strengthening"
    if normalized == "falling":
        return "Trend Weakening"
    return "ADX Match"


def _stochrsi_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "oversold":
        return "Bullish Reversal Watch"
    if normalized == "overbought":
        return "Bearish Reversal Watch"
    if normalized == "bullish_cross":
        return "Bullish Momentum Shift"
    if normalized == "bearish_cross":
        return "Bearish Momentum Shift"
    return "StochRSI Match"


# =========================================================
# INDICATOR HANDLERS
# =========================================================

def handle_lrc(asset, candles, config):
    deviation = config.get("deviation", config.get("devlen"))
    upper_dev = config.get("upper_dev", deviation if deviation is not None else 2.0)
    lower_dev = config.get("lower_dev", deviation if deviation is not None else 2.0)

    channel = compute_lrc_channel(
        candles,
        length=config.get("length", 100),
        upper_dev=upper_dev,
        lower_dev=lower_dev,
        source=config.get("source", "close"),
    )

    if not channel:
        return False, None

    if not passes_r_filter(channel["r"], config):
        return False, None

    if not evaluate_regression_lines(candles, channel, config):
        return False, None

    asset["channels"]["lrc"] = {
        "upper": channel["upper"],
        "middle": channel["middle"],
        "lower": channel["lower"]
    }

    sticker_data = build_regression_sticker("LRC", channel, config)
    return True, build_indicator_sticker(
        sticker_data["name"],
        sticker_data["condition"],
        config,
        length=sticker_data["length"],
        window=sticker_data["window"],
        decision=sticker_data.get("decision"),
    )


def handle_regression(asset, candles, config):

    channel = compute_dw_regression_channel(
        candles,
        length=config.get("length", 200),
        width_coeff=config.get("width_coeff", 1.0),
        window_type=config.get("window_type", "continuous"),
        interval_step=config.get("interval_step", 1),
        filter_type=config.get("filter_type", "SMA"),
    )

    if not channel:
        return False, None

    if not evaluate_regression_lines(candles, channel, config):
        return False, None

    asset["channels"]["regression"] = channel

    sticker_data = build_regression_sticker("Regression Channel", channel, config)
    return True, build_indicator_sticker(
        sticker_data["name"],
        sticker_data["condition"],
        config,
        length=sticker_data["length"],
        window=sticker_data["window"],
        decision=sticker_data.get("decision"),
    )


def handle_rsi(asset, candles, config):

    rsi_series = compute_rsi_series(
        candles,
        length=config.get("length", 14)
    )

    if rsi_series is None:
        return False, None

    if not evaluate_rsi_rules(
        rsi_series,
        candles,
        config
    ):
        return False, None

    return True, build_rsi_sticker(rsi_series, config)


def _trend_closed_candles(candles):
    """Drop the still-forming last bar so channel geometry, break state, and
    area-rule signals are all derived from completed candles only - an
    unclosed bar must never generate a confirmed Trend Channel match.
    """
    if candles and candles[-1].get("is_closed") is False:
        return candles[:-1]
    return candles


def handle_trend(asset, candles, config):
    wait_for_break = config.get("wait_for_break")
    show_last_channel = config.get("show_last_channel")
    closed_candles = _trend_closed_candles(candles)

    tc = compute_trend_channel(
        closed_candles,
        length=config.get("length", 8),
        wait_for_break=True if wait_for_break is None else bool(wait_for_break),
        show_last_channel=True if show_last_channel is None else bool(show_last_channel),
    )

    if not tc:
        return False, None

    evidence = []
    passed = evaluate_trend_channel_rules(
        closed_candles,
        tc,
        config,
        evidence=evidence,
    )

    if not passed:
        return False, {"sticker": None, "evidence": evidence}

    asset["channels"]["trend"] = tc

    area_rules = config.get("areas", []) or []
    area_labels = [_trend_area_condition(area_rule) for area_rule in area_rules]
    condition = " + ".join(area_labels) if area_labels else "Area Match"
    sticker_config = _trend_sticker_config(area_rules)
    sticker = build_indicator_sticker(
        "Trend Channel",
        condition,
        sticker_config,
        length=config.get("length", 8),
        window=sticker_config["window"],
        decision=_trend_decision(area_rules),
    )
    return True, {"sticker": sticker, "evidence": evidence}


def handle_linreg_candles(asset, candles, config):
    forming_bar = None
    closed = linreg_closed_candles(candles)
    if closed is not candles and candles:
        forming_bar = candles[-1]

    lr_result = compute_linreg_candles(
        closed,
        lr_length=config.get("lr_length", 11),
        signal_smoothing=config.get("signal_smoothing", 11),
        sma_signal=config.get("sma_signal", True),
        lin_reg=config.get("lin_reg", True),
    )

    if lr_result is None:
        return False, {
            "sticker": None,
            "evidence": build_linreg_evidence(closed, None, config, False, forming_bar),
        }

    passed = evaluate_linreg_candle_rules(closed, lr_result, config)
    sticker = build_linreg_candle_sticker(closed, lr_result, config) if passed else None
    evidence = build_linreg_evidence(closed, lr_result, config, passed, forming_bar)

    return passed, {"sticker": sticker, "evidence": evidence}


def handle_aroon(asset, candles, config):

    series = compute_aroon_oscillator(
        candles,
        length=config.get("length", 14)
    )

    if series is None:
        return False, None

    if not evaluate_aroon_rules(
        series,
        candles,
        config
    ):
        return False, None

    return True, build_aroon_sticker(series, candles, config)


def handle_wavetrend(asset, candles, config):

    wt = compute_wavetrend(
        candles,
        channel_length=config.get("channel_length", 10),
        average_length=config.get("average_length", 21),
        signal_length=config.get("signal_length", 4),
    )

    if wt is None:
        return False, None

    if not evaluate_wavetrend_rules(
        wt,
        candles,
        config
    ):
        return False, None

    return True, build_wavetrend_sticker(wt, config)


def handle_trendy_adx(asset, candles, config):

    computed = compute_trendy_adx(
        candles,
        length=config.get("length", 11),
    )

    if computed is None:
        return False, None

    if not evaluate_trendy_adx_rules(
        computed,
        candles,
        config
    ):
        if config.get("debug") or config.get("trace"):
            return False, {
                "sticker": None,
                "evidence": trendy_adx_debug_trace(
                    computed,
                    candles,
                    config,
                    symbol=asset.get("symbol"),
                    timeframe=asset.get("timeframe") or config.get("timeframe"),
                ),
            }
        return False, None

    sticker = build_trendy_adx_sticker(computed, candles, config)
    if config.get("debug") or config.get("trace"):
        return True, {
            "sticker": sticker,
            "evidence": trendy_adx_debug_trace(
                computed,
                candles,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            ),
        }

    return True, sticker


def handle_vlr(asset, candles, config):

    computed = compute_vlr(
        candles,
        source=config.get("source", "close"),
        num_regressions=config.get("num_regressions", 3),
        start_period=config.get("start_period", 12),
        period_increment=config.get("period_increment", 12),
    )

    if computed is None:
        return False, None

    passed, matched_tags = evaluate_vlr_rules(computed, candles, config)

    if not passed:
        return False, None

    return True, build_vlr_sticker(computed, candles, config, matched_tags)


def handle_ema(asset, candles, config):

    if not evaluate_ema_rules(candles, config):
        return False, None

    return True, build_ema_sticker(candles, config)


def handle_ema_wave(asset, candles, config):

    wave_config = dict(config or {})
    wave_config.setdefault("mode", "ema_wave")

    if not evaluate_ema_rules(candles, wave_config):
        return False, None

    return True, build_ema_sticker(candles, wave_config)


def handle_macd(asset, candles, config):

    macd_data = compute_macd(
        candles,
        fast=int(config.get("fast", 12) or 12),
        slow=int(config.get("slow", 26) or 26),
        signal=int(config.get("signal", 9) or 9),
        source=config.get("source", "close"),
    )

    if not evaluate_macd_rules(macd_data, config):
        return False, None

    return True, build_macd_sticker(macd_data, config)


def handle_volume(asset, candles, config):
    warnings = volume_spike_config_warnings(config) + volume_spike_signal_warnings(candles, config)
    if warnings:
        asset.setdefault("warnings", []).extend(warnings)

    try:
        if not evaluate_volume_spike(candles, config):
            if warnings or config.get("debug") or config.get("trace"):
                evidence = None
                if config.get("debug") or config.get("trace"):
                    evidence = volume_spike_debug_trace(
                        candles,
                        config,
                        symbol=asset.get("symbol"),
                        timeframe=asset.get("timeframe") or config.get("timeframe"),
                    )
                return False, {
                    "sticker": None,
                    "evidence": evidence or {},
                    "warnings": warnings,
                }
            return False, None

        sticker = build_volume_sticker(candles, config)
        evidence = None
        if config.get("debug") or config.get("trace"):
            evidence = volume_spike_debug_trace(
                candles,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            )
        if evidence or warnings:
            return True, {
                "sticker": sticker,
                "evidence": evidence or {},
                "warnings": warnings,
            }
        return True, sticker
    except VolumeSpikeConfigError as exc:
        logger.warning(
            "Volume Spikes config error symbol=%s error=%s config=%s",
            asset.get("symbol"),
            exc,
            config,
        )
        return False, {
            "sticker": None,
            "evidence": {
                "config_error": str(exc),
                "requested_config": dict(config or {}),
            },
            "warnings": warnings,
        }


def handle_relative_volume(asset, candles, config):
    warnings = relative_volume_config_warnings(config) + relative_volume_signal_warnings(candles, config)
    if warnings:
        asset.setdefault("warnings", []).extend(warnings)

    try:
        if not evaluate_relative_volume(candles, config):
            if warnings or config.get("debug") or config.get("trace"):
                evidence = None
                if config.get("debug") or config.get("trace"):
                    evidence = relative_volume_debug_trace(
                        candles,
                        config,
                        symbol=asset.get("symbol"),
                        timeframe=asset.get("timeframe") or config.get("timeframe"),
                    )
                return False, {
                    "sticker": None,
                    "evidence": evidence or {},
                    "warnings": warnings,
                }
            return False, None

        sticker = build_relative_volume_sticker(candles, config)
        evidence = None
        if config.get("debug") or config.get("trace"):
            evidence = relative_volume_debug_trace(
                candles,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            )
        if evidence or warnings:
            return True, {
                "sticker": sticker,
                "evidence": evidence or {},
                "warnings": warnings,
            }
        return True, sticker
    except RelativeVolumeConfigError as exc:
        logger.warning(
            "Relative Volume config error symbol=%s error=%s config=%s",
            asset.get("symbol"),
            exc,
            config,
        )
        return False, {
            "sticker": None,
            "evidence": {
                "config_error": str(exc),
                "requested_config": dict(config or {}),
            },
            "warnings": warnings,
        }


def handle_current_volume(asset, candles, config):
    warnings = current_volume_config_warnings(config) + current_volume_signal_warnings(candles, config)
    if warnings:
        asset.setdefault("warnings", []).extend(warnings)

    try:
        if not evaluate_current_volume(candles, config):
            if warnings or config.get("debug") or config.get("trace"):
                evidence = None
                if config.get("debug") or config.get("trace"):
                    evidence = current_volume_debug_trace(
                        candles,
                        config,
                        symbol=asset.get("symbol"),
                        timeframe=asset.get("timeframe") or config.get("timeframe"),
                    )
                return False, {
                    "sticker": None,
                    "evidence": evidence or {},
                    "warnings": warnings,
                }
            return False, None

        sticker = build_current_volume_sticker(candles, config)
        evidence = None
        if config.get("debug") or config.get("trace"):
            evidence = current_volume_debug_trace(
                candles,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            )
        if evidence or warnings:
            return True, {
                "sticker": sticker,
                "evidence": evidence or {},
                "warnings": warnings,
            }
        return True, sticker
    except CurrentVolumeConfigError as exc:
        logger.warning(
            "Current Volume config error symbol=%s error=%s config=%s",
            asset.get("symbol"),
            exc,
            config,
        )
        return False, {
            "sticker": None,
            "evidence": {
                "config_error": str(exc),
                "requested_config": dict(config or {}),
            },
            "warnings": warnings,
        }


def handle_float(asset, candles, config):
    float_shares = asset.get("float_shares")
    if float_shares is None:
        return False, None

    float_shares = float(float_shares)
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and float_shares < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and float_shares > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Float",
        f"Float {format_compact_number(float_shares)} shares",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Tradable Float Match",
    )


def handle_shares_outstanding(asset, candles, config):
    shares = asset.get("shares_outstanding")
    if shares is None:
        return False, None

    shares = float(shares)
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and shares < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and shares > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Shares Outstanding",
        f"Shares outstanding {format_compact_number(shares)}",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Capital Structure Match",
    )


def handle_volatility(asset, candles, config):
    warnings = volatility_config_warnings(config) + volatility_signal_warnings(candles, config)
    if warnings:
        asset.setdefault("warnings", []).extend(warnings)

    try:
        if not evaluate_volatility(candles, config):
            if warnings or config.get("debug") or config.get("trace"):
                evidence = None
                if config.get("debug") or config.get("trace"):
                    evidence = volatility_debug_trace(
                        candles,
                        config,
                        symbol=asset.get("symbol"),
                        timeframe=asset.get("timeframe") or config.get("timeframe"),
                    )
                return False, {
                    "sticker": None,
                    "evidence": evidence or {},
                    "warnings": warnings,
                }
            return False, None

        sticker = build_volatility_sticker(candles, config)
        evidence = None
        if config.get("debug") or config.get("trace"):
            evidence = volatility_debug_trace(
                candles,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            )
        if evidence or warnings:
            return True, {
                "sticker": sticker,
                "evidence": evidence or {},
                "warnings": warnings,
            }
        return True, sticker
    except VolatilityConfigError as exc:
        logger.warning(
            "Volatility config error symbol=%s error=%s config=%s",
            asset.get("symbol"),
            exc,
            config,
        )
        return False, {
            "sticker": None,
            "evidence": {
                "config_error": str(exc),
                "requested_config": dict(config or {}),
            },
            "warnings": warnings,
        }


# =========================================================
# INDICATOR REGISTRY
# =========================================================

INDICATOR_REGISTRY = {
    "lrc": handle_lrc,
    "regression": handle_regression,
    "rsi": handle_rsi,
    "trend": handle_trend,
    "linreg_candles": handle_linreg_candles,
    "aroon": handle_aroon,
    "wavetrend": handle_wavetrend,
    "adx": handle_trendy_adx,
    "vlr": handle_vlr,
    "ema": handle_ema,
    "ema_wave": handle_ema_wave,
    "macd": handle_macd,
    "volume": handle_volume,
    "relative_volume": handle_relative_volume,
    "current_volume": handle_current_volume,
    "float": handle_float,
    "shares_outstanding": handle_shares_outstanding,
    "volatility": handle_volatility,
}


# =========================================================
# SNAPSHOT EVALUATION
# =========================================================

def _snapshot_series(snapshot, name):
    series = (snapshot or {}).get(name) or []

    if isinstance(series, list):
        return series

    return [series]


def _snapshot_config_bool(config, key, default):
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off"}
    return bool(value)


def _handle_rsi_snapshot(asset, snapshot, config):
    rsi_series = np.array(_snapshot_series(snapshot, "rsi"), dtype=float)

    if rsi_series.size == 0:
        return False, None

    if not evaluate_rsi_rules(rsi_series, [], config):
        return False, None

    return True, build_rsi_sticker(rsi_series, config)


def _handle_ema_snapshot(asset, snapshot, config):
    return _handle_moving_average_snapshot(
        asset,
        snapshot,
        config,
        indicator_name="ema",
        label="EMA",
        default_length=9,
    )


def _handle_moving_average_snapshot(asset, snapshot, config, indicator_name, label, default_length=50):
    ma_series = _snapshot_series(snapshot, indicator_name)

    if not ma_series:
        return False, None

    price = float(asset["price"])
    ma_value = float(ma_series[-1])
    rule = config.get("rule")
    passed = price_matches_ema_rule(
        price,
        ma_value,
        rule,
        tolerance_pct=float(config.get("tolerance_pct", 0) or 0),
    )

    if not passed:
        return False, None

    length = int(config.get("length", default_length) or default_length)
    return True, build_moving_average_sticker(label, length, rule, price, ma_value)


def _handle_sma_snapshot(asset, snapshot, config):
    return _handle_moving_average_snapshot(
        asset,
        snapshot,
        config,
        indicator_name="sma",
        label="SMA",
    )


def _handle_macd_snapshot(asset, snapshot, config):
    points = _snapshot_series(snapshot, "macd")

    if not points:
        return False, None

    macd_data = {
        "macd": np.array([point["macd"] for point in points], dtype=float),
        "signal": np.array([point["signal"] for point in points], dtype=float),
        "hist": np.array([point.get("hist", point.get("histogram", 0.0)) for point in points], dtype=float),
    }

    if len(macd_data["macd"]) < 2 and config.get("rule") in {"bullish_cross", "bearish_cross"}:
        return False, None

    if not evaluate_macd_rules(macd_data, config):
        return False, None

    return True, build_macd_sticker(macd_data, config)


def _handle_aroon_snapshot(asset, snapshot, config):
    series = np.array(_snapshot_series(snapshot, "aroon"), dtype=float)

    if series.size == 0:
        return False, None

    if not evaluate_aroon_rules(series, [], config):
        return False, None

    return True, build_aroon_sticker(series, [], config)


def _handle_adx_snapshot(asset, snapshot, config):
    series = np.array(_snapshot_series(snapshot, "adx"), dtype=float)

    if series.size == 0:
        return False, None

    latest = float(series[-1])
    rule = config.get("rule")
    threshold = float(config.get("threshold", 25) or 25)

    if rule == "above":
        passed = latest > threshold
    elif rule == "below":
        passed = latest < threshold
    elif rule == "rising":
        if series.size < 2:
            return False, None
        passed = latest > float(series[-2])
    elif rule == "falling":
        if series.size < 2:
            return False, None
        passed = latest < float(series[-2])
    else:
        passed = False

    if not passed:
        return False, None

    return True, build_indicator_sticker(
        "ADX",
        f"ADX {format_decimal(latest, 1)} vs threshold {format_decimal(threshold, 1)}",
        {"window": 1, "confirmation": False},
        window=1,
        decision=_adx_decision(rule),
    )


def _handle_stochrsi_snapshot(asset, snapshot, config):
    points = _snapshot_series(snapshot, "stochrsi")

    if not points:
        return False, None

    k_series = np.array([point["k"] for point in points], dtype=float)
    d_series = np.array([point["d"] for point in points], dtype=float)
    latest_k = float(k_series[-1])
    latest_d = float(d_series[-1])
    rule = config.get("rule")
    threshold = float(config.get("threshold", 20) or 20)

    if rule == "oversold":
        passed = latest_k < threshold and latest_d < threshold
    elif rule == "overbought":
        upper = float(config.get("threshold", 80) or 80)
        passed = latest_k > upper and latest_d > upper
    elif rule == "bullish_cross":
        if len(k_series) < 2 or len(d_series) < 2:
            return False, None
        passed = k_series[-2] <= d_series[-2] and latest_k > latest_d
    elif rule == "bearish_cross":
        if len(k_series) < 2 or len(d_series) < 2:
            return False, None
        passed = k_series[-2] >= d_series[-2] and latest_k < latest_d
    else:
        passed = False

    if not passed:
        return False, None

    return True, build_indicator_sticker(
        "StochRSI",
        f"K {format_decimal(latest_k, 1)} vs D {format_decimal(latest_d, 1)}",
        {"window": 1, "confirmation": False},
        window=1,
        decision=_stochrsi_decision(rule),
    )


def _handle_volume_snapshot(asset, snapshot, config):
    try:
        volumes = _snapshot_series(snapshot, "volume")
        opens = _snapshot_series(snapshot, "open")
        highs = _snapshot_series(snapshot, "high")
        lows = _snapshot_series(snapshot, "low")
        closes = _snapshot_series(snapshot, "close")
        times = _snapshot_series(snapshot, "time")

        if not volumes:
            return False, None

        full_ohlc = all(len(series) == len(volumes) for series in (opens, highs, lows, closes))
        volume_only_allowed = not (
            _snapshot_config_bool(config, "only_valid_hl", True)
            or _snapshot_config_bool(config, "only_hammers_shooters", True)
            or _snapshot_config_bool(config, "only_same_color", False)
        )
        if not full_ohlc and not volume_only_allowed:
            return False, None

        if not full_ohlc:
            opens = highs = lows = closes = [0.0] * len(volumes)

        candle_like = []
        for index, volume in enumerate(volumes):
            candle = {
                "open": float(opens[index]),
                "high": float(highs[index]),
                "low": float(lows[index]),
                "close": float(closes[index]),
                "volume": float(volume),
            }
            if len(times) == len(volumes):
                candle["time"] = times[index]
            candle_like.append(candle)

        warnings = volume_spike_config_warnings(config) + volume_spike_signal_warnings(candle_like, config)
        if warnings:
            asset.setdefault("warnings", []).extend(warnings)

        if not evaluate_volume_spike(candle_like, config):
            if warnings or config.get("debug") or config.get("trace"):
                evidence = None
                if config.get("debug") or config.get("trace"):
                    evidence = volume_spike_debug_trace(
                        candle_like,
                        config,
                        symbol=asset.get("symbol"),
                        timeframe=asset.get("timeframe") or config.get("timeframe"),
                    )
                return False, {
                    "sticker": None,
                    "evidence": evidence or {},
                    "warnings": warnings,
                }
            return False, None

        sticker = build_volume_sticker(candle_like, config)
        evidence = None
        if config.get("debug") or config.get("trace"):
            evidence = volume_spike_debug_trace(
                candle_like,
                config,
                symbol=asset.get("symbol"),
                timeframe=asset.get("timeframe") or config.get("timeframe"),
            )
        if evidence or warnings:
            return True, {
                "sticker": sticker,
                "evidence": evidence or {},
                "warnings": warnings,
            }
        return True, sticker
    except VolumeSpikeConfigError as exc:
        logger.warning(
            "Volume Spikes snapshot config error symbol=%s error=%s config=%s",
            asset.get("symbol"),
            exc,
            config,
        )
        return False, {
            "sticker": None,
            "evidence": {
                "config_error": str(exc),
                "requested_config": dict(config or {}),
            },
            "warnings": warnings,
        }


def _handle_relative_volume_snapshot(asset, snapshot, config):
    volumes = _snapshot_series(snapshot, "volume")
    times = _snapshot_series(snapshot, "time")
    candles = []
    for index, volume in enumerate(volumes):
        candle = {
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "volume": float(volume),
        }
        if len(times) == len(volumes):
            candle["time"] = times[index]
        candles.append(candle)

    try:
        if not evaluate_relative_volume(candles, config):
            return False, None
        return True, build_relative_volume_sticker(candles, config)
    except RelativeVolumeConfigError:
        return False, None


def _handle_current_volume_snapshot(asset, snapshot, config):
    volumes = _snapshot_series(snapshot, "volume")
    times = _snapshot_series(snapshot, "time")
    opens = _snapshot_series(snapshot, "open")
    highs = _snapshot_series(snapshot, "high")
    lows = _snapshot_series(snapshot, "low")
    closes = _snapshot_series(snapshot, "close")
    candles = []
    for index, volume in enumerate(volumes):
        candle = {
            "open": float(opens[index]) if len(opens) == len(volumes) else 0.0,
            "high": float(highs[index]) if len(highs) == len(volumes) else 0.0,
            "low": float(lows[index]) if len(lows) == len(volumes) else 0.0,
            "close": float(closes[index]) if len(closes) == len(volumes) else 0.0,
            "volume": float(volume),
        }
        if len(times) == len(volumes):
            candle["time"] = times[index]
        candles.append(candle)

    try:
        if not evaluate_current_volume(candles, config):
            return False, None
        return True, build_current_volume_sticker(candles, config)
    except CurrentVolumeConfigError:
        return False, None


def _handle_float_snapshot(asset, snapshot, config):
    float_shares = asset.get("float_shares")
    if float_shares is None:
        return False, None

    float_shares = float(float_shares)
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and float_shares < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and float_shares > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Float",
        f"Float {format_compact_number(float_shares)} shares",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Tradable Float Match",
    )


def _handle_shares_outstanding_snapshot(asset, snapshot, config):
    shares = asset.get("shares_outstanding")
    if shares is None:
        return False, None

    shares = float(shares)
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and shares < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and shares > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Shares Outstanding",
        f"Shares outstanding {format_compact_number(shares)}",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Capital Structure Match",
    )


def _handle_volatility_snapshot(asset, snapshot, config):
    mode = str(config.get("mode", "range_avg") or "range_avg").strip().lower()
    if mode in {"returns_std", "returns", "realized"}:
        closes = _snapshot_series(snapshot, "close")
        candles = [{"close": float(close)} for close in closes]
        try:
            if not evaluate_volatility(candles, config):
                return False, None
            return True, build_volatility_sticker(candles, config)
        except VolatilityConfigError:
            return False, None

    times = _snapshot_series(snapshot, "time")
    opens = _snapshot_series(snapshot, "open")
    highs = _snapshot_series(snapshot, "high")
    lows = _snapshot_series(snapshot, "low")
    closes = _snapshot_series(snapshot, "close")
    candles = []
    for index, close in enumerate(closes):
        candle = {
            "open": float(opens[index]) if len(opens) == len(closes) else float(close),
            "high": float(highs[index]) if len(highs) == len(closes) else float(close),
            "low": float(lows[index]) if len(lows) == len(closes) else float(close),
            "close": float(close),
        }
        if len(times) == len(closes):
            candle["time"] = times[index]
        candles.append(candle)

    try:
        if not evaluate_volatility(candles, config):
            return False, None
        return True, build_volatility_sticker(candles, config)
    except VolatilityConfigError:
        return False, None


SNAPSHOT_INDICATOR_REGISTRY = {
    "rsi": _handle_rsi_snapshot,
    "stochrsi": _handle_stochrsi_snapshot,
    "ema": _handle_ema_snapshot,
    "sma": _handle_sma_snapshot,
    "macd": _handle_macd_snapshot,
    "aroon": _handle_aroon_snapshot,
    "adx": _handle_adx_snapshot,
    "volume": _handle_volume_snapshot,
    "relative_volume": _handle_relative_volume_snapshot,
    "current_volume": _handle_current_volume_snapshot,
    "float": _handle_float_snapshot,
    "shares_outstanding": _handle_shares_outstanding_snapshot,
    "volatility": _handle_volatility_snapshot,
}


def unsupported_indicator_names(selected_indicators, registry=None):
    active_registry = registry if registry is not None else INDICATOR_REGISTRY
    return sorted({
        indicator.name
        for indicator in selected_indicators
        if indicator.name.lower() not in active_registry
    })


def _compile_selected_indicators(selected_indicators, registry):
    compiled = []

    for indicator in selected_indicators:
        handler = registry.get(indicator.name.lower())

        if not handler:
            return None

        compiled.append((indicator.name.lower(), handler, indicator.config or {}))

    return compiled


# =========================================================
# MAIN ENGINE
# =========================================================

def _normalize_handler_result(result):
    """Handlers may return a sticker string or {sticker, evidence}."""
    if isinstance(result, dict):
        return result.get("sticker"), result.get("evidence"), result.get("warnings") or []
    return result, None, []


def apply_indicators(data, selected_indicators):
    compiled_indicators = _compile_selected_indicators(
        selected_indicators,
        INDICATOR_REGISTRY,
    )

    if compiled_indicators is None:
        return []

    filtered = []

    for asset in data:

        candles = asset.get("candles")

        if not candles:
            continue

        asset.setdefault("channels", {})
        asset.setdefault("stickers", [])

        stickers = []
        matched_indicators = []
        passed_all = True

        for indicator_name, handler, config in compiled_indicators:
            try:
                passed, result = handler(
                    asset,
                    candles,
                    config
                )
                sticker, _evidence, warnings = _normalize_handler_result(result)
                if warnings:
                    asset.setdefault("warnings", []).extend(warnings)
            except Exception:
                logger.exception(
                    "Indicator evaluation failed, skipping symbol symbol=%s indicator=%s",
                    asset.get("symbol"),
                    indicator_name,
                )
                passed_all = False
                break

            if not passed:
                passed_all = False
                break

            if sticker:
                stickers.append(sticker)
                matched_indicators.append(indicator_name)

        if passed_all:
            asset["stickers"] = stickers
            asset["matched_indicators"] = matched_indicators
            filtered.append(asset)

    return filtered


def evaluate_indicator_details(asset, selected_indicators, timeframe_scope=None):
    compiled_indicators = _compile_selected_indicators(
        selected_indicators,
        INDICATOR_REGISTRY,
    )

    if compiled_indicators is None:
        return []

    candles = asset.get("candles")
    if not candles:
        return []

    asset.setdefault("channels", {})
    details = []

    for indicator_name, handler, config in compiled_indicators:
        passed, result = handler(asset, candles, config)
        sticker, evidence, warnings = _normalize_handler_result(result)
        detail = {
            "name": indicator_name,
            "timeframe_scope": timeframe_scope,
            "passed": bool(passed),
            "sticker": sticker,
            "config": dict(config or {}),
        }
        if evidence:
            detail["evidence"] = evidence
        if warnings:
            detail["warnings"] = warnings
        details.append(detail)

    return details


def apply_indicator_snapshots(data, selected_indicators):
    compiled_indicators = _compile_selected_indicators(
        selected_indicators,
        SNAPSHOT_INDICATOR_REGISTRY,
    )

    if compiled_indicators is None:
        return []

    filtered = []

    for asset in data:
        snapshot = asset.get("indicator_snapshot") or {}
        asset.setdefault("stickers", [])

        stickers = []
        matched_indicators = []
        passed_all = True

        for indicator_name, handler, config in compiled_indicators:
            passed, result = handler(asset, snapshot, config)
            sticker, _evidence, warnings = _normalize_handler_result(result)
            if warnings:
                asset.setdefault("warnings", []).extend(warnings)

            if not passed:
                passed_all = False
                break

            if sticker:
                stickers.append(sticker)
                matched_indicators.append(indicator_name)

        if passed_all:
            asset["stickers"] = stickers
            asset["matched_indicators"] = matched_indicators
            filtered.append(asset)

    return filtered

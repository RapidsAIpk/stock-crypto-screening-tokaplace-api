# services/indicators.py
import logging

import numpy as np

from services.pine_math import (
    NAN,
    pine_daily_volatility,
    pine_range_volatility,
    pine_relative_volume_ratio,
)

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
    build_trendy_adx_sticker
)

from services.vlr import (
    compute_vlr,
    evaluate_vlr_rules,
    build_vlr_sticker
)

from services.ema import evaluate_ema_rules, build_ema_sticker, build_moving_average_sticker, price_matches_ema_rule
from services.macd import compute_macd, evaluate_macd_rules, build_macd_sticker
from services.volume import evaluate_volume_spike, build_volume_sticker
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


def _volatility_decision(min_pct, max_pct):
    if max_pct is None and float(min_pct or 0) > 0:
        return "Range Expansion"
    if max_pct is not None and float(min_pct or 0) <= 0:
        return "Controlled Volatility"
    if max_pct is not None:
        return "Volatility Band Match"
    return "Volatility Match"


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

    channel = compute_lrc_channel(
        candles,
        length=config.get("length", 100),
        upper_dev=config.get("upper_dev", 2.0),
        lower_dev=config.get("lower_dev", 2.0),
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
        return False, None

    return True, build_trendy_adx_sticker(computed, candles, config)


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


def handle_macd(asset, candles, config):

    macd_data = compute_macd(
        candles,
        fast=int(config.get("fast", 12) or 12),
        slow=int(config.get("slow", 26) or 26),
        signal=int(config.get("signal", 9) or 9),
    )

    if not evaluate_macd_rules(macd_data, config):
        return False, None

    return True, build_macd_sticker(macd_data, config)


def handle_volume(asset, candles, config):

    if not evaluate_volume_spike(candles, config):
        return False, None

    return True, build_volume_sticker(candles, config)


def handle_relative_volume(asset, candles, config):
    volumes = np.array([c["volume"] for c in candles], dtype=float)
    length = int(config.get("length", 10) or 10)
    min_ratio = float(config.get("min_ratio", 1.0) or 1.0)
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    ratio = pine_relative_volume_ratio(volumes, length)
    if not np.isfinite(ratio):
        return False, None

    adjusted_min_ratio = max(0.0, min_ratio * (1 - tolerance_pct / 100.0))
    if ratio < adjusted_min_ratio:
        return False, None

    return True, build_indicator_sticker(
        "Relative Volume",
        f"{format_decimal(ratio, 2)}x average on {length}-bar lookback",
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision="High Relative Volume",
    )


def handle_current_volume(asset, candles, config):
    if not candles:
        return False, None

    current_volume = float(candles[-1].get("volume", 0) or 0)
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and current_volume < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and current_volume > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Current Volume",
        f"{format_compact_number(current_volume)} traded this bar",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Liquidity Threshold Met",
    )


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
    length = int(config.get("length", 20) or 20)
    min_pct = float(config.get("min_pct", 0) or 0)
    max_pct = config.get("max_pct")
    max_pct = float(max_pct) if max_pct is not None else None
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    mode = str(config.get("mode", "range_avg") or "range_avg").strip().lower()

    if len(candles) < max(2, length):
        return False, None

    if mode == "daily":
        latest = candles[-1]
        previous_close = float(candles[-2]["close"]) if len(candles) >= 2 else float(latest["close"])
        enriched = dict(latest)
        enriched["previous_close"] = previous_close
        vol_pct = pine_daily_volatility(enriched)
        label = "Daily true-range volatility"
    elif mode == "returns_std":
        closes = np.array([c["close"] for c in candles], dtype=float)
        returns = _safe_percent_returns(closes[-(length + 1):])
        if returns.size == 0:
            return False, None
        vol_pct = float(np.std(returns) * 100)
        label = f"Realized vol over {length} bars"
    else:
        vol_pct = pine_range_volatility(candles, length)
        label = f"Range volatility over {length} bars"

    if not np.isfinite(vol_pct):
        return False, None

    if vol_pct < max(0.0, min_pct - tolerance_pct):
        return False, None
    if max_pct is not None and vol_pct > (max_pct + tolerance_pct):
        return False, None

    return True, build_indicator_sticker(
        "Volatility",
        f"{label}: {format_decimal(vol_pct, 2)}%",
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision=_volatility_decision(min_pct, max_pct),
    )


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


def _safe_percent_returns(closes):
    series = np.array(closes, dtype=float)
    if series.size < 2:
        return np.array([], dtype=float)

    previous = series[:-1]
    current = series[1:]
    valid_mask = np.isfinite(previous) & np.isfinite(current) & (previous != 0)
    if not np.any(valid_mask):
        return np.array([], dtype=float)

    returns = (current[valid_mask] - previous[valid_mask]) / previous[valid_mask]
    return returns[np.isfinite(returns)]


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
        "hist": np.array([point.get("hist", 0.0) for point in points], dtype=float),
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
    volumes = np.array(_snapshot_series(snapshot, "volume"), dtype=float)
    length = int(config.get("length", 20) or 20)
    multiplier = float(config.get("multiplier", 2) or 2)
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if len(volumes) < length + 1:
        return False, None

    avg_volume = np.mean(volumes[-length-1:-1])
    last_volume = volumes[-1]

    adjusted_multiplier = max(0.0, multiplier * (1 - tolerance_pct / 100.0))
    if not last_volume > avg_volume * adjusted_multiplier:
        return False, None

    candle_like = [{"volume": float(volume)} for volume in volumes.tolist()]
    return True, build_volume_sticker(candle_like, config)


def _handle_relative_volume_snapshot(asset, snapshot, config):
    volumes = np.array(_snapshot_series(snapshot, "volume"), dtype=float)
    length = int(config.get("length", 10) or 10)
    min_ratio = float(config.get("min_ratio", 1.0) or 1.0)
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    ratio = pine_relative_volume_ratio(volumes, length)
    if not np.isfinite(ratio):
        return False, None

    adjusted_min_ratio = max(0.0, min_ratio * (1 - tolerance_pct / 100.0))
    if ratio < adjusted_min_ratio:
        return False, None

    return True, build_indicator_sticker(
        "Relative Volume",
        f"{format_decimal(ratio, 2)}x average on {length}-bar lookback",
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision="High Relative Volume",
    )


def _handle_current_volume_snapshot(asset, snapshot, config):
    volumes = np.array(_snapshot_series(snapshot, "volume"), dtype=float)
    if len(volumes) < 1:
        return False, None

    current_volume = float(volumes[-1])
    min_value = config.get("min_value")
    max_value = config.get("max_value")
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if min_value is not None and current_volume < float(min_value) * (1 - tolerance_pct / 100.0):
        return False, None
    if max_value is not None and current_volume > float(max_value) * (1 + tolerance_pct / 100.0):
        return False, None

    return True, build_indicator_sticker(
        "Current Volume",
        f"{format_compact_number(current_volume)} traded this bar",
        {"window": 1, "confirmation": False},
        window=1,
        decision="Liquidity Threshold Met",
    )


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
    length = int(config.get("length", 20) or 20)
    min_pct = float(config.get("min_pct", 0) or 0)
    max_pct = config.get("max_pct")
    max_pct = float(max_pct) if max_pct is not None else None
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))
    mode = str(config.get("mode", "range_avg") or "range_avg").strip().lower()

    highs = _snapshot_series(snapshot, "high")
    lows = _snapshot_series(snapshot, "low")
    closes = _snapshot_series(snapshot, "close")
    if len(closes) < max(2, length):
        return False, None

    candles = [
        {"high": float(high), "low": float(low), "close": float(close)}
        for high, low, close in zip(highs, lows, closes)
    ]

    if mode == "daily":
        latest = dict(candles[-1])
        latest["previous_close"] = float(candles[-2]["close"])
        vol_pct = pine_daily_volatility(latest)
        label = "Daily true-range volatility"
    elif mode == "returns_std":
        close_values = np.array(closes, dtype=float)
        returns = _safe_percent_returns(close_values[-(length + 1):])
        if returns.size == 0:
            return False, None
        vol_pct = float(np.std(returns) * 100)
        label = f"Realized vol over {length} bars"
    else:
        vol_pct = pine_range_volatility(candles, length)
        label = f"Range volatility over {length} bars"

    if not np.isfinite(vol_pct):
        return False, None

    if vol_pct < max(0.0, min_pct - tolerance_pct):
        return False, None
    if max_pct is not None and vol_pct > (max_pct + tolerance_pct):
        return False, None

    return True, build_indicator_sticker(
        "Volatility",
        f"{label}: {format_decimal(vol_pct, 2)}%",
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision=_volatility_decision(min_pct, max_pct),
    )


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
        return result.get("sticker"), result.get("evidence")
    return result, None


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
                sticker, _evidence = _normalize_handler_result(result)
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
        sticker, evidence = _normalize_handler_result(result)
        detail = {
            "name": indicator_name,
            "timeframe_scope": timeframe_scope,
            "passed": bool(passed),
            "sticker": sticker,
            "config": dict(config or {}),
        }
        if evidence:
            detail["evidence"] = evidence
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
            passed, sticker = handler(asset, snapshot, config)

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

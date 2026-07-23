# services/dead_assets.py
#
# "Omit Dead Stock / Crypto" filter — site update/dead stock/Dead stock.pdf.
# Excludes assets stuck in a long-term structural downtrend (Strong Dead Trend,
# Slow Bleeding Trend, Failed Recovery, Flat Dead Asset), with a Recovery
# Override so an asset is never permanently blacklisted.

import logging

import numpy as np

from services.ema import compute_ema
from services.utils import build_indicator_sticker

logger = logging.getLogger(__name__)

SWING_SPAN = 5
MIN_CANDLES = SWING_SPAN * 2 + 2

RESULT_LABELS = {
    "strong_dead_trend": "Excluded — Strong Dead Trend",
    "slow_bleeding_trend": "Excluded — Slow Bleeding Trend",
    "failed_recovery": "Excluded — Failed Recovery",
    "flat_dead_asset": "Excluded — Flat Dead Asset",
}

RECOVERY_LABEL = "Allowed — Recovery Started"


# =========================================================
# APPLY DEAD ASSETS
# =========================================================

def apply_dead_assets(data, config):
    if not config or not getattr(config, "enabled", False):
        return data

    filtered = []

    for asset in data:
        candles = asset.get("candles")

        if not candles or len(candles) < MIN_CANDLES:
            filtered.append(asset)
            continue

        decision = _evaluate_dead_assets(candles, config)

        if decision["excluded"]:
            logger.info(
                "dead_assets excluded symbol=%s reason=%s",
                asset.get("symbol"),
                decision["label"],
            )
            continue

        if decision["overridden"]:
            asset.setdefault("stickers", []).append(
                build_indicator_sticker(
                    "Dead Assets",
                    decision["label"],
                    {"window": len(candles), "confirmation": False},
                    window=len(candles),
                    decision=decision["label"],
                )
            )
            asset.setdefault("matched_indicators", []).append("dead_assets")

        filtered.append(asset)

    return filtered


def evaluate_dead_assets_detail(asset, config):
    if not config:
        return None

    details = {
        "enabled": getattr(config, "enabled", False),
        "dead_trend_types": list(getattr(config, "dead_trend_types", []) or []),
        "lower_highs_required": getattr(config, "lower_highs_required", None),
        "lower_lows_required": getattr(config, "lower_lows_required", None),
        "trend_source": getattr(config, "trend_source", None),
        "recovery_lookback": getattr(config, "recovery_lookback", None),
        "volume_option": getattr(config, "volume_option", None),
        "volatility_option": getattr(config, "volatility_option", None),
        "bounce_threshold_pct": getattr(config, "bounce_threshold_pct", None),
        "failure_window": getattr(config, "failure_window", None),
        "recovery_override": getattr(config, "recovery_override", None),
    }

    if not getattr(config, "enabled", False):
        return {
            "name": "dead_assets",
            "passed": True,
            "summary": "Dead Assets filter disabled.",
            "details": details,
        }

    candles = asset.get("candles")
    if not candles or len(candles) < MIN_CANDLES:
        return {
            "name": "dead_assets",
            "passed": True,
            "summary": "Insufficient candle history to evaluate.",
            "details": details,
        }

    decision = _evaluate_dead_assets(candles, config)
    passed = not decision["excluded"]

    sticker = None
    if decision["overridden"]:
        sticker = build_indicator_sticker(
            "Dead Assets",
            decision["label"],
            {"window": len(candles), "confirmation": False},
            window=len(candles),
            decision=decision["label"],
        )

    details["decision_type"] = decision["type"]
    return {
        "name": "dead_assets",
        "passed": passed,
        "summary": decision["label"] or "No dead-trend condition detected.",
        "sticker": sticker,
        "details": details,
    }


# =========================================================
# DECISION
# =========================================================

def _evaluate_dead_assets(candles, config):
    dead_trend_types = set(getattr(config, "dead_trend_types", []) or [])
    swings = _find_swing_points(candles, SWING_SPAN)
    trend_series = _trend_line(candles, getattr(config, "trend_source", "ema_200"))

    detected_type = None

    if detected_type is None and "strong_dead_trend" in dead_trend_types:
        if _detect_strong_dead_trend(candles, swings, trend_series, config):
            detected_type = "strong_dead_trend"

    if detected_type is None and "slow_bleeding_trend" in dead_trend_types:
        if _detect_slow_bleeding_trend(candles, swings, trend_series, config):
            detected_type = "slow_bleeding_trend"

    if detected_type is None and "failed_recovery" in dead_trend_types:
        if _detect_failed_recovery(candles, swings, config):
            detected_type = "failed_recovery"

    if detected_type is None and "flat_dead_asset" in dead_trend_types:
        if _detect_flat_dead_asset(candles, config):
            detected_type = "flat_dead_asset"

    if detected_type is None:
        return {"excluded": False, "overridden": False, "label": None, "type": None}

    if _check_recovery_override(candles, swings, getattr(config, "recovery_override", "disabled")):
        return {"excluded": False, "overridden": True, "label": RECOVERY_LABEL, "type": detected_type}

    return {
        "excluded": True,
        "overridden": False,
        "label": RESULT_LABELS[detected_type],
        "type": detected_type,
    }


# =========================================================
# SWING POINTS
# =========================================================

def _find_swing_points(candles, span=SWING_SPAN):
    n = len(candles)
    if n < span * 2 + 1:
        return []

    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    swings = []

    for i in range(span, n - span):
        window_high = highs[i - span:i + span + 1]
        left_high = window_high[:span]
        right_high = window_high[span + 1:]
        if highs[i] == max(window_high) and highs[i] > max(left_high) and highs[i] >= max(right_high):
            swings.append({"type": "high", "index": i, "price": highs[i]})

        window_low = lows[i - span:i + span + 1]
        left_low = window_low[:span]
        right_low = window_low[span + 1:]
        if lows[i] == min(window_low) and lows[i] < min(left_low) and lows[i] <= min(right_low):
            swings.append({"type": "low", "index": i, "price": lows[i]})

    return sorted(swings, key=lambda swing: swing["index"])


def _trailing_consecutive_lower(swings, swing_type):
    prices = [s["price"] for s in swings if s["type"] == swing_type]
    if len(prices) < 2:
        return 0

    lower_count = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] < prices[i - 1]:
            lower_count += 1
        else:
            break

    return lower_count


# =========================================================
# TREND LINE
# =========================================================

def _trend_line(candles, source):
    closes = np.array([float(c["close"]) for c in candles], dtype=float)

    if source == "ema_50":
        return compute_ema(closes, 50)
    if source == "ema_100":
        return compute_ema(closes, 100)
    if source == "linear_regression":
        return _linear_regression_line(closes)

    return compute_ema(closes, 200)


def _linear_regression_line(closes):
    n = len(closes)
    if n < 2:
        return closes.copy()

    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, closes, 1)
    return slope * x + intercept


def _trend_is_downward(trend_series, lookback):
    n = len(trend_series)
    if n < 2:
        return False

    span = min(int(lookback), n - 1)
    if span < 1:
        return False

    return float(trend_series[-1]) < float(trend_series[-1 - span])


def _pct_closes_below_line(candles, trend_series, lookback):
    n = len(candles)
    start = max(0, n - int(lookback))
    total = n - start
    if total <= 0:
        return 0.0

    below = 0
    for i in range(start, n):
        if float(candles[i]["close"]) < float(trend_series[i]):
            below += 1

    return below / total


def _has_valid_higher_high(candles, swings, lookback):
    n = len(candles)
    start = max(0, n - int(lookback))
    highs = [s for s in swings if s["type"] == "high"]
    if len(highs) < 2:
        return False

    reference = None
    for high in highs:
        if high["index"] < start:
            reference = high
            continue
        if high["index"] >= n:
            break
        if reference is not None and high["price"] > reference["price"]:
            return True
        reference = high

    return False


def _recovery_check_confirms_downtrend(candles, swings, trend_series, config):
    lookback = min(int(getattr(config, "recovery_lookback", 200)), len(candles))
    no_higher_high = not _has_valid_higher_high(candles, swings, lookback)
    below_line_pct = _pct_closes_below_line(candles, trend_series, lookback)
    return no_higher_high and below_line_pct >= 0.8


# =========================================================
# DEAD TREND TYPE DETECTORS
# =========================================================

def _detect_strong_dead_trend(candles, swings, trend_series, config):
    lower_highs = _trailing_consecutive_lower(swings, "high") >= int(config.lower_highs_required)
    lower_lows = _trailing_consecutive_lower(swings, "low") >= int(config.lower_lows_required)
    downward = _trend_is_downward(trend_series, config.recovery_lookback)

    if not (lower_highs and lower_lows and downward):
        return False

    return _recovery_check_confirms_downtrend(candles, swings, trend_series, config)


def _detect_slow_bleeding_trend(candles, swings, trend_series, config):
    if not _trend_is_downward(trend_series, config.recovery_lookback):
        return False

    return _recovery_check_confirms_downtrend(candles, swings, trend_series, config)


def _detect_failed_recovery(candles, swings, config):
    lows = [s for s in swings if s["type"] == "low"]
    if not lows:
        return False

    threshold = float(config.bounce_threshold_pct) / 100.0
    window = int(config.failure_window)
    n = len(candles)

    for low in lows:
        low_price = low["price"]
        if low_price <= 0:
            continue

        bounce_target = low_price * (1.0 + threshold)
        bounce_index = None
        for i in range(low["index"] + 1, n):
            if float(candles[i]["high"]) >= bounce_target:
                bounce_index = i
                break

        if bounce_index is None:
            continue

        window_end = min(n, bounce_index + window + 1)
        for i in range(bounce_index, window_end):
            if float(candles[i]["low"]) < low_price:
                return True

    return False


def _detect_flat_dead_asset(candles, config):
    n = len(candles)
    recent = 20
    if n < recent + 5:
        return False

    trailing_window = min(100, n)

    volumes = np.array([float(c.get("volume") or 0.0) for c in candles], dtype=float)
    atr = _atr_series(candles, 14)

    volume_flag = _weak_activity_flag(
        volumes, recent, trailing_window, config.volume_option, "low", "declining"
    )
    volatility_flag = _weak_activity_flag(
        atr, recent, trailing_window, config.volatility_option, "low_atr", "very_low_atr"
    )

    return volume_flag and volatility_flag


def _weak_activity_flag(series, recent, trailing_window, option, low_key, secondary_key):
    n = len(series)
    recent_avg = float(np.mean(series[-recent:]))
    trailing_avg = float(np.mean(series[-trailing_window:])) if trailing_window > 0 else recent_avg

    low = trailing_avg > 0 and recent_avg < 0.5 * trailing_avg
    very_low_or_declining = False

    if secondary_key == "very_low_atr":
        very_low_or_declining = trailing_avg > 0 and recent_avg < 0.25 * trailing_avg
    elif secondary_key == "declining" and n >= 2 * recent:
        prior_avg = float(np.mean(series[-2 * recent:-recent]))
        very_low_or_declining = prior_avg > 0 and recent_avg <= 0.7 * prior_avg

    if option == low_key:
        return low
    if option == secondary_key:
        return very_low_or_declining
    return low or very_low_or_declining


def _true_range_series(candles):
    n = len(candles)
    tr = np.zeros(n, dtype=float)
    if n == 0:
        return tr

    prev_close = float(candles[0]["close"])
    for i in range(n):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        tr[i] = max(high - low, abs(high - prev_close), abs(low - prev_close)) if i > 0 else high - low
        prev_close = float(candles[i]["close"])

    return tr


def _atr_series(candles, period=14):
    tr = _true_range_series(candles)
    n = len(tr)
    if n == 0:
        return tr

    atr = np.zeros(n, dtype=float)
    if n < period:
        running_sum = 0.0
        for i, value in enumerate(tr):
            running_sum += value
            atr[i] = running_sum / (i + 1)
        return atr

    seed = float(np.mean(tr[:period]))
    atr[:period - 1] = seed
    atr[period - 1] = seed
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


# =========================================================
# RECOVERY OVERRIDE
# =========================================================

def _check_recovery_override(candles, swings, mode):
    if mode == "disabled":
        return False

    highs = [s for s in swings if s["type"] == "high"]
    if not highs or not candles:
        return False

    reference_price = highs[-1]["price"]

    if mode == "wick_above_swing_high":
        return float(candles[-1]["high"]) > reference_price

    if mode == "close_above_swing_high":
        return float(candles[-1]["close"]) > reference_price

    if mode == "two_closes_above_swing_high":
        if len(candles) < 2:
            return False
        return (
            float(candles[-1]["close"]) > reference_price
            and float(candles[-2]["close"]) > reference_price
        )

    return False

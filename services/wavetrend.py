# services/wavetrend.py
import numpy as np

from services.pine_math import NAN, pine_ema, pine_sma
from services.utils import build_indicator_sticker, confirm_if_needed, format_decimal, series_direction_matches

DEFAULT_ZONE_THRESHOLD = 60.0
DEFAULT_ZONE_THRESHOLD_SECONDARY = 53.0


def compute_wavetrend(
    candles,
    channel_length=10,
    average_length=21,
    signal_length=4,
):
    n = len(candles)

    if n < average_length + signal_length:
        return None

    hlc3 = np.array([
        (c["high"] + c["low"] + c["close"]) / 3
        for c in candles
    ], dtype=float)

    esa = pine_ema(hlc3, channel_length)
    deviation = pine_ema(np.abs(hlc3 - esa), channel_length)

    ci = np.full(n, NAN, dtype=float)
    valid = np.isfinite(deviation) & (deviation > 0)
    ci[valid] = (hlc3[valid] - esa[valid]) / (0.015 * deviation[valid])

    wt1 = pine_ema(ci, average_length)
    wt2 = pine_sma(wt1, signal_length)

    return {
        "wt1": wt1,
        "wt2": wt2,
    }


def ema(series, length):
    return pine_ema(np.asarray(series, dtype=float), length)


def sma(series, length):
    return pine_sma(np.asarray(series, dtype=float), length)


def evaluate_wavetrend_rules(
    wt,
    candles,
    config
):
    wt1 = wt["wt1"]
    wt2 = wt["wt2"]

    window = int(config.get("window", 1) or 1)
    zone_rule = config.get("zone")
    direction_rule = config.get("direction")
    tolerance_pct = float(config.get("tolerance_pct", 0) or 0)
    threshold = float(config.get("threshold", DEFAULT_ZONE_THRESHOLD) or DEFAULT_ZONE_THRESHOLD)

    if window <= 0:
        window = 1

    if len(wt1) < window:
        return False

    start = len(wt1) - window

    for idx in range(start, len(wt1)):
        if not _wavetrend_zone_matches(wt1, idx, zone_rule, tolerance_pct, threshold):
            continue

        if not _wavetrend_direction_matches(wt1, wt2, idx, direction_rule):
            continue

        if config.get("confirmation"):
            if idx >= len(candles):
                continue

            if not confirm_if_needed(candles, idx, config):
                continue

        return True

    return False


def _wavetrend_zone_matches(wt1, idx, zone_rule, tolerance_pct=0, threshold=None):
    if not zone_rule:
        return True

    value = float(wt1[idx])
    if not np.isfinite(value):
        return False

    tolerance = max(0.0, float(tolerance_pct))
    th = DEFAULT_ZONE_THRESHOLD if threshold is None else float(threshold)

    if zone_rule == "oversold":
        return value <= (-th + tolerance)
    if zone_rule == "neutral":
        return (-th - tolerance) <= value <= (th + tolerance)
    if zone_rule == "overbought":
        return value >= (th - tolerance)

    return False


def _wavetrend_direction_matches(wt1, wt2, idx, direction_rule):
    if direction_rule in {"rising", "falling", "turning_up", "turning_down"}:
        return series_direction_matches(wt1, idx, direction_rule)

    if direction_rule in {"crossed_up", "crossed_down"}:
        if idx - 1 < 0:
            return False
        prev_delta = float(wt1[idx - 1]) - float(wt2[idx - 1])
        cur_delta = float(wt1[idx]) - float(wt2[idx])
        return (prev_delta <= 0 and cur_delta > 0) if direction_rule == "crossed_up" else (prev_delta >= 0 and cur_delta < 0)

    return False


def build_wavetrend_sticker(wt, config):
    zone = config.get("zone")
    direction = config.get("direction")
    idx = _latest_matching_wavetrend_index(wt, config)
    wt1 = float(wt["wt1"][idx]) if len(wt["wt1"]) else 0.0
    wt2 = float(wt["wt2"][idx]) if len(wt["wt2"]) else 0.0
    zone_text = _zone_text(zone)
    direction_text = direction.replace("_", " ").title() if direction else None
    condition_parts = [f"WT1 {format_decimal(wt1, 1, signed=True)} vs WT2 {format_decimal(wt2, 1, signed=True)}"]
    if zone_text:
        condition_parts.append(zone_text.lower())
    if direction_text:
        condition_parts.append(direction_text.lower())

    return build_indicator_sticker(
        "WaveTrend",
        "; ".join([condition_parts[0], ", ".join(condition_parts[1:])]) if len(condition_parts) > 1 else condition_parts[0],
        config,
        length=config.get("average_length", 21),
        decision=_wavetrend_decision(zone, direction),
    )


def _zone_text(zone):
    zone_map = {
        "oversold": "Oversold",
        "neutral": "Neutral",
        "overbought": "Overbought",
    }
    return zone_map.get(zone, str(zone or "").strip().title()) if zone else None


def _latest_matching_wavetrend_index(wt, config):
    wt1 = wt["wt1"]
    if len(wt1) == 0:
        return 0

    window = max(1, int(config.get("window", 1) or 1))
    start = max(0, len(wt1) - window)
    latest_match = None

    for idx in range(start, len(wt1)):
        if not _wavetrend_zone_matches(
            wt1,
            idx,
            config.get("zone"),
            float(config.get("tolerance_pct", 0) or 0),
            float(config.get("threshold", DEFAULT_ZONE_THRESHOLD) or DEFAULT_ZONE_THRESHOLD),
        ):
            continue
        if not _wavetrend_direction_matches(wt["wt1"], wt["wt2"], idx, config.get("direction")):
            continue
        latest_match = idx

    return latest_match if latest_match is not None else len(wt1) - 1


def _wavetrend_decision(zone, direction):
    normalized_zone = str(zone or "").strip().lower()
    normalized_direction = str(direction or "").strip().lower()

    if normalized_zone == "oversold":
        if normalized_direction in {"crossed_up", "turning_up", "rising"}:
            return "Bullish Reversal"
        return "Oversold Watch"

    if normalized_zone == "overbought":
        if normalized_direction in {"crossed_down", "turning_down", "falling"}:
            return "Bearish Reversal"
        return "Overbought Watch"

    if normalized_direction in {"crossed_up", "turning_up", "rising"}:
        return "Bullish Momentum"
    if normalized_direction in {"crossed_down", "turning_down", "falling"}:
        return "Bearish Momentum"
    return "WaveTrend Match"

# services/ema.py

import numpy as np
from services.pine_math import pine_ema, pine_sma
from services.utils import build_indicator_sticker, format_price_value


# =========================================================
# EMA
# =========================================================

def compute_ema(series, length):

    series = np.asarray(series)

    ema = np.zeros_like(series)

    multiplier = 2 / (length + 1)

    ema[0] = series[0]

    for i in range(1, len(series)):
        ema[i] = (series[i] - ema[i-1]) * multiplier + ema[i-1]

    return ema


def compute_ema_wave(
    candles,
    wave_a_length=5,
    wave_b_length=25,
    wave_c_length=50,
    wave_sma_length=4,
    cutoff=10,
    source="hlc3",
):
    """EMA Wave Indicator [LazyBear] port.

    Pine:
      wa = sma(src - ema(src, alength), lengthMA)
      wb = sma(src - ema(src, blength), lengthMA)
      wc = sma(src - ema(src, clength), lengthMA)
      wcf = wb != 0 ? wc / wb > cutoff : false
      wbf = wa != 0 ? wb / wa > cutoff : false
    """
    if not candles:
        return None

    source_values = _candle_source(candles, source)
    a_length = int(wave_a_length)
    b_length = int(wave_b_length)
    c_length = int(wave_c_length)
    sma_length = int(wave_sma_length)
    cutoff_value = float(cutoff)

    if min(a_length, b_length, c_length, sma_length) <= 0:
        return None

    wave_a = pine_sma(source_values - pine_ema(source_values, a_length), sma_length)
    wave_b = pine_sma(source_values - pine_ema(source_values, b_length), sma_length)
    wave_c = pine_sma(source_values - pine_ema(source_values, c_length), sma_length)

    wave_c_spike = np.zeros(len(source_values), dtype=bool)
    wave_b_spike = np.zeros(len(source_values), dtype=bool)

    finite_c = np.isfinite(wave_c) & np.isfinite(wave_b) & (wave_b != 0)
    finite_b = np.isfinite(wave_b) & np.isfinite(wave_a) & (wave_a != 0)
    wave_c_spike[finite_c] = (wave_c[finite_c] / wave_b[finite_c]) > cutoff_value
    wave_b_spike[finite_b] = (wave_b[finite_b] / wave_a[finite_b]) > cutoff_value

    return {
        "wave_a": wave_a,
        "wave_b": wave_b,
        "wave_c": wave_c,
        "wave_b_spike": wave_b_spike,
        "wave_c_spike": wave_c_spike,
        "source": str(source or "hlc3").strip().lower(),
        "wave_a_length": a_length,
        "wave_b_length": b_length,
        "wave_c_length": c_length,
        "wave_sma_length": sma_length,
        "cutoff": cutoff_value,
    }


def price_matches_ema_rule(price, ema_value, rule, tolerance_pct=0):

    tolerance_pct = max(0.0, float(tolerance_pct or 0))
    tolerance = abs(float(ema_value)) * (tolerance_pct / 100.0)

    if rule == "above":
        return float(price) >= (float(ema_value) - tolerance)

    if rule == "below":
        return float(price) <= (float(ema_value) + tolerance)

    if rule == "touch":
        base_tolerance = abs(float(ema_value)) * 0.002
        return abs(float(price) - float(ema_value)) <= max(base_tolerance, tolerance)

    return False


# =========================================================
# RULES
# =========================================================

def evaluate_ema_rules(candles, config):
    if _is_ema_wave_config(config):
        return evaluate_ema_wave_rules(candles, config)

    closes = np.array([c["close"] for c in candles])

    length = config.get("length", 9)
    rule = config.get("rule")

    ema = compute_ema(closes, length)

    price = closes[-1]
    ema_val = ema[-1]
    tolerance_pct = max(0.0, float(config.get("tolerance_pct", 0) or 0))
    return price_matches_ema_rule(price, ema_val, rule, tolerance_pct=tolerance_pct)


def evaluate_ema_wave_rules(candles, config):
    computed = compute_ema_wave_from_config(candles, config)
    if computed is None:
        return False

    index = _latest_finite_wave_index(computed)
    if index is None:
        return False

    rule = str(config.get("rule", "any_spike") or "any_spike").strip().lower()
    tolerance = float(config.get("tolerance", config.get("tolerance_pct", 0)) or 0)
    wave_name = str(config.get("wave", "wave_c") or "wave_c").strip().lower()
    threshold = float(config.get("threshold", 0) or 0)

    if rule == "any_spike":
        return bool(computed["wave_b_spike"][index] or computed["wave_c_spike"][index])
    if rule == "both_spikes":
        return bool(computed["wave_b_spike"][index] and computed["wave_c_spike"][index])
    if rule == "wave_b_spike":
        return bool(computed["wave_b_spike"][index])
    if rule == "wave_c_spike":
        return bool(computed["wave_c_spike"][index])

    series = _wave_series(computed, wave_name)
    if series is None or not np.isfinite(series[index]):
        return False
    value = float(series[index])
    amount = abs(threshold) * tolerance / 100.0

    if rule == "above":
        return value >= threshold - amount
    if rule == "below":
        return value <= threshold + amount
    if rule == "crossed_up":
        return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) <= threshold + amount and value >= threshold - amount
    if rule == "crossed_down":
        return index > 0 and np.isfinite(series[index - 1]) and float(series[index - 1]) >= threshold - amount and value <= threshold + amount

    return False


def build_moving_average_sticker(label, length, rule, price, ma_value):
    condition = f"Price {format_price_value(price)} vs {label} @ {format_price_value(ma_value)}"
    return build_indicator_sticker(
        label,
        condition,
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision=_moving_average_decision(rule),
    )


def build_ema_sticker(candles, config):
    if _is_ema_wave_config(config):
        return build_ema_wave_sticker(candles, config)

    length = config.get("length", 9)
    rule = config.get("rule")
    closes = np.array([c["close"] for c in candles], dtype=float)
    ema_series = compute_ema(closes, length)
    price = float(closes[-1])
    ema_value = float(ema_series[-1])
    return build_moving_average_sticker("EMA", length, rule, price, ema_value)


def build_ema_wave_sticker(candles, config):
    computed = compute_ema_wave_from_config(candles, config)
    index = _latest_finite_wave_index(computed) if computed is not None else None
    wave_a = computed["wave_a"][index] if computed is not None and index is not None else np.nan
    wave_b = computed["wave_b"][index] if computed is not None and index is not None else np.nan
    wave_c = computed["wave_c"][index] if computed is not None and index is not None else np.nan
    condition = (
        f"WaveA {format_price_value(wave_a)} / "
        f"WaveB {format_price_value(wave_b)} / "
        f"WaveC {format_price_value(wave_c)}"
    )
    return build_indicator_sticker(
        "EMA Wave",
        condition,
        {"window": 1, "confirmation": False},
        length=computed["wave_c_length"] if computed is not None else config.get("wave_c_length", 50),
        window=1,
        decision=_ema_wave_decision(config.get("rule", "any_spike")),
    )


def _moving_average_decision(rule):
    normalized = str(rule or "").strip().lower()

    if normalized == "above":
        return "Bullish Trend Filter"
    if normalized == "below":
        return "Bearish Trend Filter"
    if normalized == "touch":
        return "Retest Watch"
    return "Moving Average Match"


def compute_ema_wave_from_config(candles, config):
    return compute_ema_wave(
        candles,
        wave_a_length=config.get("wave_a_length", config.get("alength", 5)),
        wave_b_length=config.get("wave_b_length", config.get("blength", 25)),
        wave_c_length=config.get("wave_c_length", config.get("clength", 50)),
        wave_sma_length=config.get("wave_sma_length", config.get("lengthMA", config.get("length_ma", 4))),
        cutoff=config.get("cutoff", 10),
        source=config.get("source", "hlc3"),
    )


def _is_ema_wave_config(config):
    mode = str(config.get("mode", config.get("type", "")) or "").strip().lower()
    if mode in {"price", "simple", "simple_ema", "ema_price", "moving_average"}:
        return False
    if config.get("simple_ema") is True:
        return False
    return True


def _has_ema_wave_config(config):
    mode = str(config.get("mode", config.get("type", "")) or "").strip().lower()
    return mode in {"wave", "ema_wave", "ewi", "ewi_lb"} or any(
        key in config
        for key in (
            "wave_a_length",
            "wave_b_length",
            "wave_c_length",
            "wave_sma_length",
            "alength",
            "blength",
            "clength",
            "lengthMA",
            "mse",
            "cutoff",
        )
    )


def _candle_source(candles, source):
    normalized = str(source or "hlc3").strip().lower()
    values = np.zeros(len(candles), dtype=float)

    for index, candle in enumerate(candles):
        open_ = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])

        if normalized == "open":
            values[index] = open_
        elif normalized == "high":
            values[index] = high
        elif normalized == "low":
            values[index] = low
        elif normalized == "close":
            values[index] = close
        elif normalized == "hl2":
            values[index] = (high + low) / 2.0
        elif normalized == "ohlc4":
            values[index] = (open_ + high + low + close) / 4.0
        else:
            values[index] = (high + low + close) / 3.0

    return values


def _latest_finite_wave_index(computed):
    if computed is None:
        return None
    finite = (
        np.isfinite(computed["wave_a"])
        & np.isfinite(computed["wave_b"])
        & np.isfinite(computed["wave_c"])
    )
    indexes = np.flatnonzero(finite)
    return int(indexes[-1]) if indexes.size else None


def _wave_series(computed, wave_name):
    normalized = str(wave_name or "wave_c").strip().lower()
    aliases = {
        "a": "wave_a",
        "wa": "wave_a",
        "wavea": "wave_a",
        "wave_a": "wave_a",
        "b": "wave_b",
        "wb": "wave_b",
        "waveb": "wave_b",
        "wave_b": "wave_b",
        "c": "wave_c",
        "wc": "wave_c",
        "wavec": "wave_c",
        "wave_c": "wave_c",
    }
    return computed.get(aliases.get(normalized, normalized))


def _ema_wave_decision(rule):
    normalized = str(rule or "").strip().lower()
    if "spike" in normalized:
        return "Spike / Exhaustion"
    if normalized in {"above", "crossed_up"}:
        return "Positive Wave"
    if normalized in {"below", "crossed_down"}:
        return "Negative Wave"
    return "EMA Wave Match"

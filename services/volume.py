# services/volume.py

import numpy as np
from services.utils import build_indicator_sticker, format_compact_number, format_decimal


# =========================================================
# VOLUME SPIKE
# =========================================================

def evaluate_volume_spike(candles, config):

    volumes = np.array([c["volume"] for c in candles])

    length = config.get("length", 20)
    multiplier = config.get("multiplier", 2)
    tolerance_pct = abs(float(config.get("tolerance_pct", 0) or 0))

    if len(volumes) < length + 1:
        return False

    avg_volume = np.mean(volumes[-length-1:-1])

    last_volume = volumes[-1]

    adjusted_multiplier = max(0.0, float(multiplier) * (1 - (tolerance_pct / 100.0)))
    return last_volume > avg_volume * adjusted_multiplier


# =========================================================
# STICKER
# =========================================================

def build_volume_sticker(candles, config):
    volumes = np.array([c["volume"] for c in candles], dtype=float)
    length = int(config.get("length", 20) or 20)
    average = np.mean(volumes[-length-1:-1]) if len(volumes) >= length + 1 else 0.0
    current = float(volumes[-1]) if len(volumes) else 0.0
    ratio = (current / average) if average > 0 else 0.0
    return build_indicator_sticker(
        "Volume",
        f"{format_decimal(ratio, 2)}x average ({format_compact_number(current)} vs {format_compact_number(average)})",
        {"window": 1, "confirmation": False},
        length=length,
        window=1,
        decision="Volume Expansion",
    )

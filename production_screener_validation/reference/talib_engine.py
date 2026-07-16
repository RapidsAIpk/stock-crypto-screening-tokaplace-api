from __future__ import annotations

from typing import Any

import numpy as np

try:
    import talib
except ImportError as exc:  # pragma: no cover - exercised by deployment startup
    raise RuntimeError("TA-Lib 0.6.8 is required for production screener validation") from exc


TALIB_VERSION = talib.__version__


def arrays(candles: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    return {
        field: np.asarray([float(candle[field]) for candle in candles], dtype=float)
        for field in ("open", "high", "low", "close", "volume")
    }


def calculate(name: str, candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, np.ndarray]:
    values = arrays(candles)
    close, high, low = values["close"], values["high"], values["low"]
    if name == "rsi":
        return {"rsi": talib.RSI(close, timeperiod=int(config["length"]))}
    if name == "aroon":
        down, up = talib.AROON(high, low, timeperiod=int(config["length"]))
        return {"aroon_down": down, "aroon_up": up, "aroon_oscillator": up - down}
    if name == "macd":
        macd, signal, hist = talib.MACD(
            close,
            fastperiod=int(config["fast"]),
            slowperiod=int(config["slow"]),
            signalperiod=int(config["signal"]),
        )
        return {"macd": macd, "signal": signal, "histogram": hist}
    if name == "ema":
        return {"ema": talib.EMA(close, timeperiod=int(config["length"]))}
    if name == "sma":
        return {"sma": talib.SMA(close, timeperiod=int(config["length"]))}
    if name == "stochrsi":
        fastk, fastd = talib.STOCHRSI(
            close,
            timeperiod=int(config["length"]),
            fastk_period=int(config.get("k", 3)),
            fastd_period=int(config.get("d", 3)),
            fastd_matype=0,
        )
        return {"k": fastk, "d": fastd}
    if name == "adx":
        return {"adx": talib.ADX(high, low, close, timeperiod=int(config["length"]))}
    raise ValueError(f"TA-Lib adapter does not support '{name}'")


def last_finite_index(series: np.ndarray) -> int | None:
    indexes = np.flatnonzero(np.isfinite(series))
    return int(indexes[-1]) if indexes.size else None


def finite_at(series: np.ndarray, index: int) -> float | None:
    if index < 0 or index >= len(series) or not np.isfinite(series[index]):
        return None
    return float(series[index])

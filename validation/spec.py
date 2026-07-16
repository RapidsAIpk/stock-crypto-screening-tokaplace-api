from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any


SCHEMA_VERSION = 1
VALIDATION_TIMEFRAME = "30min"
SUPPORTED_ADJUSTMENTS = {"all", "splits", "dividends", "none"}
FIXED_COMPARISON_START = date(2026, 6, 1)
FIXED_COMPARISON_END = date(2026, 6, 30)
TRAINING_START = date(2026, 6, 1)
TRAINING_END = date(2026, 6, 20)
VALIDATION_START = date(2026, 6, 21)
VALIDATION_END = date(2026, 6, 30)


def _as_date(value: date | str, field_name: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date without a time")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from exc


def canonical_utc_timestamp(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("timestamp cannot be empty")
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.combine(date.fromisoformat(raw_value), time.min)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat()


@dataclass(frozen=True)
class IndicatorParameters:
    rsi_length: int = 14
    aroon_length: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ema_length: int = 9
    series_type: str = "close"

    def __post_init__(self) -> None:
        numeric_fields = (
            "rsi_length",
            "aroon_length",
            "macd_fast",
            "macd_slow",
            "macd_signal",
            "ema_length",
        )
        for field_name in numeric_fields:
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be greater than zero")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be smaller than macd_slow")
        if self.series_type != "close":
            raise ValueError("only the close series is supported in the current phase")


@dataclass(frozen=True)
class ValidationSpec:
    symbol: str
    comparison_start: date | str = FIXED_COMPARISON_START
    comparison_end: date | str = FIXED_COMPARISON_END
    twelve_symbol: str | None = None
    massive_symbol: str | None = None
    timeframe: str = VALIDATION_TIMEFRAME
    timezone_name: str = "UTC"
    adjustment: str = "splits"
    closed_candles_only: bool = True
    indicators: IndicatorParameters = field(default_factory=IndicatorParameters)
    tolerance: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_symbol = str(self.symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")

        start = _as_date(self.comparison_start, "comparison_start")
        end = _as_date(self.comparison_end, "comparison_end")
        if start != FIXED_COMPARISON_START or end != FIXED_COMPARISON_END:
            raise ValueError(
                "comparison range is fixed to 2026-06-01 through 2026-06-30"
            )
        if end >= datetime.now(timezone.utc).date():
            raise ValueError("comparison_end must be a completed historical UTC day")
        if self.timeframe != VALIDATION_TIMEFRAME:
            raise ValueError(
                f"the current validation phase only supports timeframe='{VALIDATION_TIMEFRAME}'"
            )
        if self.timezone_name != "UTC":
            raise ValueError("the validation contract timezone must be UTC")
        if self.adjustment not in SUPPORTED_ADJUSTMENTS:
            raise ValueError(
                f"adjustment must be one of {sorted(SUPPORTED_ADJUSTMENTS)}"
            )
        if not self.closed_candles_only:
            raise ValueError("closed_candles_only must be enabled")
        if any(float(value) < 0 for value in self.tolerance.values()):
            raise ValueError("tolerances cannot be negative")

        object.__setattr__(self, "symbol", normalized_symbol)
        object.__setattr__(self, "comparison_start", start)
        object.__setattr__(self, "comparison_end", end)
        twelve_symbol = str(self.twelve_symbol or normalized_symbol).strip().upper()
        massive_symbol = str(self.massive_symbol or normalized_symbol).strip().upper()
        if not twelve_symbol or not massive_symbol:
            raise ValueError("provider symbols cannot be empty")
        object.__setattr__(self, "twelve_symbol", twelve_symbol)
        object.__setattr__(self, "massive_symbol", massive_symbol)
        object.__setattr__(self, "tolerance", dict(self.tolerance))

    @property
    def training_start(self) -> date:
        return TRAINING_START

    @property
    def training_end(self) -> date:
        return TRAINING_END

    @property
    def validation_start(self) -> date:
        return VALIDATION_START

    @property
    def validation_end(self) -> date:
        return VALIDATION_END

    @property
    def run_id(self) -> str:
        encoded = json.dumps(
            self.contract_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]

    def contract_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "symbol": self.symbol,
            "provider_symbols": {
                "twelve": self.twelve_symbol,
                "massive": self.massive_symbol,
            },
            "timeframe": self.timeframe,
            "timezone": self.timezone_name,
            "comparison_start": self.comparison_start.isoformat(),
            "comparison_end": self.comparison_end.isoformat(),
            "data_split": {
                "basis": "calendar_days",
                "training_start": self.training_start.isoformat(),
                "training_end": self.training_end.isoformat(),
                "training_days": 20,
                "validation_start": self.validation_start.isoformat(),
                "validation_end": self.validation_end.isoformat(),
                "validation_days": 10,
            },
            "closed_candles_only": self.closed_candles_only,
            "adjustment": self.adjustment,
            "indicators": asdict(self.indicators),
            "tolerance": dict(sorted(self.tolerance.items())),
        }

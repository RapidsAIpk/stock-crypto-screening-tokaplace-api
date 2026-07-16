from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
INDICATORS = {
    "rsi", "stochrsi", "wavetrend", "aroon", "adx", "ema", "sma",
    "macd", "volume", "relative_volume", "current_volume", "float",
    "shares_outstanding", "volatility", "lrc", "regression", "trend",
    "linreg_candles",
}
TIMEFRAME_SCOPES = {"single", "primary", "secondary"}
VERDICTS = {
    "pass", "fail", "insufficient_data", "reference_error",
    "reference_drift", "production_error", "unapproved_reference",
}
REQUIRED_CONFIG = {
    "rsi": {"length", "location", "direction", "window", "tolerance_pct", "confirmation"},
    "aroon": {"length", "level", "direction", "window", "tolerance_pct", "confirmation"},
    "macd": {"fast", "slow", "signal", "rule", "tolerance_pct"},
    "ema": {"length", "rule", "tolerance_pct"},
    "sma": {"length", "rule", "tolerance_pct"},
    "stochrsi": {"length", "rule", "tolerance_pct"},
    "adx": {"length", "rule", "threshold", "tolerance_pct"},
    "wavetrend": {"channel_length", "average_length", "signal_length", "zone", "direction", "window", "tolerance_pct", "confirmation"},
    "lrc": {"length", "upper_dev", "lower_dev", "lines", "action", "window", "tolerance_pct", "r_mode", "confirmation"},
    "regression": {"length", "width_coeff", "lines", "action", "window", "tolerance_pct", "confirmation"},
    "trend": {"length", "areas"},
    "linreg_candles": {"lr_length", "signal_smoothing", "price_position", "window", "tolerance_pct", "confirmation"},
    "volume": {"length", "multiplier", "tolerance_pct"},
    "relative_volume": {"length", "min_ratio", "tolerance_pct"},
    "current_volume": {"min_value", "max_value", "tolerance_pct"},
    "float": {"min_value", "max_value", "tolerance_pct"},
    "shares_outstanding": {"min_value", "max_value", "tolerance_pct"},
    "volatility": {"length", "min_pct", "max_pct", "tolerance_pct"},
}
ALLOWED_RULES = {
    "rsi.location": {None, "oversold", "neutral", "overbought"},
    "rsi.direction": {None, "rising", "falling", "turning_up", "turning_down"},
    "aroon.level": {"above_50", "between_50_0", "near_0", "between_0_-50", "below_-50"},
    "aroon.direction": {None, "rising", "falling", "turning_up", "turning_down"},
    "macd.rule": {"bullish_cross", "bearish_cross", "above_zero", "below_zero"},
    "ema.rule": {"above", "below", "touch"},
    "sma.rule": {"above", "below", "touch"},
    "stochrsi.rule": {"oversold", "overbought", "bullish_cross", "bearish_cross"},
    "adx.rule": {"above", "below", "rising", "falling"},
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndicatorRule:
    name: str
    timeframe: str
    config: dict[str, Any]

    def __post_init__(self) -> None:
        name = str(self.name).strip().lower()
        timeframe = str(self.timeframe).strip().lower()
        if name not in INDICATORS:
            raise ValueError(f"unsupported indicator '{name}'")
        if timeframe not in TIMEFRAME_SCOPES:
            raise ValueError(f"unsupported indicator timeframe '{timeframe}'")
        if not isinstance(self.config, dict):
            raise ValueError("indicator config must be an object")
        if not self.config:
            raise ValueError(f"{name} config must be explicit and cannot be empty")
        missing = REQUIRED_CONFIG[name] - set(self.config)
        if missing:
            raise ValueError(f"{name} config is missing explicit fields: {sorted(missing)}")
        for key in ("length", "fast", "slow", "signal", "channel_length", "average_length", "signal_length", "lr_length", "signal_smoothing", "window"):
            if key in self.config and self.config[key] is not None and int(self.config[key]) <= 0:
                raise ValueError(f"{name}.{key} must be greater than zero")
        for key in ("tolerance_pct", "confirmation_window"):
            if key in self.config and self.config[key] is not None and float(self.config[key]) < 0:
                raise ValueError(f"{name}.{key} cannot be negative")
        for qualified, allowed in ALLOWED_RULES.items():
            indicator, key = qualified.split(".")
            if indicator == name and self.config.get(key) not in allowed:
                raise ValueError(f"unknown {qualified} '{self.config.get(key)}'")
        if name == "macd" and int(self.config["fast"]) >= int(self.config["slow"]):
            raise ValueError("macd.fast must be less than macd.slow")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "config", dict(self.config))


@dataclass(frozen=True)
class ScreenerCase:
    case_id: str
    fixture_id: str
    symbols: tuple[str, ...]
    indicators: tuple[IndicatorRule, ...]
    required: bool = True
    asset_type: str = "stocks"
    timeframe_mode: str = "single"
    single_timeframe: str | None = "1day"
    gate_timeframe: str | None = None
    entry_timeframe: str | None = None
    stock_sources: tuple[str, ...] = ("zoya",)
    compliance_status: str | None = None
    compliance_standards: tuple[str, ...] = ()
    price_range: dict[str, float | None] | None = None
    channel_respect: dict[str, Any] | None = None
    confluence: dict[str, Any] | None = None
    evaluation_date: str | None = None
    description: str = ""
    golden_id: str | None = None

    def __post_init__(self) -> None:
        case_id = str(self.case_id).strip()
        fixture_id = str(self.fixture_id).strip()
        symbols = tuple(str(symbol).strip().upper() for symbol in self.symbols)
        if not case_id or not fixture_id:
            raise ValueError("case_id and fixture_id are required")
        if not symbols or any(not symbol for symbol in symbols):
            raise ValueError(f"case '{case_id}' requires explicit symbols")
        if len(set(symbols)) != len(symbols):
            raise ValueError(f"case '{case_id}' contains duplicate symbols")
        if self.asset_type not in {"stocks", "crypto"}:
            raise ValueError(f"case '{case_id}' has invalid asset_type")
        if self.timeframe_mode not in {"single", "gate_entry"}:
            raise ValueError(f"case '{case_id}' has invalid timeframe_mode")
        if self.timeframe_mode == "single" and not self.single_timeframe:
            raise ValueError(f"case '{case_id}' requires single_timeframe")
        if self.timeframe_mode == "gate_entry" and not (self.gate_timeframe and self.entry_timeframe):
            raise ValueError(f"case '{case_id}' requires gate_timeframe and entry_timeframe")
        if not self.indicators and not any((self.price_range, self.channel_respect, self.confluence, self.compliance_status)):
            raise ValueError(f"case '{case_id}' has no filters")
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "fixture_id", fixture_id)
        object.__setattr__(self, "symbols", symbols)

    @property
    def checksum(self) -> str:
        payload = asdict(self)
        payload.pop("golden_id", None)
        return semantic_hash(payload)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreenerCase":
        indicators = tuple(IndicatorRule(**item) for item in data.get("indicators", []))
        return cls(
            case_id=data["id"],
            fixture_id=data["fixture_id"],
            symbols=tuple(data.get("symbols", [])),
            indicators=indicators,
            required=bool(data.get("required", True)),
            asset_type=data.get("asset_type", "stocks"),
            timeframe_mode=data.get("timeframe_mode", "single"),
            single_timeframe=data.get("single_timeframe", "1day"),
            gate_timeframe=data.get("gate_timeframe"),
            entry_timeframe=data.get("entry_timeframe"),
            stock_sources=tuple(data.get("stock_sources", ["zoya"])),
            compliance_status=data.get("compliance_status"),
            compliance_standards=tuple(data.get("compliance_standards", [])),
            price_range=data.get("price_range"),
            channel_respect=data.get("channel_respect"),
            confluence=data.get("confluence"),
            evaluation_date=data.get("evaluation_date"),
            description=data.get("description", ""),
            golden_id=data.get("golden_id"),
        )

    def production_payload(self, *, gate_session_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "asset_type": self.asset_type,
            "symbols": list(self.symbols),
            "stock_sources": list(self.stock_sources),
            "compliance_status": self.compliance_status,
            "compliance_standards": list(self.compliance_standards),
            "timeframe_mode": self.timeframe_mode,
            "single_timeframe": self.single_timeframe,
            "gate_timeframe": self.gate_timeframe,
            "entry_timeframe": self.entry_timeframe,
            "gate_session_id": gate_session_id,
            "indicators": [asdict(item) for item in self.indicators],
            "price_range": self.price_range,
            "channel_respect": self.channel_respect,
            "confluence": self.confluence,
        }
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class CaseSuite:
    suite_id: str
    cases: tuple[ScreenerCase, ...]

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CaseSuite":
        data = json.loads(Path(path).read_text("utf-8"))
        cases = tuple(ScreenerCase.from_dict(item) for item in data.get("cases", []))
        if not cases:
            raise ValueError("case suite must contain at least one case")
        ids = [case.case_id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case suite contains duplicate case IDs")
        return cls(str(data.get("suite_id") or Path(path).stem), cases)

    @property
    def checksum(self) -> str:
        return semantic_hash({"suite_id": self.suite_id, "cases": [case.checksum for case in self.cases]})


@dataclass
class SymbolEvidence:
    symbol: str
    expected: bool | None
    status: str
    rules: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    earliest_stage: str | None = None
    error: str | None = None


@dataclass
class CaseResult:
    case_id: str
    verdict: str
    expected_symbols: list[str]
    actual_symbols: list[str]
    correctly_included: list[str]
    correctly_excluded: list[str]
    missing_symbols: list[str]
    unexpected_symbols: list[str]
    insufficient_data_symbols: list[str]
    earliest_mismatch_stage: str | None
    symbol_evidence: dict[str, Any]
    error: str | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"invalid verdict '{self.verdict}'")

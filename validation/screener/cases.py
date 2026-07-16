from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_INDICATORS = {"rsi", "aroon", "macd", "ema"}
SUPPORTED_CONFIRMATION_TYPES = {"bullish", "bearish", "strong_bullish", "strong_bearish"}
SUPPORTED_CONFIRMATION_PATTERNS = {
    "bullish_engulfing",
    "bearish_engulfing",
    "hammer",
    "shooting_star",
    "bullish_pin_bar",
    "bearish_pin_bar",
}


def _validate_config(case_id: str, indicator: str, config: dict[str, Any]) -> None:
    allowed_values = {
        "rsi": {
            "location": {None, "oversold", "neutral", "overbought"},
            "direction": {None, "turning_up", "turning_down"},
        },
        "aroon": {
            "level": {"above_50", "between_50_0", "near_0", "between_0_-50", "below_-50"},
            "direction": {None, "rising", "falling", "turning_up", "turning_down"},
        },
        "macd": {
            "rule": {"bullish_cross", "bearish_cross", "above_zero", "below_zero"},
        },
        "ema": {"rule": {"above", "below", "touch"}},
    }
    for field, allowed in allowed_values[indicator].items():
        if field not in config and None not in allowed:
            raise ValueError(f"filter case '{case_id}' requires '{field}'")
        if config.get(field) not in allowed:
            raise ValueError(
                f"filter case '{case_id}' has unsupported {field}='{config.get(field)}'"
            )
    for field in ("length", "fast", "slow", "signal", "window", "confirmation_window"):
        if field in config and int(config[field]) < (0 if field == "confirmation_window" else 1):
            raise ValueError(f"filter case '{case_id}' has invalid {field}")
    if float(config.get("tolerance_pct", 0) or 0) < 0:
        raise ValueError(f"filter case '{case_id}' has negative tolerance_pct")
    confirmation_types = set(config.get("confirmation_types") or [])
    if config.get("confirmation_type"):
        confirmation_types.add(config["confirmation_type"])
    if confirmation_types - SUPPORTED_CONFIRMATION_TYPES:
        raise ValueError(f"filter case '{case_id}' has unsupported confirmation types")
    confirmation_patterns = set(config.get("confirmation_patterns") or [])
    if confirmation_patterns - SUPPORTED_CONFIRMATION_PATTERNS:
        raise ValueError(f"filter case '{case_id}' has unsupported confirmation patterns")
    if indicator in {"ema", "macd"} and config.get("confirmation"):
        raise ValueError(f"filter case '{case_id}' enables unsupported {indicator} confirmation")


@dataclass(frozen=True)
class FilterCase:
    case_id: str
    indicator: str
    config: dict[str, Any]


@dataclass(frozen=True)
class CombinedCase:
    case_id: str
    case_ids: tuple[str, ...]
    operator: str


@dataclass(frozen=True)
class ScreenerCaseSuite:
    cases: tuple[FilterCase, ...]
    combined: tuple[CombinedCase, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScreenerCaseSuite":
        raw_cases = payload.get("cases")
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError("screener suite requires a non-empty 'cases' list")
        cases: list[FilterCase] = []
        seen_ids: set[str] = set()
        for raw in raw_cases:
            case_id = str(raw.get("id") or "").strip()
            indicator = str(raw.get("indicator") or "").strip().lower()
            config = raw.get("config")
            if not case_id or case_id in seen_ids:
                raise ValueError("filter case IDs must be non-empty and unique")
            if indicator not in SUPPORTED_INDICATORS:
                raise ValueError(f"unsupported filter indicator '{indicator}'")
            if not isinstance(config, dict):
                raise ValueError(f"filter case '{case_id}' requires an object config")
            _validate_config(case_id, indicator, config)
            seen_ids.add(case_id)
            cases.append(FilterCase(case_id, indicator, dict(config)))

        present = {case.indicator for case in cases}
        missing = sorted(SUPPORTED_INDICATORS - present)
        if missing:
            raise ValueError(f"screener suite is missing indicators: {missing}")

        combined: list[CombinedCase] = []
        for raw in payload.get("combined", []):
            case_id = str(raw.get("id") or "").strip()
            case_ids = tuple(str(value) for value in raw.get("case_ids", []))
            operator = str(raw.get("operator") or "all").strip().lower()
            if not case_id or case_id in seen_ids:
                raise ValueError("combined case IDs must be non-empty and unique")
            if operator not in {"all", "any"}:
                raise ValueError("combined operator must be 'all' or 'any'")
            if (
                not case_ids
                or len(set(case_ids)) != len(case_ids)
                or any(value not in seen_ids for value in case_ids)
            ):
                raise ValueError(f"combined case '{case_id}' references unknown cases")
            seen_ids.add(case_id)
            combined.append(CombinedCase(case_id, case_ids, operator))
        if not combined:
            raise ValueError("screener suite requires at least one combined case")
        return cls(tuple(cases), tuple(combined))

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ScreenerCaseSuite":
        payload = json.loads(Path(path).read_text("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("screener case file must contain a JSON object")
        return cls.from_payload(payload)

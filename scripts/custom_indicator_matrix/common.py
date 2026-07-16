from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_FIXTURE_ID = "stocks_daily_2026_06_30_v1"
DEFAULT_SYMBOLS = ("AAPL", "AMD", "MSFT", "NVDA", "TSLA")

WALK_FORWARD_DATES = (
    ("2026-06-01", "Jun 1"),
    ("2026-06-02", "Jun 2"),
    ("2026-06-30", "Jun 30"),
)


def make_case(
    *,
    case_id: str,
    description: str,
    indicator_name: str,
    config: dict[str, Any],
    fixture_id: str,
    symbols: list[str],
    evaluation_date: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": case_id,
        "description": description,
        "fixture_id": fixture_id,
        "symbols": [item.upper() for item in symbols],
        "required": True,
        "asset_type": "stocks",
        "timeframe_mode": "single",
        "single_timeframe": "1day",
        "stock_sources": ["zoya"],
        "indicators": [{"name": indicator_name, "timeframe": "single", "config": deepcopy(config)}],
    }
    if evaluation_date:
        payload["evaluation_date"] = evaluation_date
    return payload


def merge_config(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    merged = deepcopy(base)
    merged.update(overrides)
    return merged

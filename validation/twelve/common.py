from __future__ import annotations

from typing import Any

from validation.spec import ValidationSpec


def base_request_params(spec: ValidationSpec) -> dict[str, Any]:
    return {
        "symbol": spec.twelve_symbol,
        "interval": spec.timeframe,
        "start_date": spec.comparison_start.isoformat(),
        "end_date": spec.comparison_end.isoformat(),
        "outputsize": 5000,
        "order": "ASC",
        "timezone": spec.timezone_name,
        "adjust": spec.adjustment,
    }

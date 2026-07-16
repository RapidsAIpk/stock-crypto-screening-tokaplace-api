from __future__ import annotations

from validation.spec import ValidationSpec
from validation.twelve.client import TwelveDataClient, TwelveResponse
from validation.twelve.common import base_request_params
from validation.twelve.schema import validate_values


def fetch(client: TwelveDataClient, spec: ValidationSpec) -> TwelveResponse:
    params = {
        **base_request_params(spec),
        "fast_period": spec.indicators.macd_fast,
        "slow_period": spec.indicators.macd_slow,
        "signal_period": spec.indicators.macd_signal,
        "series_type": spec.indicators.series_type,
    }
    response = client.get("macd", params)
    validate_values(
        response,
        spec,
        ("datetime", "macd", "macd_signal", "macd_hist"),
        ("macd", "macd_signal", "macd_hist"),
    )
    return response

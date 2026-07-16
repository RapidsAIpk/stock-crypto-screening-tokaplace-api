from __future__ import annotations

from validation.spec import ValidationSpec
from validation.twelve.client import TwelveDataClient, TwelveResponse
from validation.twelve.common import base_request_params
from validation.twelve.schema import validate_values


def fetch(client: TwelveDataClient, spec: ValidationSpec) -> TwelveResponse:
    params = {
        **base_request_params(spec),
        "time_period": spec.indicators.aroon_length,
    }
    response = client.get("aroon", params)
    validate_values(
        response,
        spec,
        ("datetime", "aroon_up", "aroon_down"),
        ("aroon_up", "aroon_down"),
    )
    return response

from __future__ import annotations

from validation.spec import ValidationSpec
from validation.twelve.client import TwelveDataClient, TwelveResponse
from validation.twelve.common import base_request_params
from validation.twelve.schema import validate_values


def fetch(client: TwelveDataClient, spec: ValidationSpec) -> TwelveResponse:
    response = client.get("time_series", base_request_params(spec))
    values = response.payload.get("values")
    has_volume = isinstance(values, list) and any(
        isinstance(row, dict) and "volume" in row for row in values
    )
    numeric_fields = ("open", "high", "low", "close")
    if has_volume:
        numeric_fields = (*numeric_fields, "volume")
    validate_values(
        response,
        spec,
        ("datetime", *numeric_fields),
        numeric_fields,
    )
    return response

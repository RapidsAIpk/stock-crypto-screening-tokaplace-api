from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from validation.spec import ValidationSpec
from validation.twelve.client import TwelveDataError, TwelveResponse


def _row_date(raw_value: Any, endpoint: str) -> date:
    value = str(raw_value or "").strip()
    if not value:
        raise TwelveDataError(f"'{endpoint}' contains an empty datetime")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise TwelveDataError(
            f"'{endpoint}' contains invalid datetime '{value}'"
        ) from exc


def validate_values(
    response: TwelveResponse,
    spec: ValidationSpec,
    required_fields: Iterable[str],
    numeric_fields: Iterable[str] = (),
) -> list[dict[str, Any]]:
    values = response.payload.get("values")
    if not isinstance(values, list) or not values:
        raise TwelveDataError(f"'{response.endpoint}' returned no values")

    required = tuple(required_fields)
    numeric = tuple(numeric_fields)
    seen_datetimes: set[str] = set()
    validated: list[dict[str, Any]] = []
    for position, row in enumerate(values):
        if not isinstance(row, dict):
            raise TwelveDataError(
                f"'{response.endpoint}' row {position} is not an object"
            )
        missing = [field for field in required if field not in row]
        if missing:
            raise TwelveDataError(
                f"'{response.endpoint}' row {position} is missing fields: {missing}"
            )
        for field in numeric:
            try:
                Decimal(str(row[field]))
            except (InvalidOperation, ValueError) as exc:
                raise TwelveDataError(
                    f"'{response.endpoint}' row {position} has non-numeric field '{field}'"
                ) from exc
        timestamp = str(row["datetime"])
        if timestamp in seen_datetimes:
            raise TwelveDataError(
                f"'{response.endpoint}' contains duplicate datetime '{timestamp}'"
            )
        seen_datetimes.add(timestamp)
        timestamp_date = _row_date(timestamp, response.endpoint)
        if not spec.comparison_start <= timestamp_date <= spec.comparison_end:
            raise TwelveDataError(
                f"'{response.endpoint}' datetime '{timestamp}' is outside the comparison range"
            )
        validated.append(row)
    return validated

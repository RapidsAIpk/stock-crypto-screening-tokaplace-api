from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from services.market_data import map_symbol_for_polygon, normalize_polygon_rows
from validation.massive.client import MassiveDataClient, MassiveDataError, MassiveResponse
from validation.spec import ValidationSpec


REQUIRED_FIELDS = ("t", "o", "h", "l", "c", "v")


def massive_provider_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith("/USD"):
        normalized = f"{normalized[:-4]}-USD"
    return map_symbol_for_polygon(normalized)


def _adjusted_flag(spec: ValidationSpec) -> bool:
    if spec.adjustment == "splits":
        return True
    if spec.adjustment == "none":
        return False
    raise ValueError(
        "Massive aggregates only support split-adjusted or unadjusted prices; "
        f"cannot match adjustment='{spec.adjustment}'"
    )


def _segment_for_date(value: str, spec: ValidationSpec) -> str:
    parsed = datetime.fromisoformat(value).date()
    if spec.training_start <= parsed <= spec.training_end:
        return "training"
    if spec.validation_start <= parsed <= spec.validation_end:
        return "validation"
    raise MassiveDataError(f"Massive candle date '{value}' is outside the fixed split")


def validate_and_normalize(
    response: MassiveResponse,
    spec: ValidationSpec,
    provider_symbol: str,
) -> list[dict[str, Any]]:
    payload = response.payload
    if payload.get("ticker") and str(payload["ticker"]).upper() != provider_symbol.upper():
        raise MassiveDataError(
            f"Massive returned ticker '{payload['ticker']}' for requested '{provider_symbol}'"
        )
    expected_adjusted = _adjusted_flag(spec)
    if payload.get("adjusted") is not expected_adjusted:
        raise MassiveDataError(
            f"Massive adjusted={payload.get('adjusted')} does not match expected {expected_adjusted}"
        )

    rows = payload.get("results")
    if not isinstance(rows, list) or not rows:
        raise MassiveDataError("Massive returned no aggregate candles")

    seen_timestamps: set[int] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MassiveDataError(f"Massive row {position} is not an object")
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            raise MassiveDataError(f"Massive row {position} is missing fields: {missing}")
        try:
            timestamp_ms = int(row["t"])
        except (TypeError, ValueError) as exc:
            raise MassiveDataError(f"Massive row {position} has invalid timestamp") from exc
        if timestamp_ms in seen_timestamps:
            raise MassiveDataError(f"Massive contains duplicate timestamp '{timestamp_ms}'")
        seen_timestamps.add(timestamp_ms)
        for field in ("o", "h", "l", "c", "v"):
            try:
                Decimal(str(row[field]))
            except (InvalidOperation, ValueError) as exc:
                raise MassiveDataError(
                    f"Massive row {position} has non-numeric field '{field}'"
                ) from exc
        candle_date = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date()
        if not spec.comparison_start <= candle_date <= spec.comparison_end:
            raise MassiveDataError(
                f"Massive timestamp '{timestamp_ms}' is outside the comparison range"
            )

    normalized = normalize_polygon_rows(sorted(rows, key=lambda row: int(row["t"])))
    if len(normalized) != len(rows):
        raise MassiveDataError("Massive candle normalization dropped one or more rows")

    output: list[dict[str, Any]] = []
    for candle in normalized:
        timestamp = datetime.fromtimestamp(candle["time"], timezone.utc)
        date_value = timestamp.date().isoformat()
        output.append(
            {
                "datetime": timestamp.isoformat(),
                "date": date_value,
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
                "segment": _segment_for_date(date_value, spec),
            }
        )
    return output


class MassiveCandleFetcher:
    def __init__(self, client: MassiveDataClient) -> None:
        self.client = client

    def fetch(self, spec: ValidationSpec) -> tuple[MassiveResponse, list[dict[str, Any]]]:
        provider_symbol = massive_provider_symbol(spec.massive_symbol or spec.symbol)
        endpoint = (
            f"v2/aggs/ticker/{quote(provider_symbol, safe=':')}/range/30/minute/"
            f"{spec.comparison_start.isoformat()}/{spec.comparison_end.isoformat()}"
        )
        response = self.client.get(
            endpoint,
            {
                "adjusted": _adjusted_flag(spec),
                "sort": "asc",
                "limit": 50_000,
            },
        )
        return response, validate_and_normalize(response, spec, provider_symbol)

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import quote

import httpx


class MassiveFixtureCapture:
    def __init__(self, api_key: str, *, base_url: str = "https://api.massive.com") -> None:
        if not str(api_key).strip():
            raise ValueError("Massive API key is required")
        self.api_key = str(api_key).strip()
        self.client = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=30)

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _range(timeframe: str) -> tuple[int, str]:
        aliases = {"1day": (1, "day"), "1d": (1, "day"), "1w": (1, "week"), "1mo": (1, "month")}
        if timeframe in aliases:
            return aliases[timeframe]
        match = re.fullmatch(r"(\d+)(m|h|d|w|mo)", timeframe)
        if not match:
            raise ValueError(f"unsupported Massive timeframe '{timeframe}'")
        units = {"m": "minute", "h": "hour", "d": "day", "w": "week", "mo": "month"}
        return int(match.group(1)), units[match.group(2)]

    def fetch(self, symbol: str, start: str, end: str, timeframe: str, *, adjusted: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        multiplier, unit = self._range(timeframe)
        response = self.client.get(
            f"v2/aggs/ticker/{quote(symbol.upper(), safe=':')}/range/{multiplier}/{unit}/{start}/{end}",
            params={"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000, "apiKey": self.api_key},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") or []
        if not rows:
            raise ValueError(f"Massive returned no daily candles for {symbol}")
        normalized = []
        for row in rows:
            timestamp = datetime.fromtimestamp(int(row["t"]) / 1000, timezone.utc)
            normalized.append({
                "date": timestamp.date().isoformat(),
                "datetime": timestamp.isoformat(),
                "time": int(timestamp.timestamp()),
                "open": float(row["o"]),
                "high": float(row["h"]),
                "low": float(row["l"]),
                "close": float(row["c"]),
                "volume": float(row["v"]),
                "closed": True,
            })
        return payload, normalized

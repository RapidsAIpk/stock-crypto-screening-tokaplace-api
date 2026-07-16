from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from validation.fixture_store import FixtureStore
from validation.indicators import aroon_adapter, ema_adapter, macd_adapter, rsi_adapter
from validation.spec import ValidationSpec


def load_massive_candles(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_timestamps: set[str] = set()
    with (Path(path) / "candles.csv").open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            timestamp = raw["datetime"]
            if timestamp in seen_timestamps:
                raise ValueError(f"duplicate Massive candle timestamp: {timestamp}")
            seen_timestamps.add(timestamp)
            rows.append(
                {
                    "datetime": timestamp,
                    "date": raw["date"],
                    "time": int(raw["time"]),
                    "open": float(raw["open"]),
                    "high": float(raw["high"]),
                    "low": float(raw["low"]),
                    "close": float(raw["close"]),
                    "volume": float(raw["volume"]),
                    "segment": raw["segment"],
                }
            )
    rows.sort(key=lambda candle: candle["time"])
    return rows


class BackendIndicatorPipeline:
    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    def run(
        self,
        spec: ValidationSpec,
        massive_run_path: str | Path | None = None,
    ) -> dict[str, Any]:
        massive_path = Path(massive_run_path or self.store.massive_run_path(spec))
        self.store.verify_massive_run(massive_path)
        candles = load_massive_candles(massive_path)
        rows = [
            *rsi_adapter.calculate(candles, spec),
            *aroon_adapter.calculate(candles, spec),
            *macd_adapter.calculate(candles, spec),
            *ema_adapter.calculate(candles, spec),
        ]
        summary: dict[str, Any] = {}
        for indicator in ("rsi", "aroon", "macd", "ema"):
            indicator_rows = [row for row in rows if row["indicator"] == indicator]
            statuses = {row["status"] for row in indicator_rows}
            summary[indicator] = {
                "status": (
                    "insufficient_data"
                    if "insufficient_data" in statuses or not indicator_rows
                    else "calculated"
                ),
                "rows": len(indicator_rows),
            }
        result = {
            "run_id": spec.run_id,
            "source": "massive",
            "training_start": spec.training_start.isoformat(),
            "training_end": spec.training_end.isoformat(),
            "validation_start": spec.validation_start.isoformat(),
            "validation_end": spec.validation_end.isoformat(),
            "candle_count": len(candles),
            "summary": summary,
            "rows": rows,
        }
        result_path = self.store.write_result_once(
            spec,
            "backend_indicators.json",
            result,
        )
        return {"result_path": result_path, "result": result}

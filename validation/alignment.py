from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

from validation.fixture_store import FixtureStore
from validation.spec import ValidationSpec, canonical_utc_timestamp


PRICE_FIELDS = ("open", "high", "low", "close")


def _date_from_timestamp(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _load_twelve_candles(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads((path / "rsi" / "candles.raw.json").read_text("utf-8"))
    rows = payload.get("values") or []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = canonical_utc_timestamp(row.get("datetime"))
        if key in result:
            raise ValueError(f"duplicate Twelve candle timestamp: {key}")
        result[key] = row
    return result


def _load_massive_candles(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with (path / "candles.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = canonical_utc_timestamp(row["datetime"])
            if key in result:
                raise ValueError(f"duplicate Massive candle timestamp: {key}")
            result[key] = row
    return result


class CandleAlignmentAuditor:
    def __init__(
        self,
        store: FixtureStore,
        *,
        absolute_tolerance: float = 0.0,
        relative_tolerance: float = 0.0,
    ) -> None:
        self.store = store
        self.absolute_tolerance = max(0.0, float(absolute_tolerance))
        self.relative_tolerance = max(0.0, float(relative_tolerance))

    def audit(
        self,
        spec: ValidationSpec,
        twelve_run_path: str | Path,
        massive_run_path: str | Path,
    ) -> dict[str, Any]:
        twelve_path = Path(twelve_run_path)
        massive_path = Path(massive_run_path)
        self.store.verify_run(twelve_path)
        self.store.verify_massive_run(massive_path)
        twelve = _load_twelve_candles(twelve_path)
        massive = _load_massive_candles(massive_path)

        rows: list[dict[str, Any]] = []
        mismatch_count = 0
        validation_overlap = 0
        for timestamp in sorted(set(twelve) | set(massive)):
            candle_date = _date_from_timestamp(timestamp)
            if not spec.comparison_start <= candle_date <= spec.comparison_end:
                continue
            segment = "training" if candle_date <= spec.training_end else "validation"
            reference = twelve.get(timestamp)
            actual = massive.get(timestamp)
            if reference is None or actual is None:
                mismatch_count += 1
                rows.append(
                    {
                        "date": candle_date.isoformat(),
                        "timestamp": timestamp,
                        "segment": segment,
                        "status": "missing_twelve" if reference is None else "missing_massive",
                        "fields": {},
                    }
                )
                continue
            if segment == "validation":
                validation_overlap += 1

            field_results: dict[str, Any] = {}
            row_matches = True
            fields = (*PRICE_FIELDS, "volume") if "volume" in reference else PRICE_FIELDS
            for field in fields:
                expected = float(reference[field])
                observed = float(actual[field])
                matches = math.isclose(
                    expected,
                    observed,
                    rel_tol=self.relative_tolerance,
                    abs_tol=self.absolute_tolerance,
                )
                row_matches = row_matches and matches
                field_results[field] = {
                    "twelve": expected,
                    "massive": observed,
                    "absolute_difference": abs(expected - observed),
                    "matches": matches,
                }
            if not row_matches:
                mismatch_count += 1
            rows.append(
                {
                    "date": candle_date.isoformat(),
                    "timestamp": timestamp,
                    "segment": segment,
                    "status": "aligned" if row_matches else "value_mismatch",
                    "fields": field_results,
                }
            )

        if validation_overlap == 0:
            status = "insufficient_data"
        elif mismatch_count:
            status = "inconclusive_input_mismatch"
        else:
            status = "aligned"
        return {
            "run_id": spec.run_id,
            "status": status,
            "comparison_start": spec.comparison_start.isoformat(),
            "comparison_end": spec.comparison_end.isoformat(),
            "validation_start": spec.validation_start.isoformat(),
            "validation_end": spec.validation_end.isoformat(),
            "absolute_tolerance": self.absolute_tolerance,
            "relative_tolerance": self.relative_tolerance,
            "summary": {
                "twelve_rows": len(twelve),
                "massive_rows": len(massive),
                "validation_overlap_rows": validation_overlap,
                "mismatch_rows": mismatch_count,
            },
            "rows": rows,
        }

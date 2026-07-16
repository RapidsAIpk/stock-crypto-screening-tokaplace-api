from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from validation.fixture_store import FixtureStore
from validation.spec import ValidationSpec, canonical_utc_timestamp


REFERENCE_FIELDS = {
    "rsi": {"rsi": "rsi"},
    "aroon": {"aroon_oscillator": None},
    "macd": {
        "macd": "macd",
        "macd_signal": "macd_signal",
        "macd_hist": "macd_hist",
    },
    "ema": {"ema": "ema"},
}


def _date_value(raw: Any) -> str:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()


def _timestamp_value(raw: Any) -> str:
    return canonical_utc_timestamp(raw)


def _relative_tolerance_key(indicator: str, component: str) -> str:
    if indicator == "macd":
        suffix = {"macd": "macd", "macd_signal": "signal", "macd_hist": "hist"}[component]
        return f"macd.{suffix}.relative"
    return f"{indicator}.relative"


def _load_reference_component(
    twelve_path: Path,
    indicator: str,
    component: str,
    field: str | None,
    spec: ValidationSpec,
) -> dict[str, float]:
    payload = json.loads((twelve_path / indicator / "indicator.raw.json").read_text("utf-8"))
    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError(f"{indicator} reference has no values")
    output: dict[str, float] = {}
    for row in values:
        timestamp = _timestamp_value(row.get("datetime"))
        date_value = _date_value(row.get("datetime"))
        if not spec.validation_start.isoformat() <= date_value <= spec.validation_end.isoformat():
            continue
        if timestamp in output:
            raise ValueError(f"{indicator} reference has duplicate timestamp {timestamp}")
        if indicator == "aroon":
            value = float(row["aroon_up"]) - float(row["aroon_down"])
        else:
            value = float(row[field or component])
        if not math.isfinite(value):
            raise ValueError(f"{indicator}.{component} has a non-finite value at {timestamp}")
        output[timestamp] = value
    if not output:
        raise ValueError(f"{indicator}.{component} has no validation values")
    return output


class IndicatorComparator:
    def __init__(
        self,
        store: FixtureStore,
        *,
        tolerance_overrides: dict[str, float] | None = None,
    ) -> None:
        self.store = store
        self.tolerance_overrides = {
            str(key): float(value)
            for key, value in (tolerance_overrides or {}).items()
        }
        if any(value < 0 for value in self.tolerance_overrides.values()):
            raise ValueError("comparison tolerances cannot be negative")

    def _absolute_tolerance(
        self,
        spec: ValidationSpec,
        indicator: str,
        component: str,
        backend_row: dict[str, Any] | None,
    ) -> float:
        if indicator == "macd":
            suffix = {"macd": "macd", "macd_signal": "signal", "macd_hist": "hist"}[component]
            key = f"macd.{suffix}"
        else:
            key = indicator
        return float(
            self.tolerance_overrides.get(
                key,
                (backend_row or {}).get("tolerance", spec.tolerance.get(indicator, 0.0)),
            )
        )

    def _relative_tolerance(
        self,
        spec: ValidationSpec,
        indicator: str,
        component: str,
    ) -> float:
        key = _relative_tolerance_key(indicator, component)
        return float(self.tolerance_overrides.get(key, spec.tolerance.get(key, 0.0)))

    def compare(
        self,
        spec: ValidationSpec,
        twelve_run_path: str | Path | None = None,
    ) -> dict[str, Any]:
        twelve_path = Path(twelve_run_path or self.store.run_path(spec))
        self.store.verify_run(twelve_path)
        results_path = self.store.results_path(spec)
        alignment = json.loads((results_path / "candle_alignment.json").read_text("utf-8"))
        backend = json.loads((results_path / "backend_indicators.json").read_text("utf-8"))
        if alignment.get("run_id") != spec.run_id or backend.get("run_id") != spec.run_id:
            raise ValueError("comparison inputs do not match the validation run ID")

        backend_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        insufficient_by_indicator: set[str] = set()
        for row in backend.get("rows", []):
            if row.get("status") == "insufficient_data":
                insufficient_by_indicator.add(str(row.get("indicator")))
                continue
            timestamp = row.get("timestamp")
            if not timestamp:
                continue
            key = (str(row["indicator"]), str(row["component"]), str(timestamp))
            if key in backend_rows:
                raise ValueError(f"duplicate backend indicator row: {key}")
            backend_rows[key] = row

        comparison_rows: list[dict[str, Any]] = []
        summary: dict[str, Any] = {}
        reference_errors: dict[str, str] = {}
        for indicator, components in REFERENCE_FIELDS.items():
            indicator_rows: list[dict[str, Any]] = []
            for component, field in components.items():
                try:
                    reference = _load_reference_component(
                        twelve_path,
                        indicator,
                        component,
                        field,
                        spec,
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    reference_errors[indicator] = str(exc)
                    continue

                backend_component = {
                    timestamp: row
                    for (row_indicator, row_component, timestamp), row in backend_rows.items()
                    if row_indicator == indicator and row_component == component
                }
                for timestamp in sorted(set(reference) | set(backend_component)):
                    expected = reference.get(timestamp)
                    actual_row = backend_component.get(timestamp)
                    actual = actual_row.get("backend_value") if actual_row else None
                    absolute_tolerance = self._absolute_tolerance(
                        spec,
                        indicator,
                        component,
                        actual_row,
                    )
                    relative_tolerance = self._relative_tolerance(
                        spec,
                        indicator,
                        component,
                    )
                    if expected is None:
                        status = "reference_error"
                        absolute_difference = None
                        relative_difference = None
                    elif actual is None:
                        status = "insufficient_data"
                        absolute_difference = None
                        relative_difference = None
                    else:
                        actual = float(actual)
                        if not math.isfinite(actual):
                            absolute_difference = None
                            relative_difference = None
                            matches = False
                        else:
                            absolute_difference = abs(expected - actual)
                            relative_difference = (
                                absolute_difference / abs(expected)
                                if expected != 0
                                else (0.0 if absolute_difference == 0 else None)
                            )
                            matches = math.isclose(
                                expected,
                                actual,
                                rel_tol=relative_tolerance,
                                abs_tol=absolute_tolerance,
                            )
                        status = "pass" if matches else "fail"
                    indicator_rows.append(
                        {
                            "timestamp": timestamp,
                            "indicator": indicator,
                            "component": component,
                            "reference_value": expected,
                            "backend_value": actual,
                            "absolute_difference": absolute_difference,
                            "relative_difference": relative_difference,
                            "absolute_tolerance": absolute_tolerance,
                            "relative_tolerance": relative_tolerance,
                            "status": status,
                        }
                    )

            statuses = {row["status"] for row in indicator_rows}
            if indicator in reference_errors:
                verdict = "reference_error"
            elif indicator in insufficient_by_indicator or "insufficient_data" in statuses:
                verdict = "insufficient_data"
            elif alignment.get("status") == "inconclusive_input_mismatch":
                verdict = "inconclusive_input_mismatch"
            elif "reference_error" in statuses:
                verdict = "reference_error"
            elif "fail" in statuses:
                verdict = "fail"
            elif indicator_rows:
                verdict = "pass"
            else:
                verdict = "insufficient_data"

            differences = [
                row["absolute_difference"]
                for row in indicator_rows
                if row["absolute_difference"] is not None
            ]
            summary[indicator] = {
                "verdict": verdict,
                "rows": len(indicator_rows),
                "passed_rows": sum(row["status"] == "pass" for row in indicator_rows),
                "failed_rows": sum(row["status"] == "fail" for row in indicator_rows),
                "max_absolute_difference": max(differences) if differences else None,
                "reference_error": reference_errors.get(indicator),
            }
            comparison_rows.extend(indicator_rows)

        if alignment.get("status") == "inconclusive_input_mismatch":
            overall = "inconclusive_input_mismatch"
            earliest_stage = "candle_alignment"
        elif alignment.get("status") == "insufficient_data":
            overall = "insufficient_data"
            earliest_stage = "candle_alignment"
        elif any(item["verdict"] == "reference_error" for item in summary.values()):
            overall = "reference_error"
            earliest_stage = "reference_indicator"
        elif any(item["verdict"] == "insufficient_data" for item in summary.values()):
            overall = "insufficient_data"
            earliest_stage = "backend_indicator"
        elif any(item["verdict"] == "fail" for item in summary.values()):
            overall = "fail"
            earliest_stage = "indicator_comparison"
        else:
            overall = "pass"
            earliest_stage = None

        if earliest_stage == "candle_alignment":
            first_divergence = next(
                (
                    {"stage": "candle_alignment", **row}
                    for row in alignment.get("rows", [])
                    if row.get("status") != "aligned"
                ),
                None,
            )
        else:
            first_divergence = next(
                (
                    {"stage": "indicator_comparison", **row}
                    for row in comparison_rows
                    if row["status"] != "pass"
                ),
                None,
            )
        report = {
            "run_id": spec.run_id,
            "verdict": overall,
            "earliest_mismatch_stage": earliest_stage,
            "alignment_status": alignment.get("status"),
            "tolerance_overrides": self.tolerance_overrides,
            "validation_start": spec.validation_start.isoformat(),
            "validation_end": spec.validation_end.isoformat(),
            "summary": summary,
            "first_divergence": first_divergence,
            "rows": comparison_rows,
        }
        report_path = self.store.write_result(
            spec,
            "indicator_comparison.json",
            report,
        )
        return {"report_path": report_path, "report": report}

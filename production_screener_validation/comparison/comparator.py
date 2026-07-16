from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..contracts import CaseResult, ScreenerCase


def _earliest_stage(reference: dict[str, Any], symbols: set[str]) -> str:
    for symbol in sorted(symbols):
        evidence = reference.get("symbol_evidence", {}).get(symbol, {})
        for rule in evidence.get("rules", []):
            if not rule.get("passed", True):
                return str(rule.get("filter") or rule.get("indicator") or "indicator_rule")
    return "screener_composition"


class ScreenerComparator:
    def compare(
        self,
        case: ScreenerCase,
        reference: dict[str, Any],
        production: dict[str, Any] | None,
        *,
        reference_verdict: str | None = None,
        error: str | None = None,
    ) -> CaseResult:
        universe = set(case.symbols)
        expected = set(reference.get("expected_symbols", []))
        actual = set((production or {}).get("symbols", []))
        insufficient = set(reference.get("insufficient_data_symbols", []))
        if reference_verdict:
            verdict = reference_verdict
        elif reference.get("status") == "reference_error":
            verdict = "reference_error"
        elif insufficient:
            verdict = "insufficient_data"
        elif not production or production.get("status") != "evaluated":
            verdict = "production_error"
            error = error or (production or {}).get("error")
        elif len((production or {}).get("symbols", [])) != len(set((production or {}).get("symbols", []))):
            verdict = "production_error"
            error = "production returned duplicate symbols"
        elif expected == actual:
            verdict = "pass"
        else:
            verdict = "fail"
        comparable = reference_verdict is None and reference.get("status") == "evaluated" and production is not None
        missing = expected - actual if comparable else set()
        unexpected = actual - expected if comparable else set()
        earliest = None if verdict == "pass" else "reference" if reference_verdict else _earliest_stage(reference, missing | unexpected)
        evidence = reference.get("symbol_evidence", {})
        for result in (production or {}).get("results", []):
            symbol = str(result.get("symbol", "")).upper()
            if symbol in evidence:
                evidence[symbol]["production"] = {
                    "included": True,
                    "matched_indicators": result.get("matched_indicators", []),
                    "stickers": result.get("stickers", []),
                }
        return CaseResult(
            case_id=case.case_id,
            verdict=verdict,
            expected_symbols=sorted(expected),
            actual_symbols=sorted(actual),
            correctly_included=sorted(expected & actual) if comparable else [],
            correctly_excluded=sorted(universe - expected - actual) if comparable else [],
            missing_symbols=sorted(missing),
            unexpected_symbols=sorted(unexpected),
            insufficient_data_symbols=sorted(insufficient),
            earliest_mismatch_stage=earliest,
            symbol_evidence=evidence,
            error=error,
        )

    @staticmethod
    def as_dict(result: CaseResult) -> dict[str, Any]:
        return asdict(result)

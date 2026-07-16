from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contracts import ScreenerCase


def _indicator_summary(indicators: tuple[Any, ...]) -> list[str]:
    lines: list[str] = []
    for item in indicators:
        config = item.config
        if item.name == "rsi":
            lines.append(
                f"RSI({config['length']}): location={config['location']}, "
                f"direction={config.get('direction') or 'any'}, window={config['window']}"
            )
        elif item.name == "aroon":
            lines.append(
                f"Aroon({config['length']}): level={config['level']}, "
                f"direction={config.get('direction') or 'any'}, window={config['window']}"
            )
        elif item.name == "macd":
            lines.append(
                f"MACD({config['fast']},{config['slow']},{config['signal']}): rule={config['rule']}"
            )
        elif item.name == "ema":
            lines.append(f"EMA({config['length']}): rule={config['rule']}")
        else:
            lines.append(f"{item.name}: {json.dumps(config, sort_keys=True)}")
    return lines


def _format_rule_values(rule: dict[str, Any]) -> str:
    label = str(rule.get("indicator") or rule.get("filter") or "rule")
    values = rule.get("values") or {}
    if label == "rsi":
        return f"RSI = {values.get('rsi', 'n/a'):.2f}" if isinstance(values.get("rsi"), (int, float)) else str(values)
    if label == "macd":
        macd = values.get("macd")
        return f"MACD = {macd:.2f}" if isinstance(macd, (int, float)) else str(values)
    if label == "ema":
        price = values.get("price")
        ema = values.get("ema")
        if isinstance(price, (int, float)) and isinstance(ema, (int, float)):
            return f"close = {price:.2f}, EMA = {ema:.2f}"
    if label == "aroon":
        osc = values.get("aroon_oscillator")
        return f"Aroon oscillator = {osc:.2f}" if isinstance(osc, (int, float)) else str(values)
    return json.dumps(values, sort_keys=True)


def _symbol_status(symbol: str, result: dict[str, Any]) -> str:
    expected = symbol in result["expected_symbols"]
    actual = symbol in result["actual_symbols"]
    if expected and actual:
        return "INCLUDED (correct)"
    if expected and not actual:
        return "MISSING (production excluded it)"
    if not expected and actual:
        return "UNEXPECTED (production included it)"
    return "EXCLUDED (correct)"


def write_case_report(output_dir: str | Path, case: ScreenerCase, result: dict[str, Any]) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    case_id = case.case_id
    verdict = str(result["verdict"]).upper()
    match = result["expected_symbols"] == result["actual_symbols"]

    lines = [
        f"# {case_id}",
        "",
        f"**Verdict:** {verdict}" + (" — filters match production" if match and verdict == "PASS" else ""),
        "",
        "## Filter combo (all must pass — AND logic)",
        "",
    ]
    lines.extend(f"- {line}" for line in _indicator_summary(case.indicators))
    if case.evaluation_date:
        lines.append(f"- Evaluation date: `{case.evaluation_date}` (candles sliced to this day)")
    if case.description:
        lines.extend(["", f"_{case.description}_"])

    lines.extend(
        [
            "",
            "## Result summary",
            "",
            f"- **Expected symbols:** {', '.join(result['expected_symbols']) or 'none'}",
            f"- **Production symbols:** {', '.join(result['actual_symbols']) or 'none'}",
            f"- **Correctly included:** {', '.join(result['correctly_included']) or 'none'}",
            f"- **Missing (false negatives):** {', '.join(result['missing_symbols']) or 'none'}",
            f"- **Unexpected (false positives):** {', '.join(result['unexpected_symbols']) or 'none'}",
            f"- **Correctly excluded:** {', '.join(result['correctly_excluded']) or 'none'}",
            "",
            "## Per symbol",
            "",
        ]
    )

    for symbol in case.symbols:
        evidence = result.get("symbol_evidence", {}).get(symbol, {})
        lines.extend([f"### {symbol} — {_symbol_status(symbol, result)}", ""])
        rules = evidence.get("rules") or []
        if rules:
            lines.extend(["| Rule | Values | Pass? |", "|---|---|---|"])
            for rule in rules:
                label = str(rule.get("indicator") or rule.get("filter") or "rule")
                passed = "Yes" if rule.get("passed") else "No"
                lines.append(f"| {label} | {_format_rule_values(rule)} | {passed} |")
        else:
            lines.append("_No rule evidence available._")
        if evidence.get("error"):
            lines.append(f"\nError: `{evidence['error']}`")
        production = evidence.get("production")
        if production:
            lines.append(
                f"\nProduction: included={production.get('included')}, "
                f"matched={', '.join(production.get('matched_indicators') or []) or 'none'}"
            )
        lines.append("")

    if result.get("error"):
        lines.extend(["## Error", "", f"`{result['error']}`", ""])

    markdown_path = directory / f"{case_id}.md"
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", "utf-8")

    payload = {
        "case_id": case_id,
        "description": case.description,
        "fixture_id": case.fixture_id,
        "symbols": list(case.symbols),
        "filters": [item.name for item in case.indicators],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    json_path = directory / f"{case_id}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return {"markdown": markdown_path, "json": json_path}


def write_suite_summary(output_dir: str | Path, suite_id: str, results: list[dict[str, Any]]) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for item in results:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    failures = [item for item in results if item["verdict"] != "pass"]
    overall = "pass" if not failures else "fail"
    generated_at = datetime.now(timezone.utc).isoformat()

    summary = {
        "suite_id": suite_id,
        "generated_at": generated_at,
        "verdict": overall,
        "total_cases": len(results),
        "counts": counts,
        "cases": [
            {
                "case_id": item["case_id"],
                "verdict": item["verdict"],
                "expected_symbols": item["expected_symbols"],
                "actual_symbols": item["actual_symbols"],
                "missing_symbols": item["missing_symbols"],
                "unexpected_symbols": item["unexpected_symbols"],
            }
            for item in results
        ],
    }
    json_path = directory / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")

    lines = [
        f"# Production Screener Suite: {suite_id}",
        "",
        f"**Overall:** {overall.upper()}",
        f"**Generated:** {generated_at}",
        f"**Cases:** {len(results)} total — {counts.get('pass', 0)} pass, {len(failures)} not pass",
        "",
        "## All combos",
        "",
        "| Case | Verdict | Expected | Production | Missing | Unexpected |",
        "|---|---|---|---|---|---|",
    ]
    for item in results:
        lines.append(
            f"| {item['case_id']} | {item['verdict']} | "
            f"{', '.join(item['expected_symbols']) or 'none'} | "
            f"{', '.join(item['actual_symbols']) or 'none'} | "
            f"{', '.join(item['missing_symbols']) or '-'} | "
            f"{', '.join(item['unexpected_symbols']) or '-'} |"
        )
    lines.extend(["", "## Per-case files", ""])
    for item in results:
        lines.append(f"- `{item['case_id']}.md` — readable breakdown")
        lines.append(f"- `{item['case_id']}.json` — machine-readable")
    markdown_path = directory / "summary.md"
    markdown_path.write_text("\n".join(lines) + "\n", "utf-8")
    return {"json": json_path, "markdown": markdown_path}

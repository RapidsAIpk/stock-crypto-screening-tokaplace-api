from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_reports(output_dir: str | Path, suite_id: str, results: list[dict[str, Any]]) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for result in results:
        counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
    required_failures = [item for item in results if item.get("required", True) and item["verdict"] != "pass"]
    report = {
        "suite_id": suite_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "pass" if not required_failures else "fail",
        "counts": counts,
        "cases": results,
    }
    json_path = directory / "production_screener_report.json"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    lines = [f"# Production Screener Validation: {suite_id}", "", f"Overall verdict: **{report['verdict'].upper()}**", "", "| Case | Verdict | Missing | Unexpected | Earliest stage |", "|---|---|---|---|---|"]
    for item in results:
        lines.append(f"| {item['case_id']} | {item['verdict']} | {', '.join(item['missing_symbols']) or '-'} | {', '.join(item['unexpected_symbols']) or '-'} | {item['earliest_mismatch_stage'] or '-'} |")
    markdown_path = directory / "production_screener_report.md"
    markdown_path.write_text("\n".join(lines) + "\n", "utf-8")
    csv_path = directory / "production_screener_symbols.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "symbol", "expected", "actual", "classification"])
        writer.writeheader()
        for item in results:
            symbols = sorted(set(item["expected_symbols"]) | set(item["actual_symbols"]) | set(item["correctly_excluded"]))
            for symbol in symbols:
                expected = symbol in item["expected_symbols"]; actual = symbol in item["actual_symbols"]
                classification = "correct_inclusion" if expected and actual else "missing" if expected else "unexpected" if actual else "correct_exclusion"
                writer.writerow({"case_id": item["case_id"], "symbol": symbol, "expected": expected, "actual": actual, "classification": classification})
    return {"json": json_path, "markdown": markdown_path, "csv": csv_path}

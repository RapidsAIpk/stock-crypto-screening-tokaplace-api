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
        name = item.name
        if name == "wavetrend":
            lines.append(
                f"WaveTrend({config['channel_length']}/{config['average_length']}/{config['signal_length']}): "
                f"zone={config['zone']}, direction={config.get('direction') or 'any'}, window={config['window']}"
            )
        elif name == "lrc":
            lines.append(
                f"LRC({config['length']}): lines={config['lines']}, action={config['action']}, window={config['window']}"
            )
        elif name == "regression":
            lines.append(
                f"DW Regression({config['length']}): lines={config['lines']}, action={config['action']}, "
                f"window={config['window']}"
            )
        elif name == "linreg_candles":
            close_loc = config.get("close_location") or "any"
            lines.append(
                f"LinReg Candles({config['lr_length']}/{config['signal_smoothing']}): "
                f"position={config['price_position']}, close={close_loc}, window={config['window']}"
            )
        elif name == "trend":
            areas = config.get("areas") or []
            area_text = ", ".join(
                f"{block.get('area')}:{block.get('action')}" for block in areas if isinstance(block, dict)
            ) or "none"
            lines.append(f"Trend({config['length']}): {area_text}")
        elif name == "relative_volume":
            lines.append(
                f"Relative Volume({config['length']}): min_ratio={config['min_ratio']}"
            )
        elif name == "volatility":
            mode = config.get("mode", "range_avg")
            lines.append(
                f"Volatility({config['length']}, {mode}): band {config['min_pct']}-{config.get('max_pct', 'inf')}%"
            )
        else:
            lines.append(f"{name}: {json.dumps(config, sort_keys=True)}")
    return lines


def _format_sticker_values(sticker: dict[str, Any] | None) -> str:
    if not sticker:
        return "n/a"
    if "value" in sticker and len(sticker) == 1:
        return str(sticker["value"])
    parts: list[str] = []
    for key in ("condition", "decision", "name"):
        value = sticker.get(key)
        if value:
            parts.append(str(value))
    if not parts:
        return json.dumps(sticker, sort_keys=True)
    return " — ".join(parts)


def _format_candle(candle: dict[str, Any] | None) -> str:
    if not candle:
        return "n/a"
    date = candle.get("date") or "?"
    o = candle.get("open")
    h = candle.get("high")
    low = candle.get("low")
    c = candle.get("close")
    v = candle.get("volume")
    if all(isinstance(x, (int, float)) for x in (o, h, low, c)):
        text = f"{date} O={o:.2f} H={h:.2f} L={low:.2f} C={c:.2f}"
        if isinstance(v, (int, float)):
            text += f" V={v:,.0f}"
        return text
    return str(candle)


def write_production_case_report(
    output_dir: str | Path,
    case: ScreenerCase,
    result: dict[str, Any],
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    case_id = case.case_id
    passing = result.get("passing_symbols") or []

    lines = [
        f"# {case_id}",
        "",
        "**Source:** production screener (manual TradingView verification)",
        "",
        f"**Passing symbols:** {', '.join(passing) if passing else 'none'}",
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
            f"- **Production pass:** {', '.join(passing) if passing else 'none'}",
            f"- **Excluded:** {', '.join(result.get('excluded_symbols') or []) or 'none'}",
            "",
            "## Per symbol (for TradingView check)",
            "",
        ]
    )

    for symbol in case.symbols:
        evidence = result.get("symbol_evidence", {}).get(symbol, {})
        passed = evidence.get("passed")
        status = "PASS" if passed else "FAIL"
        lines.extend([f"### {symbol} — {status}", ""])
        lines.append(f"- Bar: {_format_candle(evidence.get('candle'))}")
        indicators = evidence.get("indicators") or []
        if indicators:
            lines.extend(["", "| Indicator | Pass? | Details |", "|---|---|---|"])
            for item in indicators:
                passed_text = "Yes" if item.get("passed") else "No"
                lines.append(
                    f"| {item.get('name')} | {passed_text} | {_format_sticker_values(item.get('sticker'))} |"
                )
        else:
            lines.append("_No indicator details._")
        if evidence.get("error"):
            lines.append(f"\nError: `{evidence['error']}`")
        lines.extend(["", "**TV check:** agree / disagree — _notes:_", ""])

    if result.get("errors"):
        lines.extend(["## Errors", ""])
        for error in result["errors"]:
            lines.append(f"- `{error}`")
        lines.append("")

    markdown_path = directory / f"{case_id}.md"
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", "utf-8")

    payload = {
        "case_id": case_id,
        "description": case.description,
        "fixture_id": case.fixture_id,
        "symbols": list(case.symbols),
        "filters": [item.name for item in case.indicators],
        "evaluation_date": case.evaluation_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    json_path = directory / f"{case_id}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    return {"markdown": markdown_path, "json": json_path}


def write_production_suite_summary(
    output_dir: str | Path,
    suite_id: str,
    results: list[dict[str, Any]],
) -> dict[str, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    summary = {
        "suite_id": suite_id,
        "generated_at": generated_at,
        "total_cases": len(results),
        "cases": [
            {
                "case_id": item["case_id"],
                "passing_symbols": item.get("passing_symbols") or [],
                "excluded_symbols": item.get("excluded_symbols") or [],
                "evaluation_date": item.get("evaluation_date"),
            }
            for item in results
        ],
    }
    json_path = directory / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", "utf-8")

    lines = [
        f"# Custom Indicator Suite: {suite_id}",
        "",
        f"**Generated:** {generated_at}",
        f"**Cases:** {len(results)}",
        "",
        "Manual TradingView verification — production pass lists only.",
        "",
        "## All combos",
        "",
        "| Case | Evaluation date | Passing symbols |",
        "|---|---|---|",
    ]
    for item in results:
        passing = ", ".join(item.get("passing_symbols") or []) or "none"
        eval_date = item.get("evaluation_date") or "latest"
        lines.append(f"| {item['case_id']} | {eval_date} | {passing} |")

    lines.extend(["", "## Per-case files", ""])
    for item in results:
        lines.append(f"- `{item['case_id']}.md`")
        lines.append(f"- `{item['case_id']}.json`")

    markdown_path = directory / "summary.md"
    markdown_path.write_text("\n".join(lines) + "\n", "utf-8")
    return {"json": json_path, "markdown": markdown_path}

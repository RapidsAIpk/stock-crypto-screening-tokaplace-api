from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.contracts import CaseSuite  # noqa: E402


INDICATOR_TV_META = {
    "wavetrend": {
        "title": "WaveTrend [LazyBear]",
        "pine_doc": "docs/pinescript/wavetrend.md",
        "tv_inputs": "channel_length=10, average_length=21, signal_length=4, threshold=±60",
        "gaps": "Single threshold only (no separate ±53 tier).",
    },
    "lrc": {
        "title": "Linear Regression Channel [jwammo12]",
        "pine_doc": "docs/pinescript/linear_regression_channel.md",
        "tv_inputs": "len=100, dev=2.0, src=close",
        "gaps": "Screener touch/window rules are backend-specific.",
    },
    "regression": {
        "title": "Regression Channel [DW]",
        "pine_doc": "docs/pinescript/regression_channel.md",
        "tv_inputs": "len=200, ndev=1.0, filt_type=SMA, continuous window",
        "gaps": "Interval mode uses UTC day reset, not Pine newbar(res). Close-only source.",
    },
    "linreg_candles": {
        "title": "Humble LinReg Candles",
        "pine_doc": "docs/pinescript/linear_regression_candle.md",
        "tv_inputs": "linreg_length=11, signal_length=11, sma_signal=true",
        "gaps": "Screener price_position rules vs chart candle colors.",
    },
    "trend": {
        "title": "Trend Channels With Liquidity Breaks [ChartPrime]",
        "pine_doc": "docs/pinescript/trend_channel.md",
        "tv_inputs": "length=8, ATR(10)×6 width",
        "gaps": "Liquidity label differs; regression fallback when pivots insufficient.",
    },
    "relative_volume": {
        "title": "RelVol (stocks)",
        "pine_doc": "docs/pinescript/relative_volumn.md",
        "tv_inputs": "SMA(volume, 10), ratio vs AvgVol[1]",
        "gaps": "RelVolForCEX USD conversion not ported.",
    },
    "volatility": {
        "title": "Volatility study",
        "pine_doc": "docs/pinescript/volatility.md",
        "tv_inputs": "mode=range_avg, length=20 (fixed bar window)",
        "gaps": "No calendar week/month bar search from time.",
    },
}


def _indicator_key(case_filters: list[str]) -> str:
    return case_filters[0] if case_filters else "unknown"


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def export_indicator_sheet(
    *,
    indicator: str,
    cases: list,
    reports_dir: Path,
    output_path: Path,
) -> None:
    meta = INDICATOR_TV_META.get(indicator, {})
    lines = [
        f"# {meta.get('title', indicator)} — TradingView checklist",
        "",
        "Compare production pass lists below against your TradingView charts.",
        "",
        "## Setup",
        "",
        "| Item | Value |",
        "|---|---|",
        "| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |",
        "| Timeframe | 1 day |",
        "| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |",
        f"| Pine reference | `{meta.get('pine_doc', 'docs/pinescript/comparison.md')}` |",
        f"| TV inputs | {meta.get('tv_inputs', 'see Pine doc')} |",
        f"| Known gaps | {meta.get('gaps', 'see comparison.md')} |",
        "",
        "## TV steps (each case)",
        "",
        "1. Open symbol on TradingView, 1D chart.",
        "2. Add the Pine indicator; match inputs above.",
        "3. Go to the evaluation date (or latest bar if none).",
        "4. Confirm whether the filter should pass for that symbol.",
        "5. Mark **agree** / **disagree** in the notes column.",
        "",
        "## Cases",
        "",
        "| Case | Description | Eval date | Passing (production) | TV agree? | Notes |",
        "|---|---|---|---|---|---|",
    ]

    for case in cases:
        report_path = reports_dir / "cases" / f"{case.case_id}.json"
        if not report_path.exists():
            lines.append(
                f"| {case.case_id} | {case.description or ''} | {case.evaluation_date or 'latest'} | _missing report_ | | |"
            )
            continue
        report = _load_report(report_path)
        passing = ", ".join(report.get("passing_symbols") or []) or "none"
        eval_date = case.evaluation_date or "latest"
        desc = (case.description or "").replace("|", "/")
        lines.append(f"| {case.case_id} | {desc} | {eval_date} | {passing} | | |")

    lines.extend(
        [
            "",
            "## Per-case detail files",
            "",
            f"Full OHLCV + sticker evidence: `{reports_dir.name}/cases/<case_id>.md`",
            "",
            "---",
            "",
            "*Generated for manual TradingView verification. Production output is the candidate answer.*",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export consolidated TradingView checklist markdown files.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=BACKEND / "production_screener_validation" / "cases" / "custom_indicators_minimal.json",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        required=True,
        help="Run output directory containing cases/*.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BACKEND.parent / "docs" / "pinescript" / "tv_validation",
    )
    args = parser.parse_args()

    suite = CaseSuite.from_json_file(args.cases)
    grouped: dict[str, list] = defaultdict(list)
    for case in suite.cases:
        key = case.indicators[0].name if case.indicators else "unknown"
        grouped[key].append(case)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for indicator, cases in sorted(grouped.items()):
        output_path = args.output_dir / f"{indicator}_minimal.md"
        export_indicator_sheet(
            indicator=indicator,
            cases=cases,
            reports_dir=args.reports_dir,
            output_path=output_path,
        )
        print(f"Wrote {output_path}")

    readme = args.output_dir / "README.md"
    readme.write_text(
        "\n".join(
            [
                "# TradingView manual validation",
                "",
                "Production screener pass lists for custom Pine-backed indicators.",
                "",
                "Workflow:",
                "",
                "1. Run `python backend/scripts/run_custom_indicator_suite.py`",
                "2. Export sheets: `python backend/scripts/export_tv_validation_sheets.py --reports-dir <run_dir>`",
                "3. Open the indicator checklist next to TradingView and mark agree/disagree.",
                "",
                "## Checklists",
                "",
                *[f"- [{INDICATOR_TV_META[k]['title']}](./{k}_minimal.md)" for k in sorted(INDICATOR_TV_META)],
                "",
                "See also: [comparison.md](../comparison.md), [fix_summary.md](../fix_summary.md).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Wrote {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

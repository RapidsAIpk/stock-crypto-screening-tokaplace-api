# RelVol (stocks) — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/relative_volumn.md` |
| TV inputs | SMA(volume, 10), ratio vs AvgVol[1] |
| Known gaps | RelVolForCEX USD conversion not ported. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| relvol_min_10 | Relative volume: min_ratio=1.0 | latest | AMD, NVDA | | |
| relvol_min_15 | Relative volume: min_ratio=1.5 | latest | none | | |
| relvol_min_20 | Relative volume: min_ratio=2.0 | latest | none | | |
| relvol_ofat_length_10 | Relative volume OFAT: length 10 | latest | AMD, NVDA | | |
| relvol_ofat_length_20 | Relative volume OFAT: length 20 | latest | AMD, NVDA | | |
| relvol_ofat_tolerance_5 | Relative volume OFAT: tolerance 5 | latest | AMD, NVDA | | |
| relvol_spike_20260601 | Relative volume walk-forward: min_ratio=1.5 on Jun 1 | 2026-06-01 | none | | |
| relvol_spike_20260602 | Relative volume walk-forward: min_ratio=1.5 on Jun 2 | 2026-06-02 | none | | |
| relvol_spike_20260630 | Relative volume walk-forward: min_ratio=1.5 on Jun 30 | 2026-06-30 | none | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

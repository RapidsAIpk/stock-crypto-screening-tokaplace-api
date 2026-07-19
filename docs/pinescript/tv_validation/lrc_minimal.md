# Linear Regression Channel [jwammo12] — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/linear_regression_channel.md` |
| TV inputs | len=100, dev=2.0, src=close |
| Known gaps | Screener touch/window rules are backend-specific. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| lrc_upper_touched | LRC core: upper touched | latest | none | | |
| lrc_upper_closedabove | LRC core: upper closed_above | latest | none | | |
| lrc_upper_closedbelow | LRC core: upper closed_below | latest | none | | |
| lrc_middle_touched | LRC core: middle touched | latest | none | | |
| lrc_middle_closedabove | LRC core: middle closed_above | latest | none | | |
| lrc_middle_closedbelow | LRC core: middle closed_below | latest | none | | |
| lrc_lower_touched | LRC core: lower touched | latest | none | | |
| lrc_lower_closedabove | LRC core: lower closed_above | latest | none | | |
| lrc_lower_closedbelow | LRC core: lower closed_below | latest | none | | |
| lrc_ofat_window_3 | LRC OFAT from middle/touched: window 3 | latest | none | | |
| lrc_ofat_tolerance_5 | LRC OFAT from middle/touched: tolerance 5 | latest | none | | |
| lrc_ofat_length_100 | LRC OFAT from middle/touched: length 100 | latest | none | | |
| lrc_ofat_touch_wick | LRC OFAT from middle/touched: touch wick | latest | none | | |
| lrc_upper_touch_20260601 | LRC walk-forward: upper touched on Jun 1 | 2026-06-01 | none | | |
| lrc_lower_touch_20260601 | LRC walk-forward: lower touched on Jun 1 | 2026-06-01 | none | | |
| lrc_upper_touch_20260602 | LRC walk-forward: upper touched on Jun 2 | 2026-06-02 | none | | |
| lrc_lower_touch_20260602 | LRC walk-forward: lower touched on Jun 2 | 2026-06-02 | none | | |
| lrc_upper_touch_20260630 | LRC walk-forward: upper touched on Jun 30 | 2026-06-30 | none | | |
| lrc_lower_touch_20260630 | LRC walk-forward: lower touched on Jun 30 | 2026-06-30 | none | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

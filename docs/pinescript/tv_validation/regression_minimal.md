# Regression Channel [DW] — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/regression_channel.md` |
| TV inputs | len=200, ndev=1.0, filt_type=SMA, continuous window |
| Known gaps | Interval mode uses UTC day reset, not Pine newbar(res). Close-only source. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| reg_upper_touch | DW Regression core: upper touched | latest | none | | |
| reg_middle_touch | DW Regression core: middle touched | latest | none | | |
| reg_lower_touch | DW Regression core: lower touched | latest | none | | |
| reg_q1_touch | DW Regression core: q1 touched | latest | none | | |
| reg_q3_touch | DW Regression core: q3 touched | latest | none | | |
| reg_ofat_filter_sma | DW Regression OFAT from middle/touched: filter sma | latest | none | | |
| reg_ofat_filter_ema | DW Regression OFAT from middle/touched: filter ema | latest | none | | |
| reg_ofat_window_3 | DW Regression OFAT from middle/touched: window 3 | latest | none | | |
| reg_ofat_width_1 | DW Regression OFAT from middle/touched: width 1 | latest | none | | |
| reg_ofat_length_200 | DW Regression OFAT from middle/touched: length 200 | latest | none | | |
| reg_upper_touch_20260601 | DW Regression walk-forward: upper touched on Jun 1 | 2026-06-01 | none | | |
| reg_q3_touch_20260601 | DW Regression walk-forward: q3 touched on Jun 1 | 2026-06-01 | none | | |
| reg_upper_touch_20260602 | DW Regression walk-forward: upper touched on Jun 2 | 2026-06-02 | none | | |
| reg_q3_touch_20260602 | DW Regression walk-forward: q3 touched on Jun 2 | 2026-06-02 | none | | |
| reg_upper_touch_20260630 | DW Regression walk-forward: upper touched on Jun 30 | 2026-06-30 | none | | |
| reg_q3_touch_20260630 | DW Regression walk-forward: q3 touched on Jun 30 | 2026-06-30 | none | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

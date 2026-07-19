# Trend Channels With Liquidity Breaks [ChartPrime] — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/trend_channel.md` |
| TV inputs | length=8, ATR(10)×6 width |
| Known gaps | Liquidity label differs; regression fallback when pivots insufficient. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| trend_top_line_closedabove | Trend core: top_line closed_above | latest | none | | |
| trend_top_line_touched | Trend core: top_line touched | latest | none | | |
| trend_middle_line_touched | Trend core: middle_line touched | latest | AMD | | |
| trend_bottom_line_closedbelow | Trend core: bottom_line closed_below | latest | none | | |
| trend_bottom_line_touched | Trend core: bottom_line touched | latest | none | | |
| trend_top_zone_closedabove | Trend core: top_zone closed_above | latest | none | | |
| trend_ofat_length_8 | Trend OFAT from top_line/closed_above: length 8 | latest | none | | |
| trend_ofat_wait_break_off | Trend OFAT from top_line/closed_above: wait break off | latest | none | | |
| trend_ofat_show_last | Trend OFAT from top_line/closed_above: show last | latest | none | | |
| trend_ofat_window_3 | Trend OFAT from top_line/closed_above: window 3 | latest | none | | |
| trend_bottom_touch_20260601 | Trend walk-forward: bottom_line touched on Jun 1 | 2026-06-01 | none | | |
| trend_bottom_touch_20260602 | Trend walk-forward: bottom_line touched on Jun 2 | 2026-06-02 | none | | |
| trend_bottom_touch_20260630 | Trend walk-forward: bottom_line touched on Jun 30 | 2026-06-30 | none | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

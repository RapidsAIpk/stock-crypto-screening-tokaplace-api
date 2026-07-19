# Humble LinReg Candles — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/linear_regression_candle.md` |
| TV inputs | linreg_length=11, signal_length=11, sma_signal=true |
| Known gaps | Screener price_position rules vs chart candle colors. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| linreg_above_any | LinReg core: above, close=any | latest | AMD, TSLA | | |
| linreg_above_bullish | LinReg core: above, close=bullish | latest | AMD, TSLA | | |
| linreg_above_bearish | LinReg core: above, close=bearish | latest | none | | |
| linreg_below_any | LinReg core: below, close=any | latest | AAPL, NVDA | | |
| linreg_below_bullish | LinReg core: below, close=bullish | latest | none | | |
| linreg_below_bearish | LinReg core: below, close=bearish | latest | AAPL, NVDA | | |
| linreg_touch_any | LinReg core: touch, close=any | latest | MSFT | | |
| linreg_touch_bullish | LinReg core: touch, close=bullish | latest | none | | |
| linreg_touch_bearish | LinReg core: touch, close=bearish | latest | MSFT | | |
| linreg_ofat_lr_len_11 | LinReg OFAT from above: lr len 11 | latest | AMD, TSLA | | |
| linreg_ofat_smooth_11 | LinReg OFAT from above: smooth 11 | latest | AMD, TSLA | | |
| linreg_ofat_ema_signal | LinReg OFAT from above: ema signal | latest | AMD, TSLA | | |
| linreg_ofat_window_3 | LinReg OFAT from above: window 3 | latest | AMD, TSLA | | |
| linreg_ofat_tolerance_5 | LinReg OFAT from above: tolerance 5 | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| linreg_above_20260601 | LinReg walk-forward: above on Jun 1 | 2026-06-01 | AAPL, AMD, MSFT | | |
| linreg_below_20260601 | LinReg walk-forward: below on Jun 1 | 2026-06-01 | NVDA | | |
| linreg_above_20260602 | LinReg walk-forward: above on Jun 2 | 2026-06-02 | AMD, MSFT, NVDA | | |
| linreg_below_20260602 | LinReg walk-forward: below on Jun 2 | 2026-06-02 | TSLA | | |
| linreg_above_20260630 | LinReg walk-forward: above on Jun 30 | 2026-06-30 | AMD, TSLA | | |
| linreg_below_20260630 | LinReg walk-forward: below on Jun 30 | 2026-06-30 | AAPL, NVDA | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

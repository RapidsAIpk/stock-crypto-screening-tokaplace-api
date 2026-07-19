# Volatility study — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/volatility.md` |
| TV inputs | mode=range_avg, length=20 (fixed bar window) |
| Known gaps | No calendar week/month bar search from time. |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| vol_range_avg | Volatility core: mode=range_avg | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_daily | Volatility core: mode=daily | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_ofat_length_20 | Volatility OFAT: length 20 | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_ofat_min_0_max_50 | Volatility OFAT: min 0 max 50 | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_ofat_min_2_max_100 | Volatility OFAT: min 2 max 100 | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_ofat_returns_std | Volatility OFAT: returns std | latest | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_band_20260601 | Volatility walk-forward: range_avg band 1-80 on Jun 1 | 2026-06-01 | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_band_20260602 | Volatility walk-forward: range_avg band 1-80 on Jun 2 | 2026-06-02 | AAPL, AMD, MSFT, NVDA, TSLA | | |
| vol_band_20260630 | Volatility walk-forward: range_avg band 1-80 on Jun 30 | 2026-06-30 | AAPL, AMD, MSFT, NVDA, TSLA | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

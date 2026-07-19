# WaveTrend [LazyBear] — TradingView checklist

Compare production pass lists below against your TradingView charts.

## Setup

| Item | Value |
|---|---|
| Symbols | AAPL, AMD, MSFT, NVDA, TSLA |
| Timeframe | 1 day |
| Evaluation window | 2026-06-01 → 2026-06-30 (some cases pin a single day) |
| Pine reference | `docs/pinescript/wavetrend.md` |
| TV inputs | channel_length=10, average_length=21, signal_length=4, threshold=±60 |
| Known gaps | Single threshold only (no separate ±53 tier). |

## TV steps (each case)

1. Open symbol on TradingView, 1D chart.
2. Add the Pine indicator; match inputs above.
3. Go to the evaluation date (or latest bar if none).
4. Confirm whether the filter should pass for that symbol.
5. Mark **agree** / **disagree** in the notes column.

## Cases

| Case | Description | Eval date | Passing (production) | TV agree? | Notes |
|---|---|---|---|---|---|
| wt_os_crossedup | WaveTrend core: oversold, crossed_up | latest | none | | |
| wt_os_crosseddown | WaveTrend core: oversold, crossed_down | latest | none | | |
| wt_os_turningup | WaveTrend core: oversold, turning_up | latest | none | | |
| wt_ob_crossedup | WaveTrend core: overbought, crossed_up | latest | none | | |
| wt_ob_crosseddown | WaveTrend core: overbought, crossed_down | latest | none | | |
| wt_ob_turningup | WaveTrend core: overbought, turning_up | latest | none | | |
| wt_os_ofat_threshold_53 | WaveTrend OFAT from oversold/crossed_up: threshold 53 | latest | none | | |
| wt_os_ofat_window_3 | WaveTrend OFAT from oversold/crossed_up: window 3 | latest | none | | |
| wt_os_ofat_confirmation_on | WaveTrend OFAT from oversold/crossed_up: confirmation on | latest | none | | |
| wt_os_ofat_channel_len_10 | WaveTrend OFAT from oversold/crossed_up: channel len 10 | latest | none | | |
| wt_os_ofat_avg_len_21 | WaveTrend OFAT from oversold/crossed_up: avg len 21 | latest | none | | |
| wt_os_xup_w1_20260601 | WaveTrend walk-forward: oversold crossed_up window=1 on Jun 1 | 2026-06-01 | none | | |
| wt_os_xup_w2_20260601 | WaveTrend walk-forward: oversold crossed_up window=2 on Jun 1 | 2026-06-01 | none | | |
| wt_os_xup_w3_20260601 | WaveTrend walk-forward: oversold crossed_up window=3 on Jun 1 | 2026-06-01 | none | | |
| wt_os_xup_w1_20260602 | WaveTrend walk-forward: oversold crossed_up window=1 on Jun 2 | 2026-06-02 | none | | |
| wt_os_xup_w2_20260602 | WaveTrend walk-forward: oversold crossed_up window=2 on Jun 2 | 2026-06-02 | none | | |
| wt_os_xup_w3_20260602 | WaveTrend walk-forward: oversold crossed_up window=3 on Jun 2 | 2026-06-02 | none | | |
| wt_os_xup_w1_20260630 | WaveTrend walk-forward: oversold crossed_up window=1 on Jun 30 | 2026-06-30 | none | | |
| wt_os_xup_w2_20260630 | WaveTrend walk-forward: oversold crossed_up window=2 on Jun 30 | 2026-06-30 | none | | |
| wt_os_xup_w3_20260630 | WaveTrend walk-forward: oversold crossed_up window=3 on Jun 30 | 2026-06-30 | none | | |

## Per-case detail files

Full OHLCV + sticker evidence: `all_minimal/cases/<case_id>.md`

---

*Generated for manual TradingView verification. Production output is the candidate answer.*

# Pine Script vs Backend — TradingView Accuracy Comparison

This document compares each Pine Script reference in `docs/pinescript/` against the production backend implementation.

**Status:** Backend parity fixes were applied on 2026-07-15. See [`fix_summary.md`](./fix_summary.md) for the implementation log.

**Legend**

| Parity | Meaning |
|--------|---------|
| **High** | Same formula and defaults; only minor float / warm-up differences |
| **Partial** | Core math aligned; known residual gaps remain |
| **Low** | Different algorithm; expect different values and pass/fail vs TV |

---

## Summary Matrix (post-fix)

| Pine doc | Pine script | Backend file(s) | Indicator key | Parity |
|----------|-------------|-------------------|---------------|--------|
| `wavetrend.md` | WaveTrend [LazyBear] | `backend/services/wavetrend.py` | `wavetrend` | **High** |
| `linear_regression_channel.md` | Linear Regression Channel [jwammo12] | `backend/services/regression_channels.py` (`compute_lrc_channel`) | `lrc` | **High** |
| `regression_channel.md` | Regression Channel [DW] | `backend/services/regression_channels.py` (`compute_dw_regression_channel`) | `regression` | **High** |
| `linear_regression_candle.md` | Humble LinReg Candles | `backend/services/linear_regression_candles.py` | `linreg_candles` | **High** |
| `trend_channel.md` | Trend Channels With Liquidity Breaks [ChartPrime] | `backend/services/trend_channels.py` | `trend` | **High** (geometry) / **Partial** (liquidity label) |
| `relative_volumn.md` | RelVol / RelVolForCEX | `backend/services/indicators.py` (`handle_relative_volume`) | `relative_volume` | **High** (stock) / **Partial** (CEX USD) |
| `volatility.md` | volatility study | `backend/services/indicators.py` (`handle_volatility`) | `volatility` | **Partial** |

Shared math primitives: `backend/services/pine_math.py`.

Handlers for all indicators are wired through `backend/services/indicators.py` and `backend/services/screener.py`.

Validation oracle: `backend/production_screener_validation/reference/custom_engine.py`.

---

## Residual gaps (not yet ported)

| Indicator | Remaining difference | Workaround |
|-----------|-------------------|------------|
| WaveTrend | Single `threshold`; Pine has 60 and 53 | Set `threshold: 53` for secondary level |
| DW Regression | Interval resets on UTC day, not Pine `newbar(res)` | Use `window_type: continuous` for closest match |
| DW Regression | Non-close `src` on TV | Backend uses close only |
| Trend Channel | Liquidity label algorithm differs | Break detection is price-only in both |
| Trend Channel | Regression fallback when pivots insufficient | Pine has no fallback |
| Relative Volume | `RelVolForCEX` USD conversion | Stock `RelVol` formula is ported |
| Volatility | Calendar week/month bar search from `time` | Use `mode: range_avg` with fixed `length` |
| Volatility | Legacy close-return std | Use `mode: returns_std` |
| All indicators | Screener rules (touch, confirmation, window) | Backend product layer beyond Pine charts |

---

## Recommended config (optional overrides)

| Indicator | Backend key | When to override |
|-----------|-------------|------------------|
| WaveTrend secondary zone | `wavetrend` | `{ "threshold": 53 }` |
| DW Regression EMA filter | `regression` | `{ "filter_type": "EMA" }` |
| LinReg EMA signal | `linreg_candles` | `{ "sma_signal": false }` |
| Volatility legacy metric | `volatility` | `{ "mode": "returns_std" }` |
| Volatility daily TR | `volatility` | `{ "mode": "daily", "length": 1 }` |

---

## Files referenced

| Path | Role |
|------|------|
| `docs/pinescript/wavetrend.md` | LazyBear WaveTrend Pine source |
| `docs/pinescript/linear_regression_channel.md` | jwammo12 LRC Pine source |
| `docs/pinescript/regression_channel.md` | Donovan Wall Regression Channel Pine source |
| `docs/pinescript/linear_regression_candle.md` | Humble LinReg Candles Pine source |
| `docs/pinescript/trend_channel.md` | ChartPrime trend channel Pine source |
| `docs/pinescript/relative_volumn.md` | RelVol Pine sources |
| `docs/pinescript/volatility.md` | Volatility study Pine source |
| `docs/pinescript/fix_summary.md` | Implementation changelog |
| `backend/services/pine_math.py` | Shared Pine math primitives |
| `backend/services/wavetrend.py` | WaveTrend computation + rules |
| `backend/services/regression_channels.py` | LRC + DW regression channels |
| `backend/services/linear_regression_candles.py` | LinReg candles computation + screener rules |
| `backend/services/trend_channels.py` | ChartPrime trend channel port |
| `backend/services/indicators.py` | Handlers: relative volume, volatility, registry |
| `backend/services/volume.py` | Volume spike (distinct from relative volume) |
| `backend/production_screener_validation/reference/custom_engine.py` | Validation oracle implementations |

---

*Updated after Pine parity implementation on 2026-07-15.*

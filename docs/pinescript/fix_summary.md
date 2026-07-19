# Pine Script Parity — Implementation Summary

This document records the backend changes made to align production indicators with the TradingView Pine references in `docs/pinescript/`.

Date: 2026-07-15

---

## New shared module

| File | Purpose |
|------|---------|
| `backend/services/pine_math.py` | Shared Pine primitives: EMA, SMA, RMA, LWMA, ALMA, VWMA, rolling `linreg`, jwammo12 LRC bands, Donovan Wall filtered regression, RelVol ratio, range/daily volatility |

---

## Changes by indicator

### 1. WaveTrend [LazyBear]

**Files:** `backend/services/wavetrend.py`

| Change | Before | After |
|--------|--------|-------|
| Zone default threshold | `35` | `60` (LazyBear `obLevel1` / `osLevel1`) |
| CI divide-by-zero | `epsilon` always added | `na` when deviation `<= 0` (Pine-like) |
| EMA / SMA | Custom warm-up | `pine_ema` / `pine_sma` from `pine_math.py` |

**Still configurable:** `threshold` (use `53` for secondary LazyBear level).

---

### 2. Linear Regression Channel [jwammo12]

**Files:** `backend/services/regression_channels.py`, `backend/production_screener_validation/reference/custom_engine.py`

| Change | Before | After |
|--------|--------|-------|
| Middle line | Full-window `polyfit` series | Rolling `linreg(close, len, 0)` |
| Bands | Parallel channel from residual `std` | Point-anchored `lrc ± deviation` using linreg slope from offset-1 diff |
| Deviation | Population std of polyfit residuals | RMS over window using jwammo12 formula |

---

### 3. Regression Channel [DW]

**Files:** `backend/services/regression_channels.py`, `pine_math.py`

| Change | Before | After |
|--------|--------|-------|
| Regression engine | OLS `np.polyfit` | Filtered correlation `lin_reg_filt` port |
| Std / width | `np.std(close) * coeff` | Filtered std: `sqrt(filt((y-filt(y))²)) * ndev` |
| Base filter | Not supported | `filter_type`: SMA (default), EMA, RMA, LWMA, ALMA, VWMA |
| Volume weighting | Not supported | VWMA path uses candle `volume` |

**Config added:** `filter_type` on `regression` indicator (default `"SMA"`).

**Remaining gap:** Interval mode still resets on UTC calendar day, not Pine `newbar(res)` with arbitrary resolution strings.

---

### 4. Humble LinReg Candles

**Files:** `backend/services/linear_regression_candles.py`, `backend/services/indicators.py`, `backend/services/screener.py`

| Change | Before | After |
|--------|--------|-------|
| OHLC regression | Close only | `linreg` on open, high, low, close |
| Signal default | SMA(7) | SMA(11) |
| Signal type | SMA only | `sma_signal` config: SMA or EMA |
| LinReg toggle | Always on | `lin_reg` config (default `true`) |
| Output shape | Shortened convolved array | Full-length series aligned to candles (`signal`, `bopen`, `bclose`, …) |
| Bullish/bearish | Raw `open` vs `close` | LinReg `bopen` vs `bclose` when available; `close_location: bullish/bearish` supported |

---

### 5. Trend Channels [ChartPrime]

**Files:** `backend/services/trend_channels.py`

| Change | Before | After |
|--------|--------|-------|
| Slope direction | Price compare (`last <= prev`) | `atan2(dy, dx)` for down/up channel triggers (matches Pine) |

**Unchanged (already ported):** pivot span, ATR(10)×6 width, offset/7 zones, price-only breaks.

**Remaining gap:** Liquidity label still uses simplified volume/range heuristics, not Pine WMA(21) percentile rank.

---

### 6. Relative Volume

**Files:** `backend/services/indicators.py`, `backend/services/screener.py`

| Change | Before | After |
|--------|--------|-------|
| Default lookback | 20 bars | 10 bars (Pine `ta.sma(volume, 10)`) |
| Ratio formula | `volume / mean(prior bars)` | `volume / AvgVol[1]` via `pine_relative_volume_ratio` |
| Default pass threshold | `min_ratio: 1.5` | `min_ratio: 1.0` |

**Remaining gap:** `RelVolForCEX` USD conversion not implemented.

---

### 7. Volatility study

**Files:** `backend/services/indicators.py`, `custom_engine.py`

| Change | Before | After |
|--------|--------|-------|
| Default formula | Close-to-close return `std` | Pine range average: `sum((H-L)/|L|*100/N)` |
| Modes | Single formula | `mode`: `range_avg` (default), `daily`, `returns_std` (legacy) |
| Daily mode | Not supported | True range / low on latest bar |

**Remaining gap:** Pine calendar week/month bar counting from `time` not implemented; use `length` as fixed bar-window substitute.

---

## Default parameter changes (breaking for unconfigured filters)

| Indicator key | Parameter | Old default | New default |
|---------------|-----------|-------------|-------------|
| `wavetrend` | `threshold` | 35 | 60 |
| `linreg_candles` | `signal_smoothing` | 7 | 11 |
| `relative_volume` | `length` | 20 | 10 |
| `relative_volume` | `min_ratio` | 1.5 | 1.0 |
| `volatility` | `mode` | (implicit returns std) | `range_avg` |
| `regression` | `filter_type` | (n/a) | `SMA` |

---

## Tests updated

| File | Notes |
|------|-------|
| `backend/tests/test_regression_channel_dw.py` | DW channel tests adapted for filtered regression + `nan` warm-up |
| `backend/tests/test_backend_services.py` | WaveTrend threshold, SMA finite comparison, volatility `returns_std` in legacy tests, regression `filter_type` mock |

**Verified:** `backend.tests.test_regression_channel_dw` + `backend.tests.test_backend_services.IndicatorMathTests` — 65 tests OK.

---

## Post-fix parity (summary)

| Indicator | Parity vs TradingView |
|-----------|----------------------|
| WaveTrend | **High** |
| LRC (jwammo12) | **High** |
| DW Regression | **High** (SMA default; other `filter_type` values supported) |
| LinReg Candles | **High** (screener rules remain backend-specific layer) |
| Trend Channel | **High** (core geometry); liquidity label partial |
| Relative Volume | **High** (stock RelVol); CEX USD not ported |
| Volatility | **Partial** (`range_avg` + `daily` modes; no calendar bar search) |

See `docs/pinescript/comparison.md` for the detailed before/after reference.

---

## Files touched

```
backend/services/pine_math.py                          (new)
backend/services/wavetrend.py
backend/services/linear_regression_candles.py
backend/services/regression_channels.py
backend/services/trend_channels.py
backend/services/indicators.py
backend/services/screener.py
backend/production_screener_validation/reference/custom_engine.py
backend/tests/test_regression_channel_dw.py
backend/tests/test_backend_services.py
docs/pinescript/comparison.md
docs/pinescript/fix_summary.md
```

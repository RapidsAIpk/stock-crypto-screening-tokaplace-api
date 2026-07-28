# Daily QA & Implementation Report: MACD and Volume Spikes

**Project:** Stock Screener TradingView Parity  
**Date:** 28 July 2026  
**Scope:** MACD and Volume Spikes [TFO] backend implementation, dynamic configuration handling, and TradingView validation

## Executive Summary

Today, the MACD indicator was validated successfully against TradingView across **13 confirmed filter combinations**, with **13 passed and 0 failed**, resulting in a **100% confirmed success rate**.

Volume Spikes [TFO] was also hardened and made dynamic. The backend now maps frontend settings to TradingView-equivalent TFO inputs, detects stale TradingView markers, supports configurable signal windows, and reports configuration mismatch warnings. Volume Spike parity validation remains pending until TradingView indicator inputs are manually aligned with frontend/backend settings.

## Objectives Completed

| Objective | Status | Notes |
|---|---|---|
| Match MACD backend logic with TradingView ChrisMoody MACD | ✅ Completed | EMA fast/slow, SMA signal, histogram, and cross rules implemented. |
| Ensure MACD crosses only pass on latest completed candle | ✅ Completed | Prevents old crossover signals from passing as fresh signals. |
| Replace static Volume Spike logic with TFO-style logic | ✅ Completed | Added local high/low, hammer/shooter, same-color, session, and SMA multiplier logic. |
| Make Volume Spike frontend settings dynamic | ✅ Completed | `length` maps to TFO `vol_ma`; `multiplier` maps to TFO `vol_x`. |
| Detect TradingView/frontend config mismatch | ✅ Completed | Backend returns warnings when effective settings differ from TradingView defaults. |
| Detect stale Volume Spike markers | ✅ Completed | Backend warns when TradingView shows an older marker outside the configured signal window. |
| Add regression coverage | ✅ Completed | MACD and Volume Spike rule behavior covered in tests. |

## Indicators Updated

| Indicator | File | Status | Key Update |
|---|---|---|---|
| MACD | `services/macd.py` | ✅ Completed | TradingView-style ChrisMoody MACD logic and latest-candle cross validation. |
| Volume Spikes [TFO] | `services/volume.py` | ✅ Completed | Dynamic TFO logic, alias mapping, signal window, warnings, and stale marker diagnostics. |

## MACD Implementation Summary

The MACD backend was aligned with the provided TradingView reference:

```text
fastMA = ema(close, fastLength)
slowMA = ema(close, slowLength)
macd   = fastMA - slowMA
signal = sma(macd, signalLength)
hist   = macd - signal
```

### MACD Rules Validated

| Rule | Backend Requirement |
|---|---|
| Bullish Cross | Previous completed candle `MACD <= Signal`, latest completed candle `MACD > Signal` |
| Bearish Cross | Previous completed candle `MACD >= Signal`, latest completed candle `MACD < Signal` |
| Above Zero | Latest completed candle `MACD > 0` |
| Above Signal | Latest completed candle `MACD >= Signal` |

## Volume Spikes Implementation Summary

The Volume Spikes backend now follows the TradingView TFO model more closely:

```text
vol_check = volume > sma(volume, vol_ma) * vol_x
result_bearish = valid_high and vol_check[1]
result_bullish = valid_low and vol_check[1]
```

### Frontend to TradingView Mapping

| Frontend Field | Backend JSON | TradingView Input |
|---|---|---|
| Average Length | `length` / `vol_ma` | Volume SMA Length |
| Spike Strength | `multiplier` / `vol_x` | Volume Multiplier |
| Tolerance % | `tolerance_pct` | Backend-only tolerance field |

### Volume Spike Dynamic Improvements

| Improvement | Status | Description |
|---|---|---|
| Alias normalization | ✅ Completed | `length` and `multiplier` dynamically normalize to TFO `vol_ma` and `vol_x`. |
| Latest completed candle handling | ✅ Completed | Default `window: 1` requires a fresh confirmed latest signal. |
| Signal window support | ✅ Completed | `window: N` allows intentionally matching recent confirmed signals. |
| Stale marker warning | ✅ Completed | Reports when TradingView shows an older marker outside the backend window. |
| Config mismatch warning | ✅ Completed | Reports when backend effective settings differ from TradingView defaults. |
| Required candle budgeting | ✅ Completed | Fetches enough history for SMA length plus signal window. |

## Issues Identified

| Issue | Root Cause | Status |
|---|---|---|
| MACD old crosses could be misread as latest crosses | Rule needed strict latest completed candle transition check | ✅ Fixed |
| MACD signal line mismatch | TradingView reference uses SMA signal, not EMA signal | ✅ Fixed |
| Volume Spike simple/static logic did not match TFO | Previous logic only compared recent volume to average | ✅ Fixed |
| Volume Spike frontend parameters did not appear in TradingView | TradingView inputs are independent/manual and stayed at defaults | ⚠️ Validation note |
| Visible TradingView dots were old signals | TradingView displays historical markers, while backend default checks latest signal | ✅ Diagnostic added |

## Confirmed MACD Validation Results

| Asset | Timeframe | Indicator | Combination | Rule | Result |
|---|---:|---|---|---|---|
| BMY | 1h | MACD | 18, 26, 9 | Bearish Cross | ✅ Pass |
| TFX | 1h | MACD | 18, 26, 9 | Bearish Cross | ✅ Pass |
| SARO | 5m | MACD | 18, 26, 9 | Bearish Cross | ✅ Pass |
| VG | 5m | MACD | 14, 22, 9 | Bullish Cross | ✅ Pass |
| RVLV | 5m | MACD | 14, 22, 9 | Bullish Cross | ✅ Pass |
| RVLV | 30m | MACD | 14, 22, 9 | Above Zero | ✅ Pass |
| AKBA | 30m | MACD | 14, 22, 9 | Above Zero | ✅ Pass |
| AWI | 30m | MACD | 14, 22, 9 | Above Zero | ✅ Pass |
| VVX | 1h | MACD | 12, 26, 9 | Bullish Cross | ✅ Pass |
| WGS | 1h | MACD | 12, 26, 9 | Bullish Cross | ✅ Pass |
| HRZN | 1h | MACD | 12, 26, 9 | Bullish Cross | ✅ Pass |
| TDAY | 1h | MACD | 12, 26, 9 | Bearish Cross | ✅ Pass |
| QCRH | 1h | MACD | 12, 26, 9 | Bearish Cross | ✅ Pass |

## Volume Spike Testing Observation

Visible Volume Spikes [TFO] signals were observed on TradingView charts, including:

```text
BJRI, BAH, CDTG, FHB, AMSF, ETHT
```

These cases were not included in the confirmed parity total because TradingView inputs were still using defaults:

```text
TradingView:
Volume Multiplier = 1.5
Volume SMA Length = 100
```

while frontend/backend test requests used values such as:

```text
Average Length = 20 or 24
Spike Strength = 2 or 4
```

## Validation Summary

| Metric | Result |
|---|---:|
| Confirmed MACD test cases executed | 13 |
| Confirmed MACD passed | 13 |
| Confirmed MACD failed | 0 |
| MACD success rate | **100%** |
| Volume Spike confirmed parity cases | ⚠️ Pending |
| Volume Spike implementation tests | ✅ Passed |

## Code Verification

| Check | Result |
|---|---|
| Python compile check | ✅ Passed |
| Focused MACD tests | ✅ Passed |
| Focused Volume Spike tests | ✅ Passed |
| Full `IndicatorMathTests` | ✅ 130/130 Passed |
| Screener smoke tests | ✅ 3/3 Passed |
| `git diff --check` | ✅ Passed, CRLF warnings only |

## Files Modified

```text
models/results.py
services/indicators.py
services/macd.py
services/screener.py
services/volume.py
tests/test_backend_services.py
MACD_fixes.md
MACD_Volume_spikes.md
```

## Key Technical Decisions

- MACD cross rules must use only the latest completed candle transition.
- MACD signal line must use SMA to match the ChrisMoody TradingView script.
- Volume Spike `length` and `multiplier` are accepted as frontend-friendly aliases and normalized to TFO `vol_ma` and `vol_x`.
- Volume Spike defaults remain TradingView-compatible, but custom frontend values must be matched manually in TradingView during validation.
- Visible historical TradingView markers do not imply latest-candle pass; backend now reports stale-signal warnings.

## Remaining Known Issues

| Item | Status | Notes |
|---|---|---|
| Volume Spike TradingView parity cases | ⚠️ Pending | Requires manual TradingView input alignment with frontend/backend values. |
| TradingView settings sync | ⚠️ Manual | Frontend/backend cannot automatically change TradingView indicator settings. |

## Next Steps

- Validate Volume Spike cases after setting TradingView inputs to match frontend/backend values.
- Add frontend helper text explaining the TradingView mapping:

```text
TradingView comparison:
Volume Multiplier = Spike Strength
Volume SMA Length = Average Length
```

- Continue collecting confirmed Volume Spike pass/fail cases after configuration alignment.

## Final Conclusion

MACD validation is complete and confirmed at **100% pass rate** for today’s 13 tested combinations.

Volume Spikes [TFO] backend implementation is now dynamic and hardened, but confirmed TradingView parity validation remains pending until TradingView inputs are manually changed to match frontend/backend settings.

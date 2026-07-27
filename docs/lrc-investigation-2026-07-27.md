# Linear Regression Channel (LRC) Investigation Report

Date: 2026-07-27

## Summary

This session investigated replacing the backend's Linear Regression Channel (LRC) implementation with a different reference Pine script, validated the result against real TradingView data, and then reverted the change on request. **Net effect on the repository: zero.** All files touched during the investigation are back to their pre-session state.

## Timeline

### 1. Requested replacement

The user provided the Pine Script source for **"Linear Regression Channel" by LonesomeTheBlue** (MPL-2.0) and asked for it to replace the backend's existing LRC implementation, which was based on a different, older script — **"Linear Regression Channel [jwammo12]"** (`docs/pinescript/linear_regression_channel.md`). That jwammo12 script contains an undefined variable (`n`) in its intercept/deviation formulas, and the backend's prior port (`jwammo12_channel` in `services/pine_math.py`) had guessed `n = length - 1` and additionally computed a per-bar *rolling* regression curve, rather than TradingView's actual behavior of fitting a single static line over the most recent `length` bars.

Files changed at this step:

- `services/pine_math.py` — replaced `jwammo12_channel()` with a new `linreg_channel()` function implementing the LonesomeTheBlue `get_channel()` algorithm: single OLS fit over the trailing `length` closes, closed-form intercept (`mid - slope*(length-1)/2`, algebraically equivalent to the script's `floor`/`mod` formula), and the deviation loop reproduced literally (including its `slope * (len - x) + intercept` term).
- `services/regression_channels.py` — `compute_lrc_channel()` updated to call `linreg_channel()`, now passing both `upper_dev` and `lower_dev` through (the old code only used `upper_dev` for both bounds).
- `production_screener_validation/reference/custom_engine.py` — the independent validation oracle's `lrc()` function updated to match, so oracle-vs-production comparisons would stay meaningful.
- `docs/pinescript/linear_regression_channel.md` — reference Pine source swapped from the jwammo12 script to the LonesomeTheBlue script.
- `docs/pinescript/comparison.md` — table entry and changelog note updated to reflect the new source.

Validation performed on this version before it was reverted:

- `tests/test_regression_channel_dw.py` (10/10 passed, including the exact-output-shape assertion).
- A synthetic check on perfectly linear input confirmed the vectorized implementation reproduced the Pine script's literal formula (including its known off-by-one deviation quirk) rather than a "corrected" version.
- An independent, unvectorized re-transcription of the Pine loop was cross-checked against the vectorized backend code using real daily candles for AAPL, AMD, MSFT, NVDA, and TSLA (from `production_screener_validation/data/fixtures/stocks_daily_2026_06_30_v1`) across three `length`/`upper_dev`/`lower_dev` combinations each — all 15 cases matched to 1e-6 precision.

### 2. Compared against TradingView (no code changes)

The user supplied a TradingView screenshot of `ADNT` (Adient plc) on the 1h timeframe with `LinReg 100 close 2 2` and a matching screener JSON config (`length: 100, upper_dev: 2, lower_dev: 2`).

Using cached real candle data already present in `data/market_data_cache.db` (symbol `ADNT`, timeframe `1h`, 270 candles), the (then-updated) `compute_lrc_channel()` was run and its output compared to the chart:

- The last cached candle (`2026-07-24 19:30:00 UTC`) matched the chart's crosshair position exactly, with an identical close price (`20.41`).
- Computed channel values at that bar (middle `20.44`, upper `21.24`, lower `19.65`, r `0.71`) were consistent with the chart once TradingView's "Extend Lines" projection past the last candle was accounted for.

No files were modified during this step.

### 3. Reverted on request

The user asked to revert the implementation change. Since none of the changes had been committed, this was done with:

```powershell
git checkout -- services/pine_math.py services/regression_channels.py production_screener_validation/reference/custom_engine.py docs/pinescript/linear_regression_channel.md docs/pinescript/comparison.md
```

This restored all five files to their exact original content (the `jwammo12`-based implementation). Confirmed via `git status` (clean for these paths) and by rerunning `tests/test_regression_channel_dw.py` (10/10 passed).

## Current State

`services/pine_math.py`, `services/regression_channels.py`, `production_screener_validation/reference/custom_engine.py`, `docs/pinescript/linear_regression_channel.md`, and `docs/pinescript/comparison.md` are byte-for-byte identical to their state before this session began. The backend's `lrc` indicator still uses the original `jwammo12_channel` rolling-regression implementation.

Unrelated, pre-existing working-tree changes from before this session (not touched here) remain in place:

- `services/vlr.py`
- `services/wavetrend.py`
- `tests/test_backend_services.py`

## Open Question For Follow-Up

The underlying concern that prompted the original request is still unresolved: the current `jwammo12_channel` implementation is a rolling per-bar regression curve, not a match for how TradingView's built-in-style Linear Regression Channel studies typically render (a single static channel refit from the most recent `length` bars). If accuracy against TradingView is still a goal, this is worth revisiting — either by re-applying the LonesomeTheBlue port from this session or another agreed-upon reference implementation.

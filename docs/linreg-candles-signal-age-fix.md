# Linear Regression Candles Signal Age Fix Report

Date: 2026-07-22

## Summary

The Linear Regression Candles filter was allowing symbols to pass when the configured `window` value meant "signal happened within the last N candles" instead of the client-expected meaning: "the current signal age is exactly N candles."

The issue was reproduced with QCRH on the 1 day timeframe using:

```json
{
  "name": "linreg_candles",
  "config": {
    "lr_length": 11,
    "signal_smoothing": 11,
    "sma_signal": true,
    "lin_reg": true,
    "price_position": "above",
    "close_location": "any",
    "tolerance_pct": 0,
    "window": 1,
    "confirmation": false
  }
}
```

In that case, both the July 20 and July 21 completed Linear Regression Candles were above the signal line. With `window = 1`, this should fail because the active signal age is 2 candles, not exactly 1.

## Correct Semantics

For continuous state positions:

- `above`
- `below`
- `on`

`window = N` now means the current active state must have started exactly N completed Linear Regression Candles ago.

Examples:

- `window = 1`: latest completed candle matches, previous candle does not match.
- `window = 2`: latest two completed candles match, candle before them does not match.
- `window = 3`: latest three completed candles match, candle before them does not match.

For event positions:

- `piercing_from_below`
- `piercing_from_above`

`window = N` now means the piercing event happened exactly N completed candles ago, using one-based age:

- `window = 1`: piercing happened on the latest completed candle.
- `window = 2`: piercing happened on the previous completed candle.

Piercing is treated as a discrete event, not as a continuous streak.

## Root Causes Fixed

### 1. Window Was Too Permissive

File: `services/linear_regression_candles.py`

Previous behavior:

The backend passed when `signal_age <= window`.

Risk:

This allowed a younger signal to pass larger windows and made the field behave like "within N candles" instead of "exactly N candles since signal."

Fix:

The evaluator now uses one shared matcher, `_linreg_signal_match`, and continuous state rules pass only when:

```python
signal_age == window
```

### 2. Piercing Was Mixed With Streak Logic

File: `services/linear_regression_candles.py`

Previous risk:

Piercing actions could be interpreted through latest-candle or continuous-state logic.

Fix:

`piercing_from_below` and `piercing_from_above` are now handled separately through `PIERCING_RULES`. The backend checks only the exact candidate candle:

```python
candle_idx = latest_index - window + 1
```

If that exact candle is not a piercing event, the filter fails.

### 3. Evidence Could Point At The Wrong Candle

File: `services/linear_regression_candles.py`

Previous risk:

Sticker/evidence helpers could fall back to the latest candle even when the actual matching event was older.

Fix:

`_latest_matching_linreg_index` now uses `_linreg_signal_match`, so evidence and stickers point to the same candle that actually made the rule pass.

### 4. Reference Validation Did Not Match Backend Logic

Files:

- `production_screener_validation/reference/custom_engine.py`
- `production_screener_validation/reference/rule_engine.py`

Previous behavior:

The reference validator only returned `line` and `bclose` for Linear Regression Candles and did not fully model all five position actions with transformed OHLC.

Risk:

Production validation could disagree with the backend, especially for `above`, `below`, `on`, and piercing rules that require transformed open/high/low/close.

Fix:

The reference engine now calculates and returns:

- `bopen`
- `bhigh`
- `blow`
- `bclose`
- `line`

The reference rule engine now applies the same exact-age semantics and supports:

- `above`
- `below`
- `on`
- `piercing_from_below`
- `piercing_from_above`

### 5. Daily Candle Closure Was Wrong

File: `services/market_data.py`

Confirmed bug:

For stock daily candles, the provider timestamp represents the market session close time. The old backend added another 24 hours before marking that candle closed.

Example:

QCRH July 21 daily candle had timestamp `2026-07-21 20:00:00 UTC`. At `2026-07-22 07:47:19 UTC` or `2026-07-22 09:47:19 UTC`, that candle should already be treated as closed. The old logic could still mark it as forming until `2026-07-22 20:00:00 UTC`.

Risk:

The evaluator could skip the latest completed daily stock candle and evaluate the wrong candle for the Linear Regression Candles filter.

Fix:

`_mark_unclosed_last_candle` now accepts `symbol` and `candles_provider`, and uses provider-aware daily timestamp semantics.

Daily candles are treated as close-stamped when:

- The symbol is a stock.
- The symbol is crypto and the candle provider is Massive/Polygon.

Those candles are closed once:

```text
now >= last_time
```

Binance crypto daily candles are still treated as open-stamped klines, because Binance kline timestamps are the candle open time. Those remain open until:

```text
now >= last_time + 1 day
```

Cached payloads are also refreshed through `_refresh_payload_candle_closed_state`, so stale `is_closed: false` markers are removed once the candle is actually closed.

## QCRH Result After Fix

For QCRH daily after applying the corrected semantics:

- July 21 completed candle is included.
- July 20 and July 21 both match `price_position = above`.
- Current signal age is 2 candles.
- Configured `window = 1`.
- Result: fail.

The diagnostic reason is:

```text
signal age 2 exceeds configured candles 1 (started too early)
```

This matches the client expectation: `window = 1` should pass only when the signal starts on the latest completed candle.

## Logical Note: `on` vs `piercing_from_below`

It is logically acceptable for `on` and `piercing_from_below` to return the same stock under the current definitions.

Current definitions:

- `on`: the transformed candle body overlaps the signal line.
- `piercing_from_below`: the transformed candle opens at/below the line and closes at/above the line.

With `tolerance_pct = 0`, a valid bullish piercing from below necessarily overlaps the line, so it can also satisfy `on`.

This is not a backend bug unless the product requirement is that these categories must be mutually exclusive. If mutual exclusivity is desired, `on` should be redefined as "touches or rests on the line without crossing it."

## Tests Added Or Updated

File: `tests/test_backend_services.py`

Coverage added/updated for:

- Exact signal age for continuous Linear Regression Candle states.
- `window = 1` fails when a state has already lasted 2 or more candles.
- `above`, `below`, `on`, `piercing_from_below`, and `piercing_from_above`.
- Piercing exact event age.
- One-based off-by-one boundaries.
- Evidence using the actual confirmed match.
- Virtual Linear Regression Candle OHLC instead of raw candle OHLC.
- `on` with zero tolerance rejecting near misses.
- Forming candle exclusion.
- Stock daily candle close timestamp behavior.
- Massive/Polygon crypto daily candle close timestamp behavior.
- Binance crypto daily candle open timestamp behavior.
- Cached daily stock payload cleanup.
- Cached daily Massive/Polygon crypto payload cleanup.

File: `tests/unit/test_production_screener_validation.py`

Coverage added/updated for:

- Reference validator support for transformed Linear Regression OHLC.
- All five position actions.
- Exact window age mismatch failures.
- Zero-tolerance `on` behavior.
- Ignoring forming candles.

## Verification

Targeted verification command:

```powershell
python -m pytest tests/test_backend_services.py -k "linreg or stock_daily_close_timestamp or massive_crypto_daily_close_timestamp or binance_crypto_daily_start_timestamp or cached_stock_daily_payload or cached_massive_crypto_daily_payload" tests/unit/test_production_screener_validation.py -q
```

Result:

```text
20 passed, 253 deselected, 18 subtests passed
```

Syntax verification:

```powershell
python -m py_compile services/linear_regression_candles.py services/market_data.py production_screener_validation/reference/custom_engine.py production_screener_validation/reference/rule_engine.py
```

Result: passed.

Whitespace verification:

```powershell
git diff --check
```

Result: passed, with only existing CRLF normalization warnings reported by Git.

## Deployment Note

The changes are local source changes. For the live backend to use this behavior, the backend process must be restarted or redeployed with these modified files.

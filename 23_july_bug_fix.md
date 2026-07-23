# Tokaplace Screener — 23 July 2026 Bug Fix Report

> **Focus:** Universal timeframe handling, TradingView-aligned stock candles, cache safety, candle validation, and Trend Channel diagnostics  
> **Status:** Core fixes completed and validated with focused automated tests  
> **Scope:** Backend only

---

## Executive Summary

Today’s work focused on fixing the underlying causes of inconsistent screener and Trend Channel results across different assets and timeframes.

The main issue was not limited to one stock or only the `1h` timeframe. Multiple parts of the market-data pipeline were independently parsing timeframes, calculating candle boundaries, determining completed candles, and validating cached data. This caused equivalent requests to behave differently and allowed incorrectly aligned candles to reach the indicators.

The implementation now uses consistent timeframe handling, correct US regular-session candle boundaries, accurate candle close times, stronger cache compatibility checks, and safer provider-data normalization.

No asset-specific workaround was added, and Trend Channel calculations were not changed simply to force more matches.

---

## 1. Root Causes Identified

### 1.1 Timeframe parsing was inconsistent

The previous parser lowercased the complete timeframe value before interpreting it.

This created a collision between:

```text
1m = one minute
1M = one month
```

As a result, a monthly request could be interpreted as a one-minute request.

Unknown or invalid timeframes could also silently fall back to daily behavior instead of being rejected clearly.

---

### 1.2 Candle close and freshness calculations used fixed durations

Several functions independently calculated a candle close time using:

```text
candle start + fixed timeframe seconds
```

This was incorrect for:

- Calendar months with 28, 29, 30, or 31 days
- Weekly and multi-day calendar boundaries
- US stock session candles
- Short final regular-session buckets

For example, the final regular-session `1h` stock candle is:

```text
15:30–16:00 America/New_York
```

It is only 30 minutes long and must close at `16:00`, not `16:30`.

---

### 1.3 Equivalent timeframe aliases were not canonicalized

Equivalent values such as:

```text
1D
1day
```

could reach different cache rows and different code paths because raw request strings were used directly.

This could cause two logically identical requests to return different data.

---

### 1.4 Stock candles were not always aligned to the market session

Some regular-session stock candles were being returned with timestamps such as:

```text
13:42, 14:42, 15:42 ... 19:42 UTC
```

TradingView regular-session candles should be anchored to the US market open:

```text
09:30 America/New_York
```

For the summer US session, correct `1h` candle starts are:

```text
13:30, 14:30, 15:30 ... 19:30 UTC
```

Incorrect candle timestamps changed:

- OHLC values
- Pivot locations
- ATR calculations
- Trend Channel boundaries
- Final PASS/FAIL results

---

### 1.5 Old incompatible candles could remain in cache

Previously generated candles with incorrect alignment could still be treated as compatible and reused after code changes.

This made it possible for a corrected backend to continue serving old misaligned data.

---

## 2. Code Changes Completed

### 2.1 Added universal timeframe parsing and canonicalization

Timeframe handling now correctly supports standard and custom values, including:

```text
1m, 3m, 5m, 15m, 30m, 45m
1h, 2h, 4h
1D, 1W, 1M
7m, 11h, 6d, 2w, 5mo
```

Key improvements:

- `1m` and `1M` are treated differently
- Equivalent aliases resolve to one canonical value
- Invalid values are rejected with a clear warning
- Unknown values no longer silently become `1day`

---

### 2.2 Centralized candle-boundary calculation

A single reusable boundary resolver now determines when candles close.

It supports:

- Fixed-duration intraday candles
- US regular-session stock buckets
- Calendar days
- ISO weeks
- Calendar months
- Multi-day, multi-week, and multi-month intervals

This removes inconsistent close-time logic from multiple parts of the pipeline.

---

### 2.3 Corrected US stock session alignment

Regular-session stock intraday candles are now anchored to:

```text
09:30–16:00 America/New_York
```

The implementation uses:

```python
ZoneInfo("America/New_York")
```

This prevents hardcoded UTC offsets and automatically handles daylight-saving changes.

Examples:

#### `1h`

```text
09:30–10:30
10:30–11:30
11:30–12:30
12:30–13:30
13:30–14:30
14:30–15:30
15:30–16:00
```

#### `4h`

```text
09:30–13:30
13:30–16:00
```

The same session-anchoring approach is reusable for supported custom intraday intervals.

---

### 2.4 Unified forming and completed candle handling

The backend now uses the real bucket end time to decide whether a candle is complete.

This prevents:

- Completed candles from being incorrectly marked as forming
- Forming candles from being used as confirmed indicator signals
- Final shortened stock-session candles from remaining open too long

Trend Channel continues to evaluate completed candles only.

---

### 2.5 Added cache alignment protection

Market-data payloads now include a candle-alignment version.

Cached data is rejected when it was created using an incompatible alignment method.

Cache compatibility now considers the relevant combination of:

- Symbol
- Provider
- Canonical timeframe
- Session policy
- Candle-alignment version

This prevents old `:42`-aligned stock candles from being reused after the fix.

---

### 2.6 Added candle-data sanitization

Provider candles are now validated before reaching indicators.

The backend now:

- Sorts candles by timestamp
- Deduplicates repeated timestamps
- Rejects malformed OHLC rows
- Validates `low <= open/close <= high`
- Handles missing volume safely
- Logs invalid rows instead of silently using them

This reduces incorrect indicator results caused by malformed provider data.

---

### 2.7 Removed duplicate and inconsistent timeframe logic

The update removed or replaced duplicate logic such as:

- Independent timeframe fallback dictionaries
- Fixed module-level timeframe duration maps
- Duplicate candle aggregation helpers
- Separate hand-written candle closure paths
- Silent invalid-timeframe fallbacks

The market-data flow now relies on one shared timeframe interpretation.

---

## 3. Trend Channel Investigation

The complete Trend Channel flow was reviewed:

```text
Frontend configuration
→ timeframe parsing
→ market-data retrieval
→ cache validation
→ candle normalization
→ stock-session alignment
→ completed-candle selection
→ channel calculation
→ line/zone rule evaluation
→ details-panel evidence
```

### Findings

The earlier timestamp mismatch was a real backend data issue and has been corrected.

Many remaining Trend Channel failures are valid because the configured rules are strict.

Example:

```text
Top Line
Wick Touch
Latest 1 Candle
0% Tolerance
```

This requires the latest completed candle to touch the exact line. Being close to the line or entering the colored zone is not enough.

Similarly:

```text
Top Zone
Entered by Wick
Latest 2 Candles
0.02% Tolerance
```

requires one of the latest two completed candles to overlap the actual top-zone boundaries.

The implementation was not changed merely to force more PASS results.

---

## 4. TradingView Comparison Improvements

The backend now allows comparisons using the same session-aligned candle timestamp as TradingView.

Example corrected final US regular-session `1h` candle:

```text
7/22/2026, 7:30 PM UTC
```

This represents:

```text
3:30 PM–4:00 PM America/New_York
```

Previous incorrect examples such as `7:35 PM`, `7:40 PM`, and `7:42 PM` were caused by misaligned candle timestamps.

The correct validation order is now:

```text
Timestamp
→ OHLC
→ Channel boundary
→ Rule result
```

---

## 5. Files Changed

Main implementation and test files involved:

```text
services/market_data.py
services/stock_session.py
tests/test_timeframe_pipeline.py
tests/test_stock_session_anchoring.py
tests/test_stock_session.py
tests/test_price_lag_diagnostics.py
tests/test_backend_services.py
```

Trend Channel formula files were not changed merely to increase the number of matches.

---

## 6. Automated Test Results

### Focused tests

```text
Timeframe pipeline:              34 passed
Stock session anchoring:         39 passed
Price-lag diagnostics:           46 passed
Market-data integration/worker:  71 passed
```

### Wider backend suite

```text
464 passed
7 failed
```

The seven remaining failures are outside the new timeframe and candle-alignment flow. They relate to older test expectations involving:

- Asset metadata normalization
- Legacy Trend Channel fixtures
- Older channel-history expectations
- API response serialization expectations

The focused tests for the new implementation passed successfully.

---

## 7. Supported Behavior After the Fix

### Stocks, regular session

Correct session-aware handling now applies to supported and custom intraday timeframes such as:

```text
1m, 3m, 5m, 15m, 30m, 45m
1h, 2h, 4h
```

### Calendar timeframes

Correct calendar boundaries now apply to:

```text
1D, 1W, 1M
```

### Crypto

Crypto remains continuous and is not restricted to US stock market hours.

### Extended hours

Existing pre-market, after-hours, and extended-session behavior remains separate from regular-session alignment.

---

## 8. Remaining Limitations

### Refresh scheduling

The authoritative candle completion and freshness logic is corrected.

Some background refresh scheduling for session-anchored custom stock timeframes may still use a general cadence rather than the exact next market-session bucket boundary. This is a polling-efficiency limitation, not a candle-correctness issue.

### TradingView feed differences

The backend uses Massive market data, while TradingView may use a different or consolidated exchange feed.

Small OHLC differences can still occur even when timestamps and sessions match exactly.

### Minimum-tick parity

Exact TradingView channel values may differ slightly in borderline cases if TradingView applies instrument-specific minimum-tick rounding and equivalent metadata is unavailable in the backend.

No fixed `$0.01` assumption was introduced.

---

## 9. Final Status

| Area | Status |
|---|---|
| Universal timeframe parsing | ✅ Completed |
| `1m` versus `1M` collision | ✅ Fixed |
| Invalid timeframe fallback | ✅ Fixed |
| Stock RTH timestamp alignment | ✅ Fixed |
| DST handling | ✅ Fixed |
| Final shortened session candle | ✅ Fixed |
| Calendar week/month closure | ✅ Fixed |
| Cache compatibility | ✅ Improved |
| Candle sanitization | ✅ Added |
| Crypto behavior | ✅ Preserved |
| Daily/weekly/monthly behavior | ✅ Preserved |
| Trend Channel forced matches | ✅ Avoided |
| Focused automated validation | ✅ Passed |

---

## Summary for Senior Review

> Today I completed a universal market-data and timeframe correction for the screener. The fix resolves incorrect timeframe parsing, misaligned US stock candles, inaccurate candle completion times, stale incompatible cache entries, and malformed provider candle handling.
>
> The solution is not limited to one asset or only the `1h` timeframe. It supports standard and custom intraday intervals as well as daily, weekly, and monthly candles while preserving crypto and extended-session behavior.
>
> Trend Channel was validated against the corrected data flow. The previous timestamp mismatch was a real backend issue, while many remaining failures are correct outcomes of strict line/zone search conditions rather than new defects.
>
> All focused timeframe, session, cache, and market-data tests passed.

---

**Date:** 23 July 2026  
**Work type:** Backend bug fixing, market-data consistency, Trend Channel validation  
**Commit status:** Local changes only, not committed or pushed

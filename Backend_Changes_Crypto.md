# Backend Changes — Crypto Project

**Date:** 20 July 2026

## Summary

Today, I fixed the backend market-data flow so historical candle requests return complete, fresh, and correctly labeled data.

## Changes Made

### 1. Historical Candle Retrieval

- Fixed the issue where a request for 20 candles could return only one candle.
- Prevented incomplete cached data from satisfying larger historical requests.
- Ensured `latest_only=False` uses the historical candle path instead of quote or snapshot logic.
- Preserved all candles through normalization, sorting, deduplication, and response construction.

### 2. Massive/Polygon Provider Limit

- Corrected the provider-limit calculation for custom hourly candles.
- Updated the logic so the limit accounts for minute-level base aggregates.
- Added proper scaling for `1h` and `4h` requests.
- Kept the maximum provider limit capped at `50,000`.

### 3. Stock Historical Window

- Expanded the date window used for intraday stock requests.
- Added enough coverage for closed market hours, weekends, holidays, and session gaps.
- Kept crypto windows smaller because crypto trades continuously.

### 4. Stale Cache Protection

- Disabled silent stale-data fallback by default.
- Added optional stale fallback through configuration.
- Added a maximum allowed stale-data age.
- Calculated cache age using the cache record's `updated_at` timestamp.
- Kept old cache stored when provider refresh fails, without presenting it as fresh data.

### 5. Market-Data Freshness Metadata

Added freshness information to backend results:

- `is_stale`
- `stale_age_seconds`
- `stale_reason`
- `data_source`

Freshness metadata is now available through:

- `/screen/run`
- `/screen/run-gate`
- `/screen/run-entry`
- `/screen/details`

Possible data sources include:

- `live_provider`
- `fresh_cache`
- `stale_cache`

### 6. API-Key Redaction

- Added secret redaction before logging provider errors.
- Protected query parameters including:
  - `apiKey`
  - `api_key`
  - `key`
  - `token`
  - `access_token`

## Files Changed

- `core/config.py`
- `models/results.py`
- `services/market_data.py`
- `services/screener.py`
- `tests/test_price_lag_diagnostics.py`

## Validation Results

### Focused Market-Data Tests

- **46 passed**
- **0 failed**

### Indicator Regression Tests

- Indicator defaults: **4 passed**
- Confluence freshness: **11 passed**
- DW Regression Channel: **10 passed**

### Live AAPL Test

- Symbol: `AAPL`
- Timeframe: `1h`
- Requested candles: `20`
- Returned candles: `20`
- Closed candles: `19`
- Forming candles: `1`
- Provider: `massive`
- Stale: `False`
- Source: `live_provider`
- Result: **PASS**

## Final Status

- Historical candle retrieval: **Fixed**
- Incomplete-cache handling: **Fixed**
- Provider-limit calculation: **Fixed**
- Stock calendar window: **Fixed**
- Silent stale-cache behavior: **Fixed**
- API freshness metadata: **Added**
- API-key exposure in logs: **Fixed**
- Live validation: **Passed**
- New indicator regressions: **None**

The remaining five failures in the main backend test suite are existing response-model and test-expectation mismatches unrelated to these market-data changes.

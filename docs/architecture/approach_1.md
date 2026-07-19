# Approach 1: Twelve Data-backed indicator validation

## Goal

Validate that the backend calculates and evaluates a small set of technical indicators correctly by comparing backend output against Twelve Data reference values.

For the current phase, the validation scope is intentionally limited to:

- `rsi`
- `aroon`
- `macd`
- `ema`

All other indicators and filters are future work. This keeps the first validation pass focused, repeatable, and easier to debug when backend output differs from the reference provider.

## Current data source

We are using Twelve Data as the independent reference source for now.

The working example is:

- `backend/scripts/twelve_test.py`

That script demonstrates the current API-call pattern:

1. Fetch OHLCV candles from Twelve Data.
2. Fetch reference indicator values from Twelve Data indicator endpoints.
3. Parse responses by `datetime`.
4. Save response data for later validation.

The final validator must improve on the example by storing exact raw JSON responses, using fixed UTC dates, and keeping RSI, Aroon, MACD, and EMA in four separate immutable fixture bundles. It must not use one merged file as the authoritative reference.

## Why this approach

The goal is not to prove every backend screener feature in one step.

The goal is to first prove that four high-priority indicators match an external reference closely enough to trust the backend pipeline for those indicators.

This approach gives us:

- independent reference values from Twelve Data
- timestamp-aligned OHLCV and indicator rows
- repeatable fixture files
- focused pass/fail output per indicator
- easier debugging when a mismatch appears

## Current validation scope

### RSI

Validate backend RSI against Twelve Data RSI.

Required inputs:

- `close`
- RSI length / time period
- selected timeframe
- symbol

Values to compare:

- RSI value
- signal timestamp
- backend pass/fail decision for RSI filters
- confirmation behavior when RSI confirmation is enabled

### Aroon

Validate backend Aroon against Twelve Data Aroon.

Required inputs:

- `high`
- `low`
- Aroon time period
- selected timeframe
- symbol

Values to compare:

- Aroon up value
- Aroon down value
- derived oscillator value if the backend uses one
- signal timestamp
- backend pass/fail decision for Aroon filters
- confirmation behavior when Aroon confirmation is enabled

### MACD

Validate backend MACD against Twelve Data MACD.

Required inputs:

- `close`
- fast period
- slow period
- signal period
- selected timeframe
- symbol

Values to compare:

- MACD value
- signal value
- histogram value
- signal timestamp
- backend pass/fail decision for MACD filters
- confirmation behavior when MACD confirmation is enabled

### EMA

Validate backend EMA against Twelve Data EMA.

Required inputs:

- `close`
- EMA length / time period
- selected timeframe
- symbol

Values to compare:

- EMA value
- signal timestamp
- backend pass/fail decision for EMA filters
- confirmation behavior when EMA confirmation is enabled

## What the validation should prove

For each indicator, the test should prove three things:

1. The backend computes the same numeric value as Twelve Data within a configured tolerance.
2. The backend evaluates the signal on the same candle timestamp as the reference row.
3. The backend returns the expected include/exclude result for the symbol.

The timestamp check is important. A numeric value can look correct while still being evaluated against the wrong candle.

## Recommended workflow

1. Fix a symbol, June 1-30, 2026 UTC date range, `1day` timeframe, closed-candle policy, adjustment policy, and indicator config.
2. Fetch OHLCV and indicator values from Twelve Data through four separate indicator modules.
3. Permanently store the untouched Twelve JSON responses and checksums; create Parquet views only for reading.
4. Fetch Massive candles for June 1-30 only; use June 1-20 for training/initialization and June 21-30 for validation.
5. Audit Twelve and Massive OHLCV alignment before judging indicator differences.
6. Run the existing backend indicator calculations on Massive candles.
7. Compare backend values against Twelve Data values by exact UTC timestamp.
8. When provider candles differ, classify the result as inconclusive and optionally run a same-input diagnostic using read-only Twelve candles.
9. Run each backend filter independently and then run the combined screener.
10. Compare expected and actual filter decisions and final inclusion/exclusion.

## Fixture requirements

Each indicator fixture bundle should include:

- the exact raw Twelve OHLCV response
- the exact raw Twelve indicator response
- request parameters and fetch timestamp
- symbol, `1day` timeframe, fixed June 1-30 dates, and the 20/10 split
- indicator parameters
- SHA-256 checksums
- a reproducible Parquet view for typed comparisons

The raw response is never changed. Sorting, numeric parsing, and timestamp conversion happen only in derived views. Missing or duplicate timestamps are reported and are never silently repaired.

## Provider-input limitation

The backend production path calculates indicators from Massive candles, while Twelve Data calculates its reference values from Twelve candles. Even with matching dates and timeframe, provider OHLC values can differ because of session, adjustment, aggregation, or market-source policies.

Therefore:

- compare provider candles before comparing indicators
- report material candle differences separately
- do not call an indicator mismatch a backend formula failure when inputs differ materially
- use an optional read-only same-input diagnostic to isolate formula behavior when needed

Only June 21-30 is scored. June 1-20 is the initialization segment. Because this fixed segment is too short for normal default MACD initialization, MACD may correctly return `insufficient_data`; the pipeline must not fetch pre-June data under this protocol.

## Comparison rules

The validator should report mismatches by stage:

- missing candle timestamp
- mismatched OHLCV input
- missing reference indicator value
- mismatched indicator value
- correct value on the wrong timestamp
- wrong backend filter pass/fail result
- wrong confirmation result
- final symbol included when it should be excluded
- final symbol excluded when it should be included

This makes failures actionable. The output should say which section is wrong instead of only reporting that the final screener result failed.

## Tolerance rules

Each indicator should have an explicit numeric tolerance.

Recommended starting point:

- RSI: small decimal tolerance
- Aroon: small decimal tolerance
- MACD: small decimal tolerance, with separate checks for MACD, signal, and histogram
- EMA: small decimal tolerance

Tolerance should be configurable per indicator because MACD and EMA values can have different decimal precision depending on symbol price and timeframe.

## What not to validate in this phase

Do not include these in the current validation pass:

- `wavetrend`
- `lrc`
- `regression`
- `trend`
- `linreg_candles`
- `volume`
- `relative_volume`
- `current_volume`
- `float`
- `shares_outstanding`
- `volatility`
- `channel_respect`
- `confluence`
- `price_range`
- universe metadata filters

Those belong in the future plan below.

## Future plan

After RSI, Aroon, MACD, and EMA validation is stable, extend the harness in phases.

### Phase 2: Additional OHLC-based indicators

Add indicators that can be validated from OHLC candles:

- `volatility`
- `linreg_candles`
- `lrc`
- `regression`
- `trend`
- `wavetrend`

These should come after the first four indicators because their behavior is more sensitive to derived series, line fitting, pivots, and implementation details.

### Phase 3: Volume-based indicators

Add indicators that require volume:

- `volume`
- `relative_volume`
- `current_volume`

Only add these once the fixture pipeline consistently includes trustworthy volume data for the selected symbol and timeframe.

### Phase 4: Fundamental indicators

Add indicators that require non-candle metadata:

- `float`
- `shares_outstanding`

These need a separate reference source or trusted fixture because they cannot be validated from OHLCV candles alone.

### Phase 5: Full screener and post-filter validation

Add full pipeline validation for:

- `channel_respect`
- `confluence`
- `price_range`
- universe filters from asset metadata
- final multi-symbol stock inclusion and exclusion

This phase should use a multi-symbol fixture set and an independently prepared expected result list.

## Practical verdict

For now, the automated validation plan should stay narrow:

- use Twelve Data as the reference provider
- validate only RSI, Aroon, MACD, and EMA
- compare both numeric values and evaluated timestamps
- report the earliest mismatch stage
- move every other indicator and post-filter into future phases

This gives us a reliable foundation before expanding to the rest of the screener.

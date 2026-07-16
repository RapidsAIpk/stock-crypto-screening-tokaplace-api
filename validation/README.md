# Twelve Data validation fixtures

Phases 1 and 2 provide a fixed June 1-30, 2026 30-minute validation contract and four immutable Twelve Data reference bundles for RSI, Aroon, MACD, and EMA.

- Training/initialization dates: June 1-20, 2026
- Scored validation dates: June 21-30, 2026

These are calendar-date ranges. Missing 30-minute timestamps are reported and are not filled.

## API key

Set the key in `backend/.env`:

```text
TWELVE_DATA_API_KEY=your_key
```

## Freeze a reference run

Run from the repository root:

```bash
python backend/scripts/freeze_twelve_validation.py --symbol BTC/USD
```

One run makes five API requests: one 30-minute OHLCV candle request shared byte-for-byte by all bundles and one request for each indicator. An existing deterministic run is rejected before any API request is made.

Raw JSON is authoritative. CSV files are derived inspection views. `checksums.sha256` and `bundle_manifest.json` detect changes, and the API key is never written to a fixture.

## Unit tests

The tests use injected in-memory responses and never contact Twelve Data:

```bash
python -m unittest backend.tests.unit.test_validation_phases_1_2 -v
```

## Fetch and audit Massive candles

After the matching Twelve run exists:

```bash
python backend/scripts/fetch_massive_validation.py --symbol BTC/USD
```

This makes one Massive request for June 1-30, freezes the raw response, creates a segmented candle CSV, and writes `candle_alignment.json`. The API key comes from `MASSIVE_API_KEY` or `POLYGON_API_KEY` and is never persisted.

## Calculate backend indicators

After the Massive fixture exists:

```bash
python backend/scripts/calculate_validation_indicators.py --symbol BTC/USD
```

This is offline. It calls the existing backend RSI, Aroon, MACD, and EMA implementations and writes `backend_indicators.json`. With the default `(12, 26, 9)` parameters, MACD is marked `insufficient_data` because the fixed 30-row June dataset is shorter than the backend's 37-candle requirement.

Phase 3 and 4 tests are also fully mocked:

```bash
python -m unittest backend.tests.unit.test_validation_phases_3_4 -v
```

## Compare indicator values

After Phase 4:

```bash
python backend/scripts/compare_validation_indicators.py --symbol BTC/USD --tolerances backend/validation/tolerances.example.json
```

This writes `indicator_comparison.json` with component-level absolute and relative differences, per-indicator verdicts, the first divergence, and the earliest failing pipeline stage. Tolerances are applied at report time and do not require refetching either provider. Derived reports are atomically replaced on rerun; frozen provider responses are never overwritten.

## Validate screener filters

Define explicit cases using `backend/validation/screener_cases.example.json`, then run:

```bash
python backend/scripts/compare_validation_screener.py --symbol BTC/USD --cases backend/validation/screener_cases.example.json
```

This writes `screener_comparison.json`. The independent oracle evaluates frozen Twelve values, while the actual side calls the backend's production filter handlers. Combined `all` cases run through `services.indicators.apply_indicators`. Combined `any` cases aggregate independent backend filter results because the production selected-indicator path currently implements AND semantics.

The independent confirmation oracle supports bullish/bearish and strong bullish/bearish candle types plus engulfing, hammer, shooting-star, and pin-bar patterns. Unsupported case tokens are rejected instead of being allowed to produce a false pass.

Phase 5 and 6 tests are fully offline:

```bash
python -m unittest backend.tests.unit.test_validation_phases_5_6 -v
```

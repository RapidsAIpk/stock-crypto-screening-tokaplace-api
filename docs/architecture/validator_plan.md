# Validator Pipeline Plan

## Objective

Build a repeatable validation pipeline for four indicators only:

- RSI
- Aroon Oscillator
- MACD
- EMA

The pipeline will permanently freeze Twelve Data reference responses, fetch matching 30-minute candles from Massive, run the existing backend calculations, compare indicator values, and finally verify the screener's include/exclude decisions.

All other indicators remain future work.

## Fixed validation contract

Every validation run must use this immutable date specification:

- one symbol
- `30min` timeframe
- comparison range: June 1 through June 30, 2026
- training/initialization range: June 1 through June 20, 2026
- scored validation range: June 21 through June 30, 2026
- closed candles only
- one parameter set per indicator
- the same timestamp convention for both providers
- an explicit price-adjustment policy

These dates are fixed in the code and manifest. The CLI must not accept alternate start or end dates.

The split uses calendar dates:

```text
June 1                    June 20 June 21             June 30
|------ 20 training/initialization days ------|-- 10 validation days --|
```

For stocks, weekends, exchange holidays, and out-of-session intervals mean these ranges can contain fewer candles than a continuously traded market. Missing timestamps must be reported and must not be filled. For continuously traded crypto, all expected 30-minute rows in the June 1-30 range are expected.

The first 20 dates initialize the indicator series. Only values dated June 21-30 are scored. With default MACD parameters `(12, 26, 9)`, the validator must report `insufficient_data` if the backend cannot produce a properly initialized value from this fixed dataset; the validator must not hide this by fetching pre-June candles.

## Core data rule: Twelve Data is immutable

Twelve Data is the external reference, not input that the application is allowed to repair.

The validator must never:

- round or overwrite Twelve Data values
- forward-fill missing reference values
- interpolate gaps
- replace Twelve candles with Massive candles
- recalculate a Twelve Data indicator and save it as the reference
- silently change timestamps, parameters, or field names

The exact JSON body returned by Twelve Data is the source of truth. It is written once, checksummed, and never overwritten. A parsed CSV file is generated for inspection in the first implementation, but it is a derived view and must remain reproducible from the raw JSON. Parquet can be added later when the project adopts a Parquet dependency.

## Permanent storage format

Use both formats for different purposes:

- Raw JSON: exact provider response, audit evidence, and source of truth.
- CSV: human-readable derived view for inspection and simple offline loading.
- Parquet: optional future derived view for typed, compact storage.

Each indicator has an independent fixture bundle. Do not merge the four Twelve Data indicator outputs into one authoritative file.

```text
backend/validation/fixtures/
  twelve/
    <symbol>/<run_id>/
      run_manifest.json
      rsi/
        candles.raw.json
        indicator.raw.json
        candles.csv
        reference.csv
        bundle_manifest.json
        checksums.sha256
      aroon/
        candles.raw.json
        indicator.raw.json
        candles.csv
        reference.csv
        bundle_manifest.json
        checksums.sha256
      macd/
        candles.raw.json
        indicator.raw.json
        candles.csv
        reference.csv
        bundle_manifest.json
        checksums.sha256
      ema/
        candles.raw.json
        indicator.raw.json
        candles.csv
        reference.csv
        bundle_manifest.json
        checksums.sha256
  massive/
    <symbol>/<run_id>/
      candles.raw.json
      candles.csv
      run_manifest.json
      checksums.sha256
  results/
    <symbol>/<run_id>/
      candle_alignment.json
      backend_indicators.json
      indicator_comparison.json
      screener_comparison.json
      report.md
```

`run_id` should be deterministic from the symbol, comparison dates, timeframe, adjustment policy, and indicator parameters. Running the same specification twice must not overwrite the original fixture.

## Run manifest

`run_manifest.json` is the contract joining all four modules and both providers. It contains:

- schema version and run ID
- symbol and each provider's symbol mapping
- timeframe and timezone
- comparison start/end timestamps
- training start/end timestamps
- validation start/end timestamps
- closed-candle policy
- adjusted/unadjusted price policy
- RSI length
- Aroon length
- MACD fast, slow, and signal periods
- EMA length
- API endpoint and request parameters for every fetch
- fetch timestamps
- raw-file checksums
- provider metadata and warnings
- code revision used for backend calculation
- tolerance configuration

No comparison may run when its inputs disagree with the manifest.

## Pipeline flow

```text
Run specification
      |
      +--> Four Twelve modules --> immutable reference bundles
      |
      +--> Massive candle module --> matched June candles
                                      |
                                      v
                         Existing backend indicator code
                                      |
                                      v
                        Timestamp/value comparison
                                      |
                                      v
                         Existing screener filters
                                      |
                                      v
                      Filter and inclusion comparison
```

## Phase 1: Run specification and storage foundation

### Module: `validation_spec`

Responsibilities:

- validate the symbol, exact UTC date range, and `30min` timeframe
- reject an open/incomplete final 30-minute candle
- resolve provider symbol mappings
- define indicator parameters
- enforce the fixed June 1-30, 2026 range and 20/10 split
- create the deterministic run ID
- produce the deterministic manifest contract that Phase 2 freezes with the fetched response metadata

### Module: `fixture_store`

Responsibilities:

- write raw responses without changing their content
- prevent accidental overwrite
- calculate and verify SHA-256 checksums
- create reproducible CSV views from raw responses
- label every derived artifact with its source checksum
- fail when a fixture or manifest has been altered

Phase output: one validated in-memory run specification with a deterministic run ID. Phase 2 writes the manifest and all four bundles together using an atomic directory rename, so a failed fetch cannot leave a run that looks complete.

## Phase 2: Four independent Twelve Data modules

The modules share a low-level HTTP client and storage contract, but each owns its endpoint, parameters, schema checks, and reference file.

### Module 1: `twelve_rsi`

Fetch and store:

- 30-minute OHLCV response for the exact comparison range
- Twelve Data RSI response
- RSI length and endpoint parameters
- `datetime` and `rsi` reference fields

### Module 2: `twelve_aroon`

Fetch and store:

- 30-minute OHLCV response for the exact comparison range
- Twelve Data Aroon response
- Aroon length and endpoint parameters
- `datetime`, `aroon_up`, and `aroon_down` fields
- a provider oscillator field only if Twelve Data returns one

The backend oscillator is compared to `aroon_up - aroon_down`. This subtraction is performed only in the comparison result; it never modifies the stored Twelve response.

### Module 3: `twelve_macd`

Fetch and store:

- 30-minute OHLCV response for the exact comparison range
- Twelve Data MACD response
- fast, slow, signal, and series parameters
- `datetime`, `macd`, `macd_signal`, and `macd_hist` fields

### Module 4: `twelve_ema`

Fetch and store:

- 30-minute OHLCV response for the exact comparison range
- Twelve Data EMA response
- EMA length and series parameters
- `datetime` and `ema` fields

### Shared module: `twelve_http_client`

Responsibilities:

- authentication, timeout, retry, and rate-limit handling
- preservation of request parameters and raw response bodies
- explicit API error reporting
- no cross-indicator merging or value normalization

Phase gate:

- all four bundles exist
- checksums pass
- every bundle matches the manifest
- reference timestamps are unique and within June 1-30, 2026
- missing provider rows are reported, not filled

## Phase 3: Massive matched-candle pipeline

### Module: `massive_candle_fetcher`

Use the repository's Massive aggregate path and symbol mapping to fetch 30-minute OHLCV candles.

Responsibilities:

- fetch from June 1 through June 30, 2026 only
- request the same symbol, `30min` timeframe, timezone boundary, and adjustment policy
- retain the raw Massive response
- create a reproducible candle CSV with numeric fields
- mark June 1-20 rows as training and June 21-30 rows as validation
- reject open/incomplete 30-minute candles

### Module: `candle_alignment_auditor`

Before indicator comparison, compare Twelve and Massive candle inputs over June 1-30:

- timestamp presence
- open, high, low, close, and volume
- 30-minute boundary and timezone
- missing/duplicate candles
- adjusted versus unadjusted prices

This audit is essential. If the providers have different OHLC values, a later indicator difference cannot automatically be blamed on backend logic.

Phase gate:

- Massive timestamps cover the scored Twelve timestamps
- candle policy matches the manifest
- input differences are measured and reported
- severe candle mismatches mark formula validation as `inconclusive`, not `failed`

## Phase 4: Backend indicator calculation

Create four backend adapters. They invoke existing code without reimplementing formulas.

### Module: `rsi_validator`

- call `services.rsi.compute_rsi_series`
- map the shortened RSI output back to its source candle timestamps
- emit only June 21-30 validation rows

### Module: `aroon_validator`

- call `services.aroon_oscillator.compute_aroon_oscillator`
- map its first value to the correct candle after the lookback
- emit the oscillator for Phase 5 to compare against read-only Twelve Aroon up/down fields

### Module: `macd_validator`

- call `services.macd.compute_macd`
- retain MACD, signal, and histogram separately
- use June 1-20 for initialization and exclude them from scoring

### Module: `ema_validator`

- call `services.ema.compute_ema`
- calculate from Massive close prices beginning June 1
- use June 1-20 for initialization and score June 21-30 only

Each adapter outputs a common row shape:

```text
timestamp, indicator, component, reference_value, backend_value,
absolute_difference, relative_difference, tolerance, status
```

The adapter never writes into a Twelve fixture.

At this phase, `reference_value`, differences, and the final comparison status remain empty. Phase 5 fills those fields after joining the backend rows to the immutable Twelve reference values.

## Phase 5: Indicator comparison and verdicts

### Module: `indicator_comparator`

Responsibilities:

- join by exact UTC candle timestamp, never by row number
- compare only timestamps from June 21 through June 30, 2026
- use component-specific absolute and relative tolerances
- distinguish training/null rows from real validation mismatches
- report the first divergent timestamp and all summary statistics
- accept report-time tolerance overrides without changing the frozen fixture run ID

Allowed verdicts:

- `pass`: candle inputs are acceptably aligned and values are within tolerance
- `fail`: candle inputs align, but backend values exceed tolerance
- `inconclusive_input_mismatch`: provider candles differ enough to explain the result
- `insufficient_data`: required timestamps or initialization history are missing
- `reference_error`: the frozen Twelve response is incomplete or invalid

The pipeline must not reduce these states to a single boolean.

### Diagnostic control

When Massive and Twelve candles differ, an optional diagnostic may run the backend formula in memory against the frozen Twelve OHLCV rows. This does not change the raw files and is not the production-path result. It answers a narrower question: "Does our formula match Twelve Data when both use the same candle inputs?"

This control separates two causes:

- backend formula/series alignment error
- market-data provider input difference

## Phase 6: Screener filter validation

Indicator correctness and screener correctness are separate checks.

### Module: `reference_filter_oracle`

Read the frozen Twelve reference values and apply explicit expected rules for test cases, such as RSI threshold, EMA price relationship, MACD cross/zero rule, or Aroon oscillator range. It must record the exact reference timestamp and values used for each expected decision.

This module creates expected filter decisions; it does not modify the reference dataset.

Case configurations are explicit JSON inputs. Unknown rule tokens, period mismatches, and unsupported confirmation patterns are rejected so two false results cannot be mistaken for successful validation.

### Module: `backend_filter_runner`

Run the existing backend evaluation paths:

- `services.rsi.evaluate_rsi_rules`
- `services.aroon_oscillator.evaluate_aroon_rules`
- `services.macd.evaluate_macd_rules`
- `services.ema.evaluate_ema_rules`
- the selected-indicator screener path

Capture:

- evaluated candle timestamp and index
- current and previous values used
- rule, window, tolerance, and confirmation config
- per-indicator pass/fail
- final symbol included/excluded result

### Module: `screener_comparator`

Compare expected and actual results in two layers:

1. Single-indicator cases prove each filter independently.
2. Combined four-indicator cases prove AND/OR behavior and final inclusion/exclusion.

The current production selected-indicator screener uses AND semantics. Therefore, combined `all` cases run through the real `apply_indicators` path, while combined `any` cases are explicitly labeled as aggregation over independently evaluated backend filters rather than presented as a native screener feature.

Report the earliest mismatch:

- candle alignment
- indicator value
- evaluated timestamp/index
- rule result
- confirmation result
- combined screener decision

## Phase 7: CLI, tests, and repeatability

### Module: `validator_cli`

Expected commands:

```bash
python -m backend.validation.cli freeze-twelve --spec validation_case.json
python -m backend.validation.cli fetch-massive --run-id <run_id>
python -m backend.validation.cli compare-indicators --run-id <run_id>
python -m backend.validation.cli compare-screener --run-id <run_id>
python -m backend.validation.cli run --spec validation_case.json
```

Network fetching and offline comparison must be separate commands. Once fixtures are frozen, indicator and screener validation must run without API access.

### Test modules

- manifest and deterministic run-ID tests
- immutable fixture/checksum tests
- raw JSON to CSV reproducibility tests
- timestamp and closed-candle alignment tests
- fixed-date and 20/10 split tests
- one focused test module per indicator adapter
- tolerance and verdict-state tests
- single-filter and combined-screener tests
- known off-by-one timestamp regression tests

## Why pure Twelve Data is useful

The untouched Twelve response gives the project an independent oracle. It helps in five concrete ways:

1. It prevents the code under test from creating its own expected answers.
2. It makes every future rerun compare against the same historical evidence, even if an API later changes.
3. It exposes timestamp and training/validation boundary mistakes that a latest-value-only test would miss.
4. It lets failures be localized: provider candles, formula output, filter rule, or final screener composition.
5. It supports offline regression tests after the one-time API fetch.

Pure reference values do not, by themselves, prove the backend formula is wrong when Massive supplies different candles. That is why the candle audit and optional same-input diagnostic are part of this design. The immutable reference is the benchmark; the alignment layers explain whether a difference is caused by data, calculation, or filtering.

## Implementation order

1. Implement the run specification, manifest, and immutable fixture store.
2. Implement `twelve_rsi` and verify the storage contract end to end.
3. Implement `twelve_aroon`, `twelve_macd`, and `twelve_ema` using the same contract.
4. Implement the Massive date-range fetch and candle alignment audit.
5. Implement the four backend indicator adapters.
6. Implement comparison verdicts and reports.
7. Implement single-indicator screener cases.
8. Implement combined screener validation.
9. Add CLI commands and offline regression tests.

## Definition of done

The current project is complete when:

- four separate, immutable Twelve indicator bundles exist for a fixed one-month 30-minute range
- the exact raw responses and request metadata can be audited by checksum
- Massive data is restricted to June 1-30 with the same 20/10 split
- all four backend calculations are compared by UTC timestamp
- results distinguish formula failures from provider candle mismatches
- each of the four screener filters is validated independently
- combined screener inclusion/exclusion is validated
- all comparisons can be rerun offline without changing the frozen reference data
- all other indicators remain outside the current scope

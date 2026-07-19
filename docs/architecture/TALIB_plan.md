# TA-Lib Production Screener Validation Plan

## Implementation files

Plan code lives under `backend/production_screener_validation/` (planned path was `backend/validation/production_screener/`).

### Core framework

- `backend/production_screener_validation/__init__.py` — package exports for cases, fixtures, and golden store
- `backend/production_screener_validation/contracts.py` — validation-owned case schema, rule catalog, verdicts, checksums
- `backend/production_screener_validation/pipeline.py` — candidate generation and validate/compare orchestration
- `backend/production_screener_validation/fixture_store.py` — immutable fixture/golden store with checksums and approval
- `backend/production_screener_validation/capture.py` — Massive API candle/metadata capture for freezing fixtures

### Independent reference oracle

- `backend/production_screener_validation/reference/__init__.py` — reference package boundary (no `services.*` imports)
- `backend/production_screener_validation/reference/talib_engine.py` — TA-Lib adapter for RSI, Aroon, MACD, EMA, SMA, StochRSI, ADX
- `backend/production_screener_validation/reference/custom_engine.py` — custom indicators (WaveTrend, channels, linreg) via TA-Lib primitives
- `backend/production_screener_validation/reference/rule_engine.py` — turns indicator series into pass/fail rule decisions
- `backend/production_screener_validation/reference/confirmation_oracle.py` — independent candle-pattern confirmation semantics
- `backend/production_screener_validation/reference/oracle.py` — top-level reference oracle producing expected symbol sets

### Production runner and comparison

- `backend/production_screener_validation/production/__init__.py` — production runner package exports
- `backend/production_screener_validation/production/runner.py` — runs real screener against fixture-backed market data
- `backend/production_screener_validation/comparison/__init__.py` — comparator package exports
- `backend/production_screener_validation/comparison/comparator.py` — expected-vs-actual symbol-set comparison and mismatch stages
- `backend/production_screener_validation/comparison/reporting.py` — writes JSON/CSV validation reports

### Case schemas and examples

- `backend/production_screener_validation/cases/standard_combinations.example.json` — example RSI/Aroon/MACD/EMA combination cases
- `backend/production_screener_validation/cases/custom_indicators.example.json` — example custom-indicator cases
- `backend/production_screener_validation/cases/metadata_filters.example.json` — example universe/metadata filter cases
- `backend/production_screener_validation/cases/post_filters.example.json` — example channel-respect/confluence post-filter cases
- `backend/production_screener_validation/cases/gate_entry.example.json` — example gate/entry multi-timeframe cases
- `backend/production_screener_validation/metadata.example.json` — example frozen asset metadata payload

### CLI scripts

- `backend/scripts/fetch_production_screener_fixtures.py` — freeze Massive candles/metadata fixtures
- `backend/scripts/generate_production_screener_reference.py` — generate unapproved golden candidates
- `backend/scripts/approve_production_screener_reference.py` — explicitly approve a candidate golden
- `backend/scripts/validate_production_screener.py` — offline production-vs-golden validation run
- `backend/scripts/build_standard_screener_case_matrix.py` — builds the 15 RSI/Aroon/MACD/EMA combination cases

### Tests and dependency

- `backend/tests/unit/test_production_screener_validation.py` — unit tests for TA-Lib adapter, contracts, fixtures, golden drift
- `backend/requirements.txt` — pins `TA-Lib==0.6.8`

## 1. Objective

Build an automated, deterministic validator that answers one question:

> For a fixed market-data snapshot and a selected combination of screener rules, does the production screener return exactly the correct set of stock symbols?

The final acceptance result is based on symbol membership, not exact agreement between Twelve Data and Massive indicator values.

For every validation case:

```text
Frozen Massive candles + frozen metadata
                  |
        +---------+---------+
        |                   |
Independent reference   Production screener
        |                   |
Expected symbols         Actual symbols
        +---------+---------+
                  |
       exact symbol-set comparison
```

The validator must identify:

- correctly included symbols
- correctly excluded symbols
- missing symbols (false negatives)
- unexpected symbols (false positives)
- symbols that could not be evaluated because data was insufficient
- the earliest rule or production stage responsible for a mismatch

## 2. Scope and non-goals

### In scope

- the real stock screener path in `backend/services/screener.py`
- single-timeframe scans
- gate and entry scans
- selected-indicator AND behavior
- RSI, Aroon, MACD, and EMA first
- all additional indicators listed in `approach_1.md` and `CLIENT_DELIVERABLES.md` in later phases
- confirmation rules, windows, tolerances, and multi-rule behavior
- price range, channel respect, confluence, and universe metadata filters
- exact expected-versus-actual stock membership
- deterministic offline execution after fixture capture
- optional scheduled live validation after the offline suite is stable

### Not an acceptance gate

- Twelve-versus-Massive candle equality
- Twelve-versus-backend numeric indicator equality
- ordering of returned symbols unless a future product requirement defines an order
- visual frontend rendering
- live market movement during a deterministic regression run

The existing Twelve Data validator remains useful as a provider comparison and diagnostic tool, but its verdict must not block this production screener validator.

## 3. Reference point and independence rules

The reference result is produced from:

1. the same frozen Massive candles used by production
2. the same frozen asset metadata used by production
3. approved, explicit product-rule definitions
4. an implementation independent from production screener code

### Independence boundary

Reference modules must not import calculation or decision logic from:

- `services.rsi`
- `services.aroon_oscillator`
- `services.macd`
- `services.ema`
- `services.wavetrend`
- `services.linear_regression_candles`
- `services.regression_channels`
- `services.trend_channels`
- `services.indicators`
- `services.channel_respect`
- `services.confluence`
- `services.screener`

Production models may be used only at the adapter boundary after the reference decision has been created. Reference case parsing should use validation-owned schemas so production defaults cannot silently change expected results.

### Reference technologies

- TA-Lib: standard RSI, Aroon, MACD, EMA, and supported mathematical primitives
- NumPy or small validation-owned functions: custom compositions and transparent threshold rules
- frozen metadata: float, shares outstanding, compliance, exchange, category, and other universe fields
- manually reviewed golden cases: custom channels, confirmation semantics, and important threshold boundaries

### Golden-reference rule

The validator must not silently regenerate expected results during a normal test run.

Reference generation is a separate command that creates a candidate golden file containing:

- fixture manifest ID and checksums
- case definition and checksum
- TA-Lib version
- reference-engine version
- per-symbol indicator values
- per-rule Boolean decisions
- expected included symbols
- expected excluded symbols
- insufficient-data symbols
- generation timestamp

A candidate becomes usable only after explicit approval. Normal validation reads the approved golden file and compares it with both the current independent oracle output and the production output.

If the current oracle differs from the approved golden file, report `reference_drift` and do not judge production against a moving reference.

## 4. Validation result model

Each case produces:

```json
{
  "case_id": "rsi_overbought_and_macd_positive",
  "verdict": "fail",
  "expected_symbols": ["AAPL", "NVDA"],
  "actual_symbols": ["AAPL", "TSLA"],
  "correctly_included": ["AAPL"],
  "missing_symbols": ["NVDA"],
  "unexpected_symbols": ["TSLA"],
  "insufficient_data_symbols": [],
  "earliest_mismatch_stage": "indicator_rule",
  "symbol_evidence": {}
}
```

### Case verdicts

- `pass`: expected and actual symbol sets are exactly equal and no required symbol is unevaluable
- `fail`: at least one expected symbol is missing or at least one unexpected symbol is returned
- `insufficient_data`: the fixture cannot evaluate one or more required symbols
- `reference_error`: the independent reference cannot evaluate a defined rule
- `reference_drift`: recomputed independent evidence differs from the approved golden reference
- `production_error`: the production pipeline raises, returns an invalid response, or loses required trace data
- `unapproved_reference`: a candidate reference exists but has not been approved

### Overall verdict

The complete run passes only when every required case passes. Optional experimental cases are reported separately and do not affect the required-suite verdict.

## 5. Proposed module structure

```text
backend/validation/production_screener/
  __init__.py
  contracts.py
  manifests.py
  fixture_store.py
  case_loader.py
  result_models.py
  reference/
    __init__.py
    talib_engine.py
    rule_engine.py
    confirmation_oracle.py
    channel_oracle.py
    volume_oracle.py
    metadata_oracle.py
    composition.py
  production/
    __init__.py
    fixture_market_data.py
    request_factory.py
    single_runner.py
    gate_entry_runner.py
    trace_adapter.py
  comparison/
    __init__.py
    symbol_sets.py
    mismatch_locator.py
    report_builder.py
  cases/
    standard_indicators.json
    standard_combinations.json
    custom_indicators.json
    metadata_filters.json
    post_filters.json
    gate_entry.json
  fixtures/
    manifests/
    candles/
    metadata/
    golden/

backend/scripts/
  fetch_production_screener_fixtures.py
  generate_production_screener_reference.py
  approve_production_screener_reference.py
  validate_production_screener.py
```

## 6. Phase 0: Rule contract and acceptance specification

### Goal

Convert every user-facing rule into an exact, reviewable Boolean contract before creating expected stock lists.

### Module 0.1: Indicator rule catalog

Document for every indicator:

- required input series
- period parameters and defaults
- warmup requirement
- comparison operator, including equality behavior
- tolerance units and application
- latest-candle or within-window behavior
- crossover definition using previous and current bars
- confirmation timing
- insufficient-data behavior

Initial rule contracts:

- RSI: location, direction, window, confirmation
- Aroon: level, direction, window, confirmation
- MACD: bullish cross, bearish cross, above zero, below zero
- EMA: above, below, touch

### Module 0.2: Composition contract

Freeze these product behaviors:

- all selected indicators use AND semantics
- every selected line or area inside a multi-rule indicator must pass
- price range is applied before indicators
- channel respect and confluence are post-filters
- gate symbols become the only candidates for entry
- a missing required value excludes the symbol and is reported as insufficient data

### Module 0.3: Case schema

Define a validation-owned JSON schema containing:

- case ID and description
- required/optional classification
- asset type and explicit symbol universe
- timeframe mode and timeframe values
- complete indicator configurations
- price range and metadata filters
- channel respect and confluence configuration
- fixture manifest ID
- approved golden-reference ID

### Tests

- reject unknown indicator and rule tokens
- reject incomplete crossover and channel configurations
- reject negative windows or tolerances
- reject duplicate case IDs
- reject implicit defaults in approved cases
- verify deterministic case checksums

### Exit criteria

- every Phase 1 rule has an approved written definition
- case files contain explicit values instead of relying on production defaults
- ambiguous rules cannot enter the required suite

## 7. Phase 1: TA-Lib foundation and isolation

### Goal

Create an independent standard-indicator engine without importing production calculations.

### Module 1.1: Dependency integration

- add a pinned TA-Lib Python dependency
- record the Python wrapper and native library versions
- verify installation on Windows and CI
- fail startup with a clear message when TA-Lib is unavailable

### Module 1.2: TA-Lib adapter

Provide typed adapters for:

- `RSI`
- `AROON` and `AROONOSC`
- `MACD`
- `EMA`
- future primitives such as `SMA`, `LINEARREG`, `STDDEV`, and `CORREL`

The adapter must preserve TA-Lib `NaN` warmup output and must never forward-fill it.

### Module 1.3: Independence enforcement

- add an import-boundary test for reference modules
- fail if reference code imports prohibited production modules
- keep reference configuration and result models validation-owned

### Tests

- small hand-calculated EMA sequence
- known RSI boundary sequence
- Aroon highest/lowest-index sequence
- MACD output shape and warmup behavior
- non-finite and short-input handling
- prohibited-import detection

### Exit criteria

- standard reference values are reproducible
- TA-Lib version is included in every reference manifest
- reference code has no production indicator imports

## 8. Phase 2: Multi-symbol immutable fixture system

### Goal

Create a permanent, auditable stock dataset that can exercise pass, fail, and boundary behavior without API calls during tests.

### Module 2.1: Universe selection

Start with a representative stock universe of approximately 20-50 symbols containing:

- high- and low-volatility stocks
- high- and low-volume stocks
- symbols likely to pass and fail each initial rule
- symbols close to important thresholds
- varied exchanges and metadata classifications

The manifest stores the explicit symbol list. Tests must not depend on the current live universe file silently adding or removing symbols.

### Module 2.2: Candle capture

- fetch Massive candles once
- freeze exact raw responses
- derive typed candle files
- record provider symbols, timeframe, adjustment, timezone, and final completed candle
- calculate required history per case
- fetch enough bars for the longest configured indicator plus an explicit safety margin
- reject partial current candles

The first suite uses `1day`. Additional timeframes are introduced in Phase 8.

### Module 2.3: Metadata capture

Freeze the exact metadata required by the production universe and filters:

- symbol, name, and exchange
- compliance fields
- float and shares outstanding
- source and report dates
- any other field used by required cases

### Module 2.4: Fixture integrity

- immutable fixture ID
- SHA-256 checksum for every raw and derived file
- atomic writes
- no overwrite of an existing fixture ID
- manifest verification before every run

### Tests

- duplicate/missing symbol detection
- duplicate/out-of-order candle detection
- insufficient-history detection
- current-candle rejection
- checksum mutation detection
- metadata completeness checks
- mocked fetch tests using tiny responses

### Exit criteria

- all initial symbols have sufficient history for RSI, Aroon, MACD, and EMA
- fixture loading is fully offline
- rerunning validation makes zero API calls

## 9. Phase 3: Independent rule engine for standard indicators

### Goal

Turn TA-Lib values into independently calculated expected pass/fail decisions.

### Module 3.1: RSI oracle

- location rules
- direction rules
- within-window behavior
- tolerance handling
- signal timestamp evidence

### Module 3.2: Aroon oracle

- Aroon Up, Down, and oscillator evidence
- level rules
- direction and turning rules
- within-window behavior

### Module 3.3: MACD oracle

- MACD, signal, and histogram evidence
- bullish/bearish crossover rules
- above/below-zero rules
- explicit previous/current-bar evidence

### Module 3.4: EMA oracle

- latest close and EMA evidence
- above/below rules
- exact touch-tolerance definition

### Module 3.5: Standard composition

- evaluate every symbol independently
- combine selected indicators with AND semantics
- retain every intermediate Boolean decision
- produce expected included and excluded symbol sets

### Tests

- one passing and one failing fixture per rule
- values exactly on each threshold
- values immediately above and below each threshold
- crossover equality cases
- window hit on first and last eligible candle
- insufficient warmup
- all 15 structural combinations of the initial four indicators

### Exit criteria

- the independent engine can generate auditable expected sets for the initial four indicators
- every expected symbol includes per-rule numeric evidence

## 10. Phase 4: Golden-reference workflow

### Goal

Prevent reference implementation changes from silently moving expected results.

### Module 4.1: Candidate generator

Generate candidate references from frozen fixtures and the independent oracle. Candidate output must be deterministic except for metadata such as generation time.

### Module 4.2: Review report

Create a human-readable review containing:

- expected symbols per case
- per-symbol indicator values
- threshold comparisons
- boundary-distance ranking
- insufficient-data warnings
- differences from the previous approved reference

### Module 4.3: Approval command

- require an explicit candidate ID
- record approver name or identifier and approval timestamp
- copy or mark the candidate as approved without recalculation
- refuse overwrite of an existing approved reference

### Module 4.4: Reference drift guard

During validation:

1. recompute independent evidence
2. compare it with the approved golden reference
3. stop with `reference_drift` if they differ
4. compare production only after the reference remains stable

### Tests

- unapproved reference rejection
- approval does not recalculate values
- modified case or candle checksum invalidates approval
- TA-Lib version change triggers reference drift
- stable regeneration produces the same semantic payload

### Exit criteria

- every required standard case has an approved golden reference
- no normal validation command can update expected results

## 11. Phase 5: Production single-scan runner

### Goal

Execute the real production single-scan path while replacing only external data access with frozen fixtures.

### Module 5.1: Fixture market-data adapter

- intercept the market-data boundary used by `run_single`
- return fixture candles in the same shape as production `fetch_live_data`
- preserve production-required candle limits
- reject symbols or timeframes absent from the fixture

### Module 5.2: Production request factory

- construct the actual `ScreeningRequest`
- preserve explicit indicator order and configuration
- support price range and universe settings
- validate request serialization used by `/screen/run`

### Module 5.3: Production runner

Run the actual sequence:

```text
build_asset_universe
-> limit_assets
-> fetch_screening_data through fixture adapter
-> attach_asset_metadata
-> apply_price_range
-> apply_selected_indicators
-> apply_post_filters
-> build_response
```

No production indicator or filter function may be mocked.

### Module 5.4: Trace capture

For each actual symbol, capture:

- production inclusion decision
- matched indicators and stickers
- indicator details where available
- fetched candle count
- production stage reached
- exception or exclusion reason when observable

Trace instrumentation must not change the decision.

### Tests

- fixture adapter is the only mocked boundary
- no network call is possible in offline mode
- actual `run_single` is invoked
- returned symbols and metadata are normalized
- production errors become structured verdicts

### Exit criteria

- the complete production single-scan path runs deterministically from fixtures
- the runner returns a canonical actual symbol set

## 12. Phase 6: Symbol-set comparison and diagnostics

### Goal

Compare approved expected sets with production output and explain every mismatch.

### Module 6.1: Exact set comparator

Calculate:

```text
correctly_included = expected intersection actual
missing_symbols = expected minus actual
unexpected_symbols = actual minus expected
correctly_excluded = universe minus expected minus actual
```

Duplicate production symbols are a `production_error`, not silently deduplicated.

### Module 6.2: Mismatch locator

For each missing or unexpected symbol, compare independent rule evidence with production trace and classify the earliest likely stage:

- universe selection
- candle loading
- price range
- indicator calculation
- indicator rule
- confirmation
- indicator composition
- channel respect
- confluence
- response construction

### Module 6.3: Report builder

Write:

- JSON report for automation
- concise Markdown report for review
- CSV table with one row per case and symbol
- summary counts by indicator, combination, and mismatch stage

### Module 6.4: CLI

Provide:

```powershell
python backend/scripts/validate_production_screener.py --suite standard
```

CLI behavior:

- exit `0` only when all required cases pass
- exit nonzero for fail, insufficient data, reference drift, or production error
- print case totals, missing symbols, unexpected symbols, and report paths
- support `--case`, `--suite`, `--symbol`, and `--verbose-evidence`

### Tests

- exact match
- false positive only
- false negative only
- simultaneous missing and unexpected symbols
- duplicate production result
- mismatch-stage classification
- required versus optional case behavior
- CLI exit codes

### Exit criteria

- failures identify symbols and likely stages instead of returning only a global Boolean
- the standard suite can be used as a CI quality gate

## 13. Phase 7: Custom indicator reference modules

### Goal

Extend the independent reference beyond indicators directly supplied by TA-Lib.

Implement these as separate modules so one custom oracle cannot invalidate unrelated indicators.

### Module 7.1: WaveTrend oracle

- calculate HLC3
- independently compose EMA/deviation/channel-index stages
- produce WT1 and WT2
- evaluate zones, direction, and cross behavior

### Module 7.2: Linear Regression Candles oracle

- use TA-Lib `LINEARREG` or an independently verified regression primitive
- apply signal smoothing
- evaluate price position and close location
- verify candle-to-line index alignment

### Module 7.3: Linear Regression Channel oracle

- regression middle line
- residual standard deviation
- asymmetric upper/lower deviations
- Pearson R filter
- selected-line touch and breach behavior

### Module 7.4: Regression Channel oracle

- continuous and interval sampling
- width coefficient
- selected-line behavior
- touch, breach, and confirmation rules

### Module 7.5: Trend Channel oracle

- pivot and channel construction
- top/middle/bottom lines
- top/bottom zones
- all configured area rules
- wait-for-break and show-last-channel behavior

### Module 7.6: Volatility oracle

- percentage-return series
- configured standard-deviation convention
- min/max and tolerance behavior

### Validation requirement

Every custom module requires:

- an approved written formula
- hand-verified small datasets
- boundary cases
- an approved golden reference
- no import from the matching production implementation

### Exit criteria

- custom-indicator cases produce stable approved expected symbol sets
- failures remain isolated by indicator module

## 14. Phase 8: Volume, fundamentals, and universe filters

### Module 8.1: Volume oracle

Implement independently:

- volume spike against previous-bar average
- relative volume
- current-volume min/max
- tolerance behavior

TA-Lib may provide moving-average primitives, but these product rules remain validation-owned.

### Module 8.2: Fundamental oracle

Use frozen metadata for:

- float min/max
- shares-outstanding min/max
- missing-value behavior

### Module 8.3: Stock universe oracle

Validate:

- explicit symbols
- source selection
- compliance status and standards
- exchange metadata where applicable
- symbol caps and deterministic ordering before the cap

### Module 8.4: Price-range oracle

- minimum price
- maximum price
- equality boundaries
- missing-price behavior

### Exit criteria

- non-technical filters are independently represented in expected symbol sets
- missing metadata cannot silently appear as a normal exclusion

## 15. Phase 9: Confirmation and advanced post-filters

### Module 9.1: Confirmation oracle

Independently define and test:

- bullish and bearish candle types
- strong bullish and strong bearish types
- supported candlestick patterns
- signal candle versus future confirmation candle
- confirmation window boundaries
- no-lookahead behavior beyond the approved fixture endpoint

TA-Lib pattern-recognition functions may be used as secondary evidence, but product-specific confirmation semantics must remain explicit.

### Module 9.2: Channel Respect oracle

- channel source construction
- line selection
- wick/body/both touches
- tolerance
- clustered-touch deduplication
- minimum and maximum respect counts

### Module 9.3: Confluence oracle

- exactly two source channels
- source line/zone selection
- bullish, bearish, breakout, and any scenarios
- 1-4 candle lookback
- liquidity sweep
- post-condition maintenance checks

### Module 9.4: Post-filter composition

Verify production order:

```text
price range
-> selected indicators
-> channel respect
-> confluence
-> response
```

### Exit criteria

- all advanced-filter expected results are auditable per symbol
- post-filter failures are distinguished from indicator failures

## 16. Phase 10: Combination coverage

### Goal

Test meaningful combinations without attempting every possible parameter permutation.

### Module 10.1: Initial structural matrix

For RSI, Aroon, MACD, and EMA, include:

- four single-indicator cases
- all six two-indicator combinations
- all four three-indicator combinations
- one four-indicator combination

This gives 15 structural combinations before rule variants.

### Module 10.2: Rule-pair coverage

Use pairwise coverage across:

- rule variants
- windows
- confirmation on/off
- threshold boundaries
- tolerance values
- pass/fail balance

### Module 10.3: Negative and boundary suite

Require cases where:

- exactly one selected indicator fails
- the first indicator fails
- the last indicator fails
- all indicators fail
- a value equals the threshold
- a signal occurs at the edge of a window
- confirmation occurs at the final allowed candle

### Module 10.4: Full-deliverable combinations

Add representative combinations involving:

- standard plus custom indicators
- indicator plus volume/fundamental filters
- indicators plus channel respect
- indicators plus confluence
- price range plus metadata plus indicators

### Exit criteria

- every rule participates in at least one passing and one failing case
- every major composition boundary is covered
- suite size remains small enough for routine offline execution

## 17. Phase 11: Gate-entry and timeframe validation

### Module 11.1: Gate oracle

- independently calculate expected gate symbols
- verify production gate symbols exactly
- verify gate session contains only expected candidates

### Module 11.2: Entry oracle

- calculate expected entry results only from expected gate candidates
- run the production entry path using the real session workflow
- compare final entry symbols exactly
- verify one-time session consumption and scope checks

### Module 11.3: Timeframe fixtures

Add fixtures incrementally for:

- `1h`
- `4h`, including production aggregation behavior
- custom minute/hour/day/week/month inputs required by acceptance cases

Each timeframe receives an independent manifest and sufficient warmup bars.

### Module 11.4: As-of and no-lookahead checks

- freeze the final completed candle for each case
- ensure neither oracle nor production can read later candles
- test signal and confirmation timestamp alignment

### Exit criteria

- gate and entry symbol sets both match approved references
- timeframe aggregation cannot use future candles

## 18. Phase 12: Automation, CI, and optional live mode

### Module 12.1: Offline CI suite

- install pinned TA-Lib
- verify fixture checksums
- run required standard cases on every relevant backend change
- run custom and full suites on scheduled or release jobs if runtime is larger
- publish JSON/Markdown reports as artifacts

### Module 12.2: Change-aware execution

Map production modules to affected suites so changes to RSI run RSI and combination cases, while changes to composition run all combination cases.

### Module 12.3: Optional live validation

After deterministic validation is stable:

- fetch current Massive data into a new immutable run
- generate a candidate independent reference
- run production against the same snapshot
- report results as informational until the reference is reviewed

Live mode must never overwrite deterministic fixtures or approved golden references.

### Module 12.4: Performance and API limits

- batch fixture capture where supported
- cache all successful provider responses
- never call Massive from unit tests
- cap live validation universes explicitly
- report API requests used

### Exit criteria

- deterministic validation is a reliable CI gate
- live validation is auditable and isolated from regression baselines

## 19. Test strategy by layer

### Unit tests

- contracts and schemas
- TA-Lib adapters
- independent rule functions
- exact set operations
- manifest/checksum handling
- golden-reference drift

Use tiny synthetic arrays and no API calls.

### Integration tests

- multi-symbol fixture loading
- actual `run_single`
- actual `run_gate` and `run_entry`
- fixture market-data adapter
- complete expected-versus-actual reports

Use small frozen universes and no API calls.

### Characterization tests

Before changing production behavior, record current production results separately. Characterization output is evidence of current behavior, not proof of correctness and must not become an approved reference automatically.

### Live tests

- explicitly invoked only
- API-budget aware
- never part of normal unit-test execution
- candidate/reference review required before promotion

## 20. Implementation order

The implementation should proceed in this order:

1. Phase 0: rule contracts and case schema
2. Phase 1: TA-Lib foundation
3. Phase 2: immutable multi-symbol fixtures
4. Phase 3: standard independent rule engine
5. Phase 4: golden-reference workflow
6. Phase 5: production single-scan runner
7. Phase 6: symbol-set comparator, reports, and CLI
8. Phase 10 initial matrix for RSI, Aroon, MACD, and EMA
9. Phases 7-9: custom indicators and filters
10. Phase 10 full-deliverable matrix
11. Phase 11: gate-entry and timeframes
12. Phase 12: CI and optional live validation

The first usable milestone ends after Phase 6 plus the initial Phase 10 matrix. At that point the project can automatically verify whether production returns the correct stocks for combinations of RSI, Aroon, MACD, and EMA.

## 21. First milestone acceptance criteria

The first production-screener milestone is complete when:

- TA-Lib is pinned and available in local and CI environments
- a frozen multi-stock Massive fixture exists with sufficient history
- approved golden references exist for the initial cases
- reference code does not import production indicator or screener logic
- the actual `run_single` path executes with only its external data boundary replaced
- all 15 structural combinations of RSI, Aroon, MACD, and EMA are represented
- reports list expected, actual, missing, and unexpected symbols
- per-symbol evidence explains each expected decision
- the CLI exits nonzero on a false positive or false negative
- unit and integration tests make zero API calls

## 22. Final deliverable

The completed validator will provide an automated answer such as:

```text
Fixture: stocks_daily_2026_06_30_v1
Cases: 38 required, 6 optional
Passed: 36
Failed: 2
Reference drift: 0
Insufficient data: 0

FAIL rsi_overbought_and_macd_positive
  Missing: NVDA
  Unexpected: TSLA
  Earliest mismatch: indicator_rule

FAIL trend_channel_with_confluence
  Missing: AMD
  Unexpected: none
  Earliest mismatch: confluence

Overall verdict: FAIL
```

This report validates production screener membership directly. TA-Lib supplies independent standard calculations, custom validation modules cover product-specific behavior, and approved golden references prevent the production code or the reference generator from silently defining correctness for itself.

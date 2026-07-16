# Production Screener Validation

This package validates the symbols returned by the real production screener against approved independent references. It does not use the old Twelve Data validator and does not import production calculation modules on the reference side.

## Workflow

1. Prepare a metadata JSON object keyed by stock symbol.
2. Freeze sufficient Massive history once.
3. Generate independent reference candidates.
4. Review candidate evidence and explicitly approve each candidate.
5. Run the production validator offline.

```powershell
python backend/scripts/fetch_production_screener_fixtures.py `
  --fixture-id stocks_daily_2026_06_30_v1 `
  --symbols AAPL MSFT NVDA TSLA AMD `
  --start 2025-04-01 `
  --end 2026-06-30 `
  --timeframes 1day `
  --metadata backend/production_screener_validation/metadata.example.json

python backend/scripts/build_standard_screener_case_matrix.py `
  --fixture-id stocks_daily_2026_06_30_v1 `
  --symbols AAPL MSFT NVDA TSLA AMD `
  --output backend/production_screener_validation/cases/standard_combinations.json

python backend/scripts/generate_production_screener_reference.py `
  --cases backend/production_screener_validation/cases/standard_combinations.json

python backend/scripts/approve_production_screener_reference.py `
  --candidate rsi_and_macd `
  --approver "Ammer"

python backend/scripts/validate_production_screener.py `
  --cases backend/production_screener_validation/cases/standard_combinations.json
```

Candidate JSON and Markdown evidence sheets are written under `data/golden/candidates`. Review the expected/excluded symbols and per-rule values before approval. The approval command accepts either the generated candidate hash ID or the readable case ID such as `rsi_and_macd`.

Fixture capture uses one Massive request per symbol and timeframe. Candidate generation, approval, validation, unit tests, and report generation make no API calls.

Normal validation never changes expected results. A case without approval returns `unapproved_reference`; changed oracle output, fixture checksums, case configuration, or TA-Lib evidence returns `reference_drift`.

Reports are written as JSON, Markdown, and CSV. The CLI exits nonzero when any required case is not `pass`.

## RSI filter matrix (all zone/direction/parameter combos)

Generate cases, then run the suite:

```powershell
python backend/scripts/build_rsi_filter_matrix.py `
  --fixture-id stocks_daily_2026_06_30_v1 `
  --symbols AAPL MSFT NVDA TSLA AMD `
  --mode minimal `
  --output backend/production_screener_validation/cases/rsi_filter_minimal.json

python backend/scripts/run_production_screener_suite.py `
  --cases backend/production_screener_validation/cases/rsi_filter_minimal.json `
  --output backend/production_screener_validation/reports/rsi_minimal_run
```

Modes:

- `minimal` (recommended, 19 cases): all UI location×direction pairs, one-factor-at-a-time parameter sweeps, and walk-forward dates where `window`/`tolerance` change outcomes.
- `pairwise` (12 cases): hand-tuned covering array — every pair of dimension values appears in at least one case.
- `full` (216 cases, 360 with `--include-backend-directions`): brute-force grid over location, direction, length, window, tolerance, confirmation.

## Test

```powershell
python -m unittest backend.tests.unit.test_production_screener_validation -v
```

## Run all combos (one command, readable reports)

Compares every case in the standard suite directly — no golden approval needed.
Writes one `.md` and one `.json` per combo under `reports/runs/<timestamp>/cases/`.

```powershell
python backend/scripts/run_production_screener_suite.py
```

Optional:

```powershell
python backend/scripts/run_production_screener_suite.py --case rsi_and_macd
python backend/scripts/run_production_screener_suite.py --output backend/production_screener_validation/reports/my_run
```

Open `summary.md` for the overview, then `cases/<case_id>.md` for per-stock pass/fail details.

## Custom Pine indicators (production-only, manual TradingView)

No oracle comparison — runs real production screener on frozen fixtures and writes pass lists for manual TV verification.

```powershell
python backend/scripts/build_custom_indicator_filter_matrix.py

python backend/scripts/run_custom_indicator_suite.py `
  --output backend/production_screener_validation/reports/custom/all_minimal

python backend/scripts/export_tv_validation_sheets.py `
  --reports-dir backend/production_screener_validation/reports/custom/all_minimal
```

Or from repo root: `make custom-indicator-tv`

Outputs:

- Case suites: `cases/*_filter_minimal.json`, `cases/custom_indicators_minimal.json`
- Run reports: `reports/custom/all_minimal/cases/<case_id>.md`
- TV checklists: `docs/pinescript/tv_validation/*.md`

See `docs/architecture/custom_indicator_plan.md` for the full workflow.

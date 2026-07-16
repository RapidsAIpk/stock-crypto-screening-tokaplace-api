# Backend README

## Overview
This backend is a FastAPI service for manual stock and crypto screening.

It supports:
- Single-timeframe screening
- Two-step gate/entry screening
- Stocks from local `data/zoya_universe.json`
- Crypto from local `data/crypto_universe.json`
- Local candle-based indicators
- Post-filters: `channel_respect` and `confluence`
- SQLite-backed warm market-data cache with background refresh

## Architecture

1. API layer
- Validates request mode and required fields
- Exposes screening and health endpoints

2. Orchestration layer (`services/screener.py`)
- Builds universe
- Fetches market data (cache-first)
- Applies selected indicators
- Applies post-filters
- Builds normalized response rows

3. Market-data layer (`services/market_data.py`, `services/market_data_store.py`)
- Fetches candles from Massive
- Stores/reuses snapshots in SQLite
- Refreshes only when due
- Falls back to stale snapshots with temporary backoff when fetch fails

4. Background worker (`services/market_data_worker.py`)
- Seeds interest rows for universe symbols/timeframes
- Refreshes due symbols continuously
- Prunes stale cache/interest rows

5. Indicator/filter layer (`services/indicators.py` + indicator modules)
- Runs indicator handlers in order
- Short-circuits on first failure
- Produces stickers and optional channel structures

## Endpoints

- `POST /screen/run`
: Single-timeframe run (`timeframe_mode=single`)

- `POST /screen/run-gate`
: Gate phase (`timeframe_mode=gate_entry`, indicators with `timeframe=primary`)

- `POST /screen/run-entry`
: Entry phase (`timeframe_mode=gate_entry`, indicators with `timeframe=secondary`, requires `gate_session_id`)

- `GET /`
: Service metadata

- `GET /healthz`
: Liveness

- `GET /readyz`
: Readiness + worker status (`503` when worker is expected but not running)

## Request Model
Defined in `models/filters.py`.

Key fields:
- `asset_type`: `stocks | crypto`
- `timeframe_mode`: `single | gate_entry`
- `indicators`: list of `{ name, timeframe, config }`
- `channel_respect` (optional)
- `confluence` (optional)

Stocks:
- `stock_sources` (currently only `zoya`)
- `compliance_status`

Crypto:
- `exchanges`
- `excluded_categories`

Gate/Entry:
- `gate_timeframe`
- `entry_timeframe`
- `gate_session_id` (entry only)

## Response Model
Defined in `models/results.py`.

Each row includes:
- `symbol`
- `price`
- `asset_type`
- `data_source`
- `exchange`
- `timeframe`
- `name`
- `category`
- `cmc_id`
- `compliance_status`
- `report_date`
- `purification_ratio`
- `candles_count`
- `last_candle_time`
- `stickers`

Envelope:
- `results`
- `gate_session_id` (gate runs)

## Screening Pipeline

Single mode:
1. Build universe
2. Limit symbols (see `SCREENING_MAX_SYMBOLS`)
3. Fetch market data for timeframe
4. Attach universe metadata
5. Apply indicators
6. Apply post-filters
7. Build response

Gate/Entry mode:
- Gate stores passed metadata in SQLite with TTL and returns `gate_session_id`
- Entry consumes that session (one-time use)

## Universe and Symbol Cap
- Universe is built from local JSON files
- `SCREENING_MAX_SYMBOLS` limits symbols used in screening and worker universe seeding
- `SCREENING_MAX_SYMBOLS <= 0` means no cap

## Market Data Behavior
Implemented in `services/market_data.py`.

- Cache-first: existing snapshots are reused until refresh is due
- Refresh due is determined primarily by `next_refresh_at`
- Missing/due symbols are fetched from Massive
- `4h` candles are derived by aggregating `1h` candles
- On fetch failure, stale snapshot is reused and stored with backoff `next_refresh_at`
- Massive is the only active market-data provider

## Background Worker
Implemented in `services/market_data_worker.py`.

### What it does
- Seeds interest for all universe symbols across all supported timeframes
- Refreshes due symbols and stores snapshots
- Prunes stale rows

### Timeframe priority
Worker refresh order is fixed:
1. `1day`
2. `4h`
3. `1h`
4. `30m`
5. `15m`
6. `5m`
7. `1m`

### Lifecycle
- Starts during app startup if `MARKET_DATA_WORKER_ENABLED=true`
- Stops during shutdown

## Indicators and Post-Filters

### Local indicators
- `lrc`
- `regression`
- `rsi`
- `trend`
- `linreg_candles`
- `aroon`
- `wavetrend`
- `ema`
- `macd`
- `volume`

### Channel Respect (`services/channel_respect.py`)
- Counts touches on selected line with tolerance and clustering
- Supports trend-channel line mapping (`upper/lower` -> `top/bottom`)

### Confluence (`services/confluence.py`)
- Evaluates scenario-based bullish, bearish, and breakout confluence
- Uses exactly 2 selected lines/zones and 1-4 candle timing windows
- Optional liquidity sweep filter

## Configuration
Defined in `core/config.py`.

Important settings:
- `APP_NAME`, `APP_VERSION`, `APP_ENV`, `DEBUG`, `LOG_LEVEL`
- `HOST`, `PORT`
- `CORS_ALLOW_ORIGINS`, `CORS_ALLOW_CREDENTIALS`
- `MARKET_DATA_WORKER_ENABLED`
- `MARKET_DATA_WORKER_POLL_INTERVAL`
- `MARKET_DATA_WORKER_BATCH_SIZE`
- `GATE_SESSION_TTL_SECONDS`
- `SCREENING_MAX_SYMBOLS`

Notes:
- In non-production, localhost origins are allowed by default
- Non-production also enables permissive local origin regex for CORS

## Run

Install:
```bash
pip install -r requirements.txt
```

Start:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```


## Tests
Backend regression tests:
- `tests/test_backend_services.py`

Run:
```bash
python -m unittest tests/test_backend_services.py
```


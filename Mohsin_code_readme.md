# Mohsin Code README

## Project Overview

This repository is a Python/FastAPI backend for a private stock and crypto screening system. It builds a stock or crypto universe, fetches and caches market data, evaluates technical indicators and post-filters, returns screening results to an external frontend, and provides validation tooling for TradingView/Twelve Data/Massive parity checks.

The repository does not contain frontend source code. Frontend behavior is represented by the API contract: the frontend signs users in with Firebase, sends the Firebase UID in `X-User-Id` for settings storage, calls REST endpoints under `/screen` and `/auth`, and may subscribe to `/screen/ws/progress` for scan progress.

There is no RAG or LLM/AI pipeline in the codebase. The "intelligence" in this project is deterministic technical-analysis and filtering logic.

## Technologies And Libraries

- Python 3 backend
- FastAPI for HTTP and WebSocket APIs
- Uvicorn ASGI server
- Pydantic / pydantic-settings for request/response models and environment configuration
- httpx for async HTTP calls, including optional HTTP/2 for Massive/Polygon-compatible APIs
- requests for some maintenance scripts
- numpy for indicator math
- python-dotenv for `.env` loading
- sqlite3 from the Python standard library for local persistent stores
- zoneinfo/tzdata for US Eastern stock-session handling
- unittest for tests

Runtime dependencies are listed in `requirements.txt`.

## Complete Project Structure

```text
.
|-- main.py                         # FastAPI app factory, middleware, routers, health/readiness, lifespan worker
|-- requirements.txt                # Python dependencies
|-- Procfile                        # Deployment command: uvicorn main:app
|-- README.md                       # Short existing backend README
|-- Mohsin_code_readme.md           # This comprehensive code README
|-- api/
|   |-- auth.py                     # User settings and signup invite-key endpoints
|   |-- screening.py                # Screening, details, progress websocket, ops/admin endpoints
|-- core/
|   |-- config.py                   # Environment settings and provider normalization
|   |-- logging_config.py           # stdout/stderr split logging configuration
|-- models/
|   |-- filters.py                  # Screening request models and validation
|   |-- results.py                  # API response/detail models
|-- services/
|   |-- asset_router.py             # Builds stock/crypto universes from local JSON caches
|   |-- stock_reference.py          # Stock sector/category metadata enrichment
|   |-- market_data.py              # Massive/Binance fetching, timeframe mapping, candle shaping, cache orchestration
|   |-- market_data_store.py        # SQLite market-data and indicator cache/interest tables
|   |-- market_data_worker.py       # Background refresh worker
|   |-- screener.py                 # Main screening pipeline and detail builder
|   |-- indicators.py               # Indicator dispatcher/registry and detail evaluation
|   |-- rsi.py                      # RSI calculation and rules
|   |-- macd.py                     # MACD calculation and rules
|   |-- ema.py                      # EMA/SMA/EMA wave rules
|   |-- aroon_oscillator.py         # Aroon oscillator logic
|   |-- wavetrend.py                # WaveTrend logic
|   |-- trendy_adx.py               # ADX/trendy ADX logic
|   |-- vlr.py                      # VLR/custom relative-volume logic
|   |-- volume.py                   # Volume spike, relative volume, current volume
|   |-- volatility.py               # Volatility and volatility-stop logic
|   |-- linear_regression_channel.py# LRC channel calculation
|   |-- regression_channel_dw.py    # DW regression channel calculation
|   |-- linear_regression_candles.py# Linear regression candle indicator
|   |-- trend_channels.py           # TradingView-style trend channel logic
|   |-- channel_line_rules.py       # Line/zone action rules for regression-style channels
|   |-- channel_respect.py          # Channel touch/respect post-filter
|   |-- confluence.py               # Two-channel confluence post-filter
|   |-- dead_assets.py              # Dead/weak asset exclusion filter
|   |-- stock_session.py            # US regular-session filtering and anchored aggregation
|   |-- gate_session_store.py       # SQLite gate-entry session store
|   |-- signup_gate_store.py        # Invite-key signup gate store
|   |-- user_data_store.py          # Per-user settings blob store
|   |-- scan_progress.py            # WebSocket progress broadcaster
|   |-- integration_runtime.py      # Runtime provider enable/pause/call history state
|   |-- utils.py                    # Shared formatting, sticker, confirmation, candle helpers
|   |-- pine_math.py                # PineScript-compatible math helpers
|-- data/
|   |-- zoya_universe.json          # Cached stock universe/compliance data
|   |-- crypto_universe.json        # Cached crypto universe/exchange/category data
|   |-- stock_reference_metadata.json
|   |-- index_constituents.json
|   |-- market_data_cache.db        # Created at runtime; SQLite market-data cache
|   |-- auth.db                     # Created at runtime; SQLite auth/settings/signup data
|-- scripts/
|   |-- update_zoya_universe.py
|   |-- update_crypto_universe.py
|   |-- filter_zoya_universe_by_massive.py
|   |-- enrich_stock_reference_metadata.py
|   |-- set_signup_invite_key.py
|   |-- freeze_twelve_validation.py
|   |-- fetch_massive_validation.py
|   |-- calculate_validation_indicators.py
|   |-- compare_validation_indicators.py
|   |-- compare_validation_screener.py
|   |-- run_validation_pipeline.py
|   |-- fetch_production_screener_fixtures.py
|   |-- build_standard_screener_case_matrix.py
|   |-- build_rsi_filter_matrix.py
|   |-- build_custom_indicator_filter_matrix.py
|   |-- generate_production_screener_reference.py
|   |-- approve_production_screener_reference.py
|   |-- validate_production_screener.py
|   |-- run_production_screener_suite.py
|   |-- run_custom_indicator_suite.py
|   |-- export_tv_validation_sheets.py
|   |-- diagnostic scripts...
|-- validation/
|   |-- README.md
|   |-- spec.py                     # Validation spec contracts
|   |-- fixture_store.py            # Frozen fixture/checksum storage
|   |-- comparison.py               # Indicator comparison
|   |-- alignment.py                # Candle alignment audit
|   |-- twelve/                     # Twelve Data fixture freezing
|   |-- massive/                    # Massive fixture fetching
|   |-- indicators/                 # Backend indicator adapters
|   |-- screener/                   # Screener oracle/comparator helpers
|   |-- fixtures/                   # Frozen validation fixtures and derived results
|-- production_screener_validation/
|   |-- README.md
|   |-- contracts.py                # Validation case/result dataclasses
|   |-- capture.py                  # Massive fixture capture
|   |-- pipeline.py                 # Validation pipeline
|   |-- fixture_store.py
|   |-- reference/                  # Independent reference/oracle engines
|   |-- production/                 # Production screener runner/evidence
|   |-- comparison/                 # Comparators and report writers
|   |-- cases/                      # Example/minimal validation case JSON files
|   |-- data/fixtures/              # Frozen provider fixtures
|   |-- data/golden/                # Approved and candidate golden references
|-- tests/
|   |-- test_backend_services.py
|   |-- test_integration_runtime.py
|   |-- test_indicator_defaults.py
|   |-- test_custom_indicator_matrix.py
|   |-- test_confluence_freshness.py
|   |-- test_candle_timestamp_regression.py
|   |-- test_stock_session.py
|   |-- test_stock_session_anchoring.py
|   |-- test_timeframe_pipeline.py
|   |-- test_trend_channels.py
|   |-- test_trend_channel_evidence.py
|   |-- test_regression_channel_dw.py
|   |-- test_price_lag_diagnostics.py
|   |-- unit/
|-- docs/
|   |-- architecture/               # Planning and architecture documents
|   |-- pinescript/                 # PineScript parity notes
|   |-- report_assets/              # Images/SVGs used in reports
|   |-- extras/
|-- client_report/                  # Client progress reports
```

## Backend Architecture

The backend has five main layers.

1. API layer:
   `main.py` creates the FastAPI app, configures CORS, installs routers, starts/stops the market-data worker, and exposes root/health/readiness endpoints. `api/screening.py` exposes the screening and operations API. `api/auth.py` exposes lightweight settings/signup endpoints.

2. Request/response model layer:
   `models/filters.py` defines `ScreeningRequest` and nested filter configs. It validates asset rules, timeframe rules, manual-symbol limits, confluence shape, stock-only sector/category filters, and exchange normalization. `models/results.py` defines response models for scans, details, options, warnings, and market-data freshness.

3. Orchestration layer:
   `services/screener.py` owns the scan pipeline: build universe, cap symbols, fetch data, drop forming bars where needed, apply price/dead-asset/indicator/post filters, store or consume gate sessions, audit market-data decisions, and build JSON-safe responses.

4. Market-data layer:
   `services/market_data.py` fetches and normalizes candles from Massive and Binance, maps symbols/timeframes, handles snapshots/grouped daily paths, applies stock-session policy, computes candle close/freshness, uses the SQLite cache, and falls back only according to stale-cache settings. `services/market_data_store.py` persists cached candle and indicator snapshots plus refresh-interest rows. `services/market_data_worker.py` keeps important timeframes warm.

5. Indicator/filter layer:
   `services/indicators.py` dispatches selected indicators to dedicated modules. Indicator handlers return pass/fail plus sticker/evidence/warnings. Post-filters such as channel respect, confluence, dead assets, price range, stock categories, sectors, and crypto categories further reduce results.

## Frontend Architecture And Communication

No frontend implementation is present in this repository. The backend is designed for an external web frontend.

Expected frontend integration:

- Firebase Auth performs login, signup, and password reset on the frontend.
- After Firebase signup, the frontend calls `POST /auth/register-account` with `{ uid, email, invite_key }`.
- For user settings, the frontend sends `X-User-Id: <firebase uid>` to `GET /auth/settings` and `POST /auth/settings`.
- For scans, the frontend posts a `ScreeningRequest` to `/screen/run`, `/screen/run-gate`, or `/screen/run-entry`.
- For live progress, the frontend creates a scan id, opens `ws://<host>/screen/ws/progress?scan_id=<id>`, and sends the same id in the scan request header `X-Scan-Id`.
- For admin/ops screens, the frontend must send `X-Admin-Token` when `ADMIN_API_TOKEN` is configured or when production mode requires it.

CORS defaults allow local development origins in non-production and include deployed origins such as `https://screener-123.netlify.app`, `https://tokaplace.com`, and `https://www.tokaplace.com`.

## API Endpoints

### Health And Metadata

- `GET /`
  Returns service status, app name, version, and environment.

- `GET /healthz`
  Liveness check. Returns `{ "status": "ok", "environment": ... }`.

- `GET /readyz`
  Readiness check. Returns worker status and active provider mode. Returns HTTP 503 with `status: degraded` if Massive is required but no API key is configured, or if the worker is enabled but not running.

FastAPI also exposes `/docs`, `/redoc`, and `/openapi.json`.

### Screening

- `POST /screen/run`
  Runs single-timeframe screening. Requires `timeframe_mode: "single"` and `single_timeframe`.

- `POST /screen/run-gate`
  Runs the primary/gate phase of two-timeframe screening. Requires `timeframe_mode: "gate_entry"`, `gate_timeframe`, and `entry_timeframe`. Uses indicators with `timeframe: "primary"`. Returns a `gate_session_id`.

- `POST /screen/run-entry`
  Runs the secondary/entry phase. Requires `timeframe_mode: "gate_entry"` and `gate_session_id` from `/screen/run-gate`. Uses indicators with `timeframe: "secondary"`.

- `POST /screen/details`
  Returns detailed evidence for one symbol/timeframe/stage. Body includes `symbol`, `asset_type`, `timeframe`, optional `scan_stage`, and the original `ScreeningRequest`.

- `GET /screen/crypto-exchanges`
  Lists exchange options from `data/crypto_universe.json` as `{ exchange, coin_count }`.

- `GET /screen/stock-filter-options`
  Lists stock asset category options and available sectors.

- `WebSocket /screen/ws/progress?scan_id=<id>`
  Sends progress messages with `type`, `scan_id`, `timestamp`, `stage`, `message`, and optional `symbol/current/total/detail`.

### Auth And Settings

- `GET /auth/settings`
  Requires `X-User-Id`. Returns the user's stored settings blob from `data/auth.db`.

- `POST /auth/settings`
  Requires `X-User-Id`. Shallow-merges the posted `data` object into the existing settings blob.

- `POST /auth/register-account`
  Verifies the shared invite key and records the Firebase UID/email. The backend does not receive passwords and does not verify Firebase ID tokens.

### Admin / Operations

All ops routes are under `/screen/ops/*` and call `_require_admin`.

- `GET /screen/ops/worker`
  Worker status and whether it is enabled by config.

- `GET /screen/ops/runtime-settings`
  App/server/screening/worker/integration runtime configuration, with API keys masked.

- `GET /screen/ops/integrations`
  Provider runtime snapshot.

- `POST /screen/ops/integrations/config`
  Update provider `enabled`, `paused`, `api_key`, or `call_limit`.

- `GET /screen/ops/integrations/{provider}/history`
  Recent provider errors and response-time history.

- `POST /screen/ops/diagnose`
  Health-style checks for integrations and worker.

- `POST /screen/ops/worker/start`
  Start background worker.

- `POST /screen/ops/worker/stop`
  Stop background worker.

- `POST /screen/ops/worker/refresh`
  Run one manual refresh cycle.

- `POST /screen/ops/worker/config`
  Update runtime worker poll interval or batch size.

- `POST /screen/ops/screening/config`
  Update runtime `SCREENING_MAX_SYMBOLS`.

## Request Model

`ScreeningRequest` fields:

- `asset_type`: `stocks` or `crypto`
- `symbols`: optional manual symbol list. Stocks are uppercased; crypto is normalized to `BASE-USD`.
- `stock_sources`: currently supports only `zoya` when `symbols` is not provided.
- `compliance_status`: `compliant`, `non-compliant`, or `questionable`
- `compliance_standards`: currently only `AAOIFI`
- `exchanges`: optional crypto exchange filter
- `excluded_categories`: optional crypto category exclusion list
- `timeframe_mode`: `single` or `gate_entry`
- `single_timeframe`: required for single mode
- `gate_timeframe`, `entry_timeframe`: required for gate-entry mode
- `gate_session_id`: required for entry
- `indicators`: list of `{ name, timeframe, config }`
- `channel_respect`: optional post-filter
- `confluence`: optional post-filter
- `price_range`: optional min/max price filter
- `dead_assets`: optional dead-asset exclusion filter
- `asset_categories`: stock-only category filters such as `nasdaq`, `nyse`, `amex`, `etf`, `sp500`, `dow_jones`, `russell_2000`
- `sectors`: stock-only sector filters

Timeframes are parsed from values such as `1m`, `15m`, `1h`, `4h`, `1day`, `2day`, `1w`, and `1mo`. In gate-entry mode, `gate_timeframe` must be greater than `entry_timeframe`.

Supported indicator names:

- `rsi`
- `stochrsi`
- `wavetrend`
- `aroon`
- `adx`
- `vlr`
- `ema`
- `ema_wave`
- `sma`
- `macd`
- `volume`
- `relative_volume`
- `current_volume`
- `float`
- `shares_outstanding`
- `volatility`
- `lrc`
- `regression`
- `trend`
- `linreg_candles`

The active candle-based registry in `services/indicators.py` implements all names above except `stochrsi` and `sma` as full candle handlers. `stochrsi` and `sma` are present in the model and snapshot registry, but `/screen/run` rejects unsupported names by checking against the candle registry.

## Response Model

`ScreeningResponse`:

- `results`: list of `ScreeningResult`
- `gate_session_id`: returned by gate runs
- `warnings`: aggregate request and asset warnings

Each result includes:

- symbol, price, asset type, data source
- timeframe and scan stage
- display metadata such as name/category/sector/rank/exchange
- stock compliance metadata such as `compliance_status`, `compliance_standard`, `report_date`, `purification_ratio`
- candle metadata such as `candles_count` and `last_candle_time`
- `stickers` and `matched_indicators`
- `market_data_freshness` with `is_stale`, `stale_age_seconds`, `stale_reason`, `data_source`
- per-result warnings

`ScreeningDetailResponse` expands this with:

- `asset_metadata`
- `request_filters`
- `indicator_details`
- `filter_details`
- `market_data` including recent candles and fundamentals
- computed `channels`
- computed `confluence_channels`

## Core Screening Flow

Single-timeframe flow:

1. Validate `ScreeningRequest`.
2. Build asset universe from manual symbols, Zoya stock cache, or crypto cache.
3. Apply `SCREENING_MAX_SYMBOLS` or `MANUAL_SYMBOLS_MAX`.
4. Choose indicators with `timeframe: "single"`.
5. Compute required candle history from selected filters/indicators.
6. Fetch market data through `fetch_screening_data` and `fetch_live_data`.
7. Attach stock/crypto metadata.
8. Apply price range.
9. Apply dead-asset filter.
10. Apply selected indicators using AND semantics.
11. Apply post-filters: channel respect and confluence.
12. Add filter stickers.
13. Audit market-data outcomes.
14. Build response.

Gate-entry flow:

1. Gate request uses `timeframe: "primary"` indicators against `gate_timeframe`.
2. Passing gate symbols are stored in `gate_sessions` with a TTL and scope hash.
3. Response returns `gate_session_id`.
4. Entry request sends the same request scope plus `gate_session_id`.
5. Entry consumes the session, checks scope hash and optional client id, then evaluates `timeframe: "secondary"` indicators against `entry_timeframe`.
6. Gate sessions are one-time by default. If entry processing raises an exception, the session is restored so the client can retry.

## Data Flow

Typical scan request/response flow:

```text
Frontend
  -> POST /screen/run or /screen/run-gate or /screen/run-entry
  -> FastAPI route validates mode and supported indicators
  -> services.screener builds universe
  -> services.market_data fetches from cache/provider
  -> services.indicators applies configured indicator handlers
  -> services.screener applies post-filters and stickers
  -> JSON response returned to frontend
```

Progress flow:

```text
Frontend opens /screen/ws/progress?scan_id=abc
Frontend sends X-Scan-Id: abc on scan request
scan_progress_scope stores scan id in a ContextVar
pipeline stages call emit_scan_progress
ScanProgressBroadcaster sends JSON messages to websocket subscribers
```

Settings flow:

```text
Firebase frontend gets UID
Frontend sends X-User-Id to /auth/settings
UserDataStore reads/writes data/auth.db:user_settings
```

## Market Data Architecture

`services/market_data.py` is the central market-data module.

Important responsibilities:

- Normalize provider names. `polygon`, `polygon.io`, and `massive.com` map to `massive`.
- Map symbols:
  - Stocks use uppercase tickers such as `AAPL`.
  - Crypto internal symbols use `BTC-USD`.
  - Massive crypto provider symbols use `X:BTCUSD`.
  - Binance symbols use pairs such as `BTCUSDT`.
- Map timeframes to provider formats.
- Normalize raw provider rows into `{ time, open, high, low, close, volume }`.
- Drop malformed candles where OHLC consistency fails.
- Sort and de-duplicate candles by timestamp.
- Decide whether cached payloads are fresh using `next_refresh_at` and actual bucket close rules.
- Support worker-managed cache for `1h`, `4h`, and `1day`.
- Fetch directly for unmanaged timeframes.
- Use fast quote/snapshot paths for latest-only requests.
- Use grouped daily paths for large daily scans where possible.
- Apply stock intraday regular-session policy for TradingView parity.
- Attach market-data freshness metadata.
- Attach Massive fundamentals for float and shares outstanding when needed.

Active providers:

- Stocks: Massive only. Config aliases still accept Polygon naming for compatibility.
- Crypto: Massive or Binance, controlled by `CRYPTO_CANDLES_PROVIDER`.

The background worker seeds all symbols from the cached universes and refreshes due data for `1h`, `4h`, and `1day`.

## Stock Session Handling

`services/stock_session.py` enforces TradingView-style regular-session behavior for stock intraday candles by default.

Important decisions:

- Default policy is `tradingview_regular`.
- Regular session is 09:30 to 16:00 America/New_York.
- Premarket/after-hours rows are filtered out.
- Intraday buckets are anchored to 09:30 ET rather than UTC clock boundaries.
- Session bucket close time is capped at 16:00 ET, so the final daily intraday bucket can be shorter.
- Crypto bypasses stock-session filtering.

Set `STOCK_INTRADAY_SESSION_POLICY=provider_default` to keep provider intraday rows unchanged.

## Database Structure

The project uses SQLite files created automatically under `data/`.

### `data/market_data_cache.db`

Created by `MarketDataStore` and `GateSessionStore`.

`market_data_cache`:

- `symbol TEXT NOT NULL`
- `timeframe TEXT NOT NULL`
- `payload TEXT NOT NULL`
- `updated_at INTEGER NOT NULL`
- primary key: `(symbol, timeframe)`

`indicator_cache`:

- `symbol TEXT NOT NULL`
- `timeframe TEXT NOT NULL`
- `payload TEXT NOT NULL`
- `updated_at INTEGER NOT NULL`
- primary key: `(symbol, timeframe)`

`market_data_interest`:

- `symbol TEXT NOT NULL`
- `timeframe TEXT NOT NULL`
- `last_requested_at INTEGER NOT NULL`
- `last_refreshed_at INTEGER`
- `next_refresh_at INTEGER NOT NULL`
- primary key: `(symbol, timeframe)`
- index: `idx_market_data_interest_refresh`
- index: `idx_market_data_interest_requested`

`indicator_interest`:

- same structure as `market_data_interest`
- indexes: `idx_indicator_interest_refresh`, `idx_indicator_interest_requested`

`gate_sessions`:

- `session_id TEXT PRIMARY KEY`
- `scope_hash TEXT NOT NULL`
- `client_id TEXT`
- `metadata TEXT NOT NULL`
- `created_at INTEGER NOT NULL`
- `expires_at INTEGER NOT NULL`
- index: `idx_gate_sessions_expires_at`

### `data/auth.db`

Created by `UserDataStore` and `SignupGateStore`.

`user_settings`:

- `user_id TEXT PRIMARY KEY`
- `data TEXT NOT NULL`
- `updated_at INTEGER NOT NULL`

`signup_gate`:

- `id INTEGER PRIMARY KEY CHECK (id = 1)`
- `key_salt TEXT NOT NULL`
- `key_hash TEXT NOT NULL`
- `created_at INTEGER NOT NULL`

`registered_accounts`:

- `uid TEXT PRIMARY KEY`
- `email TEXT`
- `created_at INTEGER NOT NULL`

## Authentication And Authorization

This backend intentionally does not implement full authentication.

User auth:

- Login/signup/password reset are expected to happen in Firebase Auth on the frontend.
- The backend trusts the `X-User-Id` header as the user key for settings.
- No Firebase ID token verification is performed.
- This is suitable only for a private/low-stakes deployment unless hardened.

Signup gate:

- New Firebase accounts must call `/auth/register-account`.
- The endpoint verifies a shared invite key.
- Invite keys are stored as PBKDF2-HMAC-SHA256 hashes with a random salt.
- `scripts/set_signup_invite_key.py` updates the invite key.
- If the signup database is fresh, `SignupGateStore.verify_invite_key` auto-seeds the hardcoded default key currently present in code.

Admin auth:

- Ops endpoints use `X-Admin-Token`.
- If `ADMIN_API_TOKEN` is unset in non-production, admin routes are allowed.
- In production, an admin token is required.

## Core Business Logic

The business objective is to screen assets by universe metadata, market-data availability, technical indicators, and post-filter confirmations.

Universe selection:

- Manual `symbols` override normal universe loading.
- Stock universe comes from `data/zoya_universe.json`, filtered by Zoya compliance status and optional stock category/sector metadata.
- Crypto universe comes from `data/crypto_universe.json`, filtered by exchange availability and excluded categories.
- Integration runtime can disable/pause stock and crypto universe caches.

Indicator semantics:

- Selected indicators are compiled from `INDICATOR_REGISTRY`.
- Indicators use AND semantics: one failing indicator rejects the asset.
- Indicator handlers can attach channels, stickers, warnings, and evidence.
- Details endpoint evaluates all selected indicators and returns pass/fail evidence instead of short-circuit-only scan output.

Filters:

- Price range filters by latest price.
- Dead assets excludes assets showing configured weak/dead trend structures.
- Channel respect counts distinct touches against channel lines with tolerance, clustering, and wick/body/both touch modes.
- Confluence requires exactly two selected channel sources and supports bullish, bearish, role-reversal, breakout, or any scenarios.
- Stock asset categories and sectors are both universe filters and detail filter evidence.
- Crypto excluded categories and exchange filters are universe filters and detail evidence.

Gate-entry:

- Gate scans a higher timeframe and stores passing symbols.
- Entry scans a lower timeframe only against gate-passed symbols.
- Scope hashes prevent reusing a gate session with different universe/filter inputs.
- Client identity can be taken from `X-Client-Id`, `X-User-Id`, or request IP.

## Important Functions And Classes

Entry points:

- `main.create_app()`: builds the FastAPI app.
- `main.lifespan()`: starts/stops `MarketDataWorker` and closes HTTP clients.
- `main.build_market_data_worker()`: creates worker from settings.

API:

- `api.screening.run_screening()`: single scan endpoint.
- `api.screening.run_gate_screening()`: gate endpoint.
- `api.screening.run_entry_screening()`: entry endpoint.
- `api.screening.screening_details()`: detailed evidence endpoint.
- `api.screening._require_admin()`: ops auth guard.
- `api.auth.require_user_id()`: settings auth guard.
- `api.auth.register_account()`: invite-key account registration.

Models:

- `models.filters.ScreeningRequest`: main request schema and validation.
- `models.filters.IndicatorConfig`: selected indicator config.
- `models.filters.ChannelRespectFilter`: channel respect config.
- `models.filters.ConfluenceConfig`: confluence config.
- `models.filters.DeadAssetsFilter`: dead asset config.
- `models.results.ScreeningResponse`: scan response.
- `models.results.ScreeningResultDetail`: detailed asset response.

Pipeline:

- `services.screener.run_single()`: single scan orchestration.
- `services.screener.run_gate()`: gate scan orchestration.
- `services.screener.run_entry()`: entry scan orchestration.
- `services.screener.get_asset_detail()`: detailed evidence builder.
- `services.screener.required_candles_for_indicators()`: history budget calculation.
- `services.screener.apply_post_filters()`: channel respect and confluence post-filtering.
- `services.screener.build_response()`: normalized API response builder.

Market data:

- `services.market_data.fetch_live_data()`: cache/provider orchestration.
- `services.market_data.fetch_batches()`: concurrent provider fetching.
- `services.market_data.validate_timeframe()`: timeframe validation.
- `services.market_data.canonicalize_timeframe()`: normalized timeframe formatting.
- `services.market_data.timeframe_bucket_close_unix()`: authoritative candle close time.
- `services.market_data.is_refresh_due()`: freshness decision.
- `services.market_data.normalize_polygon_rows()`: Massive/Polygon row shaping.
- `services.market_data.normalize_binance_rows()`: Binance row shaping.
- `services.market_data.close_market_data_clients()`: shutdown cleanup.

Stores:

- `MarketDataStore`: SQLite market-data and indicator cache.
- `GateSessionStore`: SQLite gate sessions.
- `UserDataStore`: SQLite user settings.
- `SignupGateStore`: SQLite invite key and registered accounts.
- `IntegrationRuntime`: runtime provider status and diagnostics.
- `ScanProgressBroadcaster`: WebSocket progress fanout.

Indicators:

- `services.indicators.apply_indicators()`: scan-time indicator filtering.
- `services.indicators.evaluate_indicator_details()`: detail-time pass/fail evidence.
- `services.indicators.unsupported_indicator_names()`: request guard.
- `services.indicators.INDICATOR_REGISTRY`: candle-based indicator registry.
- Individual compute/evaluate/build-sticker functions live in each indicator module.

## Configuration And Environment Variables

Settings are defined in `core/config.py`, loaded from `.env` at the repository root, and are case-insensitive.

Application:

- `APP_NAME`: default `Private Stock & Crypto Screening System`
- `APP_VERSION`: default `1.0.0`
- `APP_ENV`: default `development`
- `DEBUG`: default `False`; accepts `true/false`, `development/production`, etc.
- `LOG_LEVEL`: default `INFO`
- `HOST`: default `0.0.0.0`
- `PORT`: default `8000`

CORS:

- `CORS_ALLOW_ORIGINS`: comma-separated or JSON list
- `CORS_ALLOW_CREDENTIALS`: default `False`

Market data:

- `MASSIVE_API_KEY`: Massive API key
- `POLYGON_API_KEY`: legacy alias used as fallback for Massive
- `CANDLES_PROVIDER`: stocks provider; normalized to `massive`
- `CRYPTO_CANDLES_PROVIDER`: `massive` or `binance`
- `MARKET_DATA_API_BASE_URL`: default `https://api.massive.com`
- `MARKET_DATA_PROVIDER_DOCS_URL`: default `https://massive.com/docs`
- `BINANCE_API_BASE_URL`: default `https://api.binance.com`
- `BINANCE_PROVIDER_DOCS_URL`: Binance docs URL
- `MASSIVE_FETCH_CONCURRENCY` or `POLYGON_FETCH_CONCURRENCY`
- `BINANCE_FETCH_CONCURRENCY`
- `MASSIVE_HTTP2` or `POLYGON_HTTP2`
- `MASSIVE_REQUESTS_PER_SECOND` or `POLYGON_REQUESTS_PER_SECOND`
- `BINANCE_REQUESTS_PER_SECOND`
- `MASSIVE_CRYPTO_REQUESTS_PER_MINUTE`
- `MASSIVE_CRYPTO_END_OF_DAY_ONLY`
- `MARKET_DATA_FETCH_BATCH_SIZE`
- `ALLOW_STALE_MARKET_DATA`
- `MAX_STALE_MARKET_DATA_AGE_SECONDS`
- `STOCK_INTRADAY_SESSION_POLICY`

Worker:

- `MARKET_DATA_WORKER_ENABLED`
- `MARKET_DATA_WORKER_SEED_UNIVERSE`
- `MARKET_DATA_WORKER_POLL_INTERVAL`
- `MARKET_DATA_WORKER_BATCH_SIZE`

Screening:

- `GATE_SESSION_TTL_SECONDS`
- `SCREENING_MAX_SYMBOLS`
- `MANUAL_SYMBOLS_MAX`

Auth/admin:

- `ADMIN_API_TOKEN`

External data:

- `ZOYA_ENDPOINT`: default `https://api.zoya.finance/graphql`

Validation scripts also reference provider keys such as `TWELVE_DATA_API_KEY`, `MASSIVE_API_KEY`, and `POLYGON_API_KEY`.

Example `.env`:

```env
APP_ENV=development
DEBUG=true
LOG_LEVEL=INFO
PORT=8000
CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:5173
MASSIVE_API_KEY=your_massive_key
CRYPTO_CANDLES_PROVIDER=massive
MARKET_DATA_WORKER_ENABLED=true
ADMIN_API_TOKEN=change_me_for_ops_routes
```

## Installation And Local Setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file if live provider calls are needed.

Start the API:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

Development reload:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or:

```powershell
python main.py
```

Open API docs:

```text
http://localhost:8000/docs
```

## Important Commands

Run all discoverable unittest tests:

```powershell
python -m unittest discover -v
```

Run core backend tests:

```powershell
python -m unittest tests.test_backend_services -v
python -m unittest tests.test_integration_runtime -v
python -m unittest tests.test_indicator_defaults -v
```

Set signup invite key:

```powershell
python scripts/set_signup_invite_key.py
```

Update stock universe:

```powershell
python scripts/update_zoya_universe.py
```

Update crypto universe:

```powershell
python scripts/update_crypto_universe.py
```

Run validation pipeline:

```powershell
python scripts/run_validation_pipeline.py --symbol BTC/USD
```

Run production screener suite:

```powershell
python scripts/run_production_screener_suite.py
```

Deployment command from `Procfile`:

```text
web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

## Testing And Validation

The test suite is based on `unittest`. Many tests patch provider calls and stores, so they run offline.

Important test coverage areas:

- Asset universe building and normalization
- Crypto exchange/category filters
- Stock universe/reference filters
- Request model validation
- Confluence and channel respect behavior
- Dead asset filters
- RSI, MACD, EMA, Aroon, WaveTrend, VLR, volume, volatility, trend-channel logic
- Gate-session behavior
- API smoke tests
- Market-data provider fetching, cache freshness, grouped paths, stale fallback
- Market-data worker behavior
- Stock session anchoring
- Production screener validation contracts

Validation folders:

- `validation/` compares frozen Twelve Data and Massive fixtures against backend indicator outputs.
- `production_screener_validation/` compares production screener behavior against approved independent reference/golden data and writes JSON/Markdown/CSV reports.

Provider fixture commands make API calls only during fixture capture/freezing. Candidate generation, approval, comparison, and most tests are offline.

## Deployment

The project is deployable as a normal ASGI app.

Required deployment pieces:

- Python runtime with dependencies from `requirements.txt`
- Start command from `Procfile`
- Persistent writable `data/` directory if cache, gate sessions, auth settings, and signup records should survive restarts
- `MASSIVE_API_KEY` if Massive is used
- `ADMIN_API_TOKEN` in production
- Correct `CORS_ALLOW_ORIGINS` for frontend domains
- Optional worker tuning environment variables

Readiness:

- Use `/healthz` for liveness.
- Use `/readyz` for readiness. It returns degraded status if required provider credentials are missing or the enabled worker is not running.

Logging:

- `core/logging_config.py` sends DEBUG/INFO to stdout and WARNING+ to stderr so platforms such as Railway classify logs correctly.

## Error Handling

API-level:

- `main.py` registers a global exception handler that logs unhandled exceptions and returns `{"detail": "Internal server error"}` with HTTP 500.
- FastAPI/Pydantic handles validation errors for bad requests.
- Screening routes return HTTP 400 for wrong scan mode, missing gate session id, or unsupported indicators.
- Detail endpoint returns HTTP 404 when asset detail cannot be built.
- Ops routes return HTTP 403 if admin authorization fails.
- WebSocket progress closes with code 1008 for an empty scan id.

Pipeline-level:

- Indicator exceptions are logged and cause that symbol to fail the indicator stage rather than crashing the entire scan.
- Market-data malformed rows are dropped with warnings.
- Failed refreshes can reschedule interest rows with backoff.
- Stale cache fallback is disabled by default and only used when configured.
- Gate sessions are restored if entry processing fails after consuming a session.

Warnings:

- Request-level config warnings are generated for volume, relative volume, current volume, and volatility configurations.
- Asset-level warnings are included in both individual results and aggregate response warnings.
- Market-data freshness metadata tells clients when data is live, fresh cache, or stale cache.

## Implementation Details And Decisions

- Massive is the current stock candle provider; Polygon names remain as compatibility aliases.
- Crypto candles can use Massive or Binance.
- Worker-managed cache is limited to `1h`, `4h`, and `1day`.
- Default stale-cache fallback is disabled to avoid silently serving old market data.
- Stock intraday candles default to TradingView regular-session parity.
- The latest forming candle is removed for scan/detail evaluation where an unclosed bar could create false signals.
- Indicator filtering uses AND semantics.
- Combined validation cases may use independent aggregation when production selected-indicator flow is AND-only.
- Gate sessions include a scope hash so entry scans cannot reuse a gate result with changed universe/filter settings.
- User settings use shallow merge semantics to mirror Firestore `setDoc(..., { merge: true })`.
- API keys are masked in runtime snapshots.
- SQLite is used as an embedded store, so multi-instance deployments need care if shared state is required.
- The code supports Pydantic v2 and includes compatibility paths for Pydantic v1 in models/config.

## Example Requests

Single crypto scan:

```json
{
  "asset_type": "crypto",
  "symbols": ["BTC", "ETH"],
  "timeframe_mode": "single",
  "single_timeframe": "1h",
  "indicators": [
    {
      "name": "rsi",
      "timeframe": "single",
      "config": {
        "length": 14,
        "rule": "oversold",
        "threshold": 30
      }
    }
  ]
}
```

Gate-entry structure:

```json
{
  "asset_type": "stocks",
  "stock_sources": ["zoya"],
  "compliance_status": "compliant",
  "timeframe_mode": "gate_entry",
  "gate_timeframe": "1day",
  "entry_timeframe": "1h",
  "indicators": [
    {
      "name": "trend",
      "timeframe": "primary",
      "config": {
        "length": 8
      }
    },
    {
      "name": "macd",
      "timeframe": "secondary",
      "config": {
        "rule": "bullish_cross"
      }
    }
  ]
}
```

Entry request repeats the same scope and adds the returned `gate_session_id`.

## Maintenance Notes

- Add a new indicator by adding its compute/evaluate code, adding a handler in `services/indicators.py`, adding it to `INDICATOR_REGISTRY`, updating `IndicatorName` in `models/filters.py`, and adding focused tests.
- If the indicator can run from provider snapshot data, also add it to `SNAPSHOT_INDICATOR_REGISTRY`.
- Add a new endpoint in `api/`, include it from `main.py`, and add model definitions under `models/` if needed.
- Add new persistent data carefully because runtime DB files are created under `data/`.
- Keep validation fixtures immutable once approved. Golden approval exists to make expected-result changes explicit.

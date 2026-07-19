# Client Deliverables and Full App Logic

## 1) What will be Delivered

This project is a complete stock + crypto screening platform with:

- FastAPI backend (`/screen/*`) for screening, gate/entry workflow, worker ops, and runtime introspection.
- React frontend with authenticated access, filter builder, indicator configuration, scan execution, result analysis, and export.
- Firebase Auth + Firestore integration for user login and user-specific settings/presets.
- Local JSON universes for stock/crypto assets.
- SQLite-backed candle cache + background market-data worker.
- Full indicator parameter surface in UI (including the sub-filters requested in feedback).
- Strict crypto exchange filtering behavior (only assets listed on selected exchanges).
- Custom timeframe support (minutes/hours/days/weeks/months).

Frontend deployment reference provided by developer:

- `https://screener-123.netlify.app/`
- (i have updated it after your feedback) You can go through the website and highlight what options should be added or removed.

## 2) Feedback Coverage Summary

From the provided PDF feedback, the following requested areas are now implemented:

- RSI sub-filters:
  - speed/length, candle window, optional confirmation, confirmation window.
- Aroon sub-filters:
  - candle window, optional confirmation behavior.
- WaveTrend sub-filters:
  - candle window, optional confirmation, confirmation window.
- Linear Regression Channel (LRC):
  - upper/lower deviation parameters, R-filter options (`ignore`, `min`, `range`), touch details, window, confirmation, tolerance.
- Regression Channel:
  - touch details, window, confirmation, tolerance, breach behavior.
- Linear Regression Candles:
  - close location, window semantics, confirmation options.
- Trend Channels:
  - full area selection (`top/middle/bottom lines`, `top/bottom zones`) with per-area rule blocks, touch/breach details, time window, confirmation, tolerance.
- Timeframe customization:
  - built-in presets plus custom units (m/h/d/w/mo) in frontend, and backend parsing/aggregation support.
- Match-rule behavior:
  - selected rules/lines must all pass; if one fails, symbol is excluded.

## 3) End-to-End Architecture

## 3.1 Backend

- Framework: FastAPI
- Main entry: `backend/main.py`
- API router: `backend/api/screening.py`
- Core pipeline: `backend/services/screener.py`
- Indicators engine: `backend/services/indicators.py`
- Data fetch/cache: `backend/services/market_data.py`, `backend/services/market_data_store.py`
- Background worker: `backend/services/market_data_worker.py`
- Gate session persistence: `backend/services/gate_session_store.py`
- Universe routing: `backend/services/asset_router.py`

## 3.2 Frontend

- Framework: React + Vite + TypeScript
- App shell/routes: `frontend/src/App.tsx`
- Main workspace: `frontend/src/pages/Index.tsx`
- Settings/control dashboard: `frontend/src/pages/SettingsPage.tsx`
- Core state + API execution: `frontend/src/hooks/useScreener.ts`
- Indicator schema/defaults: `frontend/src/types/screener.ts`
- Authentication: Firebase Auth (`frontend/src/contexts/AuthContext.tsx`)
- User settings persistence: Firestore (`frontend/src/hooks/useUserSettings.ts`)

## 4) Business Workflow Logic

## 4.1 Screening Modes

- `single` mode:
  - one timeframe run using indicators set to `timeframe="single"`.
- `gate_entry` mode:
  - gate run uses indicators set to `timeframe="primary"`.
  - entry run uses indicators set to `timeframe="secondary"`.
  - entry requires `gate_session_id` returned by gate.
  - gate session is one-time consumable and TTL-bound.

## 4.2 Pipeline Order (Backend)

For each run:

1. Build universe from local stock/crypto files.
2. Apply symbol cap (`SCREENING_MAX_SYMBOLS`).
3. Fetch candles from cache/Massive for requested timeframe.
4. Attach universe metadata to fetched rows.
5. Apply selected indicators (AND logic across selected indicators).
6. Apply optional post-filters (`channel_respect`, `confluence`).
7. Return normalized response rows with stickers and metadata.

## 5) Universe and Asset Filtering Logic

## 5.1 Stocks

- Source currently supported: `zoya` only.
- Universe file: `backend/data/zoya_universe.json`.
- Optional compliance filtering:
  - `compliant`, `non-compliant`, `questionable`.
- Output metadata includes:
  - symbol, name, exchange, compliance status, report date, purification ratio.

## 5.2 Crypto

- Universe file: `backend/data/crypto_universe.json`.
- Each symbol is normalized to Massive-compatible USD market symbols like `<SYMBOL>-USD`.
- Category exclusion filter supported.
- Exchange filter is strict:
  - selected exchanges must intersect asset exchange availability.
  - if exchange availability is missing, asset is excluded.
- Output metadata includes:
  - symbol, name, category, cmc_id, selected exchange display string, exchange availability list.

## 6) Indicator Logic (Delivered)

All indicator configs are fully editable in UI and sent as `config` payload.

## 6.1 RSI (`rsi`)

- Parameters:
  - `length`, `location`, `direction`, `window`, `confirmation`, `confirmation_types`, `confirmation_window`.
- Window semantics:
  - condition must occur within the last `N` candles, not necessarily every candle.
- Confirmation:
  - evaluated after matching signal candle inside configured confirmation window.

## 6.2 WaveTrend (`wavetrend`)

- Parameters:
  - `channel_length`, `average_length`, `signal_length`, `zone`, `direction`, `window`, confirmation settings.
- Supports direction including cross logic (`crossed_up`, `crossed_down`).
- Uses within-window match behavior.

## 6.3 Aroon Oscillator (`aroon`)

- Parameters:
  - `length`, `level`, `direction`, `window`, confirmation settings.
- Uses within-window match behavior.

## 6.4 Linear Regression Channel (`lrc`)

- Parameters:
  - `length`, `upper_dev`, `lower_dev`, `lines`, `action`, `touch_type`, `window`, `tolerance`, `r_mode`, `r_min`, `r_max`, confirmation settings.
- Multi-line match rule:
  - every selected line must match within window; any failure excludes symbol.
- R filter:
  - `ignore`, `min`, or bounded `range`.

## 6.5 Regression Channel (`regression`)

- Parameters:
  - `length`, `width_coeff`, `lines`, `action`, `touch_type`, `window`, `tolerance`, confirmation settings.
- Same “all selected lines must pass” behavior as LRC.

## 6.6 Trend Channel (`trend`)

- Parameters:
  - `length`, `areas` (list of per-area rule blocks).
- Area support:
  - `top_line`, `middle_line`, `bottom_line`, `top_zone`, `bottom_zone`.
- Per-area controls:
  - `action`, `window`, `tolerance`, `touch_type`, `breach_type`, `breach_direction`, confirmation settings.
- Rule logic:
  - every configured area rule must pass.

## 6.7 Linear Regression Candles (`linreg_candles`)

- Parameters:
  - `lr_length`, `signal_smoothing`, `price_position`, `close_location`, `window`, confirmation settings.
- Includes close-location sub-filter and within-window behavior.

## 6.8 EMA (`ema`)

- Parameters:
  - `length`, `rule` (`above`, `below`, `touch`).

## 6.9 MACD (`macd`)

- Parameters:
  - `rule`, `fast`, `slow`, `signal`.
- Supported rules:
  - `bullish_cross`, `bearish_cross`, `above_zero`, `below_zero`.

## 6.10 Volume Family

- `volume` (spike):
  - `length`, `multiplier`.
- `relative_volume`:
  - `length`, `min_ratio`.
- `current_volume`:
  - `min_value`, `max_value`.
- `float`:
  - `min_value`, `max_value` (uses fetched fundamentals when available).
- `shares_outstanding`:
  - `min_value`, `max_value`.
- `volatility`:
  - `length`, `min_pct`, `max_pct`.

## 7) Confirmation and Match Rules (Global)

- Confirmation engine supports:
  - `bullish`, `bearish`, `strong_bullish`, `strong_bearish`.
- Confirmation checks future candles after signal index up to `confirmation_window`.
- Indicator-level matching is AND:
  - if any selected indicator fails, symbol is excluded.
- Multi-option sub-rules (like selected lines/areas) require all configured blocks to pass.

## 8) Advanced Post-Filters

## 8.1 Channel Respect

- Optional post-filter after indicators.
- Config:
  - `channel_type`, `line`, `min_respect`, `max_respect`, `tolerance_pct`, `cluster_gap`.
- Counts touches against chosen channel line and filters by touch count range.

## 8.2 Confluence

- Optional post-filter after indicators.
- Config:
  - `type` (`bullish`, `bearish`, `breakout`, `any`), exactly 2 selected sources, per-source line/zone selection, 1-4 candle lookback, optional `liquidity_sweep`.
- Evaluates scenario-based support/resistance confluence across the two selected lines/zones and applies post-condition maintenance checks.

## 9) Timeframe Support

Frontend:

- Presets: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1day`.
- Custom entry:
  - `<number><unit>` where unit can be `m`, `h`, `d`, `w`, `mo`.

Backend:

- Parses both preset and custom timeframe text.
- Maps custom units to Massive aggregate ranges.
- Aggregates candles for higher timeframes when needed.
- `4h` derived by aggregating `1h` candles.

## 10) Market Data and Caching

- Provider: Massive.
- Storage: SQLite DB `backend/data/market_data_cache.db`.
- Strategy:
  - cache-first reads.
  - refresh when due (`next_refresh_at` / freshness logic).
  - stale fallback with backoff if refresh fails.
- Retention and TTL:
  - timeframe-specific TTL/retention policies in store layer.
- Concurrency:
  - configurable Massive fetch concurrency via runtime settings.

## 11) Background Worker and Operations

Worker capabilities:

- Seeds universe/timeframe interest rows.
- Periodically refreshes due symbols.
- Prunes stale cached entries.

Runtime controls:

- Start/stop worker.
- Force refresh now.
- Update poll interval/batch size at runtime.

Ops endpoints (under `/screen`):

- `GET /ops/worker`
- `POST /ops/worker/start`
- `POST /ops/worker/stop`
- `POST /ops/worker/refresh`
- `POST /ops/worker/config`
- `GET /ops/runtime-settings`

## 12) API Endpoints Delivered

Public screening endpoints:

- `POST /screen/run` (single mode)
- `POST /screen/run-gate` (gate phase)
- `POST /screen/run-entry` (entry phase)

Service health endpoints:

- `GET /`
- `GET /healthz`
- `GET /readyz`

Protected ops endpoints:

- listed in Section 11.

Admin protection behavior:

- If `ADMIN_API_TOKEN` is configured on backend:
  - ops endpoints require header `X-Admin-Token`.
- If token is not configured:
  - ops endpoints are open.

## 13) Frontend Client Deliverables

## 13.1 Main Workspace

- Asset selection: stocks/crypto.
- Compliance selection for stocks.
- Exchange + category filters for crypto.
- Single vs gate-entry timeframe mode.
- Custom timeframe editors.
- Add/remove/reorder indicator blocks with per-indicator settings.
- Advanced filters: channel respect + confluence.
- Run controls:
  - single scan (`Run Scan`) or `Gate` then `Entry`.
- Results experience:
  - search, sort, pagination, compact/table modes, compare tray, detail panel.
- Export:
  - downloadable Excel-compatible `.xls` output.

## 13.2 Presets and User Settings

- Save/load/delete full filter presets per user.
- Persisted in Firestore document by authenticated user UID.

## 13.3 Settings / Control Dashboard

- Health and readiness checks.
- Runtime settings payload viewer.
- API controls:
  - admin token, API base override, timeout, retries.
- Worker controls:
  - poll interval, batch size, apply config/start/stop/refresh.
- Full indicator defaults JSON editor.
- Auth account actions:
  - reset password, logout.

## 13.4 Connectivity and Fallback Behavior

- Connection badge checks backend root endpoint on interval.
- If backend is unavailable by network failure:
  - frontend shows expanded sample results for both stocks and crypto.
  - sample data includes realistic exchange availability fields and stickers.

## 14) Authentication and Persistence

- Auth provider: Firebase Email/Password.
- Protected app routes require authenticated user.
- User settings + presets stored in Firestore (`users/{uid}`).
- Local runtime control copies also stored in browser localStorage for active session behavior.

## 15) Environment and Configuration

## 15.1 Backend `.env` (key operational values)

- `HOST`, `PORT`
- `APP_ENV`, `DEBUG`, `LOG_LEVEL`
- `CORS_ALLOW_ORIGINS`, `CORS_ALLOW_CREDENTIALS`
- `MARKET_DATA_WORKER_ENABLED`
- `MARKET_DATA_WORKER_POLL_INTERVAL`
- `MARKET_DATA_WORKER_BATCH_SIZE`
- `GATE_SESSION_TTL_SECONDS`
- `SCREENING_MAX_SYMBOLS`
- `ADMIN_API_TOKEN`
- Integration key flags:
- `ZOYA_API_KEY`, `COINMARKETCAP_API_KEY`

## 15.2 Frontend `.env`

Required Firebase values:

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_STORAGE_BUCKET`
- `VITE_FIREBASE_MESSAGING_SENDER_ID`
- `VITE_FIREBASE_APP_ID`

API base:

- `VITE_API_BASE` optional in dev, required in production.

## 16) Client Acceptance Checklist

1. Authentication:
   - Sign up/sign in/sign out and password reset.
2. Asset filters:
   - Switch stocks/crypto and validate conditional filter panels.
3. Timeframes:
   - Test preset and custom inputs (e.g., `45m`, `2h`, `3d`, `1w`, `1mo`).
4. Indicator controls:
   - Add each major indicator and confirm full parameter UI is available and retained.
5. Gate-entry flow:
   - Run gate then entry and verify entry requires gate session.
6. Exchange strict mode:
   - Select exchange(s), verify only listed pairs are returned.
7. Advanced filters:
   - Validate channel respect and confluence filter behavior.
8. Settings dashboard:
   - Check health/readiness, runtime settings payload, worker controls.
9. Indicator defaults:
   - Save custom defaults, add fresh indicator, confirm defaults applied.
10. Offline fallback:
   - Stop backend and confirm sample results appear with explanatory status.




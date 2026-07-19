# Project File Information

This document lists the files in both the backend and frontend directories of the `crypto_project` with a one-line explanation of their purpose.

## Backend Codebase (`/backend`)

### Core & Application Setup
* [main.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/main.py) - Entry point for the FastAPI application, managing middleware, lifecycles, and background worker state.
* [core/config.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/core/config.py) - Loads and parses application settings, default thresholds, and API keys from environment variables.
* [core/logging_config.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/core/logging_config.py) - Configures the standardized logging format and verbosity levels for the application.
* [test.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/test.py) - Standard validation script used to run quick checks on core backend modules.

### API Layer
* [api/screening.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/api/screening.py) - Defines the HTTP endpoints for running scans, retrieving asset details, and updating configurations.

### Data Models
* [models/filters.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/models/filters.py) - Declares the Pydantic models, schemas, and custom validation rules for incoming screening requests.
* [models/results.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/models/results.py) - Defines structural schemas for screening outputs, indicator status reports, and asset metadata.

### Services (Core Logic & Indicators)
* [services/aroon_oscillator.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/aroon_oscillator.py) - Computes Aroon Oscillator technical indicator values and evaluates rules.
* [services/asset_router.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/asset_router.py) - Handles resolving and filtering available stock and crypto symbols from local cache files.
* [services/channel_respect.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/channel_respect.py) - Evaluates whether price candles respect boundary lines of channels (regression or trend).
* [services/confluence.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/confluence.py) - Determines if multiple separate indicator criteria align to create trading signals (bullish/bearish).
* [services/ema.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/ema.py) - Calculates Exponential Moving Averages (EMA) and verifies trend direction crossovers.
* [services/gate_session_store.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/gate_session_store.py) - Tracks active scanning sessions, gates, and statuses using an SQLite-backed store.
* [services/indicators.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/indicators.py) - Primary driver for computing technical analysis indicators (RSI, WaveTrend, MACD, etc.).
* [services/integration_runtime.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/integration_runtime.py) - Manages the configuration, state, and rate limits for third-party market data APIs.
* [services/linear_regression_candles.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/linear_regression_candles.py) - Computes Linear Regression Candles (LRC) and signal lines for trend assessment.
* [services/macd.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/macd.py) - Calculates the Moving Average Convergence Divergence (MACD) oscillator and signal line.
* [services/market_data.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/market_data.py) - Fetches live and historical candle data from Polygon/Massive and Binance APIs.
* [services/market_data_store.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/market_data_store.py) - Implements local SQLite database storage for caching fetched market candle data.
* [services/market_data_worker.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/market_data_worker.py) - Periodic background worker that updates cached candles for configured universes.
* [services/regression_channels.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/regression_channels.py) - Fits linear regression channels (DW channels, LRC channels) to asset price paths.
* [services/rsi.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/rsi.py) - Calculates the Relative Strength Index (RSI) momentum oscillator.
* [services/screener.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/screener.py) - Orchestrates the full screening pipeline, filtering assets against custom parameters.
* [services/trend_channels.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/trend_channels.py) - Detects dynamic trend channels, support/resistance levels, and channel breakdowns.
* [services/utils.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/utils.py) - Common mathematical helper routines and string formattings.
* [services/volume.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/volume.py) - Evaluates volume spikes relative to moving averages.
* [services/wavetrend.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/wavetrend.py) - Computes the WaveTrend technical oscillator to find potential overbought/oversold levels.

### Data & Automation Scripts
* [data/crypto_universe.json](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/data/crypto_universe.json) - Saved JSON list of tracked cryptocurrency symbols and names.
* [data/zoya_universe.json](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/data/zoya_universe.json) - Local cache of Shariah-compliant halal stocks from Zoya.
* [scripts/filter_zoya_universe_by_massive.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/scripts/filter_zoya_universe_by_massive.py) - Filters the Zoya stock universe to symbols available on Polygon/Massive.
* [scripts/update_crypto_universe.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/scripts/update_crypto_universe.py) - Script that queries exchanges/CoinMarketCap to update the list of active crypto assets.
* [scripts/update_zoya_universe.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/scripts/update_zoya_universe.py) - Script that updates Shariah compliance status and metadata from Zoya and CoinMarketCap APIs.

---

## Frontend Codebase (`/frontend`)

### Root & Configurations
* [src/main.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/main.tsx) - The React DOM entry point that boots the client app.
* [src/App.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/App.tsx) - Main application layout routing structure and global context providers.
* [src/App.css](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/App.css) - General application-wide styles and override styles.
* [src/index.css](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/index.css) - Base styling file containing Tailwind CSS directives and theme variables.
* [src/config/env.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/config/env.ts) - Reads and parses frontend environment variables (like API hosts and Firebase keys).
* [src/vite-env.d.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/vite-env.d.ts) - TypeScript definitions for Vite-specific environment variables.

### Contexts, Hooks & Libraries
* [src/contexts/AuthContext.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/contexts/AuthContext.tsx) - React context managing Firebase authentication sessions (sign in, sign up, log out).
* [src/hooks/useScreener.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/hooks/useScreener.ts) - Custom hook orchestrating api state, filters, run controls, and fetched results.
* [src/hooks/useUserSettings.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/hooks/useUserSettings.ts) - Manages setting and retrieving customized default filters and credentials.
* [src/hooks/use-mobile.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/hooks/use-mobile.tsx) - Hook utility checking window dimensions to identify mobile viewports.
* [src/hooks/use-toast.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/hooks/use-toast.ts) - Handles state and triggers for Toast alerts.
* [src/lib/firebase.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/lib/firebase.ts) - Initializes and exports Firebase Authentication and Firestore client SDK instances.
* [src/lib/utils.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/lib/utils.ts) - Generic client-side helpers, including tailwind classes merging.

### Types
* [src/types/screener.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/types/screener.ts) - Declares TypeScript interfaces/enums matching the server API and components.

### Pages
* [src/pages/Index.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/pages/Index.tsx) - The primary screening page dashboard with filter panel, results grid, and detail views.
* [src/pages/AuthPage.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/pages/AuthPage.tsx) - Login, sign up, and password recovery interface.
* [src/pages/SettingsPage.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/pages/SettingsPage.tsx) - User interface for overriding API credentials and adjusting default screener settings.
* [src/pages/NotFound.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/pages/NotFound.tsx) - Simple fallback page shown when navigations target non-existent routes.

### Components
* [src/components/ErrorBoundary.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/ErrorBoundary.tsx) - Component catching React component tree errors to show a fallback UI.
* [src/components/NavLink.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/NavLink.tsx) - Custom navigation links that reflect the active router path.
* [src/components/auth/ProtectedRoute.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/auth/ProtectedRoute.tsx) - Guards routes from unauthenticated users, routing them to the authentication page.
* [src/components/layout/AppHeader.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/layout/AppHeader.tsx) - Global navigation bar containing page links, brand identity, and user controls.
* [src/components/screener/ConnectionStatus.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/ConnectionStatus.tsx) - Displays the current API connection health status and ping latency.
* [src/components/screener/FilterSidebar.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/FilterSidebar.tsx) - Left sidebar wrapper housing the various indicator, compliance, and asset filters.
* [src/components/screener/PresetBar.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/PresetBar.tsx) - Bar presenting action triggers for saving and choosing screen filters presets.
* [src/components/screener/ResultDetailPanel.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/ResultDetailPanel.tsx) - Shows comprehensive detail grids and charts for a single screened asset.
* [src/components/screener/ResultsTable.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/ResultsTable.tsx) - Renders the main dataset grid with full sorting, paging, and column structures.
* [src/components/screener/RunControls.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/RunControls.tsx) - Start, stop, and status control panel for active screening queries.
* [src/components/screener/indicatorColors.ts](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/indicatorColors.ts) - Visual utility for mapping color status codes.

#### Screener Filters
* [src/components/screener/filters/AssetTypeFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/AssetTypeFilter.tsx) - Form UI for checking Stocks and/or Crypto asset flags.
* [src/components/screener/filters/ChannelRespectFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/ChannelRespectFilter.tsx) - Input parameters for Trend Channel and Regression Channel respect criteria.
* [src/components/screener/filters/CheckboxGroup.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/CheckboxGroup.tsx) - Generic component managing groupable option list inputs.
* [src/components/screener/filters/ComplianceFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/ComplianceFilter.tsx) - UI selection inputs for Halal (Zoya Shariah compliant) filter status.
* [src/components/screener/filters/ConfluenceFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/ConfluenceFilter.tsx) - Parameters to manage multi-indicator confluence modes.
* [src/components/screener/filters/CryptoExchangeFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/CryptoExchangeFilter.tsx) - Select options for listing assets available on target exchanges (e.g. Gate.io).
* [src/components/screener/filters/EthicalFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/EthicalFilter.tsx) - Component managing options for ethical screenings.
* [src/components/screener/filters/IndicatorsFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/IndicatorsFilter.tsx) - UI fields to tune specific technical oscillators (RSI, WaveTrend, MACD, Vol, LRC, EMA).
* [src/components/screener/filters/PriceRangeFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/PriceRangeFilter.tsx) - Inputs specifying min/max allowed price values.
* [src/components/screener/filters/TimeframeFilter.tsx](file:///c:/Programming/Projects/02_GROWING/crypto_project/frontend/src/components/screener/filters/TimeframeFilter.tsx) - Handles timeframe selections (e.g. daily, 4-hour, weekly).

#### Shared UI Elements
* Found under `src/components/ui/` - Contains the generic layout components generated via Shadcn (e.g. Buttons, Tabs, Accordions, Dialogs, Cards, Sidebars, Table elements, etc.).

# Approach 2: Verification of Indicator Calculations and Screening Logic via Exported Table Data

This document outlines how to use TradingView-style table data (as shown in table view screenshots or downloaded CSV exports) to validate that the backend screener matches reference calculations and filters stocks correctly.

---

## 1. Executive Summary of Findings

Following a complete scan of the indicator codebase, we verified that:
* The codebase supports **18 indicator families** (15 standard ones listed in `approach_1.md` plus 3 snapshot-only indicators found in `SNAPSHOT_INDICATOR_REGISTRY`).
* Full validation against TradingView table views is **highly possible** for all price-based indicators, provided a sufficient historical "warm-up" period is supplied.
* Validation is **not possible** for volume-based indicators (when using screenshot-only tables lacking a volume column) or fundamental-based filters (which are static asset metadata).

---

## 2. What is Possible (And How?)

### A. Price- and Volume-Based Indicators (OHLCV)
Any indicator that relies strictly on price series (Open, High, Low, Close) and Volume can be verified by importing the table data.

* **Indicators Covered:** `rsi`, `aroon`, `wavetrend`, `lrc`, `regression`, `trend`, `linreg_candles`, `ema`, `sma`, `macd`, `stochrsi`, `adx`, `volatility`, `volume`, `relative_volume`, and `current_volume`.
* **How to Verify:**
  1. Export the table data as a CSV from TradingView (ensuring the standard Volume indicator is active).
  2. Parse the CSV rows into a list of candle dictionaries containing `open`, `high`, `low`, `close`, and `volume`.
  3. Instantiate the corresponding handler from [indicators.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/indicators.py) with the targeted configuration.
  4. Compare the calculated values on the most recent date against the values displayed in the TradingView chart/table on that same date.

### B. Candlestick Patterns & Confirmation Logic
Since the table view contains Open, High, Low, and Close for sequential days, it contains all information necessary to detect candlestick patterns.

* **How to Verify:**
  1. Extract OHLC values for the current day and the preceding 2 days (needed for 3-candle patterns like Morning/Evening Star).
  2. Pass the sequence into the `detect_candlestick_patterns` function in [utils.py](file:///c:/Programming/Projects/02_GROWING/crypto_project/backend/services/utils.py#L159).
  3. Validate that patterns (e.g. Bullish Engulfing, Hammer) are triggered on the correct bars.
  4. Verify that the `confirm_if_needed` helper accurately delays/restricts indicator signals according to the configured confirmation type or patterns.

---

## 3. What is NOT Possible (And Why?)

### A. Volume-Based Indicators (when using Net Volume)
* **Indicators affected:** `volume`, `relative_volume`, `current_volume`.
* **Why it can fail:** If your exported reference data contains **Net Volume** instead of standard total Volume, it will **not work**. Net Volume contains positive and negative values (buying volume minus selling volume, e.g. `-17.41 K`), whereas standard volume indicators in the backend expect **Total Volume** (which is always non-negative). Using Net Volume will break averages and ratio calculations.
* **How to circumvent:** You must ensure the standard "Volume" indicator (total volume) is added to your TradingView chart and its columns are exported. Do not use Net Volume.

### B. Fundamental Indicators
* **Indicators affected:** `float`, `shares_outstanding`.
* **Why:** These represent static company metadata (`float_shares` and `shares_outstanding`) sourced from fundamental databases (e.g. Zoya or asset metadata). They do not exist on price charts or historical price tables.
* **How to circumvent:** These must be validated against the raw API responses or database tables (such as `zoya_universe.json` or sqlite cache) rather than chart exports.

### C. Live/Intraday Timeframe Parity
* **Why:** A daily chart table view export (`1D` timeframe) cannot be used to validate a screener running on intraday charts (e.g., `5m` or `1h`).
* **How to circumvent:** You must ensure that the TradingView table view is set to the *exact same timeframe* as the backend screener request before downloading/taking a screenshot.

---

## 4. The "Warm-up" / Smoothing Constraint

> [!WARNING]
> Simple manual verification on short datasets (like the 15 rows visible in screenshots) will lead to mathematical discrepancies.

Indicators like **RSI**, **EMA**, **MACD**, and **ADX** use exponential smoothing formulas. Each new value is mathematically dependent on the previous calculated value.
* For example, the Wilder's smoothing used in the 14-period RSI means the RSI value at index $t$ depends on all RSI values from index $0$ to $t-1$.
* If you only supply 15 candles, the initial average gain/loss calculation has no historical context, resulting in a different value compared to TradingView (which has thousands of historical candles).
* **Rule of Thumb:** Always supply a **minimum of 50 to 100 historical candles** before the target validation bar to ensure the calculations stabilize and match TradingView to two decimal places.

---

## 5. Complete Field Reference for Verification

When setting up test fixtures, ensure the config dictionary contains the exact fields parsed by the backend:

| Indicator Family | Supported Configuration Fields (Scanned from Code) |
| :--- | :--- |
| **`rsi`** | `length` (default 14), `location` (`oversold`\|`neutral`\|`overbought`), `direction` (`rising`\|`falling`\|`turning_up`\|`turning_down`), `tolerance_pct`, `window` (default 1), `confirmation` (bool), `confirmation_type`, `confirmation_types`, `confirmation_patterns`, `confirmation_window` |
| **`aroon`** | `length` (default 14), `level` (`above_50`\|`between_50_0`\|`near_0`\|`between_0_-50`\|`below_-50`), `direction` (`rising`\|`falling`\|`turning_up`\|`turning_down`), `tolerance_pct`, `window`, `confirmation`, `confirmation_type`, `confirmation_types`, `confirmation_patterns`, `confirmation_window` |
| **`wavetrend`** | `channel_length` (default 10), `average_length` (default 21), `signal_length` (default 4), `zone` (`oversold`\|`neutral`\|`overbought`), `direction` (`rising`\|`falling`\|`turning_up`\|`turning_down`\|`crossed_up`\|`crossed_down`), `tolerance_pct`, `window`, `confirmation`, `confirmation_type`, `confirmation_types`, `confirmation_patterns`, `confirmation_window` |
| **`lrc`** | `length` (default 100), `upper_dev` (default 2.0), `lower_dev` (default 2.0), `min_r`, `max_r`, `lines` (list: e.g. `["middle", "upper", "lower"]`), `action` (`touch`\|`close_above`\|`close_below`\|`stay_above`\|`stay_below`), `tolerance` (float), `touch_type` (`wick`\|`body`\|`both`), `window`, `confirmation`, `confirmation_type`, `confirmation_types`, `confirmation_patterns`, `confirmation_window` |
| **`regression`** | `length` (default 200), `width_coeff` (default 1.0), `window_type` (`continuous`\|`interval`), `interval_step` (default 1), plus all shared regression fields (`lines`, `action`, `tolerance`, `touch_type`, `window`, `confirmation`, `confirmation_window`, etc.) |
| **`trend`** | `length` (default 8), `wait_for_break` (bool), `show_last_channel` (bool), `areas` (list of dicts containing: `area`, `action`, `window`, `touch_type`, `breach_type`, `breach_direction`, `confirmation`, `confirmation_window`, `confirmation_type`, etc.) |
| **`linreg_candles`**| `lr_length` (default 11), `signal_smoothing` (default 7), `price_position` (`above`\|`below`\|`on`\|`piercing_from_below`\|`piercing_from_above`), `close_location` (`close_above`\|`close_below`\|`close_on`), `tolerance_pct`, `window`, `confirmation`, `confirmation_window`, `confirmation_type`, etc. |
| **`ema`** | `length` (default 9), `rule` (`above`\|`below`\|`touch`), `tolerance_pct` |
| **`sma`** | `length` (default 50), `rule` (`above`\|`below`\|`touch`), `tolerance_pct` *(Snapshot only)* |
| **`macd`** | `fast` (default 12), `slow` (default 26), `signal` (default 9), `rule` (`bullish_cross`\|`bearish_cross`\|`above_zero`\|`below_zero`), `tolerance_pct` |
| **`stochrsi`** | `rule` (`oversold`\|`overbought`\|`bullish_cross`\|`bearish_cross`), `threshold` *(Snapshot only)* |
| **`adx`** | `rule` (`above`\|`below`\|`rising`\|`falling`), `threshold` (default 25) *(Snapshot only)* |
| **`volume`** | `length` (default 20), `multiplier` (default 2.0), `tolerance_pct` |
| **`relative_volume`**| `length` (default 20), `min_ratio` (default 1.5), `tolerance_pct` |
| **`current_volume`** | `min_value`, `max_value`, `tolerance_pct` |
| **`volatility`** | `length` (default 20), `min_pct` (default 0), `max_pct`, `tolerance_pct` |
| **`float`** | `min_value`, `max_value`, `tolerance_pct` (Evaluated on `float_shares` field) |
| **`shares_outstanding`**| `min_value`, `max_value`, `tolerance_pct` (Evaluated on `shares_outstanding` field) |

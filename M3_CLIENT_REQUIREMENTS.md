# Milestone 3 — Client Requirements vs. Current Codebase

**Purpose:** Gap analysis of the new scanner requirements (EMA filters, channel line/zone interaction filters, Trendy ADX updates, ADR $, Repeated True Empty-Space Gap Exclusion) against what actually exists today in `stock-crypto-screening-tokaplace-api` and `stock-crypto-screening-tokaplace-frontend`.

**Source requirement documents:**
- `stock_crypto_scanner_docx_source_spec.md`
- `stock_crypto_scanner_document_only_spec.md`
- `stock_scanner_final_engineering_requirements.md`
- `stock_crypto_scanner_charts_and_visuals.pdf`

**Method:** Four codebase investigations (EMA, Channel indicators, Trendy ADX, ADR/Gap) were run against the current backend and frontend source. Findings below cite exact `file:line` evidence. Nothing in this document is inferred beyond what the investigations found in code.

**Overall headline:** Almost none of the Milestone 3 behavioral requirements exist yet. Two filters (ADR $, Gap Exclusion) don't exist at all. The EMA filter exists only as a single crude "latest candle vs EMA" check with a live-candle bug. The three channel indicators (Linear Regression Channel, Trend Channel + zones, Regression Channel) have a shared rule engine that only supports single-candle "current state" actions (touch / close above / close below / stay above / stay below / entered / rejected / breach) evaluated over an **exact** window — none of the four new multi-stage conditions (Piercing, Reclaim, Rejected-From-Above, Rejected-From-Below) exist. Trendy ADX has no direction/slope filters and no min/max candle ranges — only a single "candles since event" value applied inconsistently.

---

## 1. EMA Filters

**Requirement:** Three independent filters (Touch From Above, Piercing From Below, Close Above), each with its own min/max candles-since range; a combined "Touched or Pierced and Closed Above" condition with a still-above-now check; multi-EMA selection (One/Multiple/Any/All); and a repair of the existing broken EMA filter.

**Current implementation:** `stock-crypto-screening-tokaplace-api/services/ema.py`, wired via `services/indicators.py:713-729`. Frontend schema: `stock-crypto-screening-tokaplace-frontend/src/types/screener.ts:1224-1235`.

The entire EMA filter today is one rule with three modes — `rule: "above" | "below" | "touch"` — evaluated only against the single newest candle (`ema.py:108-122`, using `closes[-1]` / `ema[-1]`). `touch` is a symmetric absolute-tolerance equality check (`ema.py:97-99`: `abs(price - ema) <= tolerance`), not a directional wick/close formula. There is no history-aware "since event" logic at all.

| Requirement | Status | Evidence |
|---|---|---|
| Touch EMA From Above (directional, low<=EMA<=high, close>EMA, prev-close>prev-EMA) | **NOT DONE** | Only symmetric tolerance-based `touch` rule exists (`ema.py:97-99`); no direction, no wick/close formula, no prev-candle check |
| Piercing EMA From Below (prev-close<prev-EMA, low<EMA, high>=EMA, close>EMA) | **NOT DONE** | No piercing-specific logic anywhere in backend (confirmed via repo-wide search) |
| Close Above EMA (strict completed-close > EMA) | **NOT DONE** as independent condition | `rule="above"` is `price >= ema - tolerance` (`ema.py:91-92`), a tolerance-padded latest-candle check, not a strict independent close-above-only condition |
| Min/max candles-since range per condition | **NOT DONE** | No such fields in `models/filters.py` or `screener.ts:1224-1235`; only a flat `length`/`rule`/`tolerance_pct` config exists |
| Touch vs. later bounce separable (two independent filters) | **NOT DONE** | No "first touch" event tracking exists at all — nothing to separate from a bounce |
| Combined "Price Touched or Pierced EMA and Closed Above" with still-above-now confirmation | **NOT DONE** | No combined rule type exists; `rule` enum is only `["above","below","touch"]` (`screener.ts:1231`) |
| Apply to all EMA periods, with One/Multiple/Any/All EMA selection | **NOT DONE** | Config supports exactly one `length` value (default 9, `screener.ts:1531`); no multi-EMA or selection-mode concept found in backend or frontend |
| Repair: EMA value must be read on the same historical candle being tested, not just the latest | **CONFIRMED BUG, needs to be built correctly (currently N/A since no history logic exists)** | `evaluate_ema_rules` only ever reads `closes[-1]`/`ema[-1]` (`ema.py:108-122`) — there is no historical evaluation to have this bug, but any new candles-since logic must index by the same historical position, not the newest value |
| Repair: exclude unfinished/live candle | **CONFIRMED BUG** | `handle_ema`/`handle_ema_wave` (`services/indicators.py:713-729`) build `closes` from all passed candles with **no `is_closed` filtering**. Compare to Trend Channel, which explicitly excludes the forming candle via `_trend_closed_candles` (`services/indicators.py:485-492`, checks `candle.get("is_closed") is False`) — EMA has no equivalent guard |
| Repair: inclusive min/max range logic works correctly | **N/A — no fields exist yet to have this bug** | A working inclusive-range reference pattern already exists elsewhere in the codebase (`services/confluence.py:336-337, 719-728`, `candles_since_close_min/max`) and can be used as an implementation template |

**Reusable reference pattern found:** `services/confluence.py:719-728` already implements a correct min/max-range "candles since" pattern for a different filter — this is the closest existing template for the new EMA (and channel) candle-range fields.

---

## 2. Channel Line/Zone Interaction Filters (Piercing, Reclaim, Rejection)

**Requirement:** Add four new independent conditions — Piercing From Below, Reclaimed From Below - Bullish, Rejected From Above - Bullish Support, Rejected From Below - Bearish Resistance — to every selectable line/zone in Linear Regression Channel, Trend Channel (+ zones), and Regression Channel. Explicitly excluded from Channel Confluence. Each line/zone evaluated independently; selection modes One/Multiple/Any/All; min/max candles-since ranges (not a single exact value).

**Current implementation:**
- `stock-crypto-screening-tokaplace-api/services/channel_line_rules.py` (shared engine for Linear Regression Channel + Regression Channel)
- `stock-crypto-screening-tokaplace-api/services/trend_channels.py` (Trend Channel + zones)
- `stock-crypto-screening-tokaplace-api/services/confluence.py` (Channel Confluence — architecturally separate, does not share code with the above two engines)
- Frontend: `stock-crypto-screening-tokaplace-frontend/src/types/screener.ts:623-649, 1083-1143, 1862-1909`, `.../filters/IndicatorsFilter.tsx:122-155, 281-286, 605-826`

Current action vocabulary:
- **LRC / Regression Channel** (`channel_line_rules.py:31, 177-201`): `touch`, `close_above`, `close_below`, `stay_above`, `stay_below`.
- **Trend Channel lines** (`trend_channels.py:943-964`): `touched`, `closed_above`, `closed_below`, `on_line`, `breach`.
- **Trend Channel zones** (`trend_channels.py:1014-1072`): `entered`, `rejected`, `breach`. The existing zone `rejected` action (`trend_channels.py:1025-1036`) is the closest thing to a rejection filter, but it is single-candle only (same candle must overlap the zone AND close back outside it) — it has no multi-candle "touch then later close back through" sequence, no bullish/bearish split by individual line, and no candles-since range.

Both engines require the matching run to end **exactly on the latest candle** and be **exactly `window` bars long** (`channel_line_rules.py:43-45`; `trend_channels.py:776-777, 819-829`) — this is a single exact integer (`IndicatorsFilter.tsx:759`, `DEFAULT_TREND_AREA_RULE.window: 1` at `screener.ts:642`), not a min/max range, and not "event happened N candles ago, may have moved since."

Selection mode: both LRC/Regression (`channel_line_rules.py:25-52`) and Trend Channel (`trend_channels.py:615-632`) require **all** selected lines/zones to match (`all_passed`) — there is no One/Multiple/Any/All mode selector anywhere in code or UI.

| Condition | Linear Regression Channel | Regression Channel | Trend Channel (lines) | Trend Channel (zones) |
|---|---|---|---|---|
| Piercing From Below | **NOT DONE** | **NOT DONE** | **NOT DONE** | **NOT DONE** |
| Reclaimed From Below - Bullish | **NOT DONE** | **NOT DONE** | **NOT DONE** | **NOT DONE** |
| Rejected From Above - Bullish Support | **NOT DONE** | **NOT DONE** | **NOT DONE** | **PARTIAL** — `rejected` action exists but is single-candle only, no directional bull/bear split, no candles-since range, no "closed back above and still holding" semantics |
| Rejected From Below - Bearish Resistance | **NOT DONE** | **NOT DONE** | **NOT DONE** | **PARTIAL** — same `rejected` action, same caveats |
| Min/max candles-since range (vs. single exact window) | **NOT DONE** | **NOT DONE** | **NOT DONE** | **NOT DONE** |
| Selection modes One/Multiple/Any/All | **NOT DONE** (implicit "All" only) | **NOT DONE** (implicit "All" only) | **NOT DONE** (implicit "All" only) | **NOT DONE** (implicit "All" only) |
| Existing Intersect-equivalent option retained | **DONE** (`touch`) | **DONE** (`touch`) | **DONE** (`touched`) | **DONE** (`entered`) |
| Channel Confluence correctly excluded from these new features | **DONE** | — | — | — |

**Channel Confluence check:** `confluence.py` implements a fully separate line-vs-line relation model (`ConfluenceLineRelation`, `screener.ts:82`) with its own `ConfluenceFilter.tsx` UI, sharing no code with `channel_line_rules.py` or `trend_channels.py`. It is correctly isolated — there's no risk of these new options accidentally leaking into Channel Confluence, and no work is needed there per the spec's exclusion.

---

## 3. Trendy ADX

**Requirement:** (a) Replace every sub-filter's single "Candles Since Event" field with either a Min/Max Candles Since Event range (event-based conditions) or a Min/Max Consecutive Candles Active range (continuing/active conditions, must still be active on newest candle). (b) Add independent Up/Down/Flat direction filters for ADX, DI+, and DI-, each with a Min/Max Candles Since Direction Changed range, and a "still active now" requirement. (c) Keep existing Window and History Depth settings, unchanged and separate from the new ranges. (d) All counting must use fully completed candles only.

**Current implementation:** `stock-crypto-screening-tokaplace-api/services/trendy_adx.py` (794 lines). Frontend: `stock-crypto-screening-tokaplace-frontend/src/types/screener.ts:714-1010`, `.../filters/IndicatorsFilter.tsx:884-949`.

| Requirement | Status | Evidence |
|---|---|---|
| Min/Max Candles Since Event (event-based: cross, bounce, threshold cross, etc.) | **NOT DONE** | `_resolve_window` (`trendy_adx.py:187-197`) reads one `candles_since` value and turns it into a max-lookback window only, no minimum bound; frontend renders a single `PresetOrCustomField` (`IndicatorsFilter.tsx:924-933`), no min/max pair exists anywhere in the Trendy ADX config |
| Min/Max Consecutive Candles Active (continuing: already-above, dominance, active states) | **NOT DONE** | Continuing conditions (`di_already_above` at `trendy_adx.py:332-334`; ADX above/below dominant/opposing/both at `407-434`) have `sub: "none"` — no candle-count field at all, just an active-or-not check on the latest index. `bg_active_for_x` (`474-491`) is architecturally the closest match (consecutive-count-≥-threshold) but is a single value and is not applied to the DI dominance conditions |
| Independent Direction (Up/Down/Flat) for ADX | **NOT DONE** | No `direction` field in the ADX config catalog (`screener.ts:975-1009`). Only ad-hoc threshold-based checks exist: `adx_rising`/`adx_falling` (`trendy_adx.py:283-286`, current vs. previous, no Flat state); `_evaluate_weak_condition`'s `adx_falling`/`adx_flat` (`582-596`) compares against 5 candles back with a tolerance band, not the exact `[0]` vs `[1]` equality the spec requires |
| Independent Direction (Up/Down/Flat) for DI+ | **NOT DONE** | No DI+ direction/slope logic exists anywhere in the file |
| Independent Direction (Up/Down/Flat) for DI- | **NOT DONE** | No DI- direction/slope logic exists anywhere in the file |
| Flat as a distinct state (never counted as Up/Down) | **NOT DONE** | Existing `adx_rising`/`adx_falling` comparisons have no tie-handling branch; ties fall through to neither Up nor Down implicitly, not an explicit Flat state |
| Min/Max Candles Since Direction Changed + "still active now" enforcement | **NOT DONE** | No such field/logic exists for any of the three lines |
| Existing Window setting retained, separate from new ranges | **DONE** | `window` field (`screener.ts:993`), section "Advanced Screening" |
| Existing History Depth setting retained (min 200), separate from new ranges | **DONE** | `min_history` field (`screener.ts:995-1000`), 200-floor enforced at `IndicatorsFilter.tsx:486, 497` |
| Completed-candle-only counting | **DONE** | `_closed_candles()` (`trendy_adx.py:40-52`) filters out any candle where `is_closed`/`is_complete`/`complete`/`closed` is `False` or `is_live` is `True`; called at the top of `compute_trendy_adx` (`:56`), `evaluate_trendy_adx_rules` (`:637`), and `build_trendy_adx_sticker` (`:729`) |

**Reusable reference pattern found:** `services/confluence.py:719-725` already has a working min/max range pattern (`candles_since_close_min`/`candles_since_close_max`) that could serve as the implementation template for Trendy ADX's new event/active ranges — the plumbing precedent exists, it was just never applied here.

---

## 4. Average Daily Range — ADR $

**Requirement:** New standalone scanner filter. `ADR($) = average(Daily High - Daily Low)` over N fully completed daily candles, always using 1-Day candles regardless of scanner timeframe. Settings: Lookback Days (default 14, min 1), Condition (GTE / LTE / Between), Minimum ADR $, Maximum ADR $ (required for Between, validated min<=max). Inclusive boundaries. Exclude symbol if insufficient daily history (never average a partial window). Never treat missing data as $0. Stocks by default; crypto only if separately enabled. Must not be ATR/True Range/percentage-based.

**Status: NOT IMPLEMENTED — does not exist anywhere in the codebase.**

Repo-wide search for "Average Daily Range", "ADR", `adr_dollar`, `AdrFilter` returned zero code hits (only incidental substring matches in unrelated data files and the requirement docs themselves). No filter model, service, or UI component exists.

What exists but is explicitly the wrong thing per spec:
- `services/volatility.py`, `services/pine_math.py`, `services/trendy_adx.py` implement **ATR / True Range** (factors in gaps from previous close) — the spec explicitly forbids using this for ADR.
- `services/dead_assets.py` → `DeadAssetsFilter.volatility_option` (`models/filters.py:370`, `Literal["low_atr","very_low_atr","either"]`) references ATR only as a sub-condition of an unrelated filter.
- `models/filters.py:323-325` `PriceRangeFilter` filters min/max *price*, not daily range.

**Reusable groundwork found** (not wired into any filter today):
- `services/market_data.py:107` — `WORKER_CACHE_TIMEFRAMES = frozenset({"1h","4h","1day"})` confirms daily candles are already cached independently of a scanner's active timeframe.
- `services/market_data.py:785` — `_daily_candle_timestamp_is_close_time(...)`, and `market_data.py:330-354` (a native `(1,'d')` bar is treated as already-settled/closed as soon as it exists) — reusable logic for excluding the unfinished daily candle.
- `services/market_data.py:2357, 2510` — `request_polygon_grouped_daily_candles`, `request_massive_grouped_daily_candles` — existing grouped-daily-candle fetchers that operate independent of scanner timeframe.

This filter must be built entirely from scratch: model, service, rule evaluation, and frontend UI (Lookback Days field, Condition dropdown, Min/Max ADR $ fields with Between-mode validation).

---

## 5. Repeated True Empty-Space Gap Exclusion

**Requirement:** New standalone scanner filter, independent of ADR and all other filters. Gap = completely blank price area between two consecutive completed daily candles (strict: `CurrentLow > PrevHigh` for Gap Up, `CurrentHigh < PrevLow` for Gap Down — no wick/body inside). Settings: Enable Filter, Lookback Trading Days, Gap Direction (Both/Up/Down), Minimum Empty Gap Size % (user-editable, not hardcoded), Maximum Allowed Qualifying Gaps. Count qualifying gaps in lookback window; exclude symbol if count exceeds maximum. A filled gap stays counted. Must use adjusted OHLC and completed daily candles only, excluding false gaps from splits/missing data/weekends/holidays.

**Status: NOT IMPLEMENTED — does not exist anywhere in the codebase.**

Repo-wide search for gap-filter classes, `FilterType`/`gap_filter`, and frontend components ("Gap Exclusion", "Empty Space Gap", "Qualifying Gap") returned zero hits.

The only "gap" references in the codebase are unrelated:
- `tests/test_backend_services.py:4666-4701` — `test_piercing_line_requires_opening_gap_down` / `test_dark_cloud_cover_requires_opening_gap_up` test **candlestick pattern recognition** (Piercing Line / Dark Cloud Cover) that incidentally requires an opening gap. No gap % calculation, no lookback setting, no min-gap-% threshold, no max-qualifying-gap counting, and not exposed as a scanner filter.
- `cluster_gap=3` parameters scattered through trend-channel touch-clustering config — an unrelated "gap" meaning (bar-index clustering tolerance), not a price gap.

This filter must be built entirely from scratch, reusing the same `market_data.py` daily-candle/closed-candle infrastructure identified in the ADR section above (both filters need "completed daily candles regardless of scanner timeframe").

---

## 6. Cross-Cutting / Global Rules

| Global rule | Status across the codebase |
|---|---|
| Fully completed candles only, everywhere | **Inconsistent.** Trend Channel and Trendy ADX correctly exclude the unfinished candle (`services/indicators.py:485-492`; `services/trendy_adx.py:40-52`). **EMA does not** (confirmed bug, see Section 1). ADR and Gap filters don't exist yet so this must be built in from day one. |
| Line/indicator value read on the same historical candle being evaluated (not just the newest value) | Channel engines (`channel_line_rules.py`, `trend_channels.py`) evaluate per-bar arrays correctly for their existing single-candle actions. EMA does not do this at all today (only ever reads the latest value) — must be built correctly when candles-since logic is added. |
| Inclusive min/max ranges, max >= min | A correct working reference pattern exists in `services/confluence.py:336-337, 719-728` (`candles_since_close_min/max`) and should be reused as the template for the new EMA, channel, and Trendy ADX range fields. |
| Independent evaluation of selected lines/zones (no averaging), with One/Multiple/Any/All selection | **NOT DONE anywhere.** Every existing engine (LRC, Regression Channel, Trend Channel lines/zones) currently hardcodes "all selected must match" with no selection-mode concept. |
| Channel Confluence excluded from all new line/zone conditions | **DONE / correctly isolated.** `services/confluence.py` shares no code with the channel line-rule engines. |

---

## 7. Summary Matrix

| Area | Status |
|---|---|
| EMA — Touch From Above | Not done |
| EMA — Piercing From Below | Not done |
| EMA — Close Above (independent) | Not done |
| EMA — Combined Touch/Pierce + Close Above | Not done |
| EMA — Multi-EMA / selection modes | Not done |
| EMA — Repair (unfinished-candle bug) | Confirmed bug, not fixed |
| EMA — Repair (historical EMA value bug) | N/A today, must be built correctly |
| Channel — Piercing From Below (all 3 indicators) | Not done |
| Channel — Reclaimed From Below - Bullish (all 3 indicators) | Not done |
| Channel — Rejected From Above (all 3 indicators) | Not done (Trend Channel zones: partial) |
| Channel — Rejected From Below (all 3 indicators) | Not done (Trend Channel zones: partial) |
| Channel — Min/max candles-since ranges | Not done (single exact window only) |
| Channel — One/Multiple/Any/All selection | Not done (implicit "All" only) |
| Channel Confluence exclusion | Done (correctly isolated) |
| Trendy ADX — Min/Max Candles Since Event | Not done |
| Trendy ADX — Min/Max Consecutive Candles Active | Not done |
| Trendy ADX — ADX/DI+/DI- direction (Up/Down/Flat) | Not done |
| Trendy ADX — Candles Since Direction Changed | Not done |
| Trendy ADX — Window / History Depth retained | Done |
| Trendy ADX — Completed-candle-only counting | Done |
| ADR $ filter | Not implemented (does not exist) |
| Repeated True Empty-Space Gap Exclusion filter | Not implemented (does not exist) |

---

## 8. Notable Reusable Assets for Implementation

- `services/confluence.py:719-728` — working inclusive min/max "candles since" range pattern; template for EMA, channel, and Trendy ADX range fields.
- `services/indicators.py:485-492` (`_trend_closed_candles`) — working unfinished-candle exclusion pattern; template for fixing EMA and for building ADR/Gap.
- `services/market_data.py:107, 330-354, 785, 2357, 2510` — daily-candle caching/fetching and closed-daily-candle detection, independent of scanner timeframe; foundation for both ADR $ and Gap Exclusion.
- `services/trendy_adx.py:474-491` (`bg_active_for_x`) — closest existing "consecutive count ≥ threshold" pattern, relevant starting point for the new Min/Max Consecutive Candles Active logic.

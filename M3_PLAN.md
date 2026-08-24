# Milestone 3 — Implementation Plan

**Source:** Gap analysis in `M3_CLIENT_REQUIREMENTS.md`. This plan sequences that gap analysis into buildable phases and modules, each rated by difficulty (**Low / Medium / High**) based on scope, number of call sites touched, and behavioral subtlety (e.g. sloped-line-per-candle math, multi-stage state sequencing).

**Difficulty legend**
- **Low** — self-contained, few call sites, straightforward arithmetic/logic, low risk of regressing existing behavior.
- **Medium** — touches multiple existing call sites or requires new stateful sequencing, but follows an existing pattern in the codebase.
- **High** — new multi-stage sequencing logic with no existing pattern to copy, applied across several indicators/engines, or with high regression risk to already-working filters.

---

## Phase 0 — Shared Infrastructure (build once, reuse everywhere)

Every later phase needs the same three primitives. Building them once here avoids four divergent implementations of the same concept (EMA, Channel, Trendy ADX, and — differently — ADR/Gap all need candle-range and completed-candle logic).

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **0.1 Inclusive Min/Max Candle-Range Utility** | Extract the working pattern from `services/confluence.py:719-728` (`candles_since_close_min/max`) into a shared helper: given an event index and current index, return pass/fail for `[min, max]` inclusive, with validation that `max >= min`. Two flavors needed: "candles since a past event" and "consecutive candles an active condition has held true, ending now." | **Low** | — |
| **0.2 Completed-Candle Filter Utility** | Generalize `services/indicators.py:485-492` (`_trend_closed_candles`) into a shared utility usable by EMA, ADR, and Gap Exclusion (Trend Channel and Trendy ADX already have their own working equivalents — leave those as-is, just don't diverge further). | **Low** | — |
| **0.3 Selection-Mode Evaluator (One / Multiple / Any / All)** | New shared evaluator: given a list of per-line/zone (or per-EMA) boolean results, resolve final pass/fail per mode. `All` = current hardcoded behavior in `channel_line_rules.py:25-52` and `trend_channels.py:615-632`; `Any` = at least one true; `One`/`Multiple` = UI-level selection constraints, not new evaluation logic. | **Medium** | — |
| **0.4 Daily-Candle-Independent-of-Timeframe Fetch Helper** | Wrap `services/market_data.py:107, 330-354, 785, 2357, 2510` into a single reusable function: "give me the last N fully completed daily candles for symbol X, regardless of the scanner's active timeframe." Needed identically by both ADR and Gap Exclusion. | **Medium** | — |

**Phase 0 exit criteria:** unit tests for each utility in isolation (range inclusivity, off-by-one boundaries, unfinished-candle exclusion, selection-mode logic, daily-candle fetch returning exactly N candles or signaling insufficient history).

---

## Phase 1 — EMA Filter Repair + Independent Conditions

**Why first (after Phase 0):** Client explicitly reports this filter is currently broken ("not returning results properly") — highest-visibility bug fix, and the smallest of the four indicator surfaces (one file, `services/ema.py`, one config schema).

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **1.1 Fix unfinished-candle bug** | Wire `0.2` into `handle_ema`/`handle_ema_wave` (`services/indicators.py:713-729`) so the live candle is excluded from both EMA calculation and rule evaluation. | **Low** | 0.2 |
| **1.2 Fix historical-value indexing** | Rewrite `evaluate_ema_rules` (`ema.py:108-122`) so any per-candle check reads `ema[i]` / `closes[i]` at the historical index being tested, not only `ema[-1]`/`closes[-1]`. Foundational for 1.3–1.5. | **Medium** | 1.1 |
| **1.3 Touch EMA From Above** | New independent condition: `PrevClose>PrevEMA AND Low<=EMA AND High>=EMA AND Close>EMA`, scanned backward to find the first qualifying candle, with `0.1` min/max-candles-since-touch range. | **Medium** | 1.2, 0.1 |
| **1.4 Piercing EMA From Below** | New independent condition: `PrevClose<PrevEMA AND Low<EMA AND High>=EMA AND Close>EMA`, same backward-scan + range pattern as 1.3. | **Medium** | 1.2, 0.1 |
| **1.5 Close Above EMA (strict, independent)** | Replace the tolerance-padded `rule="above"` with a strict `Close>EMA` check, decoupled from touch/pierce, with its own min/max candles-since-close-above range. | **Low** | 1.2, 0.1 |
| **1.6 Combined "Touched or Pierced and Closed Above"** | New compound condition combining 1.3/1.4's touch/pierce geometry with a "still above EMA on newest completed candle" confirmation (`NewestClose>NewestEMA`). | **Medium** | 1.3, 1.4 |
| **1.7 Multi-EMA period support + selection mode** | Extend config from single `length` to a list of EMA periods (standard + custom), apply 1.3–1.6 to each independently, resolve via `0.3` (One/Multiple/Any/All). | **High** | 0.3, 1.3–1.6 |
| **1.8 Frontend UI** | Replace single `rule`/`tolerance_pct` fields with per-condition min/max range inputs, multi-EMA period selector, and selection-mode control in `IndicatorsFilter.tsx` / `screener.ts:1224-1235`. | **Medium** | 1.3–1.7 |
| **1.9 Regression/validation tests** | Backward-compatibility tests against `tests/test_indicator_defaults.py:17-45`, new tests per condition, and spot-check against TradingView per the completed-candle validation rule. | **Medium** | 1.1–1.8 |

**Phase 1 exit criteria:** all 3 independent conditions + combined condition return correct results on known historical data, unfinished candle verified excluded, matches TradingView on a manual spot-check symbol/timeframe/EMA-period combination.

---

## Phase 2 — Channel Line/Zone Interaction Filters (Piercing, Reclaim, Rejection)

**Why this is the largest phase:** four new conditions × three channel indicator types (Linear Regression Channel, Regression Channel, Trend Channel lines, Trend Channel zones) = up to 16 combinations, plus this phase must not regress the existing `touch`/`close_above`/`entered`/etc. actions that are already working and relied upon. Explicitly excluded from Channel Confluence (no work needed there — already correctly isolated per `M3_CLIENT_REQUIREMENTS.md` §2).

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **2.1 Per-candle line-value formula library** | Shared formula functions implementing the four calculations from the spec (Piercing, Reclaim, Rejected-From-Above, Rejected-From-Below), parameterized on "line value at candle i" so they work identically for a flat line, sloped Trend Channel line, or Regression Channel line. This is the crux of the phase — must handle sloped lines correctly (`docs` explicitly calls this out as critical). | **High** | — |
| **2.2 Piercing From Below — LRC + Regression Channel** | Wire 2.1's piercing formula into `channel_line_rules.py`, backward-scanning for the first qualifying event + `0.1` range. No minimum consecutive-below requirement, no still-above-now requirement (event-only, per spec). | **Medium** | 2.1, 0.1 |
| **2.3 Piercing From Below — Trend Channel (lines + zones)** | Same as 2.2 but wired into `trend_channels.py`, handling both individual lines and zone boundaries. | **Medium** | 2.1, 0.1 |
| **2.4 Reclaimed From Below - Bullish — LRC + Regression Channel** | New multi-stage state machine: consecutive-below run (min>=1) via `0.1`'s "consecutive active" flavor, reclaim-close-above transition, still-above-now confirmation on newest candle, candles-since-reclaim range via `0.1`. This is new sequencing logic with no existing analog in `channel_line_rules.py`. | **High** | 2.1, 0.1 |
| **2.5 Reclaimed From Below - Bullish — Trend Channel (lines + zones)** | Same state machine as 2.4, wired into `trend_channels.py`, with the zone-boundary nuance called out in the spec (use the applicable boundary, not just "entered the zone"). | **High** | 2.1, 0.1, 2.4 (shares the state machine) |
| **2.6 Rejected From Above - Bullish Support — LRC + Regression Channel** | New condition: approach-from-above + touch/pierce + completed close back above. No existing pattern in these two engines. | **Medium** | 2.1, 0.1 |
| **2.7 Rejected From Below - Bearish Resistance — LRC + Regression Channel** | Mirror of 2.6, bearish direction. | **Medium** | 2.1, 0.1, 2.6 (shares scaffolding) |
| **2.8 Rejected From Above / Below — Trend Channel lines** | New for lines (currently zero rejection support on Trend Channel *lines*, only zones). | **Medium** | 2.1, 0.1 |
| **2.9 Rejected From Above / Below — Trend Channel zones (upgrade existing `rejected`)** | Upgrade the existing single-candle `rejected` action (`trend_channels.py:1025-1036`) to the full multi-candle approach→touch/pierce→completed-close-back sequence, split into bullish-support vs. bearish-resistance, with candles-since range. Higher risk item since it modifies an already-shipped, presumably-in-use action. | **High** | 2.1, 0.1 |
| **2.10 Selection mode (One/Multiple/Any/All) across all four engines** | Wire `0.3` into `channel_line_rules.py` and `trend_channels.py` evaluation entry points, replacing the hardcoded `all_passed` requirement, without breaking existing filters that implicitly relied on "all." | **High** | 0.3, 2.2–2.9 |
| **2.11 Frontend UI — new condition options + range inputs + selection mode** | Add Piercing/Reclaim/Rejected-Above/Rejected-Below as selectable actions per line/zone in `IndicatorsFilter.tsx`, replace exact-window field with min/max range inputs, add selection-mode control, for all three channel indicator types (not Channel Confluence). | **High** | 2.2–2.10 |
| **2.12 Regression tests for existing actions** | Ensure `touch`/`close_above`/`close_below`/`stay_above`/`stay_below`/`touched`/`closed_above`/`closed_below`/`on_line`/`breach`/`entered` continue to behave identically after 2.10's selection-mode refactor. | **Medium** | 2.10 |
| **2.13 New-condition tests + TradingView validation** | Per-condition tests (piercing-only vs. reclaim-only vs. both, per the spec's worked scenarios), plus manual TradingView spot-checks on SIGA/BTC/WULF-style examples referenced in the source docs. | **High** | 2.2–2.11 |

**Phase 2 exit criteria:** all 4 conditions work correctly and independently across all 3 channel indicator types (4 variants for Trend Channel lines vs zones), selection modes verified, zero regression in existing actions, Channel Confluence untouched.

---

## Phase 3 — Trendy ADX Updates

**Why after Phase 2, not before:** shares the same min/max-range and completed-candle primitives from Phase 0, and the direction/slope logic is conceptually similar to (but distinct from) the piercing/rejection candle-comparison logic built in Phase 2 — building it second lets the team reuse lessons learned on sloped/per-candle comparisons.

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **3.1 Direction/slope calculator (ADX)** | New `Up = ADX[0]>ADX[1]`, `Down = ADX[0]<ADX[1]`, `Flat = ADX[0]==ADX[1]` (exact equality, no tolerance band — this replaces the existing tolerance-based `adx_falling`/`adx_flat` in `_evaluate_weak_condition`, `trendy_adx.py:582-596`, which must be reconciled/deprecated carefully since it's presumably in production use). | **Medium** | — |
| **3.2 Direction/slope calculator (DI+, DI-)** | Same formula applied independently to DI+ and DI- — entirely new, no existing logic to build on (`M3_CLIENT_REQUIREMENTS.md` §3 confirms zero DI+/DI- direction logic exists today). | **Medium** | 3.1 (shares formula shape) |
| **3.3 Candles-Since-Direction-Changed + still-active-now enforcement** | For each of ADX/DI+/DI-, backward-scan for the direction-change candle, apply `0.1` range, and enforce that the selected direction is still the current direction on the newest completed candle (critical rule — a historical-only change must FAIL). | **High** | 3.1, 3.2, 0.1 |
| **3.4 Convert event-based sub-filters to Min/Max Candles Since Event** | Audit every event-based sub-filter (DI cross, bounce, threshold cross, turn — full list in requirements §3) and replace the single `candles_since`/`_resolve_window` value (`trendy_adx.py:187-197`) with `0.1`'s min/max range. Large surface area (12+ sub-filters), each individually low-risk but the audit itself is the hard part. | **High** | 0.1 |
| **3.5 Convert continuing/active sub-filters to Min/Max Consecutive Candles Active** | Audit every continuing condition (`di_already_above`, ADX dominant/opposing/both at `trendy_adx.py:332-434`, generalize the `bg_active_for_x` pattern at `474-491`) and add the consecutive-active range + still-active-now check via `0.1`. | **High** | 0.1, 3.4 (shares audit work) |
| **3.6 Retain Window / History Depth unchanged** | Verify (don't rebuild) that `window` (`screener.ts:993`) and `min_history` (`screener.ts:995-1000`) remain distinct config keys, untouched by 3.4/3.5's new fields — this is a "don't break it" verification task, not new code. | **Low** | 3.4, 3.5 |
| **3.7 Frontend UI** | Add Direction (Any/Up/Down/Flat) selector + range fields per line (ADX/DI+/DI-) in `IndicatorsFilter.tsx:884-949`; replace every single "Candles Since Event" dropdown with min/max pair per sub-filter category (event vs. active). | **High** | 3.1–3.6 |
| **3.8 Regression + validation tests** | Full sub-filter audit checklist from spec §5.12 as a test matrix; TradingView spot-check against the black/pink/blue line panel referenced in source visuals. | **High** | 3.1–3.7 |

**Phase 3 exit criteria:** ADX/DI+/DI- direction independently correct with Flat as a real third state; every sub-filter categorized and converted to the correct range type; Window/History Depth untouched; existing tests in `tests/test_backend_services.py` still pass.

---

## Phase 4 — Average Daily Range ($) Filter (new, from scratch)

**Why after 1–3, not before:** self-contained new filter with no dependency on EMA/Channel/ADX work, but Phase 0.4 (daily-candle fetch helper) should exist first, and this is lower architectural risk than Phases 1–3, so it's fine later in the sequence. Could be parallelized with Phase 3 by a second engineer if resourcing allows.

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **4.1 ADR calculation service** | New function: for N fully completed daily candles (via `0.4`), compute `sum(High-Low)/N`, using unrounded values internally. Must explicitly avoid any ATR/True-Range/previous-close logic (`services/volatility.py`/`pine_math.py` are decoys — do not reuse). | **Low** | 0.4 |
| **4.2 Insufficient-history exclusion** | If fewer than N valid completed daily candles exist, exclude the symbol — must not silently average a shorter window, and must not treat missing/invalid daily data as a $0 range. | **Low** | 4.1 |
| **4.3 Filter model + condition logic** | New `models/filters.py` entry: Lookback Days (default 14, min 1), Condition (GTE/LTE/Between), Min/Max ADR $, with Between-mode validation (`min<=max`, both required). Inclusive boundary comparisons. | **Low** | 4.1, 4.2 |
| **4.4 Stocks-default / crypto-opt-in scoping** | Wire the filter to apply to stocks by default and only to crypto when crypto scanning is separately enabled — check how other filters currently do this scoping (likely an existing asset-class flag) and follow the same pattern. | **Low** | 4.3 |
| **4.5 Frontend UI** | New filter card: Lookback Days input, Condition dropdown, Min/Max ADR $ inputs (Max required + validated only in Between mode), matching the suggested UI layout in the spec. | **Low** | 4.3 |
| **4.6 Acceptance tests** | Implement the 12 acceptance tests given verbatim in the spec (§20 of `stock_scanner_final_engineering_requirements.md` / §6.16 of the docx spec) as automated tests — inclusive boundaries, timeframe-independence, insufficient-history exclusion, missing-data handling, invalid min>max validation. | **Medium** | 4.1–4.5 |

**Phase 4 exit criteria:** all 12 spec acceptance tests pass; ADR verified identical across scanner timeframe changes (5m→1H→1D→1W) for the same symbol/lookback.

---

## Phase 5 — Repeated True Empty-Space Gap Exclusion Filter (new, from scratch)

**Why last:** fully independent, self-contained, lowest interaction risk with the rest of the scanner — good candidate for parallelizing alongside Phase 4, or doing last if resourcing is serial. Shares Phase 0.4's daily-candle infrastructure with ADR.

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **5.1 Strict gap detection** | Implement `CurrentLow>PrevHigh` (Gap Up) / `CurrentHigh<PrevLow` (Gap Down) as strict, non-inclusive comparisons over consecutive completed daily candles (via `0.4`). Must explicitly reject overlap/touch/wick-in-space cases — these are exactly the "must not count" cases the spec calls out, so unit tests should assert the negative cases as much as the positive ones. | **Medium** | 0.4 |
| **5.2 Gap-size percentage + user-editable minimum** | Implement the Gap Up %/Gap Down % formulas, using full unrounded precision for the qualifying comparison (`GapSize% >= UserMinimum%`) and rounding only for display. Must not hardcode 5%. | **Low** | 5.1 |
| **5.3 Adjusted OHLC / bad-data exclusion** | Ensure gap detection uses adjusted OHLC and does not fire false gaps from splits, reverse splits, missing data, weekends, market holidays, or corrupted history. This is the highest-uncertainty item in the phase — depends on what adjustment/data-quality signals `market_data.py` already exposes; may require new data-quality checks if none exist yet. | **High** | 5.1, 0.4 |
| **5.4 Qualifying-gap counting + exclusion logic** | Count qualifying gaps within the user's Lookback Trading Days window; PASS if count <= Maximum Allowed, EXCLUDE if it exceeds. A gap stays counted even if later filled — verify no "still open" state leaks into the count. | **Low** | 5.2 |
| **5.5 Filter model + settings** | New `models/filters.py` entry: Enable Filter (Yes/No), Lookback Trading Days, Gap Direction (Both/Up/Down), Minimum Empty Gap Size %, Maximum Allowed Qualifying Gaps. | **Low** | 5.4 |
| **5.6 Frontend UI** | New filter card matching the spec's settings list, with the gap-direction toggle and editable minimum-gap-% field (explicitly not a hardcoded checkbox). | **Low** | 5.5 |
| **5.7 Acceptance tests** | Cover: true gap up/down positive cases, all "not a gap" negative cases (overlap/touch/wick-in-space/large-candle/fast-move), max-allowed-gaps boundary (inclusive at max), filled-gap-stays-counted, split/holiday false-gap exclusion. | **Medium** | 5.1–5.6 |

**Phase 5 exit criteria:** all acceptance tests pass, including every explicit "must NOT count as a gap" negative case from the spec; split/reverse-split data confirmed not to trigger false gaps.

---

## Phase 6 — Cross-Cutting Hardening & Sign-Off

Run after Phases 1–5 are individually complete, to catch integration issues between them and satisfy the client's global sign-off checklist (`stock_scanner_final_engineering_requirements.md` §22).

| Module | Description | Difficulty | Depends on |
|---|---|---|---|
| **6.1 Global completed-candle audit** | Sweep all five filter areas (EMA, Channel, Trendy ADX, ADR, Gap) plus any indicator touched incidentally, confirming the live/unfinished candle is excluded everywhere, using `0.2`/`0.4` consistently rather than ad hoc checks. | **Medium** | Phases 1–5 |
| **6.2 Inclusive-range regression suite** | One consolidated test suite asserting inclusive min/max boundary behavior across every new range field added in Phases 1–3 (EMA, Channel, Trendy ADX) — catches copy-paste boundary bugs across ~20+ new range fields. | **Medium** | Phases 1–3 |
| **6.3 TradingView parity spot-checks** | For each filter area, run the same symbol/timeframe/settings/completed-candle combination through both the scanner and TradingView and confirm matching results, per the global validation rule repeated throughout all three spec documents. | **High** | Phases 1–5 |
| **6.4 Performance check** | New per-candle backward-scans (piercing/reclaim/rejection state machines in Phase 2, direction-change scans in Phase 3) run across the full scanner universe — verify no unacceptable latency regression versus current filter run times. | **Medium** | Phases 1–5 |
| **6.5 Documentation + sign-off checklist** | Walk the client's exact checklist from `stock_scanner_final_engineering_requirements.md` §22 line by line and confirm each item, updating `M3_CLIENT_REQUIREMENTS.md`'s status table to reflect final DONE status. | **Low** | 6.1–6.4 |

---

## Suggested Execution Order & Parallelization

```text
Phase 0 (shared infra)
   │
   ▼
Phase 1 (EMA repair)  ──┐
   │                    │
   ▼                    │
Phase 2 (Channel filters, largest)
   │                    │
   ▼                    │
Phase 3 (Trendy ADX)    │
   │                    │
   ├── Phase 4 (ADR $) ─┤   ← can run in parallel with Phase 3 on a 2nd track
   ├── Phase 5 (Gap)  ──┘   ← can run in parallel with Phase 3/4 on a 2nd track
   ▼
Phase 6 (hardening + sign-off)
```

Phase 0 is a hard prerequisite for everything else and should not be skipped even under time pressure — every later "High" difficulty item (2.10, 3.3, 3.4/3.5) becomes substantially riskier without the shared range/selection-mode/completed-candle primitives being correct and tested first.

---

## Difficulty Summary by Phase

| Phase | Low | Medium | High | Overall phase difficulty |
|---|---|---|---|---|
| 0 — Shared infrastructure | 2 | 2 | 0 | **Medium** (small but foundational — errors here propagate everywhere) |
| 1 — EMA repair + conditions | 2 | 5 | 1 | **Medium-High** |
| 2 — Channel filters | 0 | 6 | 6 | **High** (largest phase, most new sequencing logic, most regression risk) |
| 3 — Trendy ADX | 1 | 3 | 4 | **High** (large sub-filter audit surface + new direction logic) |
| 4 — ADR $ | 5 | 1 | 0 | **Low** (self-contained, well-specified, no existing behavior to regress) |
| 5 — Gap Exclusion | 3 | 2 | 1 | **Low-Medium** (mostly straightforward; data-quality/adjusted-OHLC handling is the one uncertain item) |
| 6 — Hardening & sign-off | 1 | 3 | 1 | **Medium** |

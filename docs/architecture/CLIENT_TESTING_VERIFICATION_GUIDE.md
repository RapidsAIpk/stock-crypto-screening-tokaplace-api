# Testing & Verification Guide — New Features Priority Pass (Pass 1)

**Scope of this pass:** this guide covers everything **newly built** in this engagement — Dead Assets, Trendy ADX, VLR, Watchlists, the Owner Dashboard, the Filters sidebar reorg — plus the specific new asks that came directly out of the client's latest live testing round on the deployed site (label clarity, multi-indicator combo scans, gate→entry end-to-end, the temporary open-login state). Get these fully verified first.

**What's deferred to Pass 2 (a separate old-indicators guide, coming next):** RSI, WaveTrend, Aroon, MACD, EMA, Linear Regression Candles, Linear Regression Channel, Regression Channel [DW], Trend Channel [ChartPrime], Channel Respect, Confluence, Candlestick Patterns, Relative Volume, Volatility. These are pre-existing indicators that were audited and, in several cases, bug-fixed during this engagement — they still need to be tested "by every scenario" as instructed, just in their own document so this pass isn't diluted.

**Three items are flagged here even though they belong to Pass 2, because they are currently broken per the client's own direct testing, this week, not historical audit findings:**

- **Linear Regression Candles** — Ismail tested "piercing from below" himself and got the wrong result ("price already above the line, not piercing"). This happened *after* it was reported fixed. Confirmed still broken as of this writing.
- **Trend Channel [ChartPrime]** — Ismail: *"Channel confluence and trend channel isn't correct."* Currently being re-validated against TradingView per Faizan's reply.
- **Channel Confluence** — same message, same status: currently being re-validated, not currently passing.

These three should be **first in line** when Pass 2 starts, not buried at the bottom of that list — flagging that explicitly here so it isn't lost between documents.

---

## How to use this document

- Every test case has the same shape: what to do **on our site**, what should happen, a Pass/Fail box, and a blank **Developer Notes / Accuracy Findings** area underneath. Fill it in every time, even "worked as expected" — that's still a useful record.
- 🚩 **FLAGGED BY CLIENT** — raised by the client directly (spec docs, screenshots, or this week's live testing/chat). Highest priority.
- 🆕 **NEW THIS WEEK** — a fresh ask that came directly out of the client's live testing round on the deployed site, not from the original spec docs.
- ⛔ **BLOCKED** — known incomplete, waiting on data or client action. Don't report as a new bug.

---

## Table of Contents

- [Section 0 — Before You Start](#section-0--before-you-start)
- [Priority Index — This Week's Direct Client Asks](#priority-index--this-weeks-direct-client-asks)
- [Section A — New Indicators & Filters (Phase 3 builds)](#section-a--new-indicators--filters-phase-3-builds)
- [Section B — Watchlists](#section-b--watchlists)
- [Section C — Owner Dashboard](#section-c--owner-dashboard)
- [Section D — Cross-Feature Checks & This Week's New Asks](#section-d--cross-feature-checks--this-weeks-new-asks)
- [Section E — Reliability / Bug Regression Checks](#section-e--reliability--bug-regression-checks)
- [Section F — Known Blocked Items (do not report as new bugs)](#section-f--known-blocked-items-do-not-report-as-new-bugs)
- [Section G — Account/Access Items (needs a client action)](#section-g--accountaccess-items-needs-a-client-action)
- [Section H — Deferred to Pass 2 (old indicators — placeholder only)](#section-h--deferred-to-pass-2-old-indicators--placeholder-only)
- [Sign-Off Summary](#sign-off-summary)

---

## Section 0 — Before You Start

**Pick one stock and one crypto symbol and use them for every test in this document.** Suggested: **AAPL** or **MSFT** for stocks, **BTCUSDT** for crypto.

- Stock symbol used throughout: `________________`
- Crypto symbol used throughout: `________________`
- Timeframe used throughout: `________________`
- Site URL tested: `________________` (currently: https://stock-crypto-screening-tokaplace-fr.vercel.app/)
- Date tested: `________________`

**Current login state — read before you start testing:** real Firebase sign-in is temporarily disabled. Any email/password combination will log you in right now. This is intentional, not a bug — it's disabled until the client grants Firebase developer access, at which point real login gets switched back on (the original code is commented out, not deleted). Don't report "anyone can log in" as a new finding — it's already tracked in [TC-D4](#tc-d4--login-temporary-open-access--single-user-concern-flagged-by-client-new-this-week) below. Do note anything else odd you find *while* logged in this way.

---

## Priority Index — This Week's Direct Client Asks

Pulled directly from Ismail's live testing round and the team's reply. Test these first — they are the most current, most direct signal of what the client cares about right now.

| # | Item | What the client actually said | Jump to |
|---|---|---|---|
| 1 | Linear Regression Candles — piercing bug still present | Tested "piercing from below" himself, got "price already above the line, not piercing" — wrong result, after being told it was fixed | [Section H](#section-h--deferred-to-pass-2-old-indicators--placeholder-only) (belongs to Pass 2, but re-test first) |
| 2 | Trend Channel isn't correct | *"Channel confluence and trend channel isn't correct"* | [Section H](#section-h--deferred-to-pass-2-old-indicators--placeholder-only) |
| 3 | Channel Confluence isn't correct | Same message as above | [Section H](#section-h--deferred-to-pass-2-old-indicators--placeholder-only) |
| 4 | Indicator labels need to be human-readable | "background zone active" isn't clear which color = bullish, just started, etc. — called out for Trendy ADX and VLR specifically | [TC-D3](#tc-d3--indicator-label-clarity-trendy-adx--vlr--flagged-by-client-new-this-week) |
| 5 | Test confluence to work as intended | All 4 confluence types | Deferred to Pass 2 (Confluence is a pre-existing feature) |
| 6 | Test candlestick pattern recognition | | Deferred to Pass 2 |
| 7 | Test multiple indicators chosen together | Combined scan, not just one indicator at a time | [TC-D1](#tc-d1--multiple-indicators-combined-in-one-scan-new-this-week) |
| 8 | Test gate→entry timeframe flow gives results | End to end, not just that it doesn't error | [TC-D2](#tc-d2--gate--entry-end-to-end-returns-real-results-new-this-week) |
| 9 | Login shows "not secure" / any email logs in | Concerned about access — "only my email should be the user, no other" | [TC-D4](#tc-d4--login-temporary-open-access--single-user-concern-flagged-by-client-new-this-week) |
| 10 | Screen recording of Settings section | Requested because he doesn't have time to figure it out himself | Owed deliverable — see [Section C](#section-c--owner-dashboard) note |
| 11 | Zoya API — last real piece left | Needed to properly wire Compliance Standards | Tracked in [Section F](#section-f--known-blocked-items-do-not-report-as-new-bugs) |
| 12 | Firebase developer access (not credentials) | Team asked to be added as a Firebase developer under Project Settings → Users and permissions | [Section G](#section-g--accountaccess-items-needs-a-client-action) |

---

## Section A — New Indicators & Filters (Phase 3 builds)

### TC-A1 — Dead Assets ("Omit Dead Stock") 🚩 FLAGGED BY CLIENT (non-blacklist rule)

**On our site:** Enable the Dead Assets filter with all 4 types on (Strong Dead Trend, Slow Bleeding Trend, Failed Recovery, Flat Dead Asset). Run a scan on a symbol you know has been in a clear downtrend.
**Expected:** the symbol should be excluded with one of the exact labels: `Excluded — Strong Dead Trend`, `Excluded — Slow Bleeding Trend`, `Excluded — Failed Recovery`, or `Excluded — Flat Dead Asset`.
**Then test the non-negotiable recovery rule:** find or simulate a symbol that recovers (closes above its previous swing high after being excluded) and confirm it comes back with `Allowed — Recovery Started` — it must never be permanently blacklisted.
**Then re-test the preset bug specifically:** turn Dead Assets **off**, save that as a Preset, reload the page, load that preset back, and confirm it **stays off** (this exact bug — the setting silently flipping back on after a preset reload — was already found and fixed once; this is a regression check).

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-A2 — Trendy ADX (Bonavest DI+/DI−)

**On our site:** Add Indicator → Trendy ADX. Try each of the 4 modes: Bullish, Bearish, Compression/Watch, Weak/Avoid. Default Length=11, Threshold=20.
**Mode-switching check (specifically flagged as needing testing, not yet verified):** select several conditions under one mode (e.g. Bullish), then switch to a different mode (e.g. Weak/Avoid) and back. Confirm the condition checklist actually resets/filters to match the newly selected mode each time, and that no stale condition from a previous mode silently stays checked or gets sent with the scan.
**On TradingView:** Search for **"Trendy ADX DI+ DI− Trend Strength - Bonavest"** and add it. Note: the client has already been told directly (and this is accurate) that this script is **closed-source on TradingView** — nobody can see the actual Pine code, ours included. It was built from the standard, publicly documented Wilder DMI/ADX formula, which is the closest real equivalent. Expect values **close but not necessarily exact** — the team has already told the client the numbers can be off by a couple of points in some cases. Don't chase perfect parity here; chase "clearly the same trend read," not decimal-identical.
**Expected:** DI+/DI−/ADX values on the site should be close to the TradingView plot on the same candle. Values must **not** visibly shift or flicker if you refresh while a new candle is still forming — the still-forming candle must never be included in the calculation (this was a real bug, already fixed — re-verify it holds).
**Score Levels note:** the Score field (±19/±10/±4 defaults) is intentionally inert — kept for parity with the spec but doesn't drive any actual filter logic. Not a bug.

**🆕 Label clarity check (new this week):** look at the result label/sticker text for whatever mode and condition you selected. It should clearly say something like *"Bullish, just started"* or *"Bearish, confirmed"* in plain language — not raw internal terms like "background zone active" that a non-technical user can't map to bullish or bearish at a glance. If the current build still shows the old technical zone names, that's expected right now — the team has committed to rewriting these labels; note here whether it's landed yet.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-A3 — Variable Linear Regression (VLR)

**On our site:** Add Indicator → VLR. Default: Source=Close, Regressions=3, Start Period=12, Increment=12.
**On TradingView:** Search for **"Variable Linear Regression With Pearsons R"** and its companion **"...Oscillator"** script by Gentleman-Goat (genuinely open-source, unlike Trendy ADX). Add with matching periods.
**Expected:** the Red/Green/Blue oscillator lines should track the TradingView plot closely, bounded between -1 and +1. Test a Reversal Setup match (e.g. "Exact Bullish Reversal" at Red line +0.80 to +1.00 turning down) and confirm it fires on the same candle TradingView shows the line entering/exiting that zone.
**Test the Crossing Confirmation direction cascade specifically:** switch Direction between Bullish and Bearish and confirm the crossing-option checkboxes change to match — bearish crossing options must never remain visible during a bullish-only scan, and vice versa. Toggle quickly a few times to check nothing "leaks through."
**Deviation(s) note:** intentionally inert, same treatment as Trendy ADX's Score. Not a bug.

**🆕 Label clarity check (new this week):** same as Trendy ADX above — check whether the result label reads in plain language (bullish/bearish, just started vs. already confirmed) rather than raw internal terminology.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-A4 — Filters Sidebar Order 🚩 FLAGGED BY CLIENT

Open the Filters sidebar and confirm it's a single consolidated group, in this order: **Asset Type → Price Range → Compliance (stocks) / Crypto Exchange + Ethical (crypto) → Dead Assets → Indicators → Channel Respect → Confluence**, followed by a separate Timeframe group. Test both Stock and Crypto asset types. Also collapse the sidebar to icon-only view and confirm it still works.

**Note from live client testing:** Ismail initially didn't see the Price Range filter at all when first looking at the sidebar, then found it. Worth a specific check — is Price Range visually obvious enough in its current position, or does it need to be more prominent? Not a functional bug, but a real point of confusion for the actual client, worth writing down either way.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-A5 — "Reset to Default" Button (every indicator card)

This button is itself new work — the client's spec explicitly required a one-click Reset to Default, and none of the indicators shipped before this pass had one. It was added to every indicator's card header, not just the new ones.

**On our site:** change a setting on **at least 4 different indicator cards**, including **both new indicators (Trendy ADX, VLR)** and at least 2 pre-existing ones (e.g. RSI, WaveTrend). Click each card's "Reset to Default." Confirm each one returns to its correct documented default — for Trendy ADX that's Length=11/Threshold=20/Score Levels ±19/±10/±4; for VLR that's Source=Close/Regressions=3/Start Period=12/Increment=12/Deviation=2; for WaveTrend it must return to **Threshold=35** specifically (not 60 — see the client's binding decision on this, tracked for Pass 2).
**Expected:** every card resets correctly on its own — don't just test the ones the feature was originally built against.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

## Section B — Watchlists

**Context:** the client's own spec was thin here — "Add stock, Add crypto, Save, Edit, Remove... must persist correctly" — and this page had never been walked through in a real logged-in browser before. It's had at least one real bug already (entries with no note appearing to save but silently failing) — treat every case below as a first real test, not a rubber stamp.

### TC-B1 — Add a Stock

Go to `/watchlist`. Add a stock symbol with a note. Confirm it appears in the list immediately.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B2 — Add a Crypto

Same as above, but select the crypto asset type when adding.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B3 — Add With No Note 🚩 previously a real data-loss bug

Add an entry with the note field left blank. Confirm no error toast appears and the entry is really saved — refresh the page to confirm.
**Why this matters:** this exact scenario previously appeared to save (showed on screen) but silently failed to actually persist to the account — a real "looks saved, isn't" bug, reportedly fixed. Re-test this specific no-note case, not just the with-a-note case.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B4 — Edit a Note

Edit the note on an existing entry. Confirm the change saves and survives a refresh.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B5 — Remove an Entry

Remove an entry. Confirm it disappears and stays gone after a refresh.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B6 — Persistence Across Login

Add entries, log out, log back in (or open the site on a different device/browser with the same account). Confirm the same watchlist entries are there.
**Caveat while login is temporarily open (see TC-D4):** "same account" is fuzzy right now since any email logs in — use the exact same email both times to get a meaningful result, and note that this test can't be considered fully proven until real Firebase login is restored.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-B7 — Star-Toggle in Scan Results Matches /watchlist Page

Run a scan, click the star icon on a result row to add it to your watchlist. Go to `/watchlist` and confirm that symbol appears there too — and vice versa, remove it from `/watchlist` and confirm the star un-highlights back in scan results.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

## Section C — Owner Dashboard

**Deliverable owed to the client, not a test case:** a screen recording of how to use the Settings section, since Ismail explicitly said he doesn't have time to test it himself and asked for one. Track separately — check this box once it's actually sent: ☐ Screen recording sent

### TC-C1 — Scanner Controls

Go to Settings → Scanner Controls. Test Start, Stop, and Refresh on the background worker. Change poll interval / batch size and Apply Config. Confirm the on-screen worker status actually changes to reflect what you did.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-C2 — Indicator Controls (enable/disable + defaults)

Go to Settings → Indicator Controls. Disable one indicator (e.g. MACD) and confirm it disappears from the "Add Indicator" picker, while a scan that already had it configured stays unaffected. Then edit the indicator-defaults JSON, save it, add that indicator fresh in a new scan, and confirm it picks up the new default value.
**There are two separate JSON textareas here, not one** — test both: the first is per-indicator defaults (as above); the second is specifically for **Confluence / Channel Respect toggle-on defaults**. Edit that second textarea, save, then enable Confluence or Channel Respect fresh on a new indicator card and confirm it picks up your edited defaults, not the original hardcoded ones.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-C3 — API/Integration Controls — Pause

Go to Settings → Integration Controls for one data provider (e.g. Massive). Toggle **Paused** on. Confirm live data fetches for that provider actually stop while the Enabled/API-key config stays intact. Toggle Paused back off and confirm fetches resume.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-C4 — View Errors / Response Times

Open the "View Errors / Response Times" panel for a provider after running at least one real scan. Confirm it populates with recent response-time entries (and an error entry, if you can trigger one).

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-C5 — Settings Page Health Auto-Loads

Open the Settings page fresh (don't click Refresh). Confirm Site Health/Readiness populates automatically instead of showing "unknown" until manually refreshed.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

## Section D — Cross-Feature Checks & This Week's New Asks

### TC-D1 — Multiple Indicators Combined in One Scan 🆕 NEW THIS WEEK

**Client's exact ask:** "test also multiple indicators choosed to give results."
**On our site:** Add 2-3 different indicators to a single scan (e.g. RSI + WaveTrend + Trendy ADX) with settings you'd expect at least one real symbol to satisfy. Run the scan.
**Expected:** results only include symbols that pass **all** selected indicator conditions (current production behavior is AND across selected indicators — confirm this is still true and is what actually comes back, not just that the scan runs without an error). Spot-check one returned symbol manually against 2 of the 3 indicators to confirm it genuinely does pass each one.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-D2 — Gate → Entry End-to-End Returns Real Results 🆕 NEW THIS WEEK

**Client's exact ask:** "the gate time frame is working properly and giving results."
**On our site:** Run a Gate scan with filters loose enough that some symbols pass. Then run the Entry scan using that gate session with a second timeframe/indicator set.
**Expected:** the Entry step actually returns real results (not an empty list, not an error) for symbols that passed the Gate. Also confirm a gate session can't be reused a second time (double-click or retry the Run button) — should return an empty result on the second attempt, not duplicate or error.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-D3 — Indicator Label Clarity: Trendy ADX & VLR 🚩 FLAGGED BY CLIENT 🆕 NEW THIS WEEK

**Client's exact words:** *"Can you tell them to make command for the new indicators user friendly. Example: 'background zone active' may not be easy to know which one for bullish is green just started."*
**On our site:** run scans with Trendy ADX and with VLR separately, and read the result label/sticker text for a few different matched conditions on each.
**Expected:** every label should read in plain language a non-technical user understands at a glance — direction (bullish/bearish) and stage (just started vs. already confirmed), not raw internal zone/state names. Team commitment: labels for both indicators are being rewritten to state meaning directly. If you're testing before that lands, note the exact current label text here so it's easy to compare before/after once it ships.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-D4 — Login: Temporary Open Access + Single-User Concern 🚩 FLAGGED BY CLIENT 🆕 NEW THIS WEEK

**Client's exact concern:** seeing "not secure" on the login page, and being able to log in with literally any email/password. His words: *"Only my email should be the user only one user no other can you check that."*
**Current, intentional state:** real Firebase sign-in is disabled until the client grants Firebase developer access (added under Project Settings → Users and permissions, not shared credentials). Anyone with the URL can currently get in with any email/password. This is not a bug — but it is a real, live exposure window for as long as it's in this state, and it directly caused a client trust concern.
**What to verify:**
- Confirm this state is still true (any email/password logs in) so it's not silently forgotten as "already handled."
- Confirm nothing sensitive (other users' data, admin controls) is reachable by an anonymous/random login during this window.
- Once Firebase developer access is granted and real login is restored, re-test this specific case: confirm only the client's actual email can log in, and that flipping the switch back didn't break anything else that was built/tested while login was open.

Pass ☐ Fail ☐ Partial ☐ (mark Pass once real login is restored and confirmed working — until then, this should stay open, not marked done)

Developer Notes / Accuracy Findings:



---

## Section E — Reliability / Bug Regression Checks

These are platform-level bugs already found and fixed, not indicator math — still worth a fast pass since they affect every feature above, including the new ones.

### TC-E1 — One Bad Symbol Doesn't Crash the Whole Scan

Ask a developer to simulate one malformed symbol in a batch scan and confirm the rest of the scan still completes.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-E2 — No Fake Data When Backend Is Unreachable 🚩 FLAGGED BY CLIENT

Ask a developer to briefly stop the backend, then try running a scan.
**Expected:** a clear, real error message — never fabricated results that look like a real scan.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-E3 — Confirmation Counts on the Newest Closed Candle 🚩 FLAGGED BY CLIENT

Pick any indicator, enable "Confirmation," and find a case where the signal condition is satisfied on the most recently closed candle.
**Expected:** counts as confirmed immediately, no waiting for one more candle. An in-progress/unfinished candle must never be treated as confirmed.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-E4 — Full-Universe Scan Speed 🚩 FLAGGED BY CLIENT

Run a full scan across the entire stock universe (all symbols, no narrowing filters) and time it. Expected: meaningfully faster than the original ~39.5 seconds.

Time observed: `________________`

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

### TC-E5 — Admin Endpoints Secured in Production (developer-only check)

Confirm that with `APP_ENV=production` and no `ADMIN_API_TOKEN` set, the `/screen/ops/*` admin endpoints return a 403, not open access.

Pass ☐ Fail ☐ Partial ☐

Developer Notes / Accuracy Findings:



---

## Section F — Known Blocked Items (do not report as new bugs)

| Item | Why it's blocked | What's needed to unblock |
|---|---|---|
| Compliance Standards buttons (AAOIFI, Dow Jones Islamic, MSCI, S&P, FTSE Shariah) | Current compliance data only gives one overall status, not individual standards. Client's own words: "this is the last real piece left. Everything else is implemented and tested." | The Zoya API key from the client |
| Sector Filter | No sector field exists in the current stock data file | Sector data source (Zoya or Massive API — being checked) |
| Asset Category — S&P 500 / Dow Jones / Russell / ETF groupings | No index-membership field exists in the current stock data file | Same data source as Sector Filter |
| "Replace API" / "Add backup API" (Owner Dashboard) | No provider-abstraction layer exists yet; explicitly deferred by client decision as separate scoped work | A future, separately scoped piece of work |

---

## Section G — Account/Access Items (needs a client action)

| # | Item | Action needed | Status |
|---|---|---|---|
| 1 | Firebase project access | Team asked to be added as a **developer** (Project Settings → Users and permissions) rather than sent credentials — waiting on client | ☐ Done |
| 2 | Zoya API key | Needed to wire up Compliance Standards properly — the one real remaining piece | ☐ Done |
| 3 | GitHub repository was Public with a live API key committed | Set repo to Private, rotate/cancel the exposed key | ☐ Done |
| 4 | Railway backend access | Needed to confirm why the service was showing offline | ☐ Done |
| 5 | Netlify/Vercel frontend deploy access | Needed to actually deploy fixes live, not just verify locally (site is now on Vercel per the latest link) | ☐ Done |

---

## Section H — Deferred to Pass 2 (old indicators — placeholder only)

Full test cases for these will be written in a separate guide. Listed here only so nothing is forgotten and so priority order is clear going in — **the first three are already known-broken from the client's own live testing this week and should be tested first when Pass 2 starts**, not treated as routine confirmation passes:

1. **Linear Regression Candles** — confirmed still broken (piercing-from-below gives wrong result). Start here.
2. **Trend Channel [ChartPrime]** — client says "isn't correct." Currently being re-validated against TradingView.
3. **Channel Confluence / Confluence (all 4 types)** — client says "isn't correct." Currently being re-validated. Client also separately asked to "test confluence to work as intended" and "test also... the candle recognition" — candlestick pattern testing belongs in this same pass.
4. RSI
5. WaveTrend
6. Aroon Oscillator
7. MACD
8. EMA
9. Linear Regression Channel (LRC)
10. Regression Channel [DW]
11. Channel Respect (post-filter)
12. Candlestick Patterns (Doji/Inverted Hammer additions + tightened existing patterns)
13. Relative Volume
14. Volatility

---

## Sign-Off Summary

| Section | Total test cases | Passed | Failed | Partial | Blocked (expected) |
|---|---|---|---|---|---|
| A — New Indicators & Filters | 5 | | | | |
| B — Watchlists | 7 | | | | |
| C — Owner Dashboard | 5 | | | | |
| D — Cross-Feature & New Asks | 4 | | | | |
| E — Reliability / Bug Regression | 5 | | | | |

**Overall notes / anything that needs a follow-up call before sign-off:**




**Tested by:** `________________`
**Date:** `________________`

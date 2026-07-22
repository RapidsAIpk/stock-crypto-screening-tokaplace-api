# Trend Channel Bug Fixes — Daily Report

**Project:** Backend_Crypto_project  
**Date:** 22 July 2026  
**Focus:** TradingView parity, Trend Channel rule accuracy, closed-candle safety, and validation coverage

---

## Executive Summary

Today’s work focused on correcting the Trend Channel implementation so that its channel coordinates and custom screening rules behave more consistently with the supplied TradingView ChartPrime Pine Script.

The most important fixes were:

- Corrected Trend Channel pivot anchoring.
- Fixed false positives in zone-entry rules.
- Added proper support for body-versus-wick checks.
- Applied zone tolerance correctly.
- Preserved an explicit tolerance value of `0`.
- Prevented forming candles from generating confirmed Trend Channel signals.
- Added focused evidence output for debugging.
- Added a dedicated Trend Channel regression test suite.

The focused Trend Channel suite now passes **45 out of 45 tests**.

---

## 1. Pivot Anchor Positioning Fixed

### Problem

The Python implementation already stored:

- `index`: the real pivot candle index.
- `confirm_index`: the candle where the pivot becomes confirmed.

However, the channel line initializer subtracted the Trend Channel length again. This shifted every rendered channel too far to the left.

### Fix

The channel is now anchored directly to the real pivot candle indexes.

### Result

- Channel coordinates now line up with the actual pivot candles.
- Synthetic validation confirmed that the first channel point matches the expected Pine value.
- Trend Channel placement is now materially closer to TradingView.

---

## 2. Top-Zone and Bottom-Zone Entry Logic Fixed

### Problem

The previous `entered` rule always checked the full candle wick range:

```text
candle low <= zone upper
and
candle high >= zone lower
```

This happened even when the user selected:

```text
touch type = body
```

That caused false positives. A candle could pass when only its wick touched the zone while its body stayed completely outside it.

### Fix

The evaluator now respects the configured geometry:

- `wick`: evaluates the full high-low range.
- `body`: evaluates only the open-close range.
- Other supported geometry is handled according to existing project behavior.

### Result

The confirmed CCU false-positive case is now handled correctly:

```text
Rule: top_zone → entered → body
Window: 1
Tolerance: 0
Body completely outside the zone
Expected: FAIL
```

The backend now returns **FAIL** for that condition.

---

## 3. Zone Tolerance Fixed

### Problem

Trend Channel line rules supported tolerance, but zone rules ignored it.

A separate falsy-value issue could also replace an explicit numeric zero with a default value.

### Fix

- Zone boundaries now apply the configured tolerance.
- `null` is interpreted as the default zero tolerance.
- An explicit `0` remains exactly `0`.

### Result

Boundary and near-boundary rules now behave predictably and can be tested without silently changing the user’s settings.

---

## 4. Forming Candle Signals Blocked

### Problem

The Trend Channel handler could receive a latest candle marked:

```json
"is_closed": false
```

That candle could still participate in channel calculation and signal evaluation, creating unstable or repainting matches.

### Fix

The Trend Channel handler now excludes the trailing unclosed candle before computing and evaluating confirmed signals.

### Result

- Confirmed Trend Channel matches now use completed candles only.
- Live/forming candles can no longer create a confirmed Trend Channel result.
- Behavior is more consistent with TradingView closed-bar validation.

---

## 5. Debug Evidence Added

Trend Channel evaluation now provides more useful evidence for validation and troubleshooting.

The evidence can include values such as:

- Checked candle index.
- Checked candle timestamp.
- Candle closed state.
- Selected area and action.
- Wick and body ranges.
- Line or zone boundaries.
- Tolerance.
- Final matched state.
- Channel direction and break state.

### Result

When a backend result differs from TradingView, the exact candle and boundary used by the backend can now be inspected instead of relying only on a final sticker.

---

## 6. Files Changed

### Backend logic

- `services/trend_channels.py`
  - Fixed pivot anchoring.
  - Corrected zone-entry logic.
  - Added body/wick-aware geometry checks.
  - Added zone tolerance handling.
  - Fixed explicit-zero tolerance handling.
  - Added optional rule evidence.

- `services/indicators.py`
  - Added closed-candle filtering for Trend Channel.
  - Returned Trend Channel evidence with the sticker result.

### Tests

- `tests/test_backend_services.py`
  - Updated expectations that previously depended on the incorrect shifted channel coordinates.

- `tests/test_trend_channels.py`
  - Added a new dedicated Trend Channel test suite.

---

## 7. Validation Results

### Focused Trend Channel tests

```text
45 passed / 45 total
```

### Backend regression suite

```text
234 passed
8 pre-existing failures
```

The same eight failures existed before the Trend Channel changes and were reported as unrelated to this work.

### Full unittest discovery

```text
406 tests discovered
Same 8 pre-existing failures
2 pre-existing loader errors because TA-Lib was not installed
0 new Trend Channel regressions
```

---

## 8. Manual Validation Results

### CCU

```text
Rule: top_zone → entered → body
Window: 1
Tolerance: 0
Expected: FAIL
```

The body does not overlap the visible top zone, so the corrected backend rule should now fail.

### FLL

```text
Rule: top_line → touched → wick
Window: 1
Expected: PASS when the latest completed wick intersects the top line
```

This valid wick-touch behavior is covered by regression tests and should remain working.

### GITS

```text
Rule: top_line → touched → wick
Window: 1
Expected: PASS when the latest completed wick intersects the top line
```

This valid behavior should also remain working after the zone-rule corrections.

---

## 9. Additional Integration Issue Identified

A separate Gate → Entry request-building problem was identified during validation.

### Problem

A Trend Channel configured with:

```json
"timeframe": "single"
```

inside a `gate_entry` scan was removed from the stage-specific request. The entry request then contained:

```json
"indicators": []
```

This meant Trend Channel was not evaluated even though it appeared selected in the UI.

### Correct behavior

- `primary`: run on the gate timeframe.
- `secondary`: run on the entry timeframe.
- `single`: valid only in single-scan mode.

For a 1-hour entry-stage Trend Channel, the request must use:

```json
"timeframe": "secondary"
```

### Status

This was identified as a **frontend/request-building issue** and is separate from the completed backend Trend Channel logic fixes. Its implementation should be verified independently before deployment.

---

## 10. Remaining TradingView Parity Limitations

### Minimum tick rounding

The supplied Pine Script uses:

```text
math.round_to_mintick
```

The backend does not currently expose reliable per-symbol minimum tick metadata. No universal tick size was hardcoded because that would be incorrect for many stocks and crypto assets.

### Liquidity label calculation

The current backend liquidity metadata is still based on a volume/range heuristic. It does not exactly reproduce Pine’s WMA, normalization, percentile, and `LV/MV/HV` classification.

This does not currently change the price-based channel break decision, but it remains a documented parity limitation.

---

## Final Status

| Area | Status |
|---|---|
| Pivot positioning | Fixed |
| Channel coordinates | Fixed and regression-tested |
| Top-zone body entry | Fixed |
| Wick/body selection | Fixed |
| Zone tolerance | Fixed |
| Explicit tolerance `0` | Fixed |
| Forming-candle signal protection | Fixed |
| Trend Channel evidence | Added |
| Focused tests | 45/45 passed |
| New regressions | None detected |
| Minimum-tick parity | Pending metadata support |
| Pine liquidity-label parity | Not implemented |
| Gate-entry frontend indicator transfer | Identified, requires separate verification |

---

## Conclusion

The Trend Channel backend is now significantly safer and more accurate than before. The confirmed pivot-positioning bug, zone body-entry false positives, tolerance handling, and forming-candle signal risk have all been addressed and covered by focused tests.

The next validation step is to re-check CCU, FLL, and GITS on TradingView using the same completed candle, timezone, timeframe, session, and Trend Channel settings. The separate Gate → Entry frontend scope issue should also be verified before production deployment.

# Dead Assets Strong Trend Fix

## Scope

This change corrects how the `strong_dead_trend` filter counts lower highs and
lower lows and how it detects a higher-high reset inside the recovery lookback.
It applies to every asset type that uses the shared Dead Assets service,
including stocks and crypto.

## Behavior Before

The backend used the largest lower-high and lower-low run found anywhere in the
available candle history. An old downtrend could therefore continue satisfying
the filter after a newer swing had broken and reset that structure.

The old counter also included the first reference swing in the count. A setting
of `lower_highs_required: 3` could pass with only two actual decreases, such as
`7.81 -> 3.9298 -> 3.7899`.

Higher-high detection required a confirmed swing high at or before the start of
the lookback. When the backend had exactly 200 candles and the lookback was 200,
the start index was zero and there was usually no earlier reference. The check
then returned false even when a clear higher high existed inside those 200 bars.

For CRVO, the old evaluation used:

- maximum historical lower-high run: 9
- maximum historical lower-low run: 6
- closes below EMA 200: 170 of 200 (85%)
- latest EMA 200: approximately 4.9634 and downward
- higher high in the 200-bar lookback: incorrectly false

That produced `Excluded - Strong Dead Trend`.

## What Changed

`services/dead_assets.py` now:

1. Counts only consecutive lower swings ending at the latest confirmed swing.
2. Counts actual decreases, not the initial reference swing. Three required
   lower highs therefore require four chronological swing highs with three
   consecutive decreases.
3. Stops the active count as soon as an equal or higher swing resets the run.
4. Checks chronological adjacent swing highs inside the lookback, including the
   most recent confirmed high immediately before the lookback when one exists.
5. Correctly handles `recovery_lookback == len(candles)` without requiring an
   impossible pre-index-zero reference.

Swing confirmation itself is unchanged: the backend uses a five-bar left and
five-bar right pivot (`SWING_SPAN = 5`). Only completed candles are evaluated.
The recovery override is also unchanged and still uses the configured candle
field: `close_above_swing_high` compares the latest completed close, not its
wick/high.

## Current CRVO Result

The cached CRVO 1D dataset contains 200 completed candles through July 21, 2026.
The latest candle is:

| Date | Open | High | Low | Close |
|---|---:|---:|---:|---:|
| July 21, 2026 | 2.77 | 2.9099 | 2.72 | 2.89 |

Recent confirmed swing highs are:

| Date | Swing high | Structure |
|---|---:|---|
| May 8, 2026 | 4.153 | reference before reset |
| June 18, 2026 | 7.81 | higher high; resets prior lower-high run |
| July 1, 2026 | 3.9298 | lower high 1 |
| July 10, 2026 | 3.7899 | lower high 2 |

Recent confirmed swing lows are:

| Date | Swing low | Structure |
|---|---:|---|
| March 30, 2026 | 3.51 | reference |
| April 30, 2026 | 3.61 | higher low; resets prior lower-low run |
| May 19, 2026 | 2.815 | lower low 1 |
| June 10, 2026 | 2.13 | lower low 2 |

With requirements of 3 and 3, CRVO currently has only 2 active lower highs and
2 active lower lows. It also has a valid higher high inside the lookback:
`7.81 > 4.153`.

The current backend decision is:

```text
excluded: false
overridden: false
label: null
type: null
```

This means CRVO is allowed because no strong dead trend is currently confirmed.
It is not labeled `Allowed - Recovery Started`, because the recovery override
condition is still false:

```text
latest completed close 2.89 > latest confirmed swing high 3.7899 = false
```

## Automated Verification

Regression coverage was added for:

- counting only the active trailing lower-swing sequence
- counting actual lower events rather than reference swing points
- resetting an older strong-dead-trend run after a higher swing
- finding a higher high when the lookback equals the entire 200-candle dataset
- preserving exclusion for a genuinely active strong dead trend
- preserving the close-above-swing-high recovery override

Run:

```powershell
python -m pytest tests/test_backend_services.py -k "DeadAssetsTests" -q
```

## Manual TradingView Verification

1. Open `NASDAQ:CRVO` on the `1D` timeframe and use regular-session daily bars.
2. Evaluate only completed candles. For the reproduced dataset, stop at July 21,
   2026; do not count the July 22 forming candle.
3. Add EMA 200 and confirm the broad trend is downward. EMA values can differ
   slightly because TradingView may initialize from more history than the
   backend's 200 fetched bars, but this does not change the swing reset.
4. Mark pivot highs and lows using five bars on the left and five on the right.
   A pivot is not confirmed until the fifth later daily candle has closed.
5. Confirm the June 18 high of 7.81 is above the May 8 high of 4.153. This is the
   higher-high reset.
6. From June 18, count the later confirmed lower highs: July 1 and July 10. The
   active count is 2, not 3.
7. Confirm the April 30 low of 3.61 is above the March 30 low of 3.51. This resets
   the lower-low sequence.
8. From April 30, count the later confirmed lower lows: May 19 and June 10. The
   active count is 2, not 3.
9. For the recovery override, compare the latest completed close of 2.89 with
   the latest confirmed swing high of 3.7899. Because it is below that level,
   the override itself should not trigger.
10. Rerun the backend filter. CRVO should remain in the results without a Dead
    Assets recovery sticker. If it is still excluded, restart/redeploy the API
    process so it loads the updated service code, then refresh its daily data.

For easier pivot verification in TradingView, this Pine Script plots the same
five-left/five-right confirmation model:

```pine
//@version=5
indicator("Dead Assets 5x5 Swing Check", overlay=true)
span = 5
ph = ta.pivothigh(high, span, span)
pl = ta.pivotlow(low, span, span)
plotshape(not na(ph), offset=-span, style=shape.triangledown,
     location=location.abovebar, color=color.red, size=size.tiny, text="SH")
plotshape(not na(pl), offset=-span, style=shape.triangleup,
     location=location.belowbar, color=color.green, size=size.tiny, text="SL")
plot(ta.ema(close, 200), "EMA 200", color=color.gray)
```

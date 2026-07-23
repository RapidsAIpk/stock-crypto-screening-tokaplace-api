# Dead Assets validation combos

*Regenerated: 2026-07-22 13:32 UTC · Timeframe: **1D** · Backend: current `services/dead_assets.py` after the strong-trend swing-count fix · Cache range: 2026-07-21 06:57 UTC to 2026-07-22 13:32 UTC*

Use this sheet to verify the scanner on TradingView. **Dead Assets excludes** matching symbols unless the recovery override readmits them. Indicators are **AND** filters: every enabled rule must pass.

## Important current behavior

- Strong Dead Trend now counts only the active trailing sequence of confirmed lower highs and lower lows.
- `lower_highs_required: 3` means three actual lower-high events, requiring four chronological swing highs.
- A higher high resets the active lower-high sequence.
- Recovery override is checked after a dead trend is detected.
- `close_above_swing_high` uses the latest completed candle close, not wick/high.
- The CRVO Strong Dead Trend bug is fixed: CRVO has only 2 active lower highs and 2 active lower lows in the reproduced 1D cache, so it is not Strong Dead Trend.
- CRVO can still be excluded by other enabled dead types, especially `failed_recovery`; that is a separate rule from Strong Dead Trend.

## Default settings used

### Dead Assets

| Setting | Value |
|---|---|
| Enabled | yes |
| Dead trend types | all 4 (Strong, Slow Bleeding, Failed Recovery, Flat) |
| Lower highs / lower lows required | 3 / 3 |
| Trend source | EMA 200 |
| Recovery lookback | 200 candles |
| Volume / volatility (flat dead) | either / either |
| Bounce threshold | 20% |
| Failure window | 20 candles |
| Recovery override | close above previous confirmed swing high |

### WaveTrend (current backend defaults)

| Setting | Value |
|---|---|
| Channel / average / signal length | 10 / 21 / 4 |
| Threshold | 60 |
| Zone | oversold |
| Direction | turning_up |
| Window | 1 candle |

**What it keeps:** symbols where WaveTrend is in the **oversold** zone and **turning up** on the latest closed daily bar.

### VLR (current backend defaults)

| Setting | Value |
|---|---|
| Source | close |
| Regressions | 3 (periods 12 / 24 / 36) |
| Reversal type | both (exact + early) |
| Direction | both (bullish + bearish) |
| Timing window | last 3 candles |
| Crossing / volume / candle confirmation | all off |

**What it keeps:** symbols with **any** exact/early bullish **or** bearish reversal watch in the last 3 daily bars.

## Combo scenarios

| ID | Stack | Excludes when |
|---|---|---|
| `dead_only` | Dead Assets | Any selected dead-trend pattern matches and recovery override does not save it |
| `wt_only` | WaveTrend defaults | WT is not oversold + turning up |
| `vlr_only` | VLR defaults | No bullish/bearish reversal watch in timing window |
| `dead_wt` | Dead Assets + WaveTrend | Dead **or** WT fails |
| `dead_vlr` | Dead Assets + VLR | Dead **or** VLR fails |
| `dead_wt_vlr` | All three | Dead **or** WT fails **or** VLR fails |
| `wt_vlr` | WaveTrend + VLR (no Dead Assets) | WT fails **or** VLR fails |

**Pipeline order:** Price/compliance (if used) -> **Dead Assets** -> indicators (WaveTrend, VLR, ...) -> post-filters.

## Frozen fixture matrix (5 stocks)

Reliable offline check using `production_screener_validation` frozen daily candles through **2026-06-30**, evaluated with the current backend.

| Symbol | dead_only | wt_only | vlr_only | dead_wt | dead_vlr | dead_wt_vlr | wt_vlr |
|---|---|---|---|---|---|---|---|
| AAPL | PASS | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (WaveTrend: FAIL) |
| AMD | PASS (Allowed — Recovery Started) | EXCLUDE (WaveTrend: FAIL) | PASS | EXCLUDE (WaveTrend: FAIL) | PASS | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (WaveTrend: FAIL) |
| MSFT | EXCLUDE (Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) |
| NVDA | EXCLUDE (Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) |
| TSLA | PASS | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (WaveTrend: FAIL) |

### How to read the fixture table

- **MSFT / NVDA** are dead-asset failed-recovery examples on the frozen dataset.
- **AMD** shows the recovery override behavior: the dead condition is detected, but the asset is readmitted with `Allowed — Recovery Started`.
- **AAPL / TSLA** are healthy Dead Assets controls for the same fixture date.
- `dead_wt_vlr` is the strictest stack: a symbol must survive dead-asset screening **and** match WaveTrend **and** show a VLR reversal watch.

## Current live dead-asset candidates (stocks)

Symbols below were scanned against **one dead type at a time** with recovery override **disabled**, so you see the raw pattern without a rescue.
Open each on TradingView **1D** with EMA 200 and verify the chart matches the pattern name.

Scan scope: first **500** Zoya symbols with usable cached daily candles.

### Strong Dead Trend

`VSA`, `IPW`

### Slow Bleeding Trend

`VSA`, `IPW`

### Failed Recovery

`SKYH`, `DIT`, `MSN`, `FLL`, `VG`, `NE`, `CMCO`, `THRM`, `KYMR`, `OWL`, `TFX`, `HQI`, `IHT`, `VVX`, `TER`, `ZBIO`, `CHRD`, `BMGL`, `LXRX`, `DRIO`, `GRDX`, `CRVO`, `VSA`, `OLPX`, `MBIO`

*+ 351 more in the scanned universe.*

### Flat Dead Asset

`VSA`, `WNW`, `IBG`, `NEGG`, `OS`, `SLNO`, `CREG`, `CDTG`, `LZMH`

## Current live dead-asset candidates (crypto)

Symbols below use the same fixed shared Dead Assets backend.

Scan scope: first **120** crypto symbols with usable cached daily candles.

### Strong Dead Trend

_None in the scanned sample._

### Slow Bleeding Trend

`A8-USD`, `ACS-USD`, `AGLD-USD`, `ALEO-USD`, `ALEPH-USD`, `ALPHA-USD`

### Failed Recovery

`ACA`, `ACH`, `AERGO-USD`, `ALBT`, `ALG`, `ALPHA-USD`, `ALT`, `APE-USD`, `APP`, `APT`, `ASM`, `ATOM`, `AUCTION-USD`, `AUDIO-USD`, `AURORA-USD`, `AVAX-USD`, `AXL-USD`, `BADGER-USD`, `BAL-USD`, `BAND`, `BAT-USD`, `BCH`, `BCHN-USD`, `BEAM`, `BEST-USD`

*+ 52 more in the scanned universe.*

### Flat Dead Asset

`AXL-USD`, `AZERO-USD`, `BIGTIME-USD`, `BTRST-USD`, `CHZ-USD`, `CORECHAIN-USD`, `CPOOL-USD`, `CTX-USD`

## Combo pass list on evaluated live stock symbols

For the same 500-symbol live stock sample, these symbols survive each full combo:

### `dead_only` — Dead Assets only (all 4 types, defaults)

`GCBC`, `VG`, `AIR`, `APAM`, `IPEX`, `MCB`, `VVX`, `ZBIO`, `COLA`, `OLPX`, `OZK`, `QCRH`, `FERA`, `GSL`, `TRGP`, `UHAL`, `CM`, `RUSHB`, `MOG.A`, `GCT`, `BLK`, `DAO`, `PRU`, `ETON`, `UHAL.B`

*+ 154 more.*

### `wt_only` — WaveTrend defaults only

`QBTS`, `GBR`, `IPW`, `FLY`, `AEON`

### `vlr_only` — VLR defaults only

`FLL`, `VG`, `APAM`, `NE`, `THRM`, `TER`, `ZBIO`, `CHRD`, `DRIO`, `COLA`, `GRDX`, `OZK`, `EDTK`, `TOON`, `GSL`, `DFLI`, `TRGP`, `SPRB`, `EGG`, `CM`, `MOG.A`, `ARRY`, `GCT`, `CR`, `BLK`

*+ 155 more.*

### `dead_wt` — Dead Assets + WaveTrend defaults

_None passed in the scanned sample._

### `dead_vlr` — Dead Assets + VLR defaults

`VG`, `APAM`, `ZBIO`, `COLA`, `OZK`, `GSL`, `TRGP`, `CM`, `MOG.A`, `GCT`, `BLK`, `VRSK`, `PTNM`, `BANF`, `GLDD`, `MS`, `OS`, `LYFT`, `FTNT`, `MRSH`, `UBS`, `RPD`, `WSR`, `VMI`, `DRDB`

*+ 41 more.*

### `dead_wt_vlr` — Dead Assets + WaveTrend + VLR defaults

_None passed in the scanned sample._

### `wt_vlr` — WaveTrend + VLR defaults (no Dead Assets)

`IPW`

## CRVO sanity check

With `dead_trend_types: ["strong_dead_trend"]`, CRVO should **not** be excluded by Strong Dead Trend after the fix because the active trailing count is only 2 lower highs and 2 lower lows.

With all four default dead types enabled, CRVO may still be excluded by `failed_recovery`. That does not contradict the Strong Dead Trend fix.

## TradingView checklist per combo

### `dead_only`
1. Daily chart, EMA 200.
2. Confirm downtrend / lower highs-lows / failed bounce / flat volume+ATR per the dead type label from `/screen/details`.
3. Confirm swing highs/lows with a 5-left/5-right pivot model.
4. Symbol should **disappear** from scan results when a selected dead type matches and recovery override does not readmit it.

### `wt_only`
1. Add LazyBear WaveTrend using 10 / 21 / 4.
2. Use threshold +/-60 for current backend default parity.
3. Latest closed bar: WT1 is oversold and turning up.

### `vlr_only`
1. Add Gentleman-Goat Pearson-R oscillator (12 / 24 / 36 windows).
2. Check Red line for exact/early reversal watches in the last 3 bars.

### `dead_wt_vlr`
1. Run all three checks above.
2. Symbol must pass **all** layers; if it fails any one layer, it is excluded.

## Scan scope

This file was regenerated from the current local cache, not from the old July 16 pre-fix report:

- first 500 Zoya symbols with usable cached 1D candles
- first 120 crypto symbols with usable cached 1D candles
- current shared Dead Assets backend for stocks and crypto
- recovery override disabled only for the raw per-type candidate lists
- recovery override enabled for the default combo pass lists


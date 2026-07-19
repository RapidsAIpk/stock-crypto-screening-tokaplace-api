# Dead Assets validation combos

*Generated: 2026-07-16 08:15 UTC · Timeframe: **1D** · Stock fixture bar set: frozen daily candles through **2026-06-30***

Use this sheet to verify the scanner on TradingView. **Dead Assets always excludes** matching symbols. Indicators are **AND** filters: every enabled rule must pass.

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
| Recovery override | close above previous swing high |

### WaveTrend (product defaults)

| Setting | Value |
|---|---|
| Channel / average / signal length | 10 / 21 / 4 |
| Threshold | 35 |
| Zone | oversold |
| Direction | turning_up |
| Window | 1 candle |

**What it keeps:** symbols where WaveTrend is in the **oversold** zone and **turning up** on the latest closed daily bar.

### VLR (product defaults)

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
| `dead_only` | Dead Assets | Any selected dead-trend pattern matches (unless recovery override saves it) |
| `wt_only` | WaveTrend defaults | WT not oversold + turning up |
| `vlr_only` | VLR defaults | No bullish/bearish reversal watch in timing window |
| `dead_wt` | Dead Assets + WaveTrend | Dead **or** WT fails |
| `dead_vlr` | Dead Assets + VLR | Dead **or** VLR fails |
| `dead_wt_vlr` | All three | Dead **or** WT fails **or** VLR fails |
| `wt_vlr` | WaveTrend + VLR (no dead filter) | WT fails **or** VLR fails |

**Pipeline order:** Price/compliance (if used) → **Dead Assets** → indicators (WaveTrend, VLR, …) → post-filters.

## Frozen fixture matrix (5 stocks)

Reliable offline check — same candles as `production_screener_validation` fixtures.

| Symbol | dead_only | wt_only | vlr_only | dead_wt | dead_vlr | dead_wt_vlr | wt_vlr |
|---|---|---|---|---|---|---|---|
| AAPL | PASS | PASS | EXCLUDE (VLR: FAIL) | PASS | EXCLUDE (VLR: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (VLR: FAIL) |
| AMD | PASS | EXCLUDE (WaveTrend: FAIL) | PASS | EXCLUDE (WaveTrend: FAIL) | PASS | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (WaveTrend: FAIL) |
| MSFT | EXCLUDE (Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (WaveTrend: FAIL) |
| NVDA | EXCLUDE (Excluded — Failed Recovery) | PASS | EXCLUDE (VLR: FAIL) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (Dead Assets: Excluded — Failed Recovery) | EXCLUDE (VLR: FAIL) |
| TSLA | PASS | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (VLR: FAIL) | EXCLUDE (WaveTrend: FAIL) | EXCLUDE (WaveTrend: FAIL) |

### How to read the fixture table

- **MSFT** is the canonical dead-asset example on the frozen dataset.
- **AAPL / NVDA / AMD / TSLA** are healthy controls for the same date.
- `dead_wt_vlr` is the strictest stack: a symbol must survive dead-asset screening **and** match bullish WaveTrend **and** show a VLR reversal watch.

## Live dead-asset candidates (stocks)

Symbols below were scanned against **one dead type at a time** with recovery override **disabled**, so you see the raw pattern without a rescue.
Open each on TradingView **1D** with EMA 200 and verify the chart matches the pattern name.

### Strong Dead Trend

`AFYA`, `AIV`, `AIXC`, `AKBA`, `ALG`, `AMSF`, `AMT`, `APAM`, `BANF`, `BMGL`, `BRBR`, `BTMD`, `CBZ`, `CDTG`, `CPOP`

*+ 61 more in the scanned universe.*

### Slow Bleeding Trend

`AFYA`, `AIV`, `AIXC`, `AKBA`, `ALG`, `AMSF`, `AMT`, `APAM`, `BANF`, `BMGL`, `BRBR`, `BTMD`, `CBZ`, `CDTG`, `CPOP`

*+ 63 more in the scanned universe.*

### Failed Recovery

`AAMI`, `ACRV`, `ADNT`, `ADPT`, `AEON`, `AEVA`, `AFYA`, `AIXC`, `AKAM`, `AKAN`, `AKBA`, `ALG`, `AMBP`, `AMBQ`, `AMD`

*+ 315 more in the scanned universe.*

### Flat Dead Asset

`CREG`, `IBG`, `LZMH`, `NEGG`, `OS`, `SLNO`, `VSA`, `WNW`

## Live dead-asset candidates (Binance crypto)

### Strong Dead Trend

`CHR`

### Slow Bleeding Trend

`CHR`

### Failed Recovery

`ACH`, `ALT`, `ATOM`, `AXL`, `BAND`, `BCH`, `BEAM`, `CHR`, `COMP`, `CVX`

### Flat Dead Asset

`FARM`

## Combo pass list on evaluated live symbols

For the live sample, which symbols survive each full combo:

### `dead_only` — Dead Assets only (all 4 types, defaults)

`ACIC`, `ADPT`, `AIR`, `AMAT`, `AMG`, `ANGO`, `APAM`, `ATAT`, `ATRC`, `AWI`, `AZN`, `BA`, `BANF`, `BAP`, `BDX`, `BHP`, `BJRI`, `BK`, `BLK`, `BMI`, `BMY`, `BPRN`, `BSBK`, `CARS`, `CATY`

*+ 173 more.*

### `wt_only` — WaveTrend defaults only

`AIXC`, `AKAN`, `ATAT`, `ATGL`, `BMRA`, `FENG`, `GLSI`, `GURE`, `LTRX`, `NEON`, `NPWR`, `PFAI`, `PIII`, `PLAY`, `SLI`, `UMAC`, `VSA`

### `vlr_only` — VLR defaults only

`AAMI`, `ACRV`, `AKAN`, `AKBA`, `AMAT`, `AMG`, `AMSC`, `ANGO`, `ARRY`, `ASIX`, `ATGL`, `ATRC`, `AWI`, `BAH`, `BAP`, `BSBK`, `BTMD`, `CBZ`, `CCEC`, `CCL`, `CDRE`, `CDTG`, `CHEF`, `CMCO`, `CR`

*+ 134 more.*

### `dead_wt` — Dead Assets + WaveTrend defaults

`ATAT`, `FENG`

### `dead_vlr` — Dead Assets + VLR defaults

`AMAT`, `AMG`, `ANGO`, `ATRC`, `AWI`, `BAP`, `BSBK`, `CBZ`, `DAO`, `DDL`, `DK`, `DRDB`, `ELVN`, `EXFY`, `FTNT`, `GAIN`, `GEL`, `GLDD`, `GOOG`, `GOOGL`, `GRAB`, `HDSN`, `HSBC`, `HUBG`, `HVII`

*+ 35 more.*

### `dead_wt_vlr` — Dead Assets + WaveTrend + VLR defaults

_None passed in the scanned sample._

### `wt_vlr` — WaveTrend + VLR defaults (no Dead Assets)

`AKAN`, `ATGL`, `GURE`, `PIII`, `PLAY`, `SLI`

## TradingView checklist per combo

### `dead_only`
1. Daily chart, EMA 200.
2. Confirm downtrend / lower highs-lows / failed bounce / flat volume+ATR per the dead type label from `/screen/details`.
3. Symbol should **disappear** from scan results when the filter is on.

### `wt_only`
1. Add LazyBear WaveTrend (same lengths 10/21/4).
2. Latest bar: WT1/WT2 in oversold zone (default threshold ±35) and turning up.

### `vlr_only`
1. Add Gentleman-Goat Pearson-R oscillator (12/24/36 windows).
2. Check Red line for exact/early reversal watches in the last 3 bars.

### `dead_wt_vlr`
1. Run all three checks above.
2. Symbol must pass **all** — if it fails any one layer, it is excluded.

## Scan scope

This file was generated from a **500-stock** sample of `zoya_universe.json` plus **120 Binance crypto** symbols (live Massive API, 1D, recovery override disabled for per-type lists). Re-run a broader scan when you need more names beyond the first 15 per type.


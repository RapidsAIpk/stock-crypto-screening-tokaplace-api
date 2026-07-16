# Reference Candidate: rsi_and_aroon_and_ema

Candidate ID: `abce98811a822fc8dbfd59ce`
Fixture: `stocks_daily_2026_06_30_v1`
Status: `evaluated`
Expected symbols: none
Excluded symbols: AAPL, AMD, MSFT, NVDA, TSLA
Insufficient data: none

## Symbol Evidence

### AAPL

Expected: `False`
Status: `evaluated`

- `rsi` passed=`False` values=`{"rsi":46.91116212637808}`
- `aroon` passed=`False` values=`{"aroon_down":78.57142857142857,"aroon_oscillator":-21.428571428571423,"aroon_up":57.142857142857146}`
- `ema` passed=`True` values=`{"ema":288.78767082602894,"price":289.36}`

### AMD

Expected: `False`
Status: `evaluated`

- `rsi` passed=`False` values=`{"rsi":64.94245617261495}`
- `aroon` passed=`True` values=`{"aroon_down":0.0,"aroon_oscillator":100.0,"aroon_up":100.0}`
- `ema` passed=`True` values=`{"ema":536.6272980737925,"price":580.91}`

### MSFT

Expected: `False`
Status: `evaluated`

- `rsi` passed=`False` values=`{"rsi":41.308624354301585}`
- `aroon` passed=`False` values=`{"aroon_down":78.57142857142857,"aroon_oscillator":-78.57142857142857,"aroon_up":0.0}`
- `ema` passed=`False` values=`{"ema":373.8912786249776,"price":373.02}`

### NVDA

Expected: `False`
Status: `evaluated`

- `rsi` passed=`False` values=`{"rsi":45.21381183673035}`
- `aroon` passed=`False` values=`{"aroon_down":92.85714285714286,"aroon_oscillator":-35.714285714285715,"aroon_up":57.142857142857146}`
- `ema` passed=`True` values=`{"ema":199.99186522999483,"price":200.09}`

### TSLA

Expected: `False`
Status: `evaluated`

- `rsi` passed=`False` values=`{"rsi":56.78151894870578}`
- `aroon` passed=`False` values=`{"aroon_down":85.71428571428572,"aroon_oscillator":14.285714285714278,"aroon_up":100.0}`
- `ema` passed=`True` values=`{"ema":398.6219673534287,"price":420.6}`

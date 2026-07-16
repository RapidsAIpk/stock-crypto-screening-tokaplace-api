# Reference Candidate: aroon_and_ema

Candidate ID: `a1fde1a9cfe64ebabd5eccb7`
Fixture: `stocks_daily_2026_06_30_v1`
Status: `evaluated`
Expected symbols: AMD
Excluded symbols: AAPL, MSFT, NVDA, TSLA
Insufficient data: none

## Symbol Evidence

### AAPL

Expected: `False`
Status: `evaluated`

- `aroon` passed=`False` values=`{"aroon_down":78.57142857142857,"aroon_oscillator":-21.428571428571423,"aroon_up":57.142857142857146}`
- `ema` passed=`True` values=`{"ema":288.78767082602894,"price":289.36}`

### AMD

Expected: `True`
Status: `evaluated`

- `aroon` passed=`True` values=`{"aroon_down":0.0,"aroon_oscillator":100.0,"aroon_up":100.0}`
- `ema` passed=`True` values=`{"ema":536.6272980737925,"price":580.91}`

### MSFT

Expected: `False`
Status: `evaluated`

- `aroon` passed=`False` values=`{"aroon_down":78.57142857142857,"aroon_oscillator":-78.57142857142857,"aroon_up":0.0}`
- `ema` passed=`False` values=`{"ema":373.8912786249776,"price":373.02}`

### NVDA

Expected: `False`
Status: `evaluated`

- `aroon` passed=`False` values=`{"aroon_down":92.85714285714286,"aroon_oscillator":-35.714285714285715,"aroon_up":57.142857142857146}`
- `ema` passed=`True` values=`{"ema":199.99186522999483,"price":200.09}`

### TSLA

Expected: `False`
Status: `evaluated`

- `aroon` passed=`False` values=`{"aroon_down":85.71428571428572,"aroon_oscillator":14.285714285714278,"aroon_up":100.0}`
- `ema` passed=`True` values=`{"ema":398.6219673534287,"price":420.6}`

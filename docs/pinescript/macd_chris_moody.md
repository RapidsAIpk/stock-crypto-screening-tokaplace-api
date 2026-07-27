# CM_Ult_MacD_MTF [ChrisMoody]

Reference source supplied on 2026-07-27.

Signal-relevant Pine logic:

```pinescript
source = close
fastLength = input(12, minval=1), slowLength=input(26,minval=1)
signalLength=input(9,minval=1)

fastMA = ema(source, fastLength)
slowMA = ema(source, slowLength)

macd = fastMA - slowMA
signal = sma(macd, signalLength)
hist = macd - signal

outMacD = security(tickerid, res, macd)
outSignal = security(tickerid, res, signal)
outHist = security(tickerid, res, hist)

histA_IsUp = outHist > outHist[1] and outHist > 0
histA_IsDown = outHist < outHist[1] and outHist > 0
histB_IsDown = outHist < outHist[1] and outHist <= 0
histB_IsUp = outHist > outHist[1] and outHist <= 0

macd_IsAbove = outMacD >= outSignal
macd_IsBelow = outMacD < outSignal
```

Backend indicator key: `macd`.

The backend request timeframe already selects the candle resolution, so the Pine `security(tickerid, res, ...)` behavior is represented by running the indicator over the request's selected timeframe candles.

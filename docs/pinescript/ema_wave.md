# EMA Wave Indicator [LazyBear]

Reference source supplied on 2026-07-27.

```pinescript
study("EMA Wave Indicator [LazyBear]", shorttitle="EWI_LB")
alength=input(5, title="Wave A Length"), blength=input(25, title="Wave B Length"), clength=input(50, title="Wave C Length")
lengthMA=input(4, title="Wave SMA Length")
mse=input(false, title="Identify Spikes/Exhaustions")
cutoff = input(10, title="Cutoff")
ebc=input(false, title="Color Bars on Spikes/Exhaustions")
src=hlc3
ma(s,l) => ema(s,l)
wa=sma(src-ma(src, alength),lengthMA)
wb=sma(src-ma(src, blength),lengthMA)
wc=sma(src-ma(src, clength),lengthMA)
wcf=(wb != 0) ? (wc/wb > cutoff) : false
wbf=(wa != 0) ? (wb/wa > cutoff) : false
```

Backend indicator keys: `ema` and `ema_wave`.

The `ema` key now defaults to this LazyBear EMA Wave calculation so TradingView EWI_LB validation uses the same backend path. The old simple price-vs-EMA filter remains available only when explicitly requested with `mode: "price"`, `mode: "simple"`, or `simple_ema: true`.

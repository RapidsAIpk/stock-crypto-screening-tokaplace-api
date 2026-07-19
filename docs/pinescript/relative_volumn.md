//@version=5
indicator("RelVol")
AvgVol = ta.sma(volume,10)
plot(volume/AvgVol[1], title="Relative Volume")


//@version=5
indicator("RelVolForCEX")
volExpr = syminfo.volumetype == "quote" ? volume : ( syminfo.volumetype == "base" ? close * volume : na )
volInUSD = volExpr*request.currency_rate(syminfo.currency, "USD", ignore_invalid_currency = true)
avgVol10d = ta.sma(volInUSD, 10)
plot(volInUSD / avgVol10d[1], title='relative_volume_10d_calc_usd')



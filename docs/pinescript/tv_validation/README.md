# TradingView manual validation

Production screener pass lists for custom Pine-backed indicators.

Workflow:

1. Run `python backend/scripts/run_custom_indicator_suite.py`
2. Export sheets: `python backend/scripts/export_tv_validation_sheets.py --reports-dir <run_dir>`
3. Open the indicator checklist next to TradingView and mark agree/disagree.

## Checklists

- [Humble LinReg Candles](./linreg_candles_minimal.md)
- [Linear Regression Channel [jwammo12]](./lrc_minimal.md)
- [Regression Channel [DW]](./regression_minimal.md)
- [RelVol (stocks)](./relative_volume_minimal.md)
- [Trend Channels With Liquidity Breaks [ChartPrime]](./trend_minimal.md)
- [Volatility study](./volatility_minimal.md)
- [WaveTrend [LazyBear]](./wavetrend_minimal.md)

See also: [comparison.md](../comparison.md), [fix_summary.md](../fix_summary.md).

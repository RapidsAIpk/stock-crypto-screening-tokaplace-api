import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.rsi import compute_rsi_series, evaluate_rsi_rules

FIXTURE = (
    BACKEND
    / "production_screener_validation/data/fixtures/stocks_daily_2026_06_30_v1/candles/1day/AAPL.json"
)
CONFIG = {
    "length": 14,
    "location": "overbought",
    "direction": None,
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}

candles = json.loads(FIXTURE.read_text(encoding="utf-8"))
june_days = [c for c in candles if c["date"].startswith("2026-06")]

print("AAPL RSI overbought walk-forward — June 2026")
print("Filter: RSI(14) >= 70, window=1 (same as rsi.md)")
print()
print(f"{'Date':<12} {'Close':>8} {'RSI':>7} {'Pass?':>6} {'Screener':>10}")
print("-" * 48)

pass_days = []
for day in june_days:
    idx = next(i for i, c in enumerate(candles) if c["date"] == day["date"])
    slice_candles = candles[: idx + 1]
    series = compute_rsi_series(slice_candles, 14)
    if series is None or len(series) == 0:
        continue
    passed = evaluate_rsi_rules(series, slice_candles, CONFIG)
    rsi = float(series[-1])
    verdict = "INCLUDE" if passed else "EXCLUDE"
    mark = "PASS" if passed else "no"
    print(f"{day['date']:<12} {day['close']:>8.2f} {rsi:>7.2f} {mark:>6} {verdict:>10}")
    if passed:
        pass_days.append(day["date"])

print()
print(f"Days AAPL would be INCLUDED: {', '.join(pass_days) or 'none'}")

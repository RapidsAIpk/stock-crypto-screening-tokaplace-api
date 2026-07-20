# scripts/run_lrc_brute_force.py
import asyncio
import os
import sys
import json
import numpy as np

# Ensure backend imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.linear_regression_candles import compute_linreg_candles, evaluate_linreg_candle_rules
from services.market_data import fetch_live_data, close_market_data_clients

COMBOS = [
    # (ComboID, lin_reg, lr_length, sma_signal, signal_smoothing, price_position, close_location, tolerance_pct, window)
    ("C1 (I1+R1)", True, 11, True, 11, "above", None, 0, 1),
    ("C2 (I1+R2)", True, 11, True, 11, "above", "close_above", 0, 1),
    ("C3 (I1+R3)", True, 11, True, 11, "above", "close_below", 0, 1),
    ("C4 (I1+R4)", True, 11, True, 11, "below", None, 0, 1),
    ("C5 (I1+R5)", True, 11, True, 11, "below", "close_below", 0, 1),
    ("C6 (I1+R6)", True, 11, True, 11, "below", "close_above", 0, 1),
    ("C7 (I1+R7)", True, 11, True, 11, "on", None, 0, 1),
    ("C8 (I1+R8)", True, 11, True, 11, "on", "close_on", 0, 1),
    ("C9 (I1+R9)", True, 11, True, 11, "piercing_from_below", None, 0, 1),
    ("C10 (I1+R10)", True, 11, True, 11, "piercing_from_above", None, 0, 1),
    ("C11 (I1+R11)", True, 11, True, 11, "above", None, 5, 1),
    ("C12 (I1+R12)", True, 11, True, 11, "above", None, 0, 3),
]

def format_candle(c):
    return f"O:{c['open']:.4f} H:{c['high']:.4f} L:{c['low']:.4f} C:{c['close']:.4f}"

async def main():
    target_symbols = ["AAPL", "AMD", "MSFT", "NVDA", "TSLA", "APAM", "AIR"]
    print(f"Fetching LIVE candles for: {target_symbols}")
    
    # Fetch 100 candles to have plenty of history for indicators
    try:
        data = await fetch_live_data(
            target_symbols,
            "1day",
            include_fundamentals=False,
            candles_limit=100
        )
    except Exception as e:
        print(f"Error fetching live data: {e}")
        return
    finally:
        await close_market_data_clients()

    universe = {}
    for asset in data:
        symbol = asset["symbol"]
        candles = asset.get("candles", [])
        if len(candles) >= 30:
            universe[symbol] = candles

    print(f"Successfully loaded live data for {len(universe)} symbols.")
    
    # Pre-calculate LRC results for Config I1 (LR=11, Smooth=11, SMA=True, Reg=True)
    precalc_i1 = {}
    for symbol, candles in universe.items():
        res = compute_linreg_candles(candles, lr_length=11, signal_smoothing=11, sma_signal=True, lin_reg=True)
        if res is not None:
            precalc_i1[symbol] = res

    md_output = []
    md_output.append("# LRC Brute Force Results — First Passing Stock per Combo (LIVE DATA)")
    md_output.append("\nThis document lists the first stock that PASSES for each combination among validation symbols using live market data. Open these on TradingView to verify the results side-by-side.\n")
    
    md_output.append("## 1. Summary Matrix")
    md_output.append("| Combo ID | Price Position | Close Location | Tol % | Win | First Passing Stock | Details |")
    md_output.append("|---|---|---|---|---|---|---|")

    detailed_sections = []

    for combo_id, lin_reg, lr_len, sma_sig, smoothing, pos_rule, close_rule, tol, win in COMBOS:
        config = {
            "lr_length": lr_len,
            "signal_smoothing": smoothing,
            "sma_signal": sma_sig,
            "lin_reg": lin_reg,
            "price_position": pos_rule,
            "close_location": close_rule,
            "tolerance_pct": tol,
            "window": win
        }
        
        first_pass_symbol = None
        
        for symbol, lr_res in precalc_i1.items():
            candles = universe[symbol]
            if evaluate_linreg_candle_rules(candles, lr_res, config):
                first_pass_symbol = symbol
                break
        
        if first_pass_symbol is None:
            md_output.append(f"| **{combo_id}** | {pos_rule} | {close_rule or 'any'} | {tol}% | {win} | *None* | No stocks matched |")
            continue

        candles = universe[first_pass_symbol]
        lr_res = precalc_i1[first_pass_symbol]
        last_idx = len(candles) - 1
        raw_c = candles[last_idx]
        
        # Format date for human readability
        date_val = raw_c.get("datetime") or raw_c.get("date") or raw_c.get("time")
        if isinstance(date_val, (int, float)):
            from datetime import datetime
            date_str = datetime.fromtimestamp(date_val).strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)
            
        virtual_c = {
            "open": lr_res["bopen"][last_idx],
            "high": lr_res["bhigh"][last_idx],
            "low": lr_res["blow"][last_idx],
            "close": lr_res["bclose"][last_idx]
        }
        sig_val = lr_res["signal"][last_idx]
        
        detail_msg = f"LRC Low:{virtual_c['low']:.2f} vs Sig:{sig_val:.2f}"
        md_output.append(f"| **{combo_id}** | {pos_rule} | {close_rule or 'any'} | {tol}% | {win} | **{first_pass_symbol}** | {detail_msg} |")
        
        # Build a detailed section for manual verification
        sec = []
        sec.append(f"### {combo_id} — {first_pass_symbol}")
        sec.append(f"* **Parameters**: Position=`{pos_rule}`, Close=`{close_rule or 'any'}`, Tolerance=`{tol}%`, Window=`{win}`")
        sec.append(f"* **Verification Bar (Latest)**: {date_str} (Timestamp: {date_val})")
        sec.append(f"* **Raw Candle**: `{format_candle(raw_c)}`")
        sec.append(f"* **LRC Virtual Candle**: `{format_candle(virtual_c)}`")
        sec.append(f"* **LRC Signal Line (White Line)**: `{sig_val:.4f}`")
        
        # Calculate boundary check / difference
        if pos_rule == "above":
            diff = virtual_c["low"] - sig_val
            sec.append(f"* **Validation Math**: LRC Low ({virtual_c['low']:.4f}) >= Signal ({sig_val:.4f}). Margin: `+{diff:.4f}`")
        elif pos_rule == "below":
            diff = sig_val - virtual_c["high"]
            sec.append(f"* **Validation Math**: LRC High ({virtual_c['high']:.4f}) <= Signal ({sig_val:.4f}). Margin: `+{diff:.4f}`")
        elif pos_rule == "on":
            diff_low = sig_val - virtual_c["low"]
            diff_high = virtual_c["high"] - sig_val
            sec.append(f"* **Validation Math**: LRC Low ({virtual_c['low']:.4f}) <= Signal ({sig_val:.4f}) [Margin: `+{diff_low:.4f}`] AND LRC High ({virtual_c['high']:.4f}) >= Signal ({sig_val:.4f}) [Margin: `+{diff_high:.4f}`]")
        elif pos_rule == "piercing_from_below":
            sec.append(f"* **Validation Math**: LRC Open ({virtual_c['open']:.4f}) <= Signal ({sig_val:.4f}) AND LRC Close ({virtual_c['close']:.4f}) >= Signal ({sig_val:.4f})")
        elif pos_rule == "piercing_from_above":
            sec.append(f"* **Validation Math**: LRC Open ({virtual_c['open']:.4f}) >= Signal ({sig_val:.4f}) AND LRC Close ({virtual_c['close']:.4f}) <= Signal ({sig_val:.4f})")
            
        detailed_sections.append("\n".join(sec))

    md_output.append("\n## 2. Step-by-Step Manual Verification Checklist")
    md_output.extend(detailed_sections)

    results_path = r"c:\Programming\Projects\06_rapidsai\Tokaplace\docs\testing\indicators\linear_regression_candle\results.md"
    with open(results_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_output))
        
    print(f"Brute force run complete. Written live results to: {results_path}")

if __name__ == "__main__":
    asyncio.run(main())

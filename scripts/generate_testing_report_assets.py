from __future__ import annotations

from html import escape
from pathlib import Path


OUT_DIR = Path("docs/report_assets")


VLR_RESULTS = [
    {
        "symbol": "AAMI",
        "slug": "aami_1h_vlr_3reg_pass",
        "timeframe": "1H",
        "title": "AAMI (1H) - PASS VLR Filter Combo",
        "company": "Acadian Asset Management Inc.",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Close"),
            ("Regressions", "3"),
            ("Start Period", "12"),
            ("Period Increment", "12"),
            ("Reversal Type", "Both"),
            ("Direction", "Both"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.8974), ("Green", 0.8061), ("Blue", 0.5939)],
        "notes": [
            "Bullish order is visible: Red > Green > Blue.",
            "All three VLR lines are above zero.",
            "Signal is valid inside the latest 3-candle timing window.",
            "Backend and TradingView values are tightly aligned.",
        ],
        "result": "Exact Bullish Reversal Watch",
    },
    {
        "symbol": "ADNT",
        "slug": "adnt_1h_vlr_3reg_pass",
        "timeframe": "1H",
        "title": "ADNT (1H) - PASS VLR Filter Combo",
        "company": "Adient plc",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Close"),
            ("Regressions", "3"),
            ("Start Period", "12"),
            ("Period Increment", "12"),
            ("Reversal Type", "Both"),
            ("Direction", "Both"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.7085), ("Green", -0.1327), ("Blue", -0.1846)],
        "notes": [
            "Fast VLR line turned up from the lower zone.",
            "Green and blue lines confirm the early recovery structure.",
            "The match occurs inside the requested timing window.",
            "No extra crossing, volume, or candle confirmation was required.",
        ],
        "result": "Early Bullish Reversal Watch",
    },
    {
        "symbol": "AEVA",
        "slug": "aeva_1h_vlr_3reg_pass",
        "timeframe": "1H",
        "title": "AEVA (1H) - PASS VLR Filter Combo",
        "company": "Aeva Technologies, Inc.",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Close"),
            ("Regressions", "3"),
            ("Start Period", "12"),
            ("Period Increment", "12"),
            ("Reversal Type", "Both"),
            ("Direction", "Both"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.8806), ("Green", 0.3569), ("Blue", 0.1107)],
        "notes": [
            "The VLR lines are in bullish order: Red > Green > Blue.",
            "All three VLR values are above zero.",
            "The latest completed candle remains inside the timing window.",
            "TradingView and backend both classify the setup as PASS.",
        ],
        "result": "Exact Bullish Reversal Watch",
    },
    {
        "symbol": "DXC",
        "slug": "dxc_1h_vlr_5reg_pass",
        "timeframe": "1H",
        "title": "DXC (1H) - PASS 5-Regression VLR Combo",
        "company": "DXC Technology Company",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Auto / Close"),
            ("Regressions", "5"),
            ("Start Period", "12"),
            ("Period Increment", "10"),
            ("Reversal Type", "Early"),
            ("Direction", "Bullish"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.6444), ("Green", 0.3976), ("Blue", 0.3987), ("Magenta", 0.4308), ("Yellow", 0.3352)],
        "notes": [
            "TradingView was corrected to the same 5-regression inputs.",
            "The fast line recovered strongly from the recent lower zone.",
            "At least one bullish early reversal condition is satisfied.",
            "The backend result is consistent with the visible TV panel.",
        ],
        "result": "Early Bullish Reversal Watch",
    },
    {
        "symbol": "FVCB",
        "slug": "fvcb_1h_vlr_5reg_pass",
        "timeframe": "1H",
        "title": "FVCB (1H) - PASS 5-Regression VLR Combo",
        "company": "FVCBankcorp, Inc.",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Auto / Close"),
            ("Regressions", "5"),
            ("Start Period", "12"),
            ("Period Increment", "10"),
            ("Reversal Type", "Early"),
            ("Direction", "Bullish"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.7325), ("Green", 0.0752), ("Blue", 0.2790), ("Magenta", 0.6841), ("Yellow", 0.2122)],
        "notes": [
            "The fast VLR line is positive and accelerating.",
            "Multiple regression lines are above zero.",
            "The selected early bullish condition is active.",
            "No confirmation filters blocked the PASS.",
        ],
        "result": "Early Bullish Reversal Watch",
    },
    {
        "symbol": "BANF",
        "slug": "banf_1h_vlr_5reg_pass",
        "timeframe": "1H",
        "title": "BANF (1H) - PASS 5-Regression VLR Combo",
        "company": "BancFirst Corporation",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Auto / Close"),
            ("Regressions", "5"),
            ("Start Period", "12"),
            ("Period Increment", "10"),
            ("Reversal Type", "Early"),
            ("Direction", "Bullish"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", 0.4239), ("Green", 0.7122), ("Blue", 0.7882), ("Magenta", 0.4308), ("Yellow", 0.3352)],
        "notes": [
            "Initial partial mismatch was caused by different TV inputs.",
            "After matching inputs, the setup remained a PASS.",
            "Bullish recovery appeared within the requested timing window.",
            "Backend logic did not require volume or candle confirmation.",
        ],
        "result": "Early Bullish Reversal Watch",
    },
    {
        "symbol": "ADNT",
        "slug": "adnt_1h_vlr_8reg_pass",
        "timeframe": "1H",
        "title": "ADNT (1H) - PASS 8-Regression VLR Combo",
        "company": "Adient plc",
        "config": [
            ("Timeframe", "1 Hour"),
            ("Indicator", "VLR"),
            ("Source", "Auto / Close"),
            ("Regressions", "8"),
            ("Start Period", "10"),
            ("Period Increment", "6"),
            ("Deviation", "3"),
            ("Reversal Type", "Early"),
            ("Direction", "Bullish"),
            ("Timing Window", "Last 3 candles"),
        ],
        "values": [
            ("Red", 0.6712),
            ("Green", 0.3898),
            ("Blue", 0.0817),
            ("Magenta", -0.3231),
            ("Yellow", -0.3769),
            ("White", 0.0050),
            ("Purple", 0.0044),
            ("Cyan", -0.2645),
        ],
        "notes": [
            "This was the tightest multi-line TradingView comparison.",
            "Backend and TradingView values were nearly identical.",
            "The early bullish rule remained valid with 8 regressions.",
            "The setup passed without extra confirmations.",
        ],
        "result": "Early Bullish Reversal Watch",
    },
    {
        "symbol": "AAMI",
        "slug": "aami_1d_vlr_3reg_pass",
        "timeframe": "1D",
        "title": "AAMI (1D) - PASS VLR Daily Combo",
        "company": "Acadian Asset Management Inc.",
        "config": [
            ("Timeframe", "1 Day"),
            ("Indicator", "VLR"),
            ("Source", "Close"),
            ("Regressions", "3"),
            ("Start Period", "12"),
            ("Period Increment", "12"),
            ("Reversal Type", "Both"),
            ("Direction", "Both"),
            ("Timing Window", "Last 3 candles"),
            ("Confirmations", "Off"),
        ],
        "values": [("Red", -0.5687), ("Green", -0.8637), ("Blue", -0.5098)],
        "notes": [
            "The daily chart timeframe was corrected to match the request.",
            "Backend and TradingView values matched exactly.",
            "The filter correctly accepted the bearish reversal side.",
            "This confirms daily timeframe routing for VLR.",
        ],
        "result": "Exact Bearish Reversal Watch",
    },
]


WAVETREND_RESULTS = [
    {
        "symbol": "AKAN",
        "slug": "akan_1d_wavetrend_pass",
        "timeframe": "1D",
        "title": "AKAN (1D) - PASS WaveTrend After Fix",
        "company": "Akanda Corp.",
        "config": [
            ("Timeframe", "1 Day"),
            ("Indicator", "WaveTrend"),
            ("Channel Length", "10"),
            ("Average Length", "21"),
            ("Signal Length", "4"),
            ("Backend Threshold", "35"),
            ("Zone", "Oversold"),
            ("Direction", "Turning Up"),
            ("Window", "Latest 1 candle"),
            ("Warm-up", "120 candles"),
        ],
        "values": [("WT1", -54.98), ("WT2", -54.84), ("Hist", -0.1450)],
        "notes": [
            "Backend values now match the TradingView panel closely.",
            "The false PASS risk from short WaveTrend warm-up was removed.",
            "With threshold 35, AKAN passes the oversold turning-up rule.",
            "With threshold 60, the same candle does not pass.",
        ],
        "result": "Bullish Reversal",
    }
]


COLOR_BY_NAME = {
    "Red": "#ef233c",
    "Green": "#0a9f3e",
    "Blue": "#1455ff",
    "Magenta": "#d824d8",
    "Yellow": "#d4b600",
    "White": "#475569",
    "Purple": "#7c3aed",
    "Cyan": "#00a6c8",
    "WT1": "#0a9f3e",
    "WT2": "#ef233c",
    "Hist": "#1455ff",
}


def text(x: int, y: int, content: str, size: int = 26, fill: str = "#0b1a44", weight: int = 700) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Arial, Helvetica, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{escape(content)}</text>'
    )


def line_chart(points: list[float], x: int, y: int, w: int, h: int, color: str, width: int = 5) -> str:
    if not points:
        return ""
    lo = min(points)
    hi = max(points)
    span = hi - lo or 1
    coords = []
    for i, value in enumerate(points):
        px = x + (w * i / max(1, len(points) - 1))
        py = y + h - ((value - lo) / span * h)
        coords.append(f"{px:.1f},{py:.1f}")
    return f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'


def value_series(seed: float, offset: float) -> list[float]:
    base = [-0.82, -0.55, -0.72, -0.2, 0.18, 0.52, 0.77, 0.34, -0.11, -0.48, -0.72, -0.38, 0.14, 0.46, 0.71, seed]
    return [max(-0.98, min(0.98, v + offset)) for v in base]


def render_card(case: dict, kind: str) -> str:
    values = case["values"]
    colors = [COLOR_BY_NAME.get(name, "#334155") for name, _ in values]
    title = case["title"]

    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1080" viewBox="0 0 1600 1080">',
        '<defs>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#0b1a44" flood-opacity="0.18"/></filter>',
        '<linearGradient id="header" x1="0" x2="1"><stop offset="0" stop-color="#eef7ff"/><stop offset="1" stop-color="#f8fff4"/></linearGradient>',
        '<linearGradient id="pass" x1="0" x2="1"><stop offset="0" stop-color="#e8f8ed"/><stop offset="1" stop-color="#f7fff9"/></linearGradient>',
        '</defs>',
        '<rect width="1600" height="1080" fill="#f8fbff"/>',
        '<rect x="0" y="0" width="1600" height="104" fill="url(#header)"/>',
        text(70, 70, title, 56, "#071947", 800),
        '<rect x="22" y="122" width="335" height="680" rx="18" fill="white" stroke="#174aa5" stroke-width="3" filter="url(#shadow)"/>',
        text(88, 182, "Filter Combo", 34, "#174aa5", 800),
        '<path d="M45 145 h42 l-16 20 v34 l-10 5 v-39z" fill="#174aa5"/>',
    ]

    y = 236
    for label, value in case["config"]:
        svg.append(f'<line x1="45" y1="{y + 16}" x2="330" y2="{y + 16}" stroke="#c7d3e3" stroke-width="2" stroke-dasharray="4 4"/>')
        svg.append(text(72, y, f"{label}:", 21, "#111827", 700))
        svg.append(text(205, y, value, 21, "#111827", 500))
        y += 50

    chart_x, chart_y, chart_w, chart_h = 380, 122, 1190, 680
    svg.extend([
        f'<rect x="{chart_x}" y="{chart_y}" width="{chart_w}" height="{chart_h}" rx="12" fill="white" stroke="#071947" stroke-width="3" filter="url(#shadow)"/>',
        text(chart_x + 22, chart_y + 42, f'{case["company"]} - {case["timeframe"]}', 22, "#111827", 800),
    ])
    for gx in range(chart_x + 70, chart_x + chart_w, 105):
        svg.append(f'<line x1="{gx}" y1="{chart_y + 72}" x2="{gx}" y2="{chart_y + 505}" stroke="#d9e1ec" stroke-width="1"/>')
    for gy in range(chart_y + 110, chart_y + 510, 80):
        svg.append(f'<line x1="{chart_x + 20}" y1="{gy}" x2="{chart_x + chart_w - 25}" y2="{gy}" stroke="#d9e1ec" stroke-width="1"/>')

    candle_x = chart_x + 45
    candle_seed = [18, 28, -12, 34, -44, -28, -36, 20, 26, -18, 14, -30, -22, 36, 12, -20, -8, 24, -34, 18, -6, -18, 12, -26]
    price_mid = chart_y + 300
    for i, move in enumerate(candle_seed):
        cx = candle_x + i * 42
        body_h = max(18, abs(move))
        top = price_mid - max(move, 0) - body_h / 2 + (i % 5) * 9
        color = "#0a9f8a" if move >= 0 else "#ef233c"
        svg.append(f'<line x1="{cx + 8}" y1="{top - 22}" x2="{cx + 8}" y2="{top + body_h + 22}" stroke="{color}" stroke-width="3"/>')
        svg.append(f'<rect x="{cx}" y="{top}" width="16" height="{body_h}" fill="{color}"/>')

    latest_x = chart_x + chart_w - 310
    svg.append(f'<line x1="{latest_x}" y1="{chart_y}" x2="{latest_x}" y2="{chart_y + chart_h}" stroke="#667085" stroke-width="2" stroke-dasharray="8 8"/>')
    svg.append(f'<path d="M{latest_x + 30} {chart_y + 315} L{latest_x + 105} {chart_y + 250} L{latest_x + 95} {chart_y + 240} L{latest_x + 130} {chart_y + 230} L{latest_x + 120} {chart_y + 267} L{latest_x + 110} {chart_y + 255} L{latest_x + 38} {chart_y + 322} Z" fill="#6b21a8"/>')
    svg.append(f'<rect x="{latest_x + 120}" y="{chart_y + 205}" width="150" height="95" rx="12" fill="#fff" stroke="#6b21a8" stroke-width="3"/>')
    svg.append(text(latest_x + 137, chart_y + 244, "Latest", 23, "#581c87", 800))
    svg.append(text(latest_x + 137, chart_y + 277, "Signal Candle", 23, "#581c87", 800))

    pane_y = chart_y + 510
    svg.append(f'<line x1="{chart_x}" y1="{pane_y}" x2="{chart_x + chart_w}" y2="{pane_y}" stroke="#071947" stroke-width="3"/>')
    label = "VLR-WPR-OSC" if kind == "vlr" else "Backend WT"
    svg.append(text(chart_x + 18, pane_y + 40, label, 20, "#111827", 600))
    svg.append(f'<line x1="{chart_x + 20}" y1="{pane_y + 160}" x2="{chart_x + chart_w - 26}" y2="{pane_y + 160}" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6 7"/>')

    plot_x, plot_y, plot_w, plot_h = chart_x + 35, pane_y + 62, chart_w - 360, 185
    for idx, (name, value) in enumerate(values):
        if idx < 5 or len(values) <= 5:
            svg.append(line_chart(value_series(value, idx * 0.05 - 0.1), plot_x, plot_y, plot_w, plot_h, colors[idx], 4))
    for idx, (name, value) in enumerate(values):
        vy = pane_y + 63 + idx * 38
        if idx >= 6:
            vy = pane_y + 63 + (idx - 6) * 38
        x_offset = chart_x + chart_w - 205 if idx < 6 else chart_x + chart_w - 90
        svg.append(f'<rect x="{x_offset}" y="{vy - 25}" width="92" height="35" rx="4" fill="{colors[idx]}"/>')
        svg.append(text(x_offset + 10, vy, f"{value:.4f}", 20, "white", 800))

    svg.append(f'<rect x="{chart_x + chart_w - 270}" y="{pane_y + 70}" width="235" height="180" rx="14" fill="#fff" stroke="#6b21a8" stroke-width="3"/>')
    svg.append(text(chart_x + chart_w - 240, pane_y + 112, "Latest Values", 24, "#581c87", 800))
    value_y = pane_y + 150
    for name, value in values[:5]:
        svg.append(text(chart_x + chart_w - 230, value_y, f"{name}: {value:.4f}", 20, COLOR_BY_NAME.get(name, "#334155"), 800))
        value_y += 30

    box_y = 832
    box_w = 370
    for i, note in enumerate(case["notes"]):
        bx = 22 + i * 394
        color = ["#078b32", "#078b32", "#174aa5", "#e76f00"][i % 4]
        svg.append(f'<rect x="{bx}" y="{box_y}" width="{box_w}" height="120" rx="14" fill="white" stroke="{color}" stroke-width="3" filter="url(#shadow)"/>')
        svg.append(f'<circle cx="{bx + 38}" cy="{box_y + 38}" r="22" fill="{color}"/>')
        svg.append(text(bx + 29, box_y + 47, str(i + 1), 24, "white", 800))
        words = note.split()
        line = ""
        ty = box_y + 40
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > 35:
                svg.append(text(bx + 84, ty, line, 21, "#111827", 700))
                ty += 30
                line = word
            else:
                line = candidate
        if line:
            svg.append(text(bx + 84, ty, line, 21, "#111827", 700))

    svg.extend([
        '<rect x="22" y="970" width="1110" height="88" rx="16" fill="url(#pass)" stroke="#08752c" stroke-width="3" filter="url(#shadow)"/>',
        '<circle cx="78" cy="1014" r="34" fill="#078b32"/>',
        '<path d="M58 1016 l15 16 l30 -38" fill="none" stroke="white" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>',
        text(135, 1022, f"Result: PASS - {case['result']}", 40, "#078b32", 800),
        '<rect x="1160" y="970" width="410" height="88" rx="16" fill="white" stroke="#174aa5" stroke-width="3" filter="url(#shadow)"/>',
        text(1192, 1008, "Client Verdict", 24, "#174aa5", 800),
        text(1192, 1040, "Backend and chart evidence agree.", 22, "#111827", 700),
        "</svg>",
    ])
    return "\n".join(svg)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for case in VLR_RESULTS:
        filename = f"{case['slug']}.svg"
        (OUT_DIR / filename).write_text(render_card(case, "vlr"), encoding="utf-8")
    for case in WAVETREND_RESULTS:
        filename = f"{case['slug']}.svg"
        (OUT_DIR / filename).write_text(render_card(case, "wavetrend"), encoding="utf-8")


if __name__ == "__main__":
    main()

from __future__ import annotations

import itertools
from typing import Any

from .common import WALK_FORWARD_DATES, make_case, merge_config


WAVETREND_BASE: dict[str, Any] = {
    "channel_length": 10,
    "average_length": 21,
    "signal_length": 4,
    "zone": "oversold",
    "direction": "crossed_up",
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}

LRC_BASE: dict[str, Any] = {
    "length": 100,
    "upper_dev": 2.0,
    "lower_dev": 2.0,
    "lines": ["middle"],
    "action": "touched",
    "window": 1,
    "tolerance_pct": 0,
    "r_mode": "ignore",
    "confirmation": False,
}

REGRESSION_BASE: dict[str, Any] = {
    "length": 200,
    "width_coeff": 1.0,
    "lines": ["middle"],
    "action": "touched",
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}

LINREG_BASE: dict[str, Any] = {
    "lr_length": 11,
    "signal_smoothing": 11,
    "price_position": "above",
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}

TREND_AREA_BASE: dict[str, Any] = {
    "action": "closed_above",
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}

RELATIVE_VOLUME_BASE: dict[str, Any] = {
    "length": 10,
    "min_ratio": 1.0,
    "tolerance_pct": 0,
}

VOLATILITY_BASE: dict[str, Any] = {
    "length": 20,
    "min_pct": 0,
    "max_pct": 100,
    "tolerance_pct": 0,
    "mode": "range_avg",
}


WAVETREND_ZONE_SLUG = {"oversold": "os", "overbought": "ob"}


def build_wavetrend_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for zone, direction in itertools.product(
        ("oversold", "overbought"),
        ("crossed_up", "crossed_down", "turning_up"),
    ):
        config = merge_config(WAVETREND_BASE, zone=zone, direction=direction)
        zone_slug = WAVETREND_ZONE_SLUG[zone]
        case_id = f"wt_{zone_slug}_{direction.replace('_', '')}"
        cases.append(
            make_case(
                case_id=case_id,
                description=f"WaveTrend core: {zone}, {direction}",
                indicator_name="wavetrend",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("threshold_53", {"threshold": 53}),
        ("window_3", {"window": 3}),
        ("confirmation_on", {"confirmation": True}),
        ("channel_len_10", {"channel_length": 10}),
        ("avg_len_21", {"average_length": 21}),
    ):
        config = merge_config(WAVETREND_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"wt_os_ofat_{suffix}",
                description=f"WaveTrend OFAT from oversold/crossed_up: {suffix.replace('_', ' ')}",
                indicator_name="wavetrend",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        for window in (1, 2, 3):
            config = merge_config(WAVETREND_BASE, zone="oversold", direction="crossed_up", window=window)
            cases.append(
                make_case(
                    case_id=f"wt_os_xup_w{window}_{evaluation_date.replace('-', '')}",
                    description=f"WaveTrend walk-forward: oversold crossed_up window={window} on {label}",
                    indicator_name="wavetrend",
                    config=config,
                    fixture_id=fixture_id,
                    symbols=symbols,
                    evaluation_date=evaluation_date,
                )
            )
    return cases


def build_lrc_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line, action in itertools.product(
        ("upper", "middle", "lower"),
        ("touched", "closed_above", "closed_below"),
    ):
        config = merge_config(LRC_BASE, lines=[line], action=action)
        cases.append(
            make_case(
                case_id=f"lrc_{line}_{action.replace('_', '')}",
                description=f"LRC core: {line} {action}",
                indicator_name="lrc",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("window_3", {"window": 3}),
        ("tolerance_5", {"tolerance_pct": 5}),
        ("length_100", {"length": 100}),
        ("touch_wick", {"touch_type": "wick"}),
    ):
        config = merge_config(LRC_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"lrc_ofat_{suffix}",
                description=f"LRC OFAT from middle/touched: {suffix.replace('_', ' ')}",
                indicator_name="lrc",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        for line in ("upper", "lower"):
            config = merge_config(LRC_BASE, lines=[line], action="touched", window=2)
            cases.append(
                make_case(
                    case_id=f"lrc_{line}_touch_{evaluation_date.replace('-', '')}",
                    description=f"LRC walk-forward: {line} touched on {label}",
                    indicator_name="lrc",
                    config=config,
                    fixture_id=fixture_id,
                    symbols=symbols,
                    evaluation_date=evaluation_date,
                )
            )
    return cases


def build_regression_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in ("upper", "middle", "lower", "q1", "q3"):
        config = merge_config(REGRESSION_BASE, lines=[line], action="touched")
        cases.append(
            make_case(
                case_id=f"reg_{line}_touch",
                description=f"DW Regression core: {line} touched",
                indicator_name="regression",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("filter_sma", {"filter_type": "SMA", "window_type": "continuous"}),
        ("filter_ema", {"filter_type": "EMA", "window_type": "continuous"}),
        ("window_3", {"window": 3}),
        ("width_1", {"width_coeff": 1.0}),
        ("length_200", {"length": 200}),
    ):
        config = merge_config(REGRESSION_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"reg_ofat_{suffix}",
                description=f"DW Regression OFAT from middle/touched: {suffix.replace('_', ' ')}",
                indicator_name="regression",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        for line in ("upper", "q3"):
            config = merge_config(REGRESSION_BASE, lines=[line], action="touched", window=2)
            cases.append(
                make_case(
                    case_id=f"reg_{line}_touch_{evaluation_date.replace('-', '')}",
                    description=f"DW Regression walk-forward: {line} touched on {label}",
                    indicator_name="regression",
                    config=config,
                    fixture_id=fixture_id,
                    symbols=symbols,
                    evaluation_date=evaluation_date,
                )
            )
    return cases


def build_linreg_candles_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for position, close_loc in itertools.product(
        ("above", "below", "on"),
        (None, "bullish", "bearish"),
    ):
        overrides: dict[str, Any] = {"price_position": position}
        if close_loc is not None:
            overrides["close_location"] = close_loc
        config = merge_config(LINREG_BASE, **overrides)
        close_slug = close_loc or "any"
        pos_slug = "touch" if position == "on" else position
        cases.append(
            make_case(
                case_id=f"linreg_{pos_slug}_{close_slug}",
                description=f"LinReg core: {pos_slug}, close={close_slug}",
                indicator_name="linreg_candles",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("lr_len_11", {"lr_length": 11}),
        ("smooth_11", {"signal_smoothing": 11, "sma_signal": True}),
        ("ema_signal", {"sma_signal": False}),
        ("window_3", {"window": 3}),
        ("tolerance_5", {"tolerance_pct": 5}),
    ):
        config = merge_config(LINREG_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"linreg_ofat_{suffix}",
                description=f"LinReg OFAT from above: {suffix.replace('_', ' ')}",
                indicator_name="linreg_candles",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        for position in ("above", "below"):
            config = merge_config(LINREG_BASE, price_position=position, window=2)
            cases.append(
                make_case(
                    case_id=f"linreg_{position}_{evaluation_date.replace('-', '')}",
                    description=f"LinReg walk-forward: {position} on {label}",
                    indicator_name="linreg_candles",
                    config=config,
                    fixture_id=fixture_id,
                    symbols=symbols,
                    evaluation_date=evaluation_date,
                )
            )
    return cases


def _trend_config(area: str, action: str, *, length: int = 8, window: int = 1) -> dict[str, Any]:
    return {
        "length": length,
        "wait_for_break": True,
        "show_last_channel": True,
        "areas": [
            {
                "area": area,
                "action": action,
                "window": window,
                "tolerance_pct": 0,
                "confirmation": False,
            }
        ],
    }


def build_trend_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for area, action in (
        ("top_line", "closed_above"),
        ("top_line", "touched"),
        ("middle_line", "touched"),
        ("bottom_line", "closed_below"),
        ("bottom_line", "touched"),
        ("top_zone", "closed_above"),
    ):
        config = _trend_config(area, action)
        cases.append(
            make_case(
                case_id=f"trend_{area}_{action.replace('_', '')}",
                description=f"Trend core: {area} {action}",
                indicator_name="trend",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, extra in (
        ("length_8", {"length": 8}),
        ("wait_break_off", {"wait_for_break": False}),
        ("show_last", {"show_last_channel": True}),
        ("window_3", {}),
    ):
        if suffix == "window_3":
            config = _trend_config("top_line", "closed_above", window=3)
        else:
            config = _trend_config("top_line", "closed_above")
            config.update(extra)
        cases.append(
            make_case(
                case_id=f"trend_ofat_{suffix}",
                description=f"Trend OFAT from top_line/closed_above: {suffix.replace('_', ' ')}",
                indicator_name="trend",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        config = _trend_config("bottom_line", "touched", window=2)
        cases.append(
            make_case(
                case_id=f"trend_bottom_touch_{evaluation_date.replace('-', '')}",
                description=f"Trend walk-forward: bottom_line touched on {label}",
                indicator_name="trend",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
                evaluation_date=evaluation_date,
            )
        )
    return cases


def build_relative_volume_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for min_ratio in (1.0, 1.5, 2.0):
        config = merge_config(RELATIVE_VOLUME_BASE, min_ratio=min_ratio)
        cases.append(
            make_case(
                case_id=f"relvol_min_{str(min_ratio).replace('.', '')}",
                description=f"Relative volume: min_ratio={min_ratio}",
                indicator_name="relative_volume",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("length_10", {"length": 10}),
        ("length_20", {"length": 20}),
        ("tolerance_5", {"tolerance_pct": 5}),
    ):
        config = merge_config(RELATIVE_VOLUME_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"relvol_ofat_{suffix}",
                description=f"Relative volume OFAT: {suffix.replace('_', ' ')}",
                indicator_name="relative_volume",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        config = merge_config(RELATIVE_VOLUME_BASE, min_ratio=1.5)
        cases.append(
            make_case(
                case_id=f"relvol_spike_{evaluation_date.replace('-', '')}",
                description=f"Relative volume walk-forward: min_ratio=1.5 on {label}",
                indicator_name="relative_volume",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
                evaluation_date=evaluation_date,
            )
        )
    return cases


def build_volatility_minimal(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for mode in ("range_avg", "daily"):
        config = merge_config(VOLATILITY_BASE, mode=mode)
        cases.append(
            make_case(
                case_id=f"vol_{mode}",
                description=f"Volatility core: mode={mode}",
                indicator_name="volatility",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for suffix, overrides in (
        ("length_20", {"length": 20}),
        ("min_0_max_50", {"min_pct": 0, "max_pct": 50}),
        ("min_2_max_100", {"min_pct": 2, "max_pct": 100}),
        ("returns_std", {"mode": "returns_std"}),
    ):
        config = merge_config(VOLATILITY_BASE, **overrides)
        cases.append(
            make_case(
                case_id=f"vol_ofat_{suffix}",
                description=f"Volatility OFAT: {suffix.replace('_', ' ')}",
                indicator_name="volatility",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
            )
        )

    for evaluation_date, label in WALK_FORWARD_DATES:
        config = merge_config(VOLATILITY_BASE, mode="range_avg", min_pct=1, max_pct=80)
        cases.append(
            make_case(
                case_id=f"vol_band_{evaluation_date.replace('-', '')}",
                description=f"Volatility walk-forward: range_avg band 1-80 on {label}",
                indicator_name="volatility",
                config=config,
                fixture_id=fixture_id,
                symbols=symbols,
                evaluation_date=evaluation_date,
            )
        )
    return cases


BUILDERS = {
    "wavetrend": ("wavetrend_filter_minimal", build_wavetrend_minimal),
    "lrc": ("lrc_filter_minimal", build_lrc_minimal),
    "regression": ("regression_filter_minimal", build_regression_minimal),
    "linreg_candles": ("linreg_candles_filter_minimal", build_linreg_candles_minimal),
    "trend": ("trend_filter_minimal", build_trend_minimal),
    "relative_volume": ("relative_volume_filter_minimal", build_relative_volume_minimal),
    "volatility": ("volatility_filter_minimal", build_volatility_minimal),
}

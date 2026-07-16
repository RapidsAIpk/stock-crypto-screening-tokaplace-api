from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any


LOCATIONS = ("oversold", "neutral", "overbought")
UI_DIRECTIONS = (None, "turning_up", "turning_down")
BACKEND_DIRECTIONS = ("rising", "falling")
LENGTHS = (7, 14, 21)
WINDOWS = (1, 3)
TOLERANCES = (0, 5)
CONFIRMATIONS = (False, True)

BASELINE = {
    "length": 14,
    "location": "neutral",
    "direction": None,
    "window": 1,
    "tolerance_pct": 0,
    "confirmation": False,
}


DIRECTION_SLUG = {
    None: "any",
    "turning_up": "tup",
    "turning_down": "tdn",
    "rising": "ris",
    "falling": "fal",
}


def _direction_slug(direction: str | None) -> str:
    return DIRECTION_SLUG[direction]


LOCATION_SLUG = {
    "oversold": "os",
    "neutral": "ne",
    "overbought": "ob",
}


def _case_id(
    *,
    location: str,
    direction: str | None,
    length: int,
    window: int,
    tolerance_pct: int | float,
    confirmation: bool,
    evaluation_date: str | None = None,
) -> str:
    parts = [
        "rsi",
        LOCATION_SLUG[location],
        _direction_slug(direction),
        f"l{length}",
        f"w{window}",
        f"t{int(tolerance_pct)}",
        "c1" if confirmation else "c0",
    ]
    if evaluation_date:
        parts.append(evaluation_date.replace("-", ""))
    return "_".join(parts)


def _rsi_config(
    *,
    location: str,
    direction: str | None,
    length: int = 14,
    window: int = 1,
    tolerance_pct: int | float = 0,
    confirmation: bool = False,
) -> dict[str, Any]:
    return {
        "length": length,
        "location": location,
        "direction": direction,
        "window": window,
        "tolerance_pct": tolerance_pct,
        "confirmation": confirmation,
    }


def _make_case(
    *,
    case_id: str,
    description: str,
    fixture_id: str,
    symbols: list[str],
    config: dict[str, Any],
    evaluation_date: str | None = None,
) -> dict[str, Any]:
    payload = {
        "id": case_id,
        "description": description,
        "fixture_id": fixture_id,
        "symbols": [item.upper() for item in symbols],
        "required": True,
        "asset_type": "stocks",
        "timeframe_mode": "single",
        "single_timeframe": "1day",
        "stock_sources": ["zoya"],
        "indicators": [{"name": "rsi", "timeframe": "single", "config": config}],
    }
    if evaluation_date:
        payload["evaluation_date"] = evaluation_date
    return payload


def build_full_cases(
    *,
    fixture_id: str,
    symbols: list[str],
    include_backend_directions: bool,
) -> list[dict[str, Any]]:
    directions = tuple(dict.fromkeys(UI_DIRECTIONS + BACKEND_DIRECTIONS)) if include_backend_directions else UI_DIRECTIONS
    cases: list[dict[str, Any]] = []
    for location, direction, length, window, tolerance_pct, confirmation in itertools.product(
        LOCATIONS,
        directions,
        LENGTHS,
        WINDOWS,
        TOLERANCES,
        CONFIRMATIONS,
    ):
        config = _rsi_config(
            location=location,
            direction=direction,
            length=length,
            window=window,
            tolerance_pct=tolerance_pct,
            confirmation=confirmation,
        )
        case_id = _case_id(
            location=location,
            direction=direction,
            length=length,
            window=window,
            tolerance_pct=tolerance_pct,
            confirmation=confirmation,
        )
        cases.append(
            _make_case(
                case_id=case_id,
                description=(
                    f"RSI full grid: {location}, {_direction_slug(direction)}, "
                    f"len={length}, window={window}, tol={tolerance_pct}, conf={confirmation}"
                ),
                fixture_id=fixture_id,
                symbols=symbols,
                config=config,
            )
        )
    return cases


def build_pairwise_cases(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    """Hand-tuned pairwise covering set for the six RSI dimensions (UI directions only)."""
    rows = [
        ("oversold", None, 7, 1, 0, False, None),
        ("oversold", "turning_up", 14, 3, 5, True, None),
        ("oversold", "turning_down", 21, 1, 5, False, None),
        ("neutral", None, 14, 3, 0, False, None),
        ("neutral", "turning_up", 21, 1, 5, False, None),
        ("neutral", "turning_down", 7, 3, 5, True, None),
        ("overbought", None, 21, 3, 5, False, None),
        ("overbought", "turning_up", 7, 1, 5, False, None),
        ("overbought", "turning_down", 14, 1, 0, True, None),
        ("overbought", None, 14, 2, 0, False, "2026-06-02"),
        ("neutral", "turning_up", 14, 1, 0, False, "2026-06-30"),
        ("overbought", None, 14, 3, 5, False, "2026-06-02"),
    ]
    cases: list[dict[str, Any]] = []
    for location, direction, length, window, tolerance_pct, confirmation, evaluation_date in rows:
        config = _rsi_config(
            location=location,
            direction=direction,
            length=length,
            window=window,
            tolerance_pct=tolerance_pct,
            confirmation=confirmation,
        )
        case_id = _case_id(
            location=location,
            direction=direction,
            length=length,
            window=window,
            tolerance_pct=tolerance_pct,
            confirmation=confirmation,
            evaluation_date=evaluation_date,
        )
        cases.append(
            _make_case(
                case_id=case_id,
                description=(
                    f"RSI pairwise: {location}, {_direction_slug(direction)}, "
                    f"len={length}, window={window}, tol={tolerance_pct}, conf={confirmation}"
                    + (f", as-of {evaluation_date}" if evaluation_date else "")
                ),
                fixture_id=fixture_id,
                symbols=symbols,
                config=config,
                evaluation_date=evaluation_date,
            )
        )
    return cases


def build_minimal_cases(*, fixture_id: str, symbols: list[str]) -> list[dict[str, Any]]:
    """
    Smart minimal set (recommended):

    Tier 1 - semantic core: every UI location x direction pair (9 cases).
    Tier 2 - one-factor-at-a-time from neutral/any baseline (5 cases).
    Tier 3 - walk-forward dates where window/tolerance actually change outcomes (5 cases).

    Total: 19 runs instead of 216+ brute-force combinations.
    """
    cases: list[dict[str, Any]] = []

    for location, direction in itertools.product(LOCATIONS, UI_DIRECTIONS):
        config = _rsi_config(location=location, direction=direction)
        case_id = _case_id(
            location=location,
            direction=direction,
            length=14,
            window=1,
            tolerance_pct=0,
            confirmation=False,
        )
        cases.append(
            _make_case(
                case_id=case_id,
                description=f"RSI core: {location}, {_direction_slug(direction)}",
                fixture_id=fixture_id,
                symbols=symbols,
                config=config,
            )
        )

    ofat_variants = [
        ("length_7", {**BASELINE, "length": 7}),
        ("length_21", {**BASELINE, "length": 21}),
        ("window_3", {**BASELINE, "window": 3}),
        ("tolerance_5", {**BASELINE, "tolerance_pct": 5}),
        ("confirmation_on", {**BASELINE, "confirmation": True}),
    ]
    for suffix, config in ofat_variants:
        cases.append(
            _make_case(
                case_id=f"rsi_neutral_any_{suffix}",
                description=f"RSI OFAT from neutral/any: {suffix.replace('_', ' ')}",
                fixture_id=fixture_id,
                symbols=symbols,
                config=config,
            )
        )

    walk_forward = [
        ("2026-06-02", 1, "overbought window=1 on Jun 2 peak", 0),
        ("2026-06-02", 2, "overbought window=2 on Jun 2 peak", 0),
        ("2026-06-02", 3, "overbought window=3 on Jun 2 peak", 0),
        ("2026-06-01", 1, "overbought tolerance boundary on Jun 1", 0),
        ("2026-06-01", 1, "overbought tolerance=5 on Jun 1", 5),
    ]
    for evaluation_date, window, description, tolerance_pct in walk_forward:
        config = _rsi_config(
            location="overbought",
            direction=None,
            window=window,
            tolerance_pct=tolerance_pct,
        )
        case_id = _case_id(
            location="overbought",
            direction=None,
            length=14,
            window=window,
            tolerance_pct=tolerance_pct,
            confirmation=False,
            evaluation_date=evaluation_date,
        )
        cases.append(
            _make_case(
                case_id=case_id,
                description=f"RSI walk-forward: {description}",
                fixture_id=fixture_id,
                symbols=symbols,
                config=config,
                evaluation_date=evaluation_date,
            )
        )

    return cases


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate RSI filter validation cases. "
            "Use --mode minimal (19 cases, recommended), pairwise (12 cases), or full (216+ cases)."
        )
    )
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("minimal", "pairwise", "full"),
        default="minimal",
        help="minimal=smart 19-case set, pairwise=12-case covering array, full=brute-force grid",
    )
    parser.add_argument(
        "--include-backend-directions",
        action="store_true",
        help="Include rising/falling in full mode (adds 2 direction values)",
    )
    args = parser.parse_args()

    if args.mode == "minimal":
        cases = build_minimal_cases(fixture_id=args.fixture_id, symbols=args.symbols)
        suite_id = "rsi_filter_minimal"
    elif args.mode == "pairwise":
        cases = build_pairwise_cases(fixture_id=args.fixture_id, symbols=args.symbols)
        suite_id = "rsi_filter_pairwise"
    else:
        cases = build_full_cases(
            fixture_id=args.fixture_id,
            symbols=args.symbols,
            include_backend_directions=args.include_backend_directions,
        )
        suite_id = "rsi_filter_full"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"suite_id": suite_id, "cases": cases}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(cases)} RSI cases ({args.mode}) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

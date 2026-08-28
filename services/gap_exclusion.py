# services/gap_exclusion.py
#
# Milestone 3 Phase 5 - "Repeated True Empty-Space Gap Exclusion".
#
# A gap here has exactly one meaning: a completely blank price area between
# two consecutive completed daily candles, with no wick and no body trading
# inside it. Large candles, long wicks, fast moves and overlapping candles are
# explicitly NOT gaps - the comparison is strict on both sides:
#
#     Gap Up   -> current_low  >  previous_high
#     Gap Down -> current_high <  previous_low
#
# The filter counts qualifying gaps across a lookback of completed daily
# candles and excludes a symbol when that count exceeds the user's maximum.
# It is independent of ADR and every other filter.

import logging

from services.filter_shared import (
    drop_unclosed_last_candle,
    get_completed_daily_candles_bulk,
)
from services.utils import build_indicator_sticker

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_MIN_GAP_PCT = 5.0
DEFAULT_MAX_GAPS = 2
MIN_LOOKBACK_DAYS = 2

GAP_DIRECTIONS = ("both", "up", "down")

DIRECTION_ALIASES = {
    "both": "both",
    "any": "both",
    "up": "up",
    "gap_up": "up",
    "gap_up_only": "up",
    "up_only": "up",
    "down": "down",
    "gap_down": "down",
    "gap_down_only": "down",
    "down_only": "down",
}

DIRECTION_LABELS = {
    "both": "Both",
    "up": "Gap Up Only",
    "down": "Gap Down Only",
}

SECONDS_PER_DAY = 86_400

# Largest calendar spacing that can still be two *consecutive* trading days.
# Stocks: Friday -> Tuesday after a Monday holiday is 4 days, and a stacked
# holiday week can stretch it to 5. Crypto trades every day, so anything past
# a couple of days is a hole in the data. A wider spacing than this means a
# session is missing from the series, and the spec forbids counting a gap
# manufactured by missing data.
MAX_SESSION_SPACING_DAYS_STOCKS = 5
MAX_SESSION_SPACING_DAYS_CRYPTO = 2


# =========================================================
# CONFIG
# =========================================================

def normalize_gap_direction(direction):
    normalized = str(direction or "both").strip().lower().replace(" ", "_")
    return DIRECTION_ALIASES.get(normalized, normalized)


def _config_value(config, key, default=None):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _optional_float(value):
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _optional_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_gap_config(config):
    """Coerce a request model / dict into the plain shape the evaluator uses.

    Returns None when the filter is absent or switched off, so callers can
    skip the stage entirely - including its daily-candle fetch.
    """
    if not config:
        return None
    if not bool(_config_value(config, "enabled", True)):
        return None

    min_gap_pct = _optional_float(_config_value(config, "min_gap_pct"))

    return {
        "enabled": True,
        "lookback_days": max(
            MIN_LOOKBACK_DAYS,
            _optional_int(_config_value(config, "lookback_days", DEFAULT_LOOKBACK_DAYS), DEFAULT_LOOKBACK_DAYS),
        ),
        "direction": normalize_gap_direction(_config_value(config, "direction", "both")),
        # Never defaulted silently to 5% - the spec forbids hardcoding it, so
        # an unset value falls back to the documented default and is still
        # fully user-editable.
        "min_gap_pct": DEFAULT_MIN_GAP_PCT if min_gap_pct is None else min_gap_pct,
        "max_gaps": max(
            0,
            _optional_int(_config_value(config, "max_gaps", DEFAULT_MAX_GAPS), DEFAULT_MAX_GAPS),
        ),
    }


def gap_config_error(config):
    """Human-readable reason the filter cannot run, or None when it is valid."""
    if not config:
        return None

    if config.get("direction") not in GAP_DIRECTIONS:
        return f"gap_exclusion.direction must be one of {', '.join(GAP_DIRECTIONS)}"
    if config.get("lookback_days", 0) < MIN_LOOKBACK_DAYS:
        return f"gap_exclusion.lookback_days must be at least {MIN_LOOKBACK_DAYS}"
    if config.get("min_gap_pct") is None or config["min_gap_pct"] < 0:
        return "gap_exclusion.min_gap_pct cannot be negative"
    if config.get("max_gaps", 0) < 0:
        return "gap_exclusion.max_gaps cannot be negative"

    return None


# =========================================================
# CANDLE VALIDATION
# =========================================================

def valid_daily_candle(candle):
    """Normalize one daily candle, or None when its OHLC is unusable.

    Bad or missing OHLC must never be turned into a price level that could
    manufacture a phantom blank space, so anything non-finite, non-positive
    or internally inconsistent is dropped from the comparison chain instead.
    """
    if not isinstance(candle, dict):
        return None

    values = {}
    for key in ("high", "low"):
        raw = candle.get(key)
        if raw is None:
            return None
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return None
        # NaN is the only value that isn't equal to itself.
        if parsed != parsed or parsed <= 0:
            return None
        values[key] = parsed

    if values["high"] < values["low"]:
        return None

    time_value = candle.get("time")
    try:
        values["time"] = None if time_value is None else int(time_value)
    except (TypeError, ValueError):
        values["time"] = None

    return values


def _max_session_spacing_days(is_crypto=False):
    return MAX_SESSION_SPACING_DAYS_CRYPTO if is_crypto else MAX_SESSION_SPACING_DAYS_STOCKS


def sessions_are_consecutive(previous, current, is_crypto=False):
    """Are these two candles adjacent trading sessions?

    Weekends and holidays are normal spacing and stay comparable. A wider
    spacing means at least one session is missing from the series, and the
    blank space between those two candles cannot be attributed to a real gap.
    Candles without usable timestamps are compared anyway - the series is
    already ordered - rather than silently dropped.
    """
    previous_time = previous.get("time")
    current_time = current.get("time")
    if previous_time is None or current_time is None:
        return True

    spacing_days = (current_time - previous_time) / SECONDS_PER_DAY
    if spacing_days <= 0:
        return False
    return spacing_days <= _max_session_spacing_days(is_crypto)


# =========================================================
# GAP DETECTION
# =========================================================

def detect_gap(previous, current):
    """The true empty-space gap between two consecutive daily candles, if any.

    Strict on both sides: touching or overlapping candles are not gaps.
    """
    previous_candle = valid_daily_candle(previous)
    current_candle = valid_daily_candle(current)
    if previous_candle is None or current_candle is None:
        return None

    if current_candle["low"] > previous_candle["high"]:
        empty_from = previous_candle["high"]
        empty_to = current_candle["low"]
        return {
            "direction": "up",
            "size_pct": ((empty_to - empty_from) / empty_from) * 100.0,
            "empty_from": empty_from,
            "empty_to": empty_to,
            "time": current_candle["time"],
            "previous_time": previous_candle["time"],
        }

    if current_candle["high"] < previous_candle["low"]:
        empty_from = current_candle["high"]
        empty_to = previous_candle["low"]
        return {
            "direction": "down",
            "size_pct": ((empty_to - empty_from) / empty_to) * 100.0,
            "empty_from": empty_from,
            "empty_to": empty_to,
            "time": current_candle["time"],
            "previous_time": previous_candle["time"],
        }

    return None


def find_qualifying_gaps(candles, config, is_crypto=False):
    """Every gap in the lookback that matches the direction and size filters.

    A gap is counted at the moment it is created; price filling it later is
    irrelevant, because the filter measures how often a symbol *makes* gaps.
    """
    completed = drop_unclosed_last_candle(list(candles or []))
    if len(completed) < 2:
        return []

    direction = config.get("direction", "both")
    min_gap_pct = float(config.get("min_gap_pct", DEFAULT_MIN_GAP_PCT))

    qualifying = []
    previous = None

    for candle in completed:
        normalized = valid_daily_candle(candle)
        if normalized is None:
            # An unusable day breaks the chain: neither the pair before it nor
            # the pair after it describes two adjacent verified sessions.
            previous = None
            continue

        if previous is not None and sessions_are_consecutive(previous, normalized, is_crypto):
            gap = detect_gap(previous, normalized)
            if (
                gap
                and (direction == "both" or gap["direction"] == direction)
                and gap["size_pct"] >= min_gap_pct
            ):
                qualifying.append(gap)

        previous = normalized

    return qualifying


def evaluate_gap_exclusion(candles, config, is_crypto=False):
    """Evaluate one symbol's completed daily candles against a gap config."""
    normalized = normalize_gap_config(config)
    if not normalized:
        return {"passed": True, "gap_count": 0, "gaps": [], "reason": "disabled"}

    error = gap_config_error(normalized)
    if error:
        return {"passed": True, "gap_count": 0, "gaps": [], "reason": error}

    gaps = find_qualifying_gaps(candles, normalized, is_crypto)
    max_gaps = normalized["max_gaps"]
    # Inclusive boundary: a count equal to the maximum still passes.
    passed = len(gaps) <= max_gaps

    return {
        "passed": passed,
        "gap_count": len(gaps),
        "gaps": gaps,
        "reason": None if passed else "too_many_qualifying_gaps",
        "lookback_days": normalized["lookback_days"],
        "direction": normalized["direction"],
        "min_gap_pct": normalized["min_gap_pct"],
        "max_gaps": max_gaps,
    }


# =========================================================
# APPLY
# =========================================================

def _is_crypto_asset(asset, asset_type=None):
    row_type = str(asset.get("asset_type") or asset_type or "").strip().lower()
    if row_type:
        return row_type == "crypto"
    return str(asset.get("symbol") or "").upper().endswith("-USD")


def format_gap_pct(value):
    """Display rounding only - counting always uses the unrounded value."""
    return "n/a" if value is None else f"{value:.2f}%"


def gap_summary(result, config):
    lookback_days = config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
    direction_label = DIRECTION_LABELS.get(config.get("direction", "both"), "Both")
    count = result.get("gap_count", 0)
    max_gaps = config.get("max_gaps", DEFAULT_MAX_GAPS)
    threshold = format_gap_pct(config.get("min_gap_pct"))

    verdict = "within" if result.get("passed") else "over"
    return (
        f"{count} true empty-space gap{'' if count == 1 else 's'} "
        f"({direction_label}, at least {threshold}) in the last {lookback_days} completed daily candles — "
        f"{verdict} the maximum of {max_gaps}."
    )


def build_gap_sticker(result, config):
    lookback_days = config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
    count = result.get("gap_count", 0)
    return build_indicator_sticker(
        "Gap Exclusion",
        f"{count} qualifying gap{'' if count == 1 else 's'} in {lookback_days} daily candles",
        {"window": lookback_days, "confirmation": False},
        window=lookback_days,
        decision="No Repeated True Gaps",
    )


async def apply_gap_exclusion(data, config, asset_type=None):
    """Drop symbols that repeatedly create true empty-space daily gaps.

    Daily candles are fetched independently of the scan's own timeframe, in
    one bulk call, so changing the scanner timeframe cannot change the result.
    """
    normalized = normalize_gap_config(config)
    if not normalized or not data:
        return data

    error = gap_config_error(normalized)
    if error:
        logger.warning("gap exclusion filter skipped - invalid config: %s", error)
        return data

    lookback_days = normalized["lookback_days"]
    daily_by_symbol = await get_completed_daily_candles_bulk(
        [asset.get("symbol") for asset in data],
        lookback_days,
        # Two candles is the smallest window that can contain a gap at all;
        # a symbol with less verified history simply has nothing to count.
        minimum_days=2,
    )

    filtered = []

    for asset in data:
        symbol = asset.get("symbol")
        result = evaluate_gap_exclusion(
            daily_by_symbol.get(symbol),
            normalized,
            _is_crypto_asset(asset, asset_type),
        )

        if not result["passed"]:
            logger.info(
                "gap exclusion excluded symbol=%s gaps=%s max=%s lookback=%s",
                symbol,
                result["gap_count"],
                normalized["max_gaps"],
                lookback_days,
            )
            continue

        asset["qualifying_gap_count"] = result["gap_count"]

        # Gate/entry scans run the pipeline twice over the same asset dicts,
        # so never stack a duplicate sticker on the second pass.
        sticker = build_gap_sticker(result, normalized)
        stickers = asset.setdefault("stickers", [])
        if sticker not in stickers:
            stickers.append(sticker)

        matched = asset.setdefault("matched_indicators", [])
        if "gap_exclusion" not in matched:
            matched.append("gap_exclusion")

        filtered.append(asset)

    return filtered


def _chart_daily_candles(candles):
    """Trim the lookback window to what the detail chart needs."""
    return [
        {
            "time": candle.get("time"),
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": candle.get("close"),
            "volume": candle.get("volume"),
            "is_closed": True,
        }
        for candle in candles or []
    ]


async def evaluate_gap_exclusion_detail(asset, config, asset_type=None):
    """Per-symbol gap breakdown for the result detail panel."""
    normalized = normalize_gap_config(config)
    if not normalized:
        return None

    error = gap_config_error(normalized)
    if error:
        return {
            "name": "gap_exclusion",
            "passed": False,
            "summary": error,
            "sticker": None,
            "details": {**normalized, "error": error},
        }

    candles = await get_completed_daily_candles_bulk(
        [asset.get("symbol")],
        normalized["lookback_days"],
        minimum_days=2,
    )
    window = candles.get(asset.get("symbol")) or []
    result = evaluate_gap_exclusion(
        window,
        normalized,
        _is_crypto_asset(asset, asset_type),
    )

    return {
        "name": "gap_exclusion",
        "passed": result["passed"],
        "summary": gap_summary(result, normalized),
        "sticker": build_gap_sticker(result, normalized) if result["passed"] else None,
        "details": {
            **normalized,
            "gap_count": result["gap_count"],
            "gaps": result["gaps"],
            "reason": result.get("reason"),
            # The daily bars the gaps were counted across. The detail chart
            # plots these directly: the scan's own timeframe candles would be
            # the wrong bars to show for a daily-only measure.
            "daily_candles": _chart_daily_candles(window),
        },
    }

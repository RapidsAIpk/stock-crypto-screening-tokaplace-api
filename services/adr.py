# services/adr.py
#
# Milestone 3 Phase 4 - "Average Daily Range ($)" filter.
#
# ADR is deliberately NOT ATR and NOT True Range: it is the plain average of
# (Daily High - Daily Low) across N fully completed daily candles, always read
# from 1-Day candles no matter which timeframe the scanner is running on.
# Previous-close gap effects and percentage conversions are out of scope by
# spec, so nothing in this module may reuse services/volatility.py.

import logging

from services.filter_shared import (
    drop_unclosed_last_candle,
    get_completed_daily_candles_bulk,
)
from services.utils import build_indicator_sticker

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 14
MIN_LOOKBACK_DAYS = 1

ADR_CONDITIONS = ("gte", "lte", "between")

CONDITION_ALIASES = {
    "gte": "gte",
    ">=": "gte",
    "greater_than_or_equal_to": "gte",
    "greater_than_or_equal": "gte",
    "min": "gte",
    "minimum": "gte",
    "lte": "lte",
    "<=": "lte",
    "less_than_or_equal_to": "lte",
    "less_than_or_equal": "lte",
    "max": "lte",
    "maximum": "lte",
    "between": "between",
    "range": "between",
}

CONDITION_LABELS = {
    "gte": "Greater Than or Equal To",
    "lte": "Less Than or Equal To",
    "between": "Between Minimum and Maximum",
}


# =========================================================
# CONFIG
# =========================================================

def normalize_adr_condition(condition):
    normalized = str(condition or "gte").strip().lower()
    return CONDITION_ALIASES.get(normalized, normalized)


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
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def normalize_adr_config(config):
    """Coerce a request model / dict into the plain shape the evaluator uses.

    Returns None when the filter is absent or switched off so callers can skip
    the whole stage (including the daily-candle fetch).
    """
    if not config:
        return None
    if not bool(_config_value(config, "enabled", True)):
        return None

    try:
        lookback_days = int(_config_value(config, "lookback_days", DEFAULT_LOOKBACK_DAYS))
    except (TypeError, ValueError):
        lookback_days = DEFAULT_LOOKBACK_DAYS

    return {
        "enabled": True,
        "lookback_days": max(MIN_LOOKBACK_DAYS, lookback_days),
        "condition": normalize_adr_condition(_config_value(config, "condition", "gte")),
        "min_adr": _optional_float(_config_value(config, "min_adr")),
        "max_adr": _optional_float(_config_value(config, "max_adr")),
        "apply_to_crypto": bool(_config_value(config, "apply_to_crypto", False)),
    }


def adr_config_error(config):
    """Human-readable reason the filter cannot run, or None when it is valid.

    Mirrors models/filters.py's validation so the same rules also hold for
    dict-shaped configs coming from tests and internal callers.
    """
    if not config:
        return None

    condition = config.get("condition")
    if condition not in ADR_CONDITIONS:
        return f"adr.condition must be one of {', '.join(ADR_CONDITIONS)}"

    min_adr = config.get("min_adr")
    max_adr = config.get("max_adr")

    if min_adr is not None and min_adr < 0:
        return "adr.min_adr cannot be negative"
    if max_adr is not None and max_adr < 0:
        return "adr.max_adr cannot be negative"

    if condition == "gte" and min_adr is None:
        return "adr.min_adr is required when condition is 'gte'"
    if condition == "lte" and max_adr is None:
        return "adr.max_adr is required when condition is 'lte'"
    if condition == "between":
        if min_adr is None or max_adr is None:
            return "adr.min_adr and adr.max_adr are both required when condition is 'between'"
        if min_adr > max_adr:
            return "adr.min_adr cannot be greater than adr.max_adr"

    return None


# =========================================================
# CALCULATION
# =========================================================

def daily_range(candle):
    """High - Low for one completed daily candle.

    Returns None - never 0.0 - for missing or unusable data, so the caller can
    exclude the symbol instead of averaging a phantom "$0 movement" day.
    """
    if not isinstance(candle, dict):
        return None

    high = candle.get("high")
    low = candle.get("low")
    if high is None or low is None:
        return None

    try:
        high = float(high)
        low = float(low)
    except (TypeError, ValueError):
        return None

    # NaN check without importing math: NaN is the only value != itself.
    if high != high or low != low:
        return None
    if high < low:
        return None

    return high - low


def compute_adr(candles, lookback_days=DEFAULT_LOOKBACK_DAYS):
    """Average daily range in dollars over the last `lookback_days` completed
    daily candles, or None when the symbol should be excluded.

    None is returned when there is not enough completed daily history, or when
    any candle inside the window has missing/invalid high-low data.
    """
    try:
        lookback_days = int(lookback_days)
    except (TypeError, ValueError):
        return None
    if lookback_days < MIN_LOOKBACK_DAYS:
        return None

    # Defensive: callers that fetch through filter_shared already dropped the
    # forming bar, but direct callers must never see today's partial range.
    completed = drop_unclosed_last_candle(list(candles or []))
    if len(completed) < lookback_days:
        return None

    window = completed[-lookback_days:]
    total = 0.0
    for candle in window:
        candle_range = daily_range(candle)
        if candle_range is None:
            return None
        total += candle_range

    return total / lookback_days


def adr_passes(adr_value, condition, min_adr=None, max_adr=None):
    """Inclusive dollar comparison on the full unrounded ADR value."""
    if adr_value is None:
        return False

    normalized = normalize_adr_condition(condition)

    if normalized == "gte":
        return min_adr is not None and adr_value >= float(min_adr)
    if normalized == "lte":
        return max_adr is not None and adr_value <= float(max_adr)
    if normalized == "between":
        if min_adr is None or max_adr is None:
            return False
        return float(min_adr) <= adr_value <= float(max_adr)

    return False


def evaluate_adr(candles, config):
    """Evaluate one symbol's completed daily candles against an ADR config."""
    normalized = normalize_adr_config(config)
    if not normalized:
        return {"passed": True, "adr": None, "reason": "disabled"}

    error = adr_config_error(normalized)
    if error:
        return {"passed": False, "adr": None, "reason": error}

    adr_value = compute_adr(candles, normalized["lookback_days"])
    if adr_value is None:
        return {
            "passed": False,
            "adr": None,
            "reason": "insufficient_daily_history",
            "lookback_days": normalized["lookback_days"],
        }

    passed = adr_passes(
        adr_value,
        normalized["condition"],
        normalized.get("min_adr"),
        normalized.get("max_adr"),
    )

    return {
        "passed": passed,
        "adr": adr_value,
        "reason": None if passed else "outside_threshold",
        "lookback_days": normalized["lookback_days"],
        "condition": normalized["condition"],
        "min_adr": normalized.get("min_adr"),
        "max_adr": normalized.get("max_adr"),
    }


# =========================================================
# SCOPE
# =========================================================

def _is_crypto_asset(asset, asset_type=None):
    row_type = str(asset.get("asset_type") or asset_type or "").strip().lower()
    if row_type:
        return row_type == "crypto"
    return str(asset.get("symbol") or "").upper().endswith("-USD")


def adr_applies_to_asset(asset, config, asset_type=None):
    """Stocks by default; crypto only when the user explicitly enables it."""
    if not config:
        return False
    if _is_crypto_asset(asset, asset_type):
        return bool(config.get("apply_to_crypto"))
    return True


# =========================================================
# APPLY
# =========================================================

def format_adr_value(adr_value):
    """Display rounding only - comparisons always use the unrounded value."""
    if adr_value is None:
        return "n/a"
    return f"${adr_value:,.2f}"


def adr_summary(adr_value, config, passed=True):
    lookback_days = config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
    condition = config.get("condition", "gte")
    min_adr = config.get("min_adr")
    max_adr = config.get("max_adr")

    if adr_value is None:
        return (
            f"Fewer than {lookback_days} completed daily candles available — "
            "excluded instead of averaging a shorter window."
        )

    value = format_adr_value(adr_value)
    if condition == "gte":
        threshold = f"minimum {format_adr_value(min_adr)}"
    elif condition == "lte":
        threshold = f"maximum {format_adr_value(max_adr)}"
    else:
        threshold = f"range {format_adr_value(min_adr)}–{format_adr_value(max_adr)}"

    verdict = "meets" if passed else "misses"
    return f"{lookback_days}-day ADR {value} {verdict} {threshold}."


def build_adr_sticker(adr_value, config):
    lookback_days = config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
    return build_indicator_sticker(
        "ADR $",
        f"{lookback_days}-day average daily range {format_adr_value(adr_value)}",
        {"window": lookback_days, "confirmation": False},
        window=lookback_days,
        decision="Average Daily Range",
    )


async def apply_adr(data, config, asset_type=None):
    """Filter a scan payload down to symbols whose ADR matches the config.

    Daily candles are fetched separately from the scan's own timeframe, in one
    bulk call, so the ADR of a symbol never changes with the scanner timeframe.
    """
    normalized = normalize_adr_config(config)
    if not normalized or not data:
        return data

    error = adr_config_error(normalized)
    if error:
        logger.warning("adr filter skipped - invalid config: %s", error)
        return data

    in_scope = [
        asset for asset in data
        if adr_applies_to_asset(asset, normalized, asset_type)
    ]
    if not in_scope:
        return data

    lookback_days = normalized["lookback_days"]
    daily_by_symbol = await get_completed_daily_candles_bulk(
        [asset.get("symbol") for asset in in_scope],
        lookback_days,
    )

    in_scope_ids = {id(asset) for asset in in_scope}
    filtered = []

    for asset in data:
        if id(asset) not in in_scope_ids:
            filtered.append(asset)
            continue

        symbol = asset.get("symbol")
        result = evaluate_adr(daily_by_symbol.get(symbol), normalized)

        if not result["passed"]:
            logger.info(
                "adr excluded symbol=%s reason=%s adr=%s lookback=%s",
                symbol,
                result.get("reason"),
                result.get("adr"),
                lookback_days,
            )
            continue

        asset["adr"] = result["adr"]

        # Gate/entry scans run the pipeline twice over the same asset dicts,
        # so never stack a duplicate sticker on the second pass.
        sticker = build_adr_sticker(result["adr"], normalized)
        stickers = asset.setdefault("stickers", [])
        if sticker not in stickers:
            stickers.append(sticker)

        matched = asset.setdefault("matched_indicators", [])
        if "adr" not in matched:
            matched.append("adr")

        filtered.append(asset)

    return filtered


def _chart_daily_candles(candles):
    """Trim the ADR window to what the detail chart needs, with each day's
    own High-Low range attached so the chart never recomputes it."""
    chart_candles = []
    for candle in candles or []:
        candle_range = daily_range(candle)
        chart_candles.append({
            "time": candle.get("time"),
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": candle.get("close"),
            "volume": candle.get("volume"),
            "is_closed": True,
            "daily_range": candle_range,
        })
    return chart_candles


async def evaluate_adr_detail(asset, config, asset_type=None):
    """Per-symbol ADR breakdown for the result detail panel."""
    normalized = normalize_adr_config(config)
    if not normalized:
        return None

    error = adr_config_error(normalized)
    if error:
        return {
            "name": "adr",
            "passed": False,
            "summary": error,
            "sticker": None,
            "details": {**normalized, "error": error},
        }

    if not adr_applies_to_asset(asset, normalized, asset_type):
        return {
            "name": "adr",
            "passed": True,
            "summary": "ADR filter not applied — crypto is excluded unless enabled for crypto.",
            "sticker": None,
            "details": {**normalized, "applied": False},
        }

    candles = await get_completed_daily_candles_bulk(
        [asset.get("symbol")],
        normalized["lookback_days"],
    )
    window = candles.get(asset.get("symbol")) or []
    result = evaluate_adr(window, normalized)
    summary = adr_summary(result["adr"], normalized, passed=result["passed"])

    return {
        "name": "adr",
        "passed": result["passed"],
        "summary": summary,
        "sticker": build_adr_sticker(result["adr"], normalized) if result["passed"] else None,
        "details": {
            **normalized,
            "applied": True,
            "adr": result["adr"],
            "adr_display": format_adr_value(result["adr"]),
            "reason": result.get("reason"),
            # The daily bars the average was actually taken over. The detail
            # chart plots these directly: the scan's own timeframe candles
            # would be the wrong bars to show for a daily-only measure.
            "daily_candles": _chart_daily_candles(window),
            "daily_candle_times": [candle.get("time") for candle in window],
        },
    }

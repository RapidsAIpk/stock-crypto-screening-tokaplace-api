# services/filter_shared.py
"""Milestone 3 Phase 0 shared primitives.

EMA, Channel, Trendy ADX, and ADR/Gap all independently need the same three
concepts (inclusive candle-range checks, completed-candle filtering, and
daily-candle fetching). These helpers generalize the working patterns already
proven in confluence.py / indicators.py so later phases share one tested
implementation instead of diverging.
"""

from services.market_data import fetch_live_data


# =========================================================
# 0.1 - Inclusive Min/Max Candle-Range Utility
# =========================================================

def candles_since_event_in_range(event_index, current_index, min_candles=None, max_candles=None):
    """Did a past event at `event_index` happen within an inclusive
    [min_candles, max_candles] window of candles ago, as of `current_index`?

    Generalizes the candles_since_close_min/max pattern in
    services/confluence.py's `_source_sub_filter_passes`.
    """
    if event_index is None or current_index is None:
        return False
    if current_index < event_index:
        return False
    if min_candles is not None and max_candles is not None and max_candles < min_candles:
        raise ValueError("max_candles must be >= min_candles")

    candles_since = current_index - event_index

    if min_candles is not None and candles_since < int(min_candles):
        return False
    if max_candles is not None and candles_since > int(max_candles):
        return False
    return True


def consecutive_active_in_range(streak, min_candles=None, max_candles=None):
    """Has an active condition held true for a consecutive `streak` of
    candles ending now, within an inclusive [min_candles, max_candles]
    window?

    Same range check as `candles_since_event_in_range`, but for "still
    active" streaks (e.g. reclaim state machines) rather than a single past
    event.
    """
    if streak is None or streak <= 0:
        return False
    if min_candles is not None and max_candles is not None and max_candles < min_candles:
        raise ValueError("max_candles must be >= min_candles")

    if min_candles is not None and streak < int(min_candles):
        return False
    if max_candles is not None and streak > int(max_candles):
        return False
    return True


# =========================================================
# 0.2 - Completed-Candle Filter Utility
# =========================================================

def drop_unclosed_last_candle(candles):
    """Drop a still-forming last candle so calculations and rule evaluation
    only ever see fully completed bars.

    Generalizes services/indicators.py's `_trend_closed_candles`. Trend
    Channel and Trendy ADX keep their own existing equivalents - this is for
    EMA, ADR, and Gap Exclusion to share instead of each re-implementing it.
    """
    if candles and candles[-1].get("is_closed") is False:
        return candles[:-1]
    return candles


# =========================================================
# 0.3 - Selection-Mode Evaluator (One / Multiple / Any / All)
# =========================================================

SELECTION_MODES = {"one", "multiple", "any", "all"}


def resolve_selection(results, mode="all", required_count=None):
    """Resolve a list of independent per-line/zone/EMA booleans into a
    single pass/fail under a selection mode.

    - "all": every result must be True (today's hardcoded behavior in
      channel_line_rules.py:25-52 and trend_channels.py:615-632).
    - "any": at least one True.
    - "one": exactly one True.
    - "multiple": at least `required_count` True (defaults to 2, since
      "multiple" implies more than a single match).
    """
    normalized_mode = str(mode or "all").strip().lower()
    if normalized_mode not in SELECTION_MODES:
        raise ValueError(f"Unknown selection mode: {mode!r}")

    if not results:
        return False

    true_count = sum(1 for result in results if result)

    if normalized_mode == "all":
        return true_count == len(results)
    if normalized_mode == "any":
        return true_count >= 1
    if normalized_mode == "one":
        return true_count == 1

    threshold = 2 if required_count is None else int(required_count)
    return true_count >= threshold


# =========================================================
# 0.4 - Daily-Candle-Independent-of-Timeframe Fetch Helper
# =========================================================

async def get_completed_daily_candles(symbol, lookback_days):
    """Last `lookback_days` fully completed daily candles for `symbol`,
    regardless of the scanner's active timeframe.

    Wraps market_data.fetch_live_data with a hardcoded "1day" timeframe so
    ADR and Gap Exclusion always evaluate real daily bars even when the
    scanner itself is running on an intraday timeframe. Returns None when
    fewer than `lookback_days` completed candles are available so callers
    can exclude the symbol instead of silently averaging a shorter window.
    """
    lookback_days = int(lookback_days)
    if lookback_days <= 0 or not symbol:
        return None

    # +1 so a still-forming daily candle can be dropped without leaving the
    # caller one candle short of the requested lookback.
    results = await fetch_live_data([symbol], "1day", candles_limit=lookback_days + 1)
    if not results:
        return None

    candles = drop_unclosed_last_candle(results[0].get("candles") or [])
    if len(candles) < lookback_days:
        return None

    return candles[-lookback_days:]

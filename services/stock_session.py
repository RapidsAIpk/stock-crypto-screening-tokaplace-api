"""US stock intraday session filtering for TradingView parity."""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from core.config import settings


US_EASTERN = ZoneInfo("America/New_York")
REGULAR_SESSION_OPEN = time(9, 30)
REGULAR_SESSION_CLOSE = time(16, 0)

SESSION_POLICY_PROVIDER_DEFAULT = "provider_default"
SESSION_POLICY_TRADINGVIEW_REGULAR = "tradingview_regular"
SUPPORTED_STOCK_INTRADAY_SESSION_POLICIES = frozenset(
    {
        SESSION_POLICY_PROVIDER_DEFAULT,
        SESSION_POLICY_TRADINGVIEW_REGULAR,
    }
)

# Massive UTC-aligned intraday bars can include pre-market and after-hours rows.
# Request extra history so post-filter slices still satisfy indicator lookbacks.
SESSION_FILTER_FETCH_MULTIPLIER = 2.5

_INTRADAY_TIMEFRAMES = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})


def normalize_session_policy(value, default=SESSION_POLICY_TRADINGVIEW_REGULAR) -> str:
    normalized = str(value or default).strip().lower()
    if normalized in SUPPORTED_STOCK_INTRADAY_SESSION_POLICIES:
        return normalized
    return default


def is_stock_intraday_timeframe(timeframe: str) -> bool:
    normalized = str(timeframe or "").strip().lower()
    if normalized in _INTRADAY_TIMEFRAMES:
        return True

    if normalized.endswith(("m", "min", "mins", "minute", "minutes", "h", "hr", "hour", "hours")):
        return True

    return False


def expected_session_policy_for_symbol(symbol: str, timeframe: str) -> str | None:
    if str(symbol or "").endswith("-USD"):
        return None
    if not is_stock_intraday_timeframe(timeframe):
        return None
    return normalize_session_policy(settings.STOCK_INTRADAY_SESSION_POLICY)


def should_apply_tradingview_regular_filter(symbol: str, timeframe: str, session_policy: str | None = None) -> bool:
    policy = session_policy
    if policy is None:
        policy = expected_session_policy_for_symbol(symbol, timeframe)
    return (
        policy == SESSION_POLICY_TRADINGVIEW_REGULAR
        and not str(symbol or "").endswith("-USD")
        and is_stock_intraday_timeframe(timeframe)
    )


def is_tradingview_regular_session_bar(unix_seconds: int) -> bool:
    """True when a UTC-aligned bar open falls inside US regular cash session.

    Massive/Polygon hourly bars are UTC clock-hour buckets. TradingView's
    NASDAQ regular-session 1h chart keeps bars whose ET open is 09:30 <= t < 16:00
    and drops after-hours rows such as 20:00 / 22:00 UTC on ZBIO.
    """
    start_et = datetime.fromtimestamp(int(unix_seconds), tz=timezone.utc).astimezone(US_EASTERN)
    if start_et.weekday() >= 5:
        return False
    start_clock = start_et.time()
    return REGULAR_SESSION_OPEN <= start_clock < REGULAR_SESSION_CLOSE


def filter_tradingview_regular_candles(candles, timeframe: str | None = None):
    del timeframe  # reserved for future timeframe-specific rules
    if not candles:
        return []

    return [
        candle
        for candle in candles
        if candle.get("time") is not None
        and is_tradingview_regular_session_bar(int(candle["time"]))
    ]


def apply_stock_session_policy(candles, symbol: str, timeframe: str, session_policy: str | None = None):
    if not should_apply_tradingview_regular_filter(symbol, timeframe, session_policy):
        return list(candles or [])

    return filter_tradingview_regular_candles(candles, timeframe)


def session_fetch_multiplier(symbol: str, timeframe: str, session_policy: str | None = None) -> float:
    if should_apply_tradingview_regular_filter(symbol, timeframe, session_policy):
        return SESSION_FILTER_FETCH_MULTIPLIER
    return 1.0


def is_payload_session_compatible(payload, symbol: str, timeframe: str) -> bool:
    expected = expected_session_policy_for_symbol(symbol, timeframe)
    if expected is None:
        return True

    if not isinstance(payload, dict):
        return False

    cached_policy = payload.get("session_policy") or SESSION_POLICY_PROVIDER_DEFAULT
    return normalize_session_policy(cached_policy) == normalize_session_policy(expected)

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


# =========================================================
# SESSION-ANCHORED INTRADAY AGGREGATION
#
# Massive/Polygon aggregate 1h/4h/custom-minute bars on UTC clock boundaries
# (e.g. hourly bars start at :00 UTC), which almost never lines up with the
# 09:30 ET regular-session open. TradingView anchors every intraday bar to
# that 09:30 open instead, so a 1h chart shows 09:30-10:30, 10:30-11:30, ...,
# with a short 15:30-16:00 bar closing the day.
#
# The provider's own candle "time" is NEVER trusted as already being on a
# clean boundary - its custom-bars endpoint aggregates relative to the
# requested fetch window (which itself trails "now"), not to fixed
# 09:30/:00 clock marks, so a candle's own timestamp can drift by whatever
# offset the fetch window happened to start at (e.g. 13:42/14:42/...
# instead of 13:30/14:30/...). Every intraday candle - including native
# 1m/5m/15m/30m ones - is therefore re-anchored through
# resolve_session_bucket_start, which derives the bucket start purely from
# the session's own 09:30 ET open, never from request/scan time, the
# provider's row timestamp, or any other external clock.
# =========================================================


def resolve_session_bucket_start(source_time_unix: int, bucket_minutes: int) -> int:
    """The single reusable bucket-boundary resolver for every intraday
    timeframe: the canonical 09:30-ET-anchored bucket start covering
    `source_time_unix`, computed as

        session_open + floor((source_time - session_open) / bucket_seconds) * bucket_seconds

    This is derived purely from the session's own open and the candle's own
    time-of-day - never from request/scan time, the current clock minute,
    the provider's response time, or the first downloaded candle's
    timestamp - so the result is identical no matter when the fetch runs.
    """
    source_time_unix = int(source_time_unix)
    bucket_seconds = int(bucket_minutes) * 60
    if bucket_seconds <= 0:
        return source_time_unix

    start_et = datetime.fromtimestamp(source_time_unix, tz=timezone.utc).astimezone(US_EASTERN)
    session_open_et = start_et.replace(
        hour=REGULAR_SESSION_OPEN.hour,
        minute=REGULAR_SESSION_OPEN.minute,
        second=0,
        microsecond=0,
    )
    session_open_unix = int(session_open_et.timestamp())
    bucket_index = (source_time_unix - session_open_unix) // bucket_seconds
    return session_open_unix + bucket_index * bucket_seconds


def session_bucket_close_unix(bucket_start_unix: int, bucket_minutes: int) -> int:
    """Close time (unix seconds) of a session-anchored bucket that opened at
    `bucket_start_unix`, capped to that trading date's 16:00 ET session
    close so a shortened final-of-day bucket (e.g. the 15:30-16:00 ET tail
    of a 1h chart) is treated as closed once the session ends rather than at
    `bucket_start + bucket_minutes` (which can land after the close).
    """
    start_et = datetime.fromtimestamp(int(bucket_start_unix), tz=timezone.utc).astimezone(US_EASTERN)
    session_close_et = start_et.replace(
        hour=REGULAR_SESSION_CLOSE.hour,
        minute=REGULAR_SESSION_CLOSE.minute,
        second=0,
        microsecond=0,
    )
    nominal_close_unix = int(bucket_start_unix) + int(bucket_minutes) * 60
    return min(nominal_close_unix, int(session_close_et.timestamp()))


_REGULAR_SESSION_LENGTH_MINUTES = (
    (REGULAR_SESSION_CLOSE.hour * 60 + REGULAR_SESSION_CLOSE.minute)
    - (REGULAR_SESSION_OPEN.hour * 60 + REGULAR_SESSION_OPEN.minute)
)


def aggregate_session_anchored_candles(candles, bucket_minutes: int):
    """Aggregate ascending stock intraday candles into `bucket_minutes`-wide
    buckets anchored to the 09:30 ET session open, using
    resolve_session_bucket_start as the sole source of each bucket's stored
    "time" - never the source candle's own (possibly misaligned) timestamp.
    Any candle starting outside 09:30-16:00 ET (pre-market/after-hours) is
    dropped defensively, even though callers are expected to have already
    session-filtered `candles`.

    Because resolve_session_bucket_start is computed independently per
    candle from that candle's own trading date, grouping by its return
    value alone is sufficient - buckets never span more than one ET trading
    date. The last bucket of a date may be shorter than `bucket_minutes`
    since the 6.5-hour session does not always divide evenly, but it still
    starts on an anchored boundary and simply ends at the session close.
    """
    if not candles or bucket_minutes <= 0:
        return []

    buckets = []
    current_bucket_start = None
    current_bucket = None

    for candle in candles:
        unix_seconds = candle.get("time")
        if unix_seconds is None:
            continue

        unix_seconds = int(unix_seconds)
        start_et = datetime.fromtimestamp(unix_seconds, tz=timezone.utc).astimezone(US_EASTERN)
        minutes_since_open = (
            (start_et.hour - REGULAR_SESSION_OPEN.hour) * 60
            + (start_et.minute - REGULAR_SESSION_OPEN.minute)
        )
        if minutes_since_open < 0 or minutes_since_open >= _REGULAR_SESSION_LENGTH_MINUTES:
            continue

        bucket_start_unix = resolve_session_bucket_start(unix_seconds, bucket_minutes)

        if bucket_start_unix != current_bucket_start:
            if current_bucket is not None:
                buckets.append(current_bucket)
            current_bucket_start = bucket_start_unix
            current_bucket = {
                "time": bucket_start_unix,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle.get("volume") or 0.0,
            }
            continue

        current_bucket["high"] = max(current_bucket["high"], candle["high"])
        current_bucket["low"] = min(current_bucket["low"], candle["low"])
        current_bucket["close"] = candle["close"]
        current_bucket["volume"] += candle.get("volume") or 0.0

    if current_bucket is not None:
        buckets.append(current_bucket)

    return buckets

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import math
import re
import time
from urllib.parse import quote

import httpx

from core.config import settings
from services.market_data_store import store
from services.integration_runtime import integration_runtime
from services.stock_session import (
    apply_stock_session_policy,
    expected_session_policy_for_symbol,
    is_payload_session_compatible,
    session_fetch_multiplier,
)


logger = logging.getLogger(__name__)

MARKET_DATA_PROVIDER = "massive"
LEGACY_MARKET_DATA_PROVIDER = "polygon"
BINANCE_PROVIDER = "binance"
MARKET_DATA_PROVIDER_ALIASES = {
    MARKET_DATA_PROVIDER: MARKET_DATA_PROVIDER,
    "massive.com": MARKET_DATA_PROVIDER,
    LEGACY_MARKET_DATA_PROVIDER: MARKET_DATA_PROVIDER,
    "polygonio": MARKET_DATA_PROVIDER,
    "polygon.io": MARKET_DATA_PROVIDER,
    BINANCE_PROVIDER: BINANCE_PROVIDER,
    "binance_spot": BINANCE_PROVIDER,
}

DEFAULT_BATCH_SIZE = max(1, int(settings.MARKET_DATA_FETCH_BATCH_SIZE or 500))
DOWNLOAD_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.5
MAX_CANDLES = 500
ONE_DAY_SECONDS = 24 * 60 * 60
SLOW_FETCH_WARNING_SECONDS = 10.0
FAILED_REFRESH_BACKOFF_SECONDS = 5 * 60
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1day": 24 * 60 * 60,
}
REFRESH_BUFFER_SECONDS = 5
FUNDAMENTALS_CACHE = {}
MASSIVE_BASE_URL = str(settings.MARKET_DATA_API_BASE_URL or "").strip() or "https://api.massive.com"
POLYGON_BASE_URL = MASSIVE_BASE_URL
POLYGON_TIMEOUT_SECONDS = 10
POLYGON_MAX_BASE_AGGREGATES = 50_000
POLYGON_MIN_BASE_AGGREGATES = 64
POLYGON_MAX_PAGES = 6
POLYGON_FAST_PATH_CHUNK_SIZE = 250
POLYGON_FULL_MARKET_SNAPSHOT_STOCK_MIN_SYMBOLS = 1000
POLYGON_FULL_MARKET_SNAPSHOT_CRYPTO_MIN_SYMBOLS = 400
POLYGON_LOOKBACK_BUFFER_RATIO = 0.2
POLYGON_LOOKBACK_BUFFER_MIN_BARS = 8
# Regular-session stocks trade roughly 6.5 hours out of each 24-hour day and
# not at all on weekends/holidays, so a calendar-time window sized only for
# candle *count* (as if the market traded around the clock) can under-cover
# real trading-hour availability - e.g. a window that lands on a weekend can
# come back with far fewer candles than requested. Intraday stock lookback
# windows get an extra calendar-time multiplier plus a flat floor so a
# request for N candles can still find N candles when the window starts
# near a weekend or market holiday. Crypto trades 24/7 and does not need
# this expansion.
POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_RATIO = 4.0
POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_MIN_SECONDS = 4 * ONE_DAY_SECONDS
POLYGON_FUNDAMENTALS_TTL_SECONDS = 6 * 60 * 60
POLYGON_GROUPED_DAILY_MIN_SYMBOLS = 100
POLYGON_GROUPED_DAILY_CRYPTO_MIN_SYMBOLS = 25
POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_RATIO = 0.25
POLYGON_GROUPED_DAILY_MAX_CANDLES = MAX_CANDLES
POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_DAYS = 8
POLYGON_GROUPED_DAILY_CRYPTO_LOOKBACK_PADDING_DAYS = 2
POLYGON_GROUPED_DAILY_CRYPTO_DEFAULT_REQUEST_INTERVAL_SECONDS = 5
POLYGON_GROUPED_DAILY_MAX_TRADING_DAYS = (
    MAX_CANDLES
    + max(
        POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_DAYS,
        int(math.ceil(MAX_CANDLES * POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_RATIO)),
    )
)
POLYGON_GROUPED_HISTORY_MAX_SOURCE_DAYS = 800
POLYGON_GROUPED_DAILY_DATE_CONCURRENCY = 8
POLYGON_GROUPED_DAILY_SPARSE_SCAN_THRESHOLD = 1000
POLYGON_GROUPED_DAILY_BULK_ONLY_THRESHOLD = 2000
POLYGON_GROUPED_DAILY_CRYPTO_BULK_ONLY_THRESHOLD = 200
POLYGON_INTRADAY_SNAPSHOT_PREFILTER_MIN_SYMBOLS = (
    POLYGON_FULL_MARKET_SNAPSHOT_STOCK_MIN_SYMBOLS
)
BINANCE_BASE_URL = str(settings.BINANCE_API_BASE_URL or "").strip() or "https://api.binance.com"
BINANCE_TIMEOUT_SECONDS = 12
BINANCE_MAX_LIMIT = 1000
BINANCE_EXCHANGE_INFO_TTL_SECONDS = 60 * 60
BINANCE_QUOTE_PREFERENCE = ("USDT", "USDC", "FDUSD", "BUSD", "USD")
BINANCE_QUOTES_REQUEST_WEIGHT = 4
BINANCE_KLINES_REQUEST_WEIGHT = 2
BINANCE_EXCHANGE_INFO_REQUEST_WEIGHT = 20
SUPPORTED_CANDLE_PROVIDERS = {MARKET_DATA_PROVIDER}
SUPPORTED_CRYPTO_CANDLE_PROVIDERS = {MARKET_DATA_PROVIDER, BINANCE_PROVIDER}
WORKER_CACHE_TIMEFRAMES = frozenset({"1h", "4h", "1day"})
_polygon_key_warning_emitted = False
_polygon_client = None
_polygon_client_lock = asyncio.Lock()
_polygon_rate_lock = asyncio.Lock()
_polygon_next_request_at = 0.0
_binance_client = None
_binance_client_lock = asyncio.Lock()
_binance_rate_lock = asyncio.Lock()
_binance_next_request_at = 0.0
_binance_exchange_info_lock = asyncio.Lock()
_binance_exchange_info_cache = {
    "loaded_at": 0,
    "pairs_by_base": {},
}
_binance_pair_not_found_logged = set()


def normalize_market_data_provider_name(provider):
    normalized = str(provider or MARKET_DATA_PROVIDER).strip().lower()
    if not normalized:
        return MARKET_DATA_PROVIDER
    return MARKET_DATA_PROVIDER_ALIASES.get(normalized, normalized)


def _polygon_client_limits():
    concurrency = settings.market_data_fetch_concurrency
    keepalive = max(8, min(96, concurrency))
    max_connections = max(keepalive, concurrency * 4)
    return httpx.Limits(
        max_keepalive_connections=keepalive,
        max_connections=max_connections,
    )


def _binance_client_limits():
    concurrency = max(1, int(settings.BINANCE_FETCH_CONCURRENCY or 1))
    keepalive = max(8, min(32, concurrency))
    max_connections = max(keepalive, concurrency * 4)
    return httpx.Limits(
        max_keepalive_connections=keepalive,
        max_connections=max_connections,
    )


async def _get_polygon_client():
    global _polygon_client

    if _polygon_client is not None:
        return _polygon_client

    async with _polygon_client_lock:
        if _polygon_client is None:
            _polygon_client = httpx.AsyncClient(
                base_url=MASSIVE_BASE_URL,
                timeout=httpx.Timeout(POLYGON_TIMEOUT_SECONDS),
                limits=_polygon_client_limits(),
                headers={"Accept": "application/json"},
                http2=settings.market_data_http2_enabled,
            )
    return _polygon_client


async def _get_binance_client():
    global _binance_client

    if _binance_client is not None:
        return _binance_client

    async with _binance_client_lock:
        if _binance_client is None:
            _binance_client = httpx.AsyncClient(
                base_url=BINANCE_BASE_URL,
                timeout=httpx.Timeout(BINANCE_TIMEOUT_SECONDS),
                limits=_binance_client_limits(),
                headers={"Accept": "application/json"},
                http2=True,
            )
    return _binance_client


async def close_polygon_client():
    global _polygon_client, _polygon_next_request_at

    if _polygon_client is None:
        return

    async with _polygon_client_lock:
        if _polygon_client is None:
            return
        await _polygon_client.aclose()
        _polygon_client = None
        _polygon_next_request_at = 0.0


async def close_binance_client():
    global _binance_client, _binance_next_request_at

    if _binance_client is None:
        return

    async with _binance_client_lock:
        if _binance_client is None:
            return
        await _binance_client.aclose()
        _binance_client = None
        _binance_next_request_at = 0.0


async def close_massive_client():
    await close_polygon_client()


async def close_market_data_clients():
    await close_polygon_client()
    await close_binance_client()


def normalize_candles_limit(candles_limit):
    if candles_limit is None:
        return MAX_CANDLES

    try:
        parsed = int(candles_limit)
    except (TypeError, ValueError):
        return MAX_CANDLES

    return max(1, min(MAX_CANDLES, parsed))


def timeframe_uses_worker_cache(timeframe):
    return str(timeframe or "").strip().lower() in WORKER_CACHE_TIMEFRAMES

# =========================================================
# TIMEFRAME MAP
# =========================================================

def map_timeframe_for_polygon(tf):
    parsed = parse_timeframe_spec(tf)

    if parsed:
        amount, unit = parsed
        if unit == "m":
            return amount, "minute"
        if unit == "h":
            return amount, "hour"
        if unit == "d":
            return amount, "day"
        if unit == "w":
            return amount, "week"
        if unit == "mo":
            return amount, "month"

    mapping = {
        "1m": (1, "minute"),
        "5m": (5, "minute"),
        "15m": (15, "minute"),
        "30m": (30, "minute"),
        "1h": (1, "hour"),
        "4h": (4, "hour"),
        "1day": (1, "day"),
    }
    return mapping.get(tf, (1, "day"))


def map_timeframe_for_binance(tf):
    parsed = parse_timeframe_spec(tf)

    if parsed:
        amount, unit = parsed
        if unit == "m" and amount in {1, 3, 5, 15, 30}:
            return f"{amount}m"
        if unit == "h" and amount in {1, 2, 4, 6, 8, 12}:
            return f"{amount}h"
        if unit == "d" and amount in {1, 3}:
            return f"{amount}d"
        if unit == "w" and amount == 1:
            return "1w"
        if unit == "mo" and amount == 1:
            return "1M"
        return None

    mapping = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1day": "1d",
    }
    return mapping.get(tf)


def timeframe_seconds(tf):
    parsed = parse_timeframe_spec(tf)

    if parsed:
        amount, unit = parsed
        if unit == "m":
            return amount * 60
        if unit == "h":
            return amount * 60 * 60
        if unit == "d":
            return amount * 24 * 60 * 60
        if unit == "w":
            return amount * 7 * 24 * 60 * 60
        if unit == "mo":
            return amount * 30 * 24 * 60 * 60

    return TIMEFRAME_SECONDS.get(tf, 24 * 60 * 60)


def next_refresh_at_for_timeframe(timeframe, now=None):

    reference = int(time.time()) if now is None else int(now)
    seconds = timeframe_seconds(timeframe)
    if seconds <= 0:
        logger.warning(
            "Invalid timeframe seconds=%s for timeframe=%s; falling back to 1day refresh cadence.",
            seconds,
            timeframe,
        )
        seconds = ONE_DAY_SECONDS
    next_boundary = ((reference // seconds) + 1) * seconds
    return next_boundary + REFRESH_BUFFER_SECONDS


def is_payload_fresh(payload, timeframe, now=None):

    if not payload:
        return False

    candles = payload.get("candles") or []
    if not candles:
        return False

    latest = candles[-1]
    latest_time = latest.get("time")
    if latest_time is None:
        return False

    reference = int(time.time()) if now is None else int(now)
    return reference < (int(latest_time) + timeframe_seconds(timeframe))


def is_refresh_due(payload, timeframe, now=None):
    if not payload:
        return True

    reference = int(time.time()) if now is None else int(now)
    next_refresh_at = payload.get("next_refresh_at")

    if isinstance(next_refresh_at, (int, float)):
        return reference >= int(next_refresh_at)

    return not is_payload_fresh(payload, timeframe, reference)


# =========================================================
# SYMBOL MAPPING
# =========================================================

def is_crypto_symbol(symbol):
    return symbol.endswith("-USD")


def map_symbol_for_polygon(symbol):
    if is_crypto_symbol(symbol):
        base = symbol[:-4].replace("-", "").strip().upper()
        return f"X:{base}USD"

    return str(symbol).strip().upper()


def map_symbol_for_binance(symbol):
    normalized = str(symbol).strip().upper()
    if normalized.endswith("-USD"):
        base = normalized[:-4].replace("-", "").strip().upper()
        return f"{base}USDT"
    if normalized.endswith("-USDT"):
        return normalized.replace("-", "")
    return normalized.replace("-", "")


def _binance_base_asset(symbol):
    normalized = str(symbol).strip().upper()
    if normalized.endswith("-USD"):
        return normalized[:-4].replace("-", "").strip().upper()
    if normalized.endswith("-USDT"):
        return normalized[:-5].replace("-", "").strip().upper()
    return normalized.replace("-", "")


# =========================================================
# CANDLE SHAPING
# =========================================================

def slice_recent(candles, limit=MAX_CANDLES):
    normalized_limit = normalize_candles_limit(limit)
    if len(candles) <= normalized_limit:
        return candles
    return candles[-normalized_limit:]


def normalize_polygon_rows(rows):
    candles = []

    for row in rows or []:
        timestamp_ms = row.get("t")
        open_ = _coerce_number(row.get("o"))
        high = _coerce_number(row.get("h"))
        low = _coerce_number(row.get("l"))
        close = _coerce_number(row.get("c"))
        volume = _coerce_number(row.get("v"), default=0.0)

        if timestamp_ms is None or any(value is None for value in (open_, high, low, close)):
            continue

        candles.append(
            {
                "time": int(int(timestamp_ms) / 1000),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }
        )

    return candles


def normalize_binance_rows(rows):
    candles = []

    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue

        open_time_ms = row[0]
        open_ = _coerce_number(row[1])
        high = _coerce_number(row[2])
        low = _coerce_number(row[3])
        close = _coerce_number(row[4])
        volume = _coerce_number(row[5], default=0.0)

        if open_time_ms is None or any(value is None for value in (open_, high, low, close)):
            continue

        candles.append(
            {
                "time": int(int(open_time_ms) / 1000),
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume or 0),
            }
        )

    return candles


def _coerce_number(value, default=None):
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def aggregate_candles(candles, group_size):

    if group_size <= 1:
        return candles

    trimmed_length = len(candles) - (len(candles) % group_size)
    if trimmed_length <= 0:
        return []

    grouped = []

    for index in range(0, trimmed_length, group_size):
        chunk = candles[index:index + group_size]

        grouped.append({
            "time": chunk[0]["time"],
            "open": chunk[0]["open"],
            "high": max(item["high"] for item in chunk),
            "low": min(item["low"] for item in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(item["volume"] for item in chunk),
        })

    return grouped


def candles_for_timeframe(candles, timeframe, limit=MAX_CANDLES):
    parsed = parse_timeframe_spec(timeframe)

    if not parsed:
        if timeframe == "4h":
            aggregated = aggregate_candles(candles, 4)
            return slice_recent(aggregated, limit=limit)
        return slice_recent(candles, limit=limit)

    amount, unit = parsed
    if amount <= 1:
        return slice_recent(candles, limit=limit)

    if unit == "m":
        if amount < 60:
            return slice_recent(aggregate_candles(candles, amount), limit=limit)
        if amount in {60, 90}:
            return slice_recent(candles, limit=limit)
        if amount % 60 == 0:
            return slice_recent(aggregate_candles(candles, amount // 60), limit=limit)
        return slice_recent(candles, limit=limit)

    if unit == "h":
        return slice_recent(aggregate_candles(candles, amount), limit=limit)
    if unit == "d":
        return slice_recent(aggregate_candles(candles, amount), limit=limit)
    if unit == "w":
        return slice_recent(aggregate_candles(candles, amount), limit=limit)
    if unit == "mo":
        return slice_recent(aggregate_candles(candles, amount), limit=limit)

    return slice_recent(candles, limit=limit)


def parse_timeframe_spec(tf):
    if not isinstance(tf, str):
        return None

    lowered = tf.strip().lower()
    mapping = {
        "1m": (1, "m"),
        "5m": (5, "m"),
        "15m": (15, "m"),
        "30m": (30, "m"),
        "1h": (1, "h"),
        "4h": (4, "h"),
        "1day": (1, "d"),
    }

    if lowered in mapping:
        return mapping[lowered]

    match = re.match(
        r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days|w|wk|week|weeks|mo|mon|month|months)$",
        lowered,
    )
    if not match:
        return None

    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return amount, "m"
    if unit in {"h", "hr", "hour", "hours"}:
        return amount, "h"
    if unit in {"d", "day", "days"}:
        return amount, "d"
    if unit in {"w", "wk", "week", "weeks"}:
        return amount, "w"
    return amount, "mo"


# =========================================================
# CANDLE PROVIDER
# =========================================================

def active_candle_provider():
    provider = normalize_market_data_provider_name(settings.CANDLES_PROVIDER or MARKET_DATA_PROVIDER)
    if provider in SUPPORTED_CANDLE_PROVIDERS:
        return provider

    logger.warning(
        "Unsupported CANDLES_PROVIDER=%s; falling back to %s",
        provider,
        MARKET_DATA_PROVIDER,
    )
    return MARKET_DATA_PROVIDER


def active_crypto_candle_provider():
    provider = normalize_market_data_provider_name(settings.CRYPTO_CANDLES_PROVIDER or MARKET_DATA_PROVIDER)
    if provider in SUPPORTED_CRYPTO_CANDLE_PROVIDERS:
        return provider

    logger.warning(
        "Unsupported CRYPTO_CANDLES_PROVIDER=%s; falling back to %s",
        provider,
        MARKET_DATA_PROVIDER,
    )
    return MARKET_DATA_PROVIDER


def default_concurrency_for_provider(provider=None):
    provider_name = normalize_market_data_provider_name(provider or active_candle_provider())
    if provider_name == BINANCE_PROVIDER:
        return max(1, int(settings.BINANCE_FETCH_CONCURRENCY or 1))
    return settings.market_data_fetch_concurrency


def payload_candle_provider(payload):
    if not isinstance(payload, dict):
        return ""
    provider = str(payload.get("candles_provider") or "").strip()
    if not provider:
        return ""
    return normalize_market_data_provider_name(provider)


def is_payload_for_provider(payload, provider):
    provider_name = normalize_market_data_provider_name(provider)
    if provider_name not in (SUPPORTED_CANDLE_PROVIDERS | SUPPORTED_CRYPTO_CANDLE_PROVIDERS):
        provider_name = MARKET_DATA_PROVIDER
    return payload_candle_provider(payload) == provider_name


def is_payload_for_active_provider(payload):
    return is_payload_for_provider(payload, active_candle_provider())


def expected_candle_provider_for_symbol(symbol):
    if is_crypto_symbol(symbol):
        return active_crypto_candle_provider()
    return active_candle_provider()


def is_payload_for_symbol_provider(payload, symbol):
    return is_payload_for_provider(payload, expected_candle_provider_for_symbol(symbol))


def is_payload_compatible_for_fetch(payload, symbol, timeframe):
    if not is_payload_for_symbol_provider(payload, symbol):
        return False
    return is_payload_session_compatible(payload, symbol, timeframe)


def _mark_unclosed_last_candle(candles, timeframe, now=None):
    if not candles:
        return candles

    last = candles[-1]
    last_time = last.get("time")
    if last_time is None:
        return candles

    reference = int(time.time()) if now is None else int(now)
    if reference >= int(last_time) + timeframe_seconds(timeframe):
        return candles

    candles = list(candles)
    candles[-1] = {**last, "is_closed": False}
    return candles


def _build_market_data_payload(symbol, candles, timeframe, candles_provider=None, session_policy=None):
    candles = _mark_unclosed_last_candle(candles, timeframe)
    resolved_session_policy = session_policy
    if resolved_session_policy is None and not is_crypto_symbol(symbol):
        resolved_session_policy = expected_session_policy_for_symbol(symbol, timeframe)

    payload = {
        "symbol": symbol,
        "price": candles[-1]["close"],
        "candles": candles,
        "candles_provider": normalize_market_data_provider_name(
            candles_provider or expected_candle_provider_for_symbol(symbol)
        ),
        "shares_outstanding": None,
        "float_shares": None,
        "next_refresh_at": next_refresh_at_for_timeframe(timeframe),
    }
    if resolved_session_policy:
        payload["session_policy"] = resolved_session_policy
    return payload


def _finalize_intraday_candles(candles, symbol, timeframe, candles_limit, session_policy=None):
    filtered = apply_stock_session_policy(candles, symbol, timeframe, session_policy)
    return slice_recent(filtered, limit=candles_limit)


def _polygon_download_limit(candles_limit, symbol, timeframe, session_policy=None):
    normalized_limit = normalize_candles_limit(candles_limit)
    multiplier = session_fetch_multiplier(symbol, timeframe, session_policy)
    if multiplier <= 1.0:
        return normalized_limit
    return min(
        MAX_CANDLES,
        max(normalized_limit, int(math.ceil(normalized_limit * multiplier))),
    )


def _payload_with_recent_candles(payload, candles_limit):
    if not isinstance(payload, dict):
        return payload

    candles = payload.get("candles") or []
    recent = slice_recent(candles, limit=candles_limit)
    if len(recent) == len(candles):
        return payload

    refreshed = dict(payload)
    refreshed["candles"] = recent
    if recent:
        refreshed["price"] = recent[-1].get("close", refreshed.get("price"))
    return refreshed


# =========================================================
# MARKET-DATA FRESHNESS METADATA
#
# These tags are attached only to the in-memory payload handed back to API
# callers - they are never written into the SQLite cache (store_snapshots
# always receives the untagged payload), so the cache schema/contents are
# unaffected.
# =========================================================

MARKET_DATA_SOURCE_LIVE = "live_provider"
MARKET_DATA_SOURCE_FRESH_CACHE = "fresh_cache"
MARKET_DATA_SOURCE_STALE_CACHE = "stale_cache"
STALE_REASON_PROVIDER_REFRESH_FAILED = "provider_refresh_failed"


def _with_freshness_metadata(payload, *, is_stale, market_data_source, stale_age_seconds=0, stale_reason=None):
    tagged = dict(payload)
    tagged["is_stale"] = bool(is_stale)
    tagged["stale_age_seconds"] = max(0, int(stale_age_seconds or 0))
    tagged["stale_reason"] = stale_reason
    tagged["market_data_source"] = market_data_source
    return tagged


def _cache_age_seconds(updated_at, now):
    if updated_at is None:
        return None
    return max(0, int(now) - int(updated_at))


# =========================================================
# MASSIVE FETCH (FORMERLY POLYGON)
# =========================================================

def _polygon_api_key():
    return str(settings.market_data_api_key or "").strip()


_SECRET_QUERY_PARAM_PATTERN = re.compile(
    r"(apiKey|api_key|apikey|token|X-MBX-APIKEY)=[^&\s'\"]+",
    re.IGNORECASE,
)


def _redact_secrets(value):
    """Strips API-key-like query parameter values out of a string before it
    is written to logs or stored as an error message (e.g. httpx exceptions
    stringify to include the full request URL, query string included).
    """
    if value is None:
        return value
    return _SECRET_QUERY_PARAM_PATTERN.sub(r"\1=[REDACTED]", str(value))


def _polygon_buffer_bars(candles_limit):
    normalized_limit = normalize_candles_limit(candles_limit)
    return max(
        POLYGON_LOOKBACK_BUFFER_MIN_BARS,
        int(math.ceil(normalized_limit * POLYGON_LOOKBACK_BUFFER_RATIO)),
    )


def _polygon_base_aggregate_seconds(timeframe):
    # Per Massive/Polygon's Custom Bars documentation, the "limit" query
    # parameter does not count final aggregated candles - it caps the number
    # of underlying 1-MINUTE base aggregates scanned to build the response
    # (see _polygon_minute_base_aggregates_per_bar / _polygon_required_
    # base_aggregates below). This value is the duration of ONE of those base
    # aggregates in seconds, so that `base_seconds * base_limit` in
    # _request_polygon_aggregate_page yields the real trading-time span
    # covered by `base_limit` base aggregates - the correct input to the
    # calendar-buffer expansion applied there for stock intraday requests.
    _, timespan = map_timeframe_for_polygon(timeframe)
    if timespan in {"minute", "hour"}:
        return 60
    return ONE_DAY_SECONDS


def _polygon_minute_base_aggregates_per_bar(timeframe):
    """How many 1-minute base aggregates Massive/Polygon must scan to build
    ONE final candle at this timeframe's native (multiplier + unit)
    granularity - e.g. a native "4h" bar (multiplier=4, unit=hour) is built
    from 4 * 60 = 240 one-minute base aggregates.
    """
    multiplier, timespan = map_timeframe_for_polygon(timeframe)
    multiplier = max(1, int(multiplier))

    if timespan == "minute":
        return multiplier
    if timespan == "hour":
        return multiplier * 60
    if timespan == "day":
        return multiplier * 24 * 60
    if timespan == "week":
        return multiplier * 7 * 24 * 60
    if timespan == "month":
        return multiplier * 31 * 24 * 60
    return multiplier


def _polygon_required_base_aggregates(timeframe, result_bars):
    # The Polygon/Massive "limit" query parameter is a count of 1-minute base
    # aggregates, not final candles - so requesting N final bars requires
    # N * (base aggregates per bar) as the limit, e.g. 20 native "1h" bars
    # need at least 20 * 60 = 1200 (plus the caller's own history buffer).
    target_bars = max(1, int(result_bars))
    return max(1, target_bars * _polygon_minute_base_aggregates_per_bar(timeframe))


def _extract_polygon_results(payload):
    results = payload.get("results")
    if results is not None:
        return results

    status = payload.get("status")
    if status not in {"OK", "DELAYED"}:
        detail = payload.get("error") or payload.get("message") or "unknown error"
        raise ValueError(f"{MARKET_DATA_PROVIDER} status={status} detail={detail}")
    return []


async def _polygon_wait_for_request_slot():
    global _polygon_next_request_at

    requests_per_second = max(0, int(settings.market_data_requests_per_second or 0))
    if requests_per_second <= 0:
        return

    min_interval = 1.0 / float(requests_per_second)
    async with _polygon_rate_lock:
        now = time.monotonic()
        wait_seconds = _polygon_next_request_at - now
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
            now = time.monotonic()
        _polygon_next_request_at = max(_polygon_next_request_at, now) + min_interval


async def _polygon_push_back_next_request(exc):
    global _polygon_next_request_at

    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is None or retry_after <= 0:
        return

    async with _polygon_rate_lock:
        _polygon_next_request_at = max(
            _polygon_next_request_at,
            time.monotonic() + retry_after,
        )


async def _polygon_get_json(path, params=None):
    api_key = _polygon_api_key()
    if not api_key:
        return {}

    query = dict(params or {})
    query["apiKey"] = api_key

    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        client = await _get_polygon_client()
        await _polygon_wait_for_request_slot()
        try:
            response = await client.get(path, params=query)
            response.raise_for_status()
            return response.json()
        except httpx.TransportError as exc:
            logger.warning(
                "%s request transport failure path=%s attempt=%s/%s: %s",
                MARKET_DATA_PROVIDER,
                path,
                attempt,
                DOWNLOAD_RETRIES,
                _redact_secrets(exc),
            )
            await close_polygon_client()
            if attempt == DOWNLOAD_RETRIES:
                raise
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
        except httpx.HTTPStatusError as exc:
            status_code = getattr(response, "status_code", None)
            if attempt == DOWNLOAD_RETRIES or status_code not in {429, 500, 502, 503, 504}:
                raise
            await _polygon_push_back_next_request(exc)
            await asyncio.sleep(_polygon_backoff_seconds(exc, attempt))

    return {}


async def _request_polygon_aggregate_page(symbol, timeframe, to_timestamp_ms, target_bars):
    multiplier, timespan = map_timeframe_for_polygon(timeframe)
    provider_symbol = quote(map_symbol_for_polygon(symbol), safe=":")
    base_seconds = _polygon_base_aggregate_seconds(timeframe)
    base_limit = min(
        POLYGON_MAX_BASE_AGGREGATES,
        max(
            POLYGON_MIN_BASE_AGGREGATES,
            _polygon_required_base_aggregates(
                timeframe,
                max(1, int(target_bars)) + _polygon_buffer_bars(target_bars),
            ),
        ),
    )
    window_seconds = max(base_seconds * base_limit, timeframe_seconds(timeframe))

    if timespan in {"minute", "hour"} and not is_crypto_symbol(symbol):
        window_seconds = max(
            int(math.ceil(window_seconds * POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_RATIO)),
            window_seconds + POLYGON_STOCK_INTRADAY_CALENDAR_BUFFER_MIN_SECONDS,
        )

    from_timestamp_ms = max(0, int(to_timestamp_ms - (window_seconds * 1000)))

    payload = await _polygon_get_json(
        f"/v2/aggs/ticker/{provider_symbol}/range/{multiplier}/{timespan}/{from_timestamp_ms}/{to_timestamp_ms}",
        params={
            "adjusted": "true",
            "sort": "desc",
            "limit": base_limit,
        },
    )
    return _extract_polygon_results(payload)


async def _download_polygon_rows(symbol, timeframe, candles_limit):
    normalized_limit = normalize_candles_limit(candles_limit)
    target_bars = normalized_limit + _polygon_buffer_bars(normalized_limit)
    collected = []
    seen_timestamps = set()
    next_to_ms = int(time.time() * 1000)

    for _ in range(POLYGON_MAX_PAGES):
        remaining_bars = max(1, target_bars - len(collected))
        page = await _request_polygon_aggregate_page(
            symbol,
            timeframe,
            next_to_ms,
            remaining_bars,
        )
        if not page:
            break

        oldest_timestamp_ms = None
        page_added = 0
        for row in page:
            timestamp_ms = row.get("t")
            if timestamp_ms is None or timestamp_ms in seen_timestamps:
                continue
            seen_timestamps.add(timestamp_ms)
            collected.append(row)
            page_added += 1
            if oldest_timestamp_ms is None or int(timestamp_ms) < oldest_timestamp_ms:
                oldest_timestamp_ms = int(timestamp_ms)

        if len(collected) >= target_bars:
            break

        if page_added == 0 or oldest_timestamp_ms is None or oldest_timestamp_ms <= 0:
            break

        next_to_ms = oldest_timestamp_ms - 1

    collected.sort(key=lambda row: int(row.get("t") or 0))
    return collected


def _extract_retry_after_seconds(exc):
    response = getattr(exc, "response", None)
    if response is None:
        return None

    header = response.headers.get("Retry-After")
    if not header:
        return None

    try:
        return max(0.0, float(header))
    except (TypeError, ValueError):
        return None


def _polygon_backoff_seconds(exc, attempt):
    base = RETRY_BACKOFF_SECONDS * attempt
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 429:
        base = max(base, 15.0 * attempt)
    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is None:
        return base
    return max(base, retry_after)


async def request_polygon_candles(symbol, timeframe, candles_limit=MAX_CANDLES):
    global _polygon_key_warning_emitted

    if not integration_runtime.is_enabled(MARKET_DATA_PROVIDER):
        return None

    if not _polygon_api_key():
        if not _polygon_key_warning_emitted:
            logger.warning(
                "CANDLES_PROVIDER=%s but MASSIVE_API_KEY/POLYGON_API_KEY is missing.",
                MARKET_DATA_PROVIDER,
            )
            _polygon_key_warning_emitted = True
        return None

    normalized_limit = normalize_candles_limit(candles_limit)
    session_policy = expected_session_policy_for_symbol(symbol, timeframe)
    download_limit = _polygon_download_limit(normalized_limit, symbol, timeframe, session_policy)
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        started = time.perf_counter()
        try:
            rows = await _download_polygon_rows(symbol, timeframe, download_limit)
            candles = normalize_polygon_rows(rows)
            candles = _finalize_intraday_candles(
                candles,
                symbol,
                timeframe,
                normalized_limit,
                session_policy=session_policy,
            )

            if not candles:
                return None

            if len(candles) < normalized_limit:
                logger.info(
                    "%s returned fewer candles than requested symbol=%s timeframe=%s "
                    "requested=%s returned=%s",
                    MARKET_DATA_PROVIDER,
                    symbol,
                    timeframe,
                    normalized_limit,
                    len(candles),
                )

            integration_runtime.record_call(MARKET_DATA_PROVIDER)
            elapsed = time.perf_counter() - started
            integration_runtime.record_response_time(MARKET_DATA_PROVIDER, elapsed * 1000)
            if elapsed >= SLOW_FETCH_WARNING_SECONDS:
                logger.warning(
                    "slow %s request symbol=%s timeframe=%s candles=%s elapsed=%.2fs",
                    MARKET_DATA_PROVIDER,
                    symbol,
                    timeframe,
                    len(candles),
                    elapsed,
                )
            return _build_market_data_payload(
                symbol,
                candles,
                timeframe,
                candles_provider=MARKET_DATA_PROVIDER,
                session_policy=session_policy,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            safe_exc = _redact_secrets(exc)
            logger.warning(
                "%s candle request failed for %s timeframe=%s attempt=%s/%s status=%s candles_limit=%s: %s",
                MARKET_DATA_PROVIDER,
                symbol,
                timeframe,
                attempt,
                DOWNLOAD_RETRIES,
                status_code,
                normalized_limit,
                safe_exc,
            )

            if attempt == DOWNLOAD_RETRIES:
                integration_runtime.record_error(
                    MARKET_DATA_PROVIDER,
                    f"{symbol} {timeframe}: status={status_code} {safe_exc}",
                )
                return None

            await asyncio.sleep(_polygon_backoff_seconds(exc, attempt))

    return None


async def request_massive_candles(symbol, timeframe, candles_limit=MAX_CANDLES):
    if _timeframe_uses_grouped_daily_history(timeframe):
        grouped_items = await request_massive_grouped_daily_candles(
            [symbol],
            timeframe,
            candles_limit,
        )
        if not grouped_items:
            return None
        return grouped_items[0]
    return await request_polygon_candles(symbol, timeframe, candles_limit=candles_limit)


async def _binance_wait_for_request_slot(weight=1):
    global _binance_next_request_at

    requests_per_second = max(0, int(settings.BINANCE_REQUESTS_PER_SECOND or 0))
    if requests_per_second <= 0:
        return

    normalized_weight = max(1, int(weight))
    min_interval = float(normalized_weight) / float(requests_per_second)
    async with _binance_rate_lock:
        now = time.monotonic()
        wait_seconds = _binance_next_request_at - now
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
            now = time.monotonic()
        _binance_next_request_at = max(_binance_next_request_at, now) + min_interval


async def _binance_push_back_next_request(exc):
    global _binance_next_request_at

    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is None or retry_after <= 0:
        return

    async with _binance_rate_lock:
        _binance_next_request_at = max(
            _binance_next_request_at,
            time.monotonic() + retry_after,
        )


def _binance_backoff_seconds(exc, attempt):
    base = RETRY_BACKOFF_SECONDS * attempt
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {418, 429}:
        base = max(base, 5.0 * attempt)
    retry_after = _extract_retry_after_seconds(exc)
    if retry_after is None:
        return base
    return max(base, retry_after)


async def _binance_get_json(path, params=None, weight=1):
    client = await _get_binance_client()

    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        await _binance_wait_for_request_slot(weight=weight)
        response = await client.get(path, params=dict(params or {}))
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status_code = getattr(response, "status_code", None)
            if attempt == DOWNLOAD_RETRIES or status_code not in {418, 429, 500, 502, 503, 504}:
                raise
            await _binance_push_back_next_request(exc)
            await asyncio.sleep(_binance_backoff_seconds(exc, attempt))

    return {}


def _build_binance_pairs_index(payload):
    pairs_by_base = {}
    for row in payload.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "TRADING":
            continue
        if row.get("isSpotTradingAllowed") is False:
            continue
        base = str(row.get("baseAsset") or "").strip().upper()
        quote = str(row.get("quoteAsset") or "").strip().upper()
        pair = str(row.get("symbol") or "").strip().upper()
        if not base or not quote or not pair:
            continue

        bucket = pairs_by_base.setdefault(base, [])
        bucket.append((quote, pair))

    return pairs_by_base


async def _invalidate_binance_pairs_cache():
    async with _binance_exchange_info_lock:
        _binance_exchange_info_cache["loaded_at"] = 0


async def _get_binance_pairs_index(force_refresh=False):
    now = int(time.time())

    async with _binance_exchange_info_lock:
        loaded_at = int(_binance_exchange_info_cache.get("loaded_at") or 0)
        pairs_by_base = _binance_exchange_info_cache.get("pairs_by_base") or {}
        if (
            not force_refresh
            and pairs_by_base
            and (now - loaded_at) < BINANCE_EXCHANGE_INFO_TTL_SECONDS
        ):
            return pairs_by_base

        cached_pairs = pairs_by_base
        try:
            payload = await _binance_get_json(
                "/api/v3/exchangeInfo",
                weight=BINANCE_EXCHANGE_INFO_REQUEST_WEIGHT,
            )
            pairs_by_base = _build_binance_pairs_index(payload)
            _binance_exchange_info_cache["loaded_at"] = now
            _binance_exchange_info_cache["pairs_by_base"] = pairs_by_base
            return pairs_by_base
        except Exception as exc:
            logger.warning("Failed to load Binance exchangeInfo: %s", _redact_secrets(exc))
            return cached_pairs


def _log_missing_binance_pair_once(symbol, base):
    cache_key = f"{str(symbol).strip().upper()}::{str(base).strip().upper()}"
    if cache_key in _binance_pair_not_found_logged:
        return
    _binance_pair_not_found_logged.add(cache_key)
    logger.info(
        "No Binance spot pair found for %s (base=%s); skipping symbol",
        symbol,
        base,
    )


def _select_binance_pair_from_index(symbol, pairs_by_base):
    base = _binance_base_asset(symbol)
    candidates = (pairs_by_base or {}).get(base) or []
    if not pairs_by_base:
        return map_symbol_for_binance(symbol)
    if not candidates:
        _log_missing_binance_pair_once(symbol, base)
        return None

    by_quote = {}
    for quote, pair in candidates:
        if quote not in by_quote:
            by_quote[quote] = pair

    for quote in BINANCE_QUOTE_PREFERENCE:
        pair = by_quote.get(quote)
        if pair:
            return pair

    return candidates[0][1]


async def _resolve_binance_pair(symbol, force_refresh=False):
    pairs_by_base = await _get_binance_pairs_index(force_refresh=force_refresh)
    return _select_binance_pair_from_index(symbol, pairs_by_base)


def _quote_candle(price, now=None):
    candle_time = int(time.time()) if now is None else int(now)
    price_value = float(price)
    return {
        "time": candle_time,
        "open": price_value,
        "high": price_value,
        "low": price_value,
        "close": price_value,
        "volume": 0.0,
    }


async def request_binance_quotes(symbols, timeframe):
    if not symbols:
        return []

    if not integration_runtime.is_enabled(BINANCE_PROVIDER):
        return []

    crypto_symbols = [symbol for symbol in symbols if is_crypto_symbol(symbol)]
    if not crypto_symbols:
        return []

    try:
        payload = await _binance_get_json(
            "/api/v3/ticker/price",
            weight=BINANCE_QUOTES_REQUEST_WEIGHT,
        )
    except Exception as exc:
        logger.warning("binance quote request failed symbols=%s: %s", len(crypto_symbols), _redact_secrets(exc))
        return []

    if not isinstance(payload, list):
        return []

    price_map = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        pair = str(row.get("symbol") or "").strip().upper()
        price = _coerce_number(row.get("price"))
        if not pair or price is None:
            continue
        price_map[pair] = float(price)

    if not price_map:
        return []

    pairs_by_base = await _get_binance_pairs_index()
    integration_runtime.record_call(BINANCE_PROVIDER)
    now = int(time.time())
    results = []
    for symbol in crypto_symbols:
        pair = _select_binance_pair_from_index(symbol, pairs_by_base)
        if not pair:
            continue
        price = price_map.get(pair)
        if price is None:
            continue
        results.append(
            _build_market_data_payload(
                symbol,
                [_quote_candle(price, now=now)],
                timeframe,
                candles_provider=BINANCE_PROVIDER,
            )
        )

    return results


async def request_binance_candles(symbol, timeframe, candles_limit=MAX_CANDLES):
    if not integration_runtime.is_enabled(BINANCE_PROVIDER):
        return None

    if not is_crypto_symbol(symbol):
        return None

    interval = map_timeframe_for_binance(timeframe)
    if not interval:
        logger.warning(
            "Unsupported Binance timeframe=%s; supported intervals are 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1mo.",
            timeframe,
        )
        return None

    normalized_limit = normalize_candles_limit(candles_limit)
    limit = max(1, min(BINANCE_MAX_LIMIT, normalized_limit))

    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        started = time.perf_counter()
        provider_symbol = await _resolve_binance_pair(symbol, force_refresh=attempt > 1)
        if not provider_symbol:
            return None

        try:
            payload = await _binance_get_json(
                "/api/v3/klines",
                params={
                    "symbol": provider_symbol,
                    "interval": interval,
                    "limit": limit,
                },
                weight=BINANCE_KLINES_REQUEST_WEIGHT,
            )
            if not isinstance(payload, list):
                return None

            candles = normalize_binance_rows(payload)
            # Binance already returns candles at the requested interval, so
            # re-aggregating here would distort native 4h/1w/etc. klines.
            candles = slice_recent(candles, limit=normalized_limit)
            if not candles:
                return None

            integration_runtime.record_call(BINANCE_PROVIDER)
            elapsed = time.perf_counter() - started
            integration_runtime.record_response_time(BINANCE_PROVIDER, elapsed * 1000)
            if elapsed >= SLOW_FETCH_WARNING_SECONDS:
                logger.warning(
                    "slow %s request symbol=%s timeframe=%s candles=%s elapsed=%.2fs",
                    BINANCE_PROVIDER,
                    symbol,
                    timeframe,
                    len(candles),
                    elapsed,
                )
            return _build_market_data_payload(
                symbol,
                candles,
                timeframe,
                candles_provider=BINANCE_PROVIDER,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            safe_exc = _redact_secrets(exc)
            if status_code == 400:
                await _invalidate_binance_pairs_cache()
            logger.warning(
                "%s candle request failed for %s timeframe=%s attempt=%s/%s status=%s candles_limit=%s: %s",
                BINANCE_PROVIDER,
                symbol,
                timeframe,
                attempt,
                DOWNLOAD_RETRIES,
                status_code,
                normalized_limit,
                safe_exc,
            )

            if attempt == DOWNLOAD_RETRIES:
                integration_runtime.record_error(
                    BINANCE_PROVIDER,
                    f"{symbol} {timeframe}: status={status_code} {safe_exc}",
                )
                return None

            if status_code in {400, 418, 429, 500, 502, 503, 504}:
                await asyncio.sleep(_binance_backoff_seconds(exc, attempt))
                continue

            integration_runtime.record_error(
                BINANCE_PROVIDER,
                f"{symbol} {timeframe}: status={status_code} {safe_exc}",
            )
            return None

    return None


def _polygon_snapshot_endpoint(symbols):
    if not symbols:
        return None
    if all(is_crypto_symbol(symbol) for symbol in symbols):
        return "/v2/snapshot/locale/global/markets/crypto/tickers"
    if all(not is_crypto_symbol(symbol) for symbol in symbols):
        return "/v2/snapshot/locale/us/markets/stocks/tickers"
    return None


def _chunked(values, chunk_size):
    size = max(1, int(chunk_size))
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _polygon_snapshot_params(symbols, tickers):
    params = {"tickers": tickers}
    if symbols and all(not is_crypto_symbol(symbol) for symbol in symbols):
        params["include_otc"] = "true"
    return params


def _build_polygon_snapshot_results(payload, requested_map, timeframe):
    items = payload.get("tickers") or payload.get("results") or []
    results = []

    for item in items:
        provider_symbol = str(item.get("ticker") or "").strip().upper()
        symbol = requested_map.get(provider_symbol)
        if not symbol:
            continue
        candle = _snapshot_candle_from_polygon_item(item)
        if not candle:
            continue
        session_policy = expected_session_policy_for_symbol(symbol, timeframe)
        candles = _finalize_intraday_candles([candle], symbol, timeframe, 1, session_policy=session_policy)
        if not candles:
            continue
        results.append(
            _build_market_data_payload(
                symbol,
                candles,
                timeframe,
                candles_provider=MARKET_DATA_PROVIDER,
                session_policy=session_policy,
            )
        )

    return results


def _can_use_full_market_snapshot(symbols):
    if not symbols:
        return False

    if all(is_crypto_symbol(symbol) for symbol in symbols):
        return len(symbols) >= POLYGON_FULL_MARKET_SNAPSHOT_CRYPTO_MIN_SYMBOLS
    if all(not is_crypto_symbol(symbol) for symbol in symbols):
        return len(symbols) >= POLYGON_FULL_MARKET_SNAPSHOT_STOCK_MIN_SYMBOLS
    return False


def _snapshot_candle_from_polygon_item(item):
    if not isinstance(item, dict):
        return None

    for key in ("min", "day", "prevDay"):
        bar = item.get(key)
        if not isinstance(bar, dict):
            continue
        timestamp_ms = bar.get("t")
        if timestamp_ms is None:
            continue
        candles = normalize_polygon_rows([bar])
        if candles:
            return candles[-1]

    return None


def _grouped_daily_candle_from_polygon_row(row):
    candles = normalize_polygon_rows(
        [
            {
                "t": row.get("t"),
                "o": row.get("o"),
                "h": row.get("h"),
                "l": row.get("l"),
                "c": row.get("c"),
                "v": row.get("v"),
            }
        ]
    )
    if candles:
        return candles[-1]
    return None


def _grouped_daily_candidate_dates(candles_limit, reference_date=None):
    normalized_limit = normalize_candles_limit(candles_limit)
    return _grouped_daily_candidate_dates_with_calendar(
        normalized_limit,
        reference_date=reference_date,
        skip_weekends=True,
        padding_days=max(
            POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_DAYS,
            int(math.ceil(normalized_limit * POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_RATIO)),
        ),
    )


def _grouped_daily_candidate_dates_with_calendar(
    candles_limit,
    reference_date=None,
    skip_weekends=True,
    padding_days=None,
    max_source_days=POLYGON_GROUPED_DAILY_MAX_TRADING_DAYS,
):
    normalized_limit = normalize_candles_limit(candles_limit)
    current_date = reference_date or datetime.now(timezone.utc).date()
    effective_padding_days = (
        POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_DAYS
        if padding_days is None
        else max(0, int(padding_days))
    )
    target_trading_days = min(
        max(1, int(max_source_days)),
        normalized_limit + effective_padding_days,
    )

    dates = []
    offset = 0
    while len(dates) < target_trading_days:
        candidate = current_date - timedelta(days=offset)
        offset += 1
        if skip_weekends and candidate.weekday() >= 5:
            continue
        dates.append(candidate.isoformat())
    return dates


def _grouped_daily_crypto_candidate_dates(candles_limit, reference_date=None):
    crypto_reference_date = reference_date or datetime.now(timezone.utc).date()
    if settings.MASSIVE_CRYPTO_END_OF_DAY_ONLY:
        crypto_reference_date = crypto_reference_date - timedelta(days=1)
    return _grouped_daily_candidate_dates_with_calendar(
        candles_limit,
        reference_date=crypto_reference_date,
        skip_weekends=False,
        padding_days=POLYGON_GROUPED_DAILY_CRYPTO_LOOKBACK_PADDING_DAYS,
    )


def _timeframe_uses_grouped_daily_history(timeframe):
    parsed = parse_timeframe_spec(timeframe)
    if not parsed:
        return False

    _, unit = parsed
    return unit in {"d", "w", "mo"}


def _is_native_grouped_daily_timeframe(timeframe):
    parsed = parse_timeframe_spec(timeframe)
    return parsed == (1, "d")


def _grouped_history_source_candles_limit(timeframe, candles_limit, is_crypto=False):
    normalized_limit = normalize_candles_limit(candles_limit)
    parsed = parse_timeframe_spec(timeframe)
    if not parsed:
        return normalized_limit

    amount, unit = parsed
    if unit == "d":
        factor = amount
    elif unit == "w":
        factor = amount * (7 if is_crypto else 5)
    elif unit == "mo":
        factor = amount * (30 if is_crypto else 21)
    else:
        factor = 1

    return max(normalized_limit, normalized_limit * max(1, factor))


def _grouped_history_candidate_dates(timeframe, candles_limit, is_crypto=False, reference_date=None):
    source_candles_limit = _grouped_history_source_candles_limit(
        timeframe,
        candles_limit,
        is_crypto=is_crypto,
    )
    normalized_limit = normalize_candles_limit(candles_limit)
    padding_days = max(
        POLYGON_GROUPED_DAILY_CRYPTO_LOOKBACK_PADDING_DAYS
        if is_crypto
        else POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_DAYS,
        int(math.ceil(normalized_limit * POLYGON_GROUPED_DAILY_LOOKBACK_PADDING_RATIO)),
    )
    return _grouped_daily_candidate_dates_with_calendar(
        source_candles_limit,
        reference_date=reference_date,
        skip_weekends=not is_crypto,
        padding_days=padding_days,
        max_source_days=POLYGON_GROUPED_HISTORY_MAX_SOURCE_DAYS,
    )


def _grouped_history_bucket_key(timestamp_seconds, timeframe):
    parsed = parse_timeframe_spec(timeframe)
    if not parsed:
        return None

    amount, unit = parsed
    candle_date = datetime.fromtimestamp(int(timestamp_seconds), tz=timezone.utc).date()

    if unit == "d":
        return unit, candle_date.toordinal() // max(1, amount)
    if unit == "w":
        week_start = candle_date - timedelta(days=candle_date.weekday())
        return unit, week_start.toordinal() // max(1, amount * 7)
    if unit == "mo":
        month_index = (candle_date.year * 12) + (candle_date.month - 1)
        return unit, month_index // max(1, amount)

    return None


def _merge_grouped_history_bucket(bucket, candle):
    bucket["time"] = candle["time"]
    bucket["open"] = candle["open"]
    bucket["high"] = max(bucket["high"], candle["high"])
    bucket["low"] = min(bucket["low"], candle["low"])
    bucket["volume"] += candle["volume"]


async def _request_polygon_grouped_history_series(
    symbols,
    timeframe,
    candles_limit,
    fetcher,
    candidate_dates,
    is_crypto=False,
):
    if not symbols:
        return []

    requested_map = {
        map_symbol_for_polygon(symbol): symbol
        for symbol in symbols
        if symbol
    }
    if not requested_map:
        return []

    normalized_limit = normalize_candles_limit(candles_limit)
    aggregated_by_symbol = {symbol: [] for symbol in requested_map.values()}
    active_bucket_by_symbol = {}
    active_key_by_symbol = {}
    resolved_symbols = set()
    request_count = 0
    date_concurrency = _grouped_daily_date_concurrency(is_crypto=is_crypto)
    inter_chunk_delay_seconds = (
        _grouped_daily_crypto_request_interval_seconds()
        if is_crypto
        else 0.0
    )
    first_chunk = True

    for date_chunk in _chunked(candidate_dates, date_concurrency):
        if not first_chunk and inter_chunk_delay_seconds > 0:
            await asyncio.sleep(inter_chunk_delay_seconds)
        first_chunk = False
        chunk_results = await _request_polygon_grouped_daily_chunk_with_fetcher(date_chunk, fetcher)
        for date_value, rows in chunk_results:
            if isinstance(rows, Exception):
                logger.warning(
                    "%s grouped history request failed timeframe=%s date=%s symbols=%s candles_limit=%s: %s",
                    MARKET_DATA_PROVIDER,
                    timeframe,
                    date_value,
                    len(symbols),
                    normalized_limit,
                    rows,
                )
                continue

            request_count += 1
            for row in rows or []:
                provider_symbol = str(row.get("T") or "").strip().upper()
                symbol = requested_map.get(provider_symbol)
                if not symbol or symbol in resolved_symbols:
                    continue
                candle = _grouped_daily_candle_from_polygon_row(row)
                if not candle:
                    continue
                bucket_key = _grouped_history_bucket_key(candle["time"], timeframe)
                if bucket_key is None:
                    continue

                active_key = active_key_by_symbol.get(symbol)
                if active_key is None:
                    active_key_by_symbol[symbol] = bucket_key
                    active_bucket_by_symbol[symbol] = dict(candle)
                    continue

                if active_key != bucket_key:
                    aggregated_by_symbol[symbol].append(active_bucket_by_symbol[symbol])
                    if len(aggregated_by_symbol[symbol]) >= normalized_limit:
                        resolved_symbols.add(symbol)
                        active_key_by_symbol.pop(symbol, None)
                        active_bucket_by_symbol.pop(symbol, None)
                        continue
                    active_key_by_symbol[symbol] = bucket_key
                    active_bucket_by_symbol[symbol] = dict(candle)
                    continue

                _merge_grouped_history_bucket(active_bucket_by_symbol[symbol], candle)

        if len(resolved_symbols) == len(aggregated_by_symbol):
            break

    for symbol, bucket in active_bucket_by_symbol.items():
        if symbol in resolved_symbols:
            continue
        aggregated_by_symbol[symbol].append(bucket)

    if request_count:
        integration_runtime.record_call(MARKET_DATA_PROVIDER, amount=request_count)

    results = []
    for symbol in symbols:
        candles = aggregated_by_symbol.get(symbol) or []
        if not candles:
            continue
        recent_desc = candles[:normalized_limit]
        ordered = list(reversed(recent_desc))
        results.append(
            _build_market_data_payload(
                symbol,
                ordered,
                timeframe,
                candles_provider=MARKET_DATA_PROVIDER,
            )
        )

    return results


def _has_explicit_market_data_request_rate_limit():
    return settings.market_data_requests_per_second > 0


def _grouped_daily_crypto_request_interval_seconds():
    requests_per_minute = max(0, int(settings.market_data_crypto_requests_per_minute or 0))
    if requests_per_minute > 0:
        return 60.0 / float(requests_per_minute)
    if not settings.MASSIVE_CRYPTO_END_OF_DAY_ONLY:
        return 0.0
    return POLYGON_GROUPED_DAILY_CRYPTO_DEFAULT_REQUEST_INTERVAL_SECONDS


def _grouped_daily_date_concurrency(is_crypto=False):
    if is_crypto:
        if settings.MASSIVE_CRYPTO_END_OF_DAY_ONLY:
            return 1
    configured = max(1, int(settings.market_data_fetch_concurrency or 1))
    return max(1, min(POLYGON_GROUPED_DAILY_DATE_CONCURRENCY, configured))


async def _request_polygon_grouped_daily(date_value):
    payload = await _polygon_get_json(
        f"/v2/aggs/grouped/locale/us/market/stocks/{date_value}",
        params={
            "adjusted": "true",
            "include_otc": "true",
        },
    )
    return _extract_polygon_results(payload)


async def _request_polygon_grouped_daily_crypto(date_value):
    payload = await _polygon_get_json(
        f"/v2/aggs/grouped/locale/global/market/crypto/{date_value}",
        params={
            "adjusted": "true",
        },
    )
    return _extract_polygon_results(payload)


def _grouped_daily_unresolved_symbols(candles_by_symbol, candles_limit):
    normalized_limit = normalize_candles_limit(candles_limit)
    return [
        symbol
        for symbol, candles in candles_by_symbol.items()
        if len(candles) < normalized_limit
    ]


async def _request_polygon_grouped_daily_chunk(date_chunk):
    results = await asyncio.gather(
        *(_request_polygon_grouped_daily(date_value) for date_value in date_chunk),
        return_exceptions=True,
    )
    return list(zip(date_chunk, results))


async def _request_polygon_grouped_daily_chunk_with_fetcher(date_chunk, fetcher):
    results = await asyncio.gather(
        *(fetcher(date_value) for date_value in date_chunk),
        return_exceptions=True,
    )
    return list(zip(date_chunk, results))


async def _request_polygon_grouped_daily_series(
    symbols,
    candles_limit,
    fetcher,
    candidate_dates,
    is_crypto=False,
):
    if not symbols:
        return []

    requested_map = {
        map_symbol_for_polygon(symbol): symbol
        for symbol in symbols
        if symbol
    }
    if not requested_map:
        return []

    normalized_limit = normalize_candles_limit(candles_limit)
    candles_by_symbol = {symbol: [] for symbol in requested_map.values()}
    request_count = 0
    date_concurrency = _grouped_daily_date_concurrency(is_crypto=is_crypto)
    inter_chunk_delay_seconds = (
        _grouped_daily_crypto_request_interval_seconds()
        if is_crypto
        else 0.0
    )
    first_chunk = True

    for date_chunk in _chunked(candidate_dates, date_concurrency):
        if not first_chunk and inter_chunk_delay_seconds > 0:
            await asyncio.sleep(inter_chunk_delay_seconds)
        first_chunk = False
        chunk_results = await _request_polygon_grouped_daily_chunk_with_fetcher(date_chunk, fetcher)
        for date_value, rows in chunk_results:
            if isinstance(rows, Exception):
                logger.warning(
                    "%s grouped daily request failed date=%s symbols=%s candles_limit=%s: %s",
                    MARKET_DATA_PROVIDER,
                    date_value,
                    len(symbols),
                    normalized_limit,
                    rows,
                )
                continue

            request_count += 1
            for row in rows or []:
                provider_symbol = str(row.get("T") or "").strip().upper()
                symbol = requested_map.get(provider_symbol)
                if not symbol:
                    continue
                candle = _grouped_daily_candle_from_polygon_row(row)
                if candle:
                    candles_by_symbol[symbol].append(candle)

        if not _grouped_daily_unresolved_symbols(candles_by_symbol, normalized_limit):
            break

    if request_count:
        integration_runtime.record_call(MARKET_DATA_PROVIDER, amount=request_count)

    results = []
    for symbol in symbols:
        candles = candles_by_symbol.get(symbol) or []
        if not candles:
            continue
        ordered = sorted(candles, key=lambda candle: int(candle.get("time") or 0))
        results.append(
            _build_market_data_payload(
                symbol,
                slice_recent(ordered, limit=normalized_limit),
                "1day",
                candles_provider=MARKET_DATA_PROVIDER,
            )
        )

    return results


async def request_polygon_grouped_daily_candles(symbols, timeframe, candles_limit):
    if not symbols or not _timeframe_uses_grouped_daily_history(timeframe):
        return []

    if not integration_runtime.is_enabled(MARKET_DATA_PROVIDER) or not _polygon_api_key():
        return []

    normalized_limit = normalize_candles_limit(candles_limit)
    stock_symbols = [symbol for symbol in symbols if symbol and not is_crypto_symbol(symbol)]
    crypto_symbols = [symbol for symbol in symbols if symbol and is_crypto_symbol(symbol)]
    results_by_symbol = {}

    if stock_symbols:
        if _is_native_grouped_daily_timeframe(timeframe):
            candidate_dates = _grouped_daily_candidate_dates(normalized_limit)
            stock_items = await _request_polygon_grouped_daily_series(
                stock_symbols,
                normalized_limit,
                _request_polygon_grouped_daily,
                candidate_dates,
            )
        else:
            candidate_dates = _grouped_history_candidate_dates(timeframe, normalized_limit)
            stock_items = await _request_polygon_grouped_history_series(
                stock_symbols,
                timeframe,
                normalized_limit,
                _request_polygon_grouped_daily,
                candidate_dates,
            )
        for item in stock_items:
            symbol = item.get("symbol")
            if symbol:
                results_by_symbol[symbol] = item

    if crypto_symbols:
        if _is_native_grouped_daily_timeframe(timeframe):
            candidate_dates = _grouped_daily_crypto_candidate_dates(normalized_limit)
            crypto_items = await _request_polygon_grouped_daily_series(
                crypto_symbols,
                normalized_limit,
                _request_polygon_grouped_daily_crypto,
                candidate_dates,
                is_crypto=True,
            )
        else:
            candidate_dates = _grouped_history_candidate_dates(
                timeframe,
                normalized_limit,
                is_crypto=True,
            )
            crypto_items = await _request_polygon_grouped_history_series(
                crypto_symbols,
                timeframe,
                normalized_limit,
                _request_polygon_grouped_daily_crypto,
                candidate_dates,
                is_crypto=True,
            )
        for item in crypto_items:
            symbol = item.get("symbol")
            if symbol:
                results_by_symbol[symbol] = item

    return [results_by_symbol[symbol] for symbol in symbols if symbol in results_by_symbol]


async def _request_polygon_snapshot_chunk(symbols, timeframe):
    endpoint = _polygon_snapshot_endpoint(symbols)
    if not endpoint:
        return []

    requested_map = {
        map_symbol_for_polygon(symbol): symbol
        for symbol in symbols
    }
    payload = await _polygon_get_json(
        endpoint,
        params=_polygon_snapshot_params(symbols, ",".join(requested_map.keys())),
    )
    return _build_polygon_snapshot_results(payload, requested_map, timeframe)


async def _request_polygon_full_market_snapshot(symbols, timeframe):
    endpoint = _polygon_snapshot_endpoint(symbols)
    if not endpoint:
        return []

    requested_map = {
        map_symbol_for_polygon(symbol): symbol
        for symbol in symbols
    }
    payload = await _polygon_get_json(
        endpoint,
        params=_polygon_snapshot_params(symbols, ""),
    )
    return _build_polygon_snapshot_results(payload, requested_map, timeframe)


async def request_polygon_snapshots(symbols, timeframe):
    if not symbols:
        return []

    if not integration_runtime.is_enabled(MARKET_DATA_PROVIDER) or not _polygon_api_key():
        return []

    symbol_groups = []
    stock_symbols = [symbol for symbol in symbols if not is_crypto_symbol(symbol)]
    crypto_symbols = [symbol for symbol in symbols if is_crypto_symbol(symbol)]
    if stock_symbols:
        symbol_groups.append(stock_symbols)
    if crypto_symbols:
        symbol_groups.append(crypto_symbols)
    if not symbol_groups:
        return []

    chunks = []
    for group in symbol_groups:
        if _can_use_full_market_snapshot(group):
            chunks.append((group, True))
            continue
        chunks.extend((chunk, False) for chunk in _chunked(group, POLYGON_FAST_PATH_CHUNK_SIZE))
    semaphore = asyncio.Semaphore(max(1, int(settings.market_data_fetch_concurrency or 1)))

    async def _run_chunk(chunk, use_full_market=False):
        async with semaphore:
            if use_full_market:
                return await _request_polygon_full_market_snapshot(chunk, timeframe)
            return await _request_polygon_snapshot_chunk(chunk, timeframe)

    chunk_results = await asyncio.gather(
        *(_run_chunk(chunk, use_full_market=use_full_market) for chunk, use_full_market in chunks),
        return_exceptions=True,
    )
    merged = []
    request_count = 0
    for result in chunk_results:
        if isinstance(result, Exception):
            logger.warning("%s snapshot request failed symbols=%s: %s", MARKET_DATA_PROVIDER, len(symbols), result)
            continue
        request_count += 1
        merged.extend(result)

    if request_count:
        integration_runtime.record_call(MARKET_DATA_PROVIDER, amount=request_count)

    return merged


async def request_massive_snapshots(symbols, timeframe):
    return await request_polygon_snapshots(symbols, timeframe)


async def request_massive_grouped_daily_candles(symbols, timeframe, candles_limit):
    return await request_polygon_grouped_daily_candles(symbols, timeframe, candles_limit)


def _polygon_fundamentals_cache_get(symbol):
    cached = FUNDAMENTALS_CACHE.get(symbol)
    if not isinstance(cached, dict):
        return None

    loaded_at = int(cached.get("loaded_at") or 0)
    if loaded_at and (int(time.time()) - loaded_at) < POLYGON_FUNDAMENTALS_TTL_SECONDS:
        return dict(cached.get("value") or {})

    return None


def _polygon_fundamentals_cache_set(symbol, value):
    FUNDAMENTALS_CACHE[symbol] = {
        "loaded_at": int(time.time()),
        "value": dict(value or {}),
    }


async def _request_polygon_fundamentals(symbol):
    cached = _polygon_fundamentals_cache_get(symbol)
    if cached is not None:
        return cached

    payload = await _polygon_get_json(
        f"/v3/reference/tickers/{quote(str(symbol).strip().upper(), safe='')}",
        params={},
    )
    details = payload.get("results") or {}
    shares_outstanding = _coerce_number(
        details.get("weighted_shares_outstanding")
        or details.get("share_class_shares_outstanding")
    )
    fundamentals = {
        "shares_outstanding": float(shares_outstanding) if shares_outstanding is not None else None,
        "float_shares": None,
    }
    _polygon_fundamentals_cache_set(symbol, fundamentals)
    integration_runtime.record_call(MARKET_DATA_PROVIDER)
    return fundamentals


async def attach_polygon_fundamentals(items):
    if not items:
        return

    stock_symbols = [
        item["symbol"]
        for item in items
        if item.get("symbol") and not is_crypto_symbol(item["symbol"])
    ]
    if not stock_symbols:
        return

    unique_symbols = list(dict.fromkeys(stock_symbols))
    semaphore = asyncio.Semaphore(max(1, int(settings.market_data_fetch_concurrency or 1)))
    details_by_symbol = {}

    async def _load(symbol):
        async with semaphore:
            try:
                details_by_symbol[symbol] = await _request_polygon_fundamentals(symbol)
            except Exception as exc:
                logger.warning(
                    "%s fundamentals request failed for %s: %s",
                    MARKET_DATA_PROVIDER,
                    symbol,
                    _redact_secrets(exc),
                )

    await asyncio.gather(*(_load(symbol) for symbol in unique_symbols))

    for item in items:
        symbol = item.get("symbol")
        details = details_by_symbol.get(symbol)
        if not details:
            continue
        item["shares_outstanding"] = details.get("shares_outstanding")
        item["float_shares"] = details.get("float_shares")


async def attach_massive_fundamentals(items):
    await attach_polygon_fundamentals(items)


def resolve_candle_fetcher(provider=None):
    provider_name = normalize_market_data_provider_name(provider or active_candle_provider())
    if provider_name != MARKET_DATA_PROVIDER:
        return request_massive_candles
    return request_massive_candles


def resolve_crypto_candle_fetcher(provider=None):
    provider_name = normalize_market_data_provider_name(provider or active_crypto_candle_provider())
    if provider_name == BINANCE_PROVIDER:
        return request_binance_candles
    return request_massive_candles


def resolve_candle_fetcher_for_symbol(symbol):
    if is_crypto_symbol(symbol):
        return resolve_crypto_candle_fetcher()
    return resolve_candle_fetcher()


def provider_name_for_symbol(symbol):
    if is_crypto_symbol(symbol):
        return active_crypto_candle_provider()
    return active_candle_provider()


def default_concurrency_for_symbol(symbol):
    return default_concurrency_for_provider(provider_name_for_symbol(symbol))


def _fetch_provider_label(symbols):
    if not symbols:
        return active_candle_provider()

    labels = {provider_name_for_symbol(symbol) for symbol in symbols}
    if len(labels) == 1:
        return next(iter(labels))
    return "mixed:" + ",".join(sorted(labels))


def _is_all_symbols_using_fetcher(symbols, fetcher):
    return bool(symbols) and all(resolve_candle_fetcher_for_symbol(symbol) is fetcher for symbol in symbols)


def _default_concurrency_for_symbols(symbols):
    if not symbols:
        return 1
    labels = {provider_name_for_symbol(symbol) for symbol in symbols}
    if len(labels) == 1:
        return default_concurrency_for_provider(next(iter(labels)))
    return max(default_concurrency_for_symbol(symbol) for symbol in symbols)


def _can_use_grouped_daily_bulk_path(symbols, timeframe, candles_limit):
    normalized_limit = normalize_candles_limit(candles_limit)
    providers = {provider_name_for_symbol(symbol) for symbol in symbols}
    if providers != {MARKET_DATA_PROVIDER}:
        return False
    all_stocks = bool(symbols) and all(not is_crypto_symbol(symbol) for symbol in symbols)
    all_crypto = bool(symbols) and all(is_crypto_symbol(symbol) for symbol in symbols)
    min_symbols = POLYGON_GROUPED_DAILY_MIN_SYMBOLS
    if all_crypto:
        min_symbols = POLYGON_GROUPED_DAILY_CRYPTO_MIN_SYMBOLS
    return (
        timeframe == "1day"
        and normalized_limit > 1
        and normalized_limit <= POLYGON_GROUPED_DAILY_MAX_CANDLES
        and len(symbols) >= min_symbols
        and (all_stocks or all_crypto)
    )


def _is_intraday_timeframe(timeframe):
    parsed = parse_timeframe_spec(timeframe)
    if not parsed:
        return str(timeframe or "").strip().lower() in {"1m", "5m", "15m", "30m", "1h", "4h"}

    _, unit = parsed
    return unit in {"m", "h"}


def _can_use_intraday_snapshot_prefilter(symbols, timeframe):
    if len(symbols) < POLYGON_INTRADAY_SNAPSHOT_PREFILTER_MIN_SYMBOLS:
        return False
    if not _is_intraday_timeframe(timeframe):
        return False
    if not all(provider_name_for_symbol(symbol) == MARKET_DATA_PROVIDER for symbol in symbols):
        return False
    return all(not is_crypto_symbol(symbol) for symbol in symbols)


def _grouped_daily_massive_symbols(symbols, timeframe):
    if not _timeframe_uses_grouped_daily_history(timeframe):
        return []
    return [
        symbol
        for symbol in symbols
        if provider_name_for_symbol(symbol) == MARKET_DATA_PROVIDER
    ]


# =========================================================
# FETCH BATCHES
# =========================================================

async def fetch_batches(
    symbols,
    timeframe,
    batch_size=DEFAULT_BATCH_SIZE,
    concurrency=None,
    candles_limit=MAX_CANDLES,
):

    if not symbols:
        return []

    provider = _fetch_provider_label(symbols)
    normalized_limit = normalize_candles_limit(candles_limit)
    effective_batch_size = batch_size
    if concurrency is None:
        concurrency = _default_concurrency_for_symbols(symbols)
    concurrency = max(1, int(concurrency))
    symbol_semaphore = asyncio.Semaphore(concurrency)
    results_by_symbol = {}
    started = time.perf_counter()

    pending_symbols = list(symbols)
    grouped_daily_symbols = _grouped_daily_massive_symbols(pending_symbols, timeframe)
    if grouped_daily_symbols:
        grouped_items = await request_massive_grouped_daily_candles(
            grouped_daily_symbols,
            timeframe,
            normalized_limit,
        )
        for item in grouped_items:
            symbol = item.get("symbol")
            if symbol:
                results_by_symbol[symbol] = item
        grouped_symbol_set = set(grouped_daily_symbols)
        unresolved_grouped_symbols = [
            symbol for symbol in grouped_daily_symbols
            if symbol not in results_by_symbol
        ]
        pending_symbols = [
            symbol
            for symbol in pending_symbols
            if symbol not in grouped_symbol_set
        ]
        logger.info(
            "fetch_batches grouped_history_path timeframe=%s requested=%s resolved=%s unresolved=%s candles_limit=%s bulk=%s",
            timeframe,
            len(grouped_daily_symbols),
            len(grouped_items),
            len(unresolved_grouped_symbols),
            normalized_limit,
            _can_use_grouped_daily_bulk_path(
                grouped_daily_symbols,
                timeframe,
                normalized_limit,
            ),
        )

    intraday_prefilter_symbols = [
        symbol
        for symbol in pending_symbols
        if not is_crypto_symbol(symbol)
        and provider_name_for_symbol(symbol) == MARKET_DATA_PROVIDER
    ]
    if _can_use_intraday_snapshot_prefilter(intraday_prefilter_symbols, timeframe):
        snapshot_items = await request_massive_snapshots(intraday_prefilter_symbols, timeframe)
        snapshot_symbol_set = {
            item.get("symbol")
            for item in snapshot_items
            if item.get("symbol")
        }
        if snapshot_symbol_set:
            skipped_snapshot_symbols = [
                symbol
                for symbol in intraday_prefilter_symbols
                if symbol not in snapshot_symbol_set
            ]
            if skipped_snapshot_symbols:
                skipped_symbol_set = set(skipped_snapshot_symbols)
                pending_symbols = [
                    symbol
                    for symbol in pending_symbols
                    if symbol not in skipped_symbol_set
                ]
            logger.info(
                "fetch_batches intraday_snapshot_prefilter timeframe=%s requested=%s eligible=%s skipped=%s",
                timeframe,
                len(intraday_prefilter_symbols),
                len(snapshot_symbol_set),
                len(skipped_snapshot_symbols),
            )

    async def _fetch_symbol_subset(subset):
        if not subset:
            return []

        tasks = []
        for symbol in subset:
            async def run_symbol(target_symbol=symbol):
                async with symbol_semaphore:
                    fetcher = resolve_candle_fetcher_for_symbol(target_symbol)
                    return await fetcher(
                        target_symbol,
                        timeframe,
                        normalized_limit,
                    )

            tasks.append(run_symbol())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        items = []
        for symbol, result in zip(subset, results):
            if isinstance(result, Exception):
                logger.warning(
                    "fetch_batches symbol fetch failed symbol=%s timeframe=%s: %s",
                    symbol,
                    timeframe,
                    result,
                )
                continue
            if result:
                items.append(result)
        return items

    # A single semaphore-gated wave over every pending symbol, rather than
    # sequential batches, so a freed concurrency slot always has more work
    # ready to pick up instead of stalling at a batch boundary.
    items = await _fetch_symbol_subset(pending_symbols)
    for item in items:
        symbol = item.get("symbol")
        if symbol:
            results_by_symbol[symbol] = item

    merged = [results_by_symbol[symbol] for symbol in symbols if symbol in results_by_symbol]

    elapsed = time.perf_counter() - started
    logger.info(
        "fetch_batches complete provider=%s timeframe=%s requested=%s returned=%s candles_limit=%s batch_size=%s elapsed=%.2fs",
        provider,
        timeframe,
        len(symbols),
        len(merged),
        normalized_limit,
        effective_batch_size,
        elapsed,
    )
    if elapsed >= SLOW_FETCH_WARNING_SECONDS:
        logger.warning(
            "slow fetch_batches provider=%s timeframe=%s requested=%s candles_limit=%s elapsed=%.2fs",
            provider,
            timeframe,
            len(symbols),
            normalized_limit,
            elapsed,
        )

    return merged


# =========================================================
# MAIN ENTRY
# =========================================================

async def fetch_live_data(
    symbols,
    timeframe,
    batch_size=DEFAULT_BATCH_SIZE,
    include_fundamentals=False,
    candles_limit=MAX_CANDLES,
    latest_only=False,
):
    if not symbols:
        return []

    normalized_limit = normalize_candles_limit(candles_limit)
    worker_cache_enabled = timeframe_uses_worker_cache(timeframe)
    now = int(time.time())
    overall_started = time.perf_counter()
    logger.info(
        "fetch_live_data start symbols=%s timeframe=%s candles_limit=%s include_fundamentals=%s worker_cache=%s latest_only=%s",
        len(symbols),
        timeframe,
        normalized_limit,
        include_fundamentals,
        worker_cache_enabled,
        latest_only,
    )

    if latest_only:
        massive_snapshot_symbols = [
            symbol
            for symbol in symbols
            if provider_name_for_symbol(symbol) == MARKET_DATA_PROVIDER
            and (
                not is_crypto_symbol(symbol)
                or not settings.MASSIVE_CRYPTO_END_OF_DAY_ONLY
            )
        ]
        binance_quote_symbols = [
            symbol
            for symbol in symbols
            if is_crypto_symbol(symbol) and provider_name_for_symbol(symbol) == BINANCE_PROVIDER
        ]
        if massive_snapshot_symbols or binance_quote_symbols:
            started = time.perf_counter()
            latest_map = {}

            if massive_snapshot_symbols:
                snapshot_items = await request_massive_snapshots(massive_snapshot_symbols, timeframe)
                latest_map.update({item["symbol"]: item for item in snapshot_items})

            if binance_quote_symbols:
                quote_items = await request_binance_quotes(binance_quote_symbols, timeframe)
                latest_map.update({item["symbol"]: item for item in quote_items})

            if len(latest_map) < len(symbols):
                missing_symbols = [symbol for symbol in symbols if symbol not in latest_map]
                if missing_symbols:
                    fallback_items = await fetch_batches(
                        missing_symbols,
                        timeframe,
                        batch_size=batch_size,
                        candles_limit=1,
                    )
                    latest_map.update({
                        item["symbol"]: _payload_with_recent_candles(item, 1)
                        for item in fallback_items
                    })

            if latest_map:
                results = [latest_map[symbol] for symbol in symbols if symbol in latest_map]
                if include_fundamentals:
                    await attach_massive_fundamentals(results)
                logger.info(
                    "fetch_live_data done symbols=%s timeframe=%s returned=%s mode=quote_fast_path elapsed=%.2fs",
                    len(symbols),
                    timeframe,
                    len(results),
                    time.perf_counter() - started,
                )
                return results

    if not worker_cache_enabled:
        cached_map = await asyncio.to_thread(store.get_cached, symbols, timeframe)
        fresh_results = {}
        missing_symbols = []

        for symbol in symbols:
            cached = cached_map.get(symbol)
            if not cached:
                missing_symbols.append(symbol)
                continue

            cached_payload = cached["payload"] or {}
            if not is_payload_compatible_for_fetch(cached_payload, symbol, timeframe):
                missing_symbols.append(symbol)
                continue

            cached_candles = cached_payload.get("candles") or []
            if len(cached_candles) < normalized_limit:
                missing_symbols.append(symbol)
                continue

            if is_refresh_due(cached_payload, timeframe, now):
                missing_symbols.append(symbol)
                continue

            fresh_results[symbol] = _payload_with_recent_candles(cached_payload, normalized_limit)

        cached_hits = len(fresh_results)
        fetched = []
        if missing_symbols:
            fetched = await fetch_batches(
                missing_symbols,
                timeframe,
                batch_size=batch_size,
                candles_limit=normalized_limit,
            )

        if fetched:
            await asyncio.to_thread(store.store_snapshots, fetched, timeframe)
            fresh_results.update({
                item["symbol"]: item
                for item in fetched
            })

        results = [
            _payload_with_recent_candles(fresh_results[symbol], normalized_limit)
            for symbol in symbols
            if symbol in fresh_results
        ]

        if include_fundamentals:
            await attach_massive_fundamentals(results)

        elapsed = time.perf_counter() - overall_started
        logger.info(
            "fetch_live_data done symbols=%s timeframe=%s returned=%s mode=direct elapsed=%.2fs",
            len(symbols),
            timeframe,
            len(results),
            elapsed,
        )
        logger.info(
            "fetch_live_data direct cache_hits=%s fetched=%s requested=%s timeframe=%s",
            cached_hits,
            len(fetched),
            len(symbols),
            timeframe,
        )
        if elapsed >= SLOW_FETCH_WARNING_SECONDS:
            logger.warning(
                "slow fetch_live_data symbols=%s timeframe=%s mode=direct elapsed=%.2fs",
                len(symbols),
                timeframe,
                elapsed,
            )
        return results

    cached_map = await asyncio.to_thread(store.get_cached, symbols, timeframe)
    next_refresh_map = {}

    fresh_results = {}
    stale_results = {}
    stale_updated_at = {}
    missing_symbols = []

    for symbol in symbols:
        cached = cached_map.get(symbol)

        if not cached:
            next_refresh_map[symbol] = now
            missing_symbols.append(symbol)
            continue

        cached_payload = cached["payload"] or {}

        if not is_payload_compatible_for_fetch(cached_payload, symbol, timeframe):
            next_refresh_map[symbol] = now
            stale_results[symbol] = cached_payload
            stale_updated_at[symbol] = cached.get("updated_at")
            missing_symbols.append(symbol)
            continue

        cached_candles = cached_payload.get("candles") or []
        if len(cached_candles) < normalized_limit:
            next_refresh_map[symbol] = now
            stale_results[symbol] = cached_payload
            stale_updated_at[symbol] = cached.get("updated_at")
            missing_symbols.append(symbol)
            continue

        if not is_refresh_due(cached_payload, timeframe, now):
            next_refresh_map[symbol] = next_refresh_at_for_timeframe(timeframe, now)
            fresh_results[symbol] = _with_freshness_metadata(
                _payload_with_recent_candles(cached_payload, normalized_limit),
                is_stale=False,
                market_data_source=MARKET_DATA_SOURCE_FRESH_CACHE,
                stale_age_seconds=_cache_age_seconds(cached.get("updated_at"), now) or 0,
            )
            continue

        next_refresh_map[symbol] = now
        stale_results[symbol] = cached_payload
        stale_updated_at[symbol] = cached.get("updated_at")
        missing_symbols.append(symbol)

    await asyncio.to_thread(
        store.register_interest, symbols, timeframe, next_refresh_map=next_refresh_map
    )

    if missing_symbols:
        fetched = await fetch_batches(
            missing_symbols,
            timeframe,
            batch_size=batch_size,
            candles_limit=normalized_limit,
        )

        if fetched:
            await asyncio.to_thread(store.store_snapshots, fetched, timeframe)
            fresh_results.update({
                item["symbol"]: _with_freshness_metadata(
                    item,
                    is_stale=False,
                    market_data_source=MARKET_DATA_SOURCE_LIVE,
                    stale_age_seconds=0,
                )
                for item in fetched
            })

        unresolved_symbols = [
            symbol for symbol in missing_symbols
            if symbol not in fresh_results
        ]

        if unresolved_symbols:
            backoff_until = now + max(FAILED_REFRESH_BACKOFF_SECONDS, timeframe_seconds(timeframe) // 4)
            allow_stale = bool(settings.ALLOW_STALE_MARKET_DATA)
            max_stale_age = max(0, int(settings.MAX_STALE_MARKET_DATA_AGE_SECONDS or 0))
            stale_with_backoff = []
            unresolved_backoff_map = {}

            for symbol in unresolved_symbols:
                stale_payload = stale_results.get(symbol)
                cache_age = _cache_age_seconds(stale_updated_at.get(symbol), now)
                provider = (
                    payload_candle_provider(stale_payload)
                    or expected_candle_provider_for_symbol(symbol)
                )

                if not stale_payload:
                    rejection_reason = "no_cached_payload"
                elif not is_payload_compatible_for_fetch(stale_payload, symbol, timeframe):
                    # When provider/session policy changed, avoid serving stale snapshots.
                    rejection_reason = "cached_payload_provider_mismatch"
                elif not allow_stale:
                    rejection_reason = "stale_fallback_disabled"
                elif cache_age is not None and cache_age > max_stale_age:
                    rejection_reason = "stale_payload_exceeds_max_age"
                else:
                    rejection_reason = None

                stale_returned = rejection_reason is None

                logger.warning(
                    "market_data_refresh_failed symbol=%s timeframe=%s provider=%s "
                    "cache_age_seconds=%s max_stale_age_seconds=%s allow_stale=%s "
                    "stale_returned=%s next_retry_at=%s failure_reason=%s",
                    symbol,
                    timeframe,
                    provider,
                    cache_age,
                    max_stale_age,
                    allow_stale,
                    stale_returned,
                    backoff_until,
                    rejection_reason or STALE_REASON_PROVIDER_REFRESH_FAILED,
                )

                if not stale_returned:
                    unresolved_backoff_map[symbol] = backoff_until
                    continue

                refreshed_payload = _payload_with_recent_candles(stale_payload, normalized_limit)
                refreshed_payload = dict(refreshed_payload)
                refreshed_payload["next_refresh_at"] = backoff_until
                stale_with_backoff.append(refreshed_payload)
                fresh_results[symbol] = _with_freshness_metadata(
                    refreshed_payload,
                    is_stale=True,
                    market_data_source=MARKET_DATA_SOURCE_STALE_CACHE,
                    stale_age_seconds=cache_age or 0,
                    stale_reason=STALE_REASON_PROVIDER_REFRESH_FAILED,
                )

            if stale_with_backoff:
                logger.warning(
                    "Using stale cached market data for %s symbols on timeframe=%s",
                    len(stale_with_backoff),
                    timeframe,
                )

            if stale_with_backoff:
                await asyncio.to_thread(store.store_snapshots, stale_with_backoff, timeframe)

            if unresolved_backoff_map:
                await asyncio.to_thread(
                    store.update_interest_schedule,
                    list(unresolved_backoff_map.keys()),
                    timeframe,
                    unresolved_backoff_map,
                )

    results = [
        _payload_with_recent_candles(fresh_results[symbol], normalized_limit)
        for symbol in symbols
        if symbol in fresh_results
    ]

    if include_fundamentals:
        await attach_massive_fundamentals(results)

    elapsed = time.perf_counter() - overall_started
    logger.info(
        "fetch_live_data done symbols=%s timeframe=%s returned=%s missing=%s mode=worker_cache elapsed=%.2fs",
        len(symbols),
        timeframe,
        len(results),
        len([symbol for symbol in symbols if symbol not in fresh_results]),
        elapsed,
    )
    if elapsed >= SLOW_FETCH_WARNING_SECONDS:
        logger.warning(
            "slow fetch_live_data symbols=%s timeframe=%s mode=worker_cache elapsed=%.2fs",
            len(symbols),
            timeframe,
            elapsed,
        )

    return results

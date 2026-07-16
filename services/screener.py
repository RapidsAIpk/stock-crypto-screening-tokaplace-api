# services/screener.py
import hashlib
import json
import logging
import time

import numpy as np

from core.config import settings
from services.asset_router import build_asset_universe, resolve_asset_metadata
from services.indicators import apply_indicators, evaluate_indicator_details
from services.channel_respect import apply_channel_respect, evaluate_channel_respect_detail
from services.dead_assets import apply_dead_assets, evaluate_dead_assets_detail
from services.confluence import (
    apply_confluence,
    default_confluence_selection,
    evaluate_confluence_detail,
    normalize_confluence_selection,
    normalize_confluence_type,
)
from services.market_data import fetch_live_data
from services.gate_session_store import store as gate_session_store
from services.regression_channels import compute_lrc_channel, compute_dw_regression_channel
from services.trend_channels import compute_trend_channel, required_trend_channel_history
from services.utils import build_indicator_sticker, format_price_value, humanize_token
from services.stock_reference import asset_category_label, matches_asset_categories, matches_sectors

logger = logging.getLogger(__name__)
DETAIL_RECENT_CANDLES = 20
SNAPSHOT_COMPATIBLE_INDICATORS = {"float", "shares_outstanding"}


# ---------------------------------------------------------
# GATE CACHE
# ---------------------------------------------------------

GATE_CACHE = {}
GATE_CACHE_TTL_SECONDS = settings.GATE_SESSION_TTL_SECONDS


def _prune_gate_cache(now=None):
    gate_session_store.prune(now=now)


def _store_gate_results(metadata, scope_hash="", client_id=None):
    _prune_gate_cache()
    return gate_session_store.store(
        metadata=metadata,
        ttl_seconds=GATE_CACHE_TTL_SECONDS,
        scope_hash=scope_hash or "legacy",
        client_id=client_id,
    )


def _consume_gate_results(session_id, scope_hash="", client_id=None, delete_session=True):
    _prune_gate_cache()
    return gate_session_store.consume(
        session_id=session_id,
        scope_hash=scope_hash or "legacy",
        client_id=client_id,
        delete=delete_session,
    )


def _delete_gate_results(session_id):
    gate_session_store.delete(session_id)


def _restore_gate_results(session_id, metadata, scope_hash="", client_id=None):
    if not session_id:
        return
    gate_session_store.restore(
        session_id=session_id,
        metadata=metadata,
        scope_hash=scope_hash or "legacy",
        client_id=client_id,
        ttl_seconds=GATE_CACHE_TTL_SECONDS,
    )


def _normalize_list(value):
    if not value:
        return []
    return sorted(str(item).strip().lower() for item in value if item is not None)


def _scope_payload_from_request(request):
    return {
        "asset_type": getattr(request, "asset_type", None),
        "symbols": _normalize_list(getattr(request, "symbols", None)),
        "stock_sources": _normalize_list(getattr(request, "stock_sources", None)),
        "compliance_status": getattr(request, "compliance_status", None),
        "asset_categories": _normalize_list(getattr(request, "asset_categories", None)),
        "sectors": _normalize_list(getattr(request, "sectors", None)),
        "exchanges": _normalize_list(getattr(request, "exchanges", None)),
        "excluded_categories": _normalize_list(getattr(request, "excluded_categories", None)),
        "gate_timeframe": getattr(request, "gate_timeframe", None),
    }


def _scope_hash_from_request(request):
    payload = _scope_payload_from_request(request)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------
# INDICATOR FILTER HELPER
# ---------------------------------------------------------

def filter_indicators(indicators, tf):

    return [
        i for i in indicators
        if i.timeframe == tf
    ]


def limit_assets(assets, request=None):
    if getattr(request, "symbols", None):
        manual_limit = int(settings.MANUAL_SYMBOLS_MAX or 0)
        if manual_limit > 0:
            return assets[:manual_limit]
        return assets

    max_symbols = int(settings.SCREENING_MAX_SYMBOLS or 0)
    if max_symbols > 0:
        return assets[:max_symbols]
    return assets


# ---------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------

def apply_post_filters(data, request):
    data = attach_post_filter_channels(data, request)

    if request.channel_respect:
        data = apply_channel_respect(
            data,
            request.channel_respect
        )

    if request.confluence:
        data = apply_confluence(
            data,
            request.confluence
        )

    return data


def apply_price_range(data, price_range):
    if not price_range:
        return data

    min_price = getattr(price_range, "min_price", None)
    max_price = getattr(price_range, "max_price", None)

    filtered = []
    for row in data:
        price = row.get("price")
        if price is None:
            continue

        if min_price is not None and float(price) < float(min_price):
            continue

        if max_price is not None and float(price) > float(max_price):
            continue

        filtered.append(row)

    return filtered


def annotate_request_filter_stickers(data, request):
    for asset in data:
        detail_items = []

        price_range_detail = _build_price_range_detail(asset, getattr(request, "price_range", None))
        if price_range_detail:
            detail_items.append(price_range_detail)

        detail_items.extend(_build_universe_filter_details(asset, request))

        for item in detail_items:
            if not item.get("passed") or not item.get("sticker"):
                continue
            _append_asset_sticker(asset, item["name"], item["sticker"])

    return data


def _append_asset_sticker(asset, name, sticker):
    stickers = asset.get("stickers")
    if not isinstance(stickers, list):
        stickers = []
        asset["stickers"] = stickers

    matched = asset.get("matched_indicators")
    if not isinstance(matched, list):
        matched = []
        asset["matched_indicators"] = matched

    if sticker not in stickers:
        stickers.append(sticker)

    if name not in matched:
        matched.append(name)


def _safe_int(value, default, minimum=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(minimum, parsed)


def _config_value(config, key, default=None):
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _confluence_sources_from_config(config):
    sources = []
    raw_type = normalize_confluence_type(_config_value(config, "type", "bullish"))

    for index, source in enumerate(_config_value(config, "sources", []) or []):
        channel_type = _config_value(source, "channel_type") or _config_value(source, "type")
        if not channel_type:
            continue

        default_length = _default_channel_length(channel_type)
        sources.append(
            {
                "id": str(_config_value(source, "id") or f"{channel_type}_{index}"),
                "channel_type": channel_type,
                "selection": normalize_confluence_selection(
                    channel_type,
                    _config_value(source, "selection"),
                    confluence_type=raw_type,
                    source_index=index,
                ),
                "length": _safe_int(_config_value(source, "length"), default_length, minimum=2),
                "width_coeff": _config_value(source, "width_coeff"),
                "upper_dev": _config_value(source, "upper_dev"),
                "lower_dev": _config_value(source, "lower_dev"),
                "window_type": _config_value(source, "window_type"),
                "interval_step": _config_value(source, "interval_step"),
                "wait_for_break": _config_value(source, "wait_for_break"),
                "show_last_channel": _config_value(source, "show_last_channel"),
            }
        )

    if sources:
        return sources[:2]

    for index, channel_type in enumerate(_config_value(config, "channels", []) or []):
        sources.append(
            {
                "id": f"{channel_type}_{index}",
                "channel_type": channel_type,
                "selection": default_confluence_selection(
                    channel_type,
                    confluence_type=raw_type,
                    source_index=index,
                ),
                "length": _default_channel_length(channel_type),
                "width_coeff": None,
                "upper_dev": None,
                "lower_dev": None,
                "window_type": None,
                "interval_step": None,
                "wait_for_break": None,
                "show_last_channel": None,
            }
        )

    return sources[:2]


def _compute_channel_for_source(candles, source):
    channel_type = source["channel_type"]

    if channel_type == "lrc":
        return compute_lrc_channel(
            candles,
            length=_safe_int(source.get("length"), 100, minimum=2),
            upper_dev=float(source.get("upper_dev") if source.get("upper_dev") is not None else 2.0),
            lower_dev=float(source.get("lower_dev") if source.get("lower_dev") is not None else 2.0),
        )

    if channel_type == "regression":
        return compute_dw_regression_channel(
            candles,
            length=_safe_int(source.get("length"), 200, minimum=2),
            width_coeff=float(source.get("width_coeff") if source.get("width_coeff") is not None else 1.0),
            window_type=source.get("window_type") or "continuous",
            interval_step=_safe_int(source.get("interval_step"), 1, minimum=1),
        )

    if channel_type == "trend":
        wait_for_break = source.get("wait_for_break")
        show_last_channel = source.get("show_last_channel")
        return compute_trend_channel(
            candles,
            length=_safe_int(source.get("length"), 8, minimum=2),
            wait_for_break=True if wait_for_break is None else bool(wait_for_break),
            show_last_channel=True if show_last_channel is None else bool(show_last_channel),
        )

    return None


def _confirmation_window_from_config(config):
    confirmation_types = config.get("confirmation_types") or []
    confirmation_patterns = config.get("confirmation_patterns") or []
    has_confirmation_rule = (
        bool(config.get("confirmation_type"))
        or bool(confirmation_types)
        or bool(confirmation_patterns)
    )
    if not config.get("confirmation") or not has_confirmation_rule:
        return 0
    return _safe_int(config.get("confirmation_window"), 1, minimum=0)


def _trend_area_window(config):
    areas = config.get("areas") or []
    if not isinstance(areas, list) or not areas:
        return 1, 0

    window = 1
    confirmation_window = 0
    for area in areas:
        if not isinstance(area, dict):
            continue
        area_window = _safe_int(area.get("window"), 1, minimum=1)
        window = max(window, area_window)

        area_confirmation_types = area.get("confirmation_types") or []
        area_confirmation_patterns = area.get("confirmation_patterns") or []
        has_confirmation_rule = (
            bool(area.get("confirmation_type"))
            or bool(area_confirmation_types)
            or bool(area_confirmation_patterns)
        )
        if area.get("confirmation") and has_confirmation_rule:
            area_confirmation_window = _safe_int(area.get("confirmation_window"), 1, minimum=0)
            confirmation_window = max(confirmation_window, area_confirmation_window)

    return window, confirmation_window


def required_candles_for_indicators(indicators):
    required = 1

    for indicator in indicators or []:
        name = str(getattr(indicator, "name", "") or "").strip().lower()
        config = getattr(indicator, "config", {}) or {}
        window = _safe_int(config.get("window"), 1, minimum=1)
        confirmation_window = _confirmation_window_from_config(config)

        if name in {"rsi", "aroon"}:
            length = _safe_int(config.get("length"), 14, minimum=1)
            needed = length + 1 + window + confirmation_window
        elif name == "wavetrend":
            channel_length = _safe_int(config.get("channel_length"), 10, minimum=1)
            average_length = _safe_int(config.get("average_length"), 21, minimum=1)
            signal_length = _safe_int(config.get("signal_length"), 4, minimum=1)
            needed = max(channel_length, average_length + signal_length) + window + confirmation_window
        elif name == "adx":
            length = _safe_int(config.get("length"), 11, minimum=1)
            max_candles_since = 0
            for condition in config.get("conditions") or []:
                value = condition.get("candles_since") if isinstance(condition, dict) else getattr(condition, "candles_since", None)
                if value is not None:
                    max_candles_since = max(max_candles_since, _safe_int(value, 0, minimum=0))
            # +10 covers the fixed internal lookback constants used by Weak/Compression
            # conditions (see WEAK_LOOKBACK etc. in services/trendy_adx.py), which aren't
            # driven by user-configured candles_since values.
            # Wilder RMA needs a long warm-up past its SMA seed before it converges
            # to TradingView's fully-warmed-up values (TradingView seeds from the
            # start of the whole chart); 200 is a practical floor for that, confirmed
            # against a live TradingView mismatch (ADX off by ~6 points on 22 candles).
            needed = max(length + 1 + max(max_candles_since + 1, 10), 200)
        elif name == "vlr":
            num_regressions = _safe_int(config.get("num_regressions"), 3, minimum=1)
            start_period = _safe_int(config.get("start_period"), 12, minimum=2)
            period_increment = _safe_int(config.get("period_increment"), 12, minimum=0)
            longest_period = start_period + (num_regressions - 1) * period_increment
            timing_candles = _safe_int(config.get("timing_candles"), 1, minimum=0)
            needed = longest_period + timing_candles + 2
        elif name == "lrc":
            length = _safe_int(config.get("length"), 100, minimum=2)
            needed = length + window + confirmation_window
        elif name == "regression":
            length = _safe_int(config.get("length"), 200, minimum=2)
            needed = length + window + confirmation_window
        elif name == "trend":
            length = _safe_int(config.get("length"), 8, minimum=2)
            area_window, area_confirmation_window = _trend_area_window(config)
            needed = _required_candles_for_channel_type("trend", length) + area_window + area_confirmation_window
        elif name == "linreg_candles":
            lr_length = _safe_int(config.get("lr_length"), 11, minimum=1)
            signal_smoothing = _safe_int(config.get("signal_smoothing"), 11, minimum=1)
            needed = lr_length + signal_smoothing + window + confirmation_window
        elif name == "ema":
            needed = _safe_int(config.get("length"), 9, minimum=1) + 1
        elif name == "macd":
            fast = _safe_int(config.get("fast"), 12, minimum=1)
            slow = _safe_int(config.get("slow"), 26, minimum=1)
            signal = _safe_int(config.get("signal"), 9, minimum=1)
            needed = max(fast, slow) + signal + 2
        elif name in {"volume", "volatility"}:
            length = _safe_int(config.get("length"), 20, minimum=1)
            needed = length + 1
        elif name == "relative_volume":
            length = _safe_int(config.get("length"), 10, minimum=1)
            needed = length + 1
        elif name in {"current_volume", "float", "shares_outstanding"}:
            needed = 1
        else:
            needed = window + confirmation_window + 2

        required = max(required, needed)

    return min(500, max(1, required))


def _default_channel_length(channel_type):
    if channel_type == "lrc":
        return 100
    if channel_type == "regression":
        return 200
    if channel_type == "trend":
        return 8
    return 1


def _required_candles_for_channel_type(channel_type, length=None):
    normalized_length = _safe_int(length, _default_channel_length(channel_type), minimum=2)

    if channel_type == "lrc":
        return normalized_length
    if channel_type == "regression":
        return normalized_length
    if channel_type == "trend":
        return required_trend_channel_history(normalized_length)
    return 1


def required_candles_for_request(request, indicators):
    required = required_candles_for_indicators(indicators)

    channel_respect = getattr(request, "channel_respect", None)
    if channel_respect:
        required = max(
            required,
            _required_candles_for_channel_type(getattr(channel_respect, "channel_type", None)),
        )

    confluence = getattr(request, "confluence", None)
    if confluence:
        for source in _confluence_sources_from_config(confluence):
            required = max(
                required,
                _required_candles_for_channel_type(
                    source.get("channel_type"),
                    source.get("length"),
                ),
            )

    dead_assets = getattr(request, "dead_assets", None)
    if dead_assets and getattr(dead_assets, "enabled", False):
        required = max(required, int(getattr(dead_assets, "recovery_lookback", 200) or 200))

    return min(500, max(1, required))


def indicator_requires_candle_history(indicator):
    name = str(getattr(indicator, "name", "") or "").strip().lower()
    return name not in SNAPSHOT_COMPATIBLE_INDICATORS


def requires_candle_history(request, indicators):
    if bool(getattr(request, "channel_respect", None)) or bool(getattr(request, "confluence", None)):
        return True

    dead_assets = getattr(request, "dead_assets", None)
    if dead_assets and getattr(dead_assets, "enabled", False):
        return True

    return any(indicator_requires_candle_history(indicator) for indicator in (indicators or []))


async def fetch_screening_data(assets, timeframe, indicators, need_candle_history=True, request=None):
    symbols = [a["symbol"] for a in assets]
    candles_limit = required_candles_for_request(request, indicators) if need_candle_history else 1
    include_fundamentals = any(
        indicator.name in {"float", "shares_outstanding"}
        for indicator in indicators
    )
    latest_only = not need_candle_history
    start = time.perf_counter()
    logger.info(
        "screening fetch start symbols=%s timeframe=%s indicators=%s candles_limit=%s include_fundamentals=%s need_candle_history=%s latest_only=%s",
        len(symbols),
        timeframe,
        len(indicators or []),
        candles_limit,
        include_fundamentals,
        need_candle_history,
        latest_only,
    )
    data = await fetch_live_data(
        symbols,
        timeframe,
        include_fundamentals=include_fundamentals,
        candles_limit=candles_limit,
        latest_only=latest_only,
    )
    logger.info(
        "screening fetch done symbols=%s timeframe=%s returned=%s elapsed=%.2fs",
        len(symbols),
        timeframe,
        len(data),
        time.perf_counter() - start,
    )
    return data


def attach_post_filter_channels(data, request):
    if not data:
        return data

    needed_channels = set()

    channel_respect = getattr(request, "channel_respect", None)
    if channel_respect:
        needed_channels.add(channel_respect.channel_type)

    confluence = getattr(request, "confluence", None)
    if confluence:
        for source in _confluence_sources_from_config(confluence):
            needed_channels.add(source["channel_type"])

    if not needed_channels:
        needed_channels = set()

    confluence_sources = _confluence_sources_from_config(confluence) if confluence else []

    for asset in data:
        candles = asset.get("candles") or []
        if not candles:
            continue

        channels = asset.setdefault("channels", {})

        for channel_type in needed_channels:
            if channel_type in channels:
                continue

            if channel_type == "lrc":
                channel = compute_lrc_channel(candles)
            elif channel_type == "regression":
                channel = compute_dw_regression_channel(candles)
            elif channel_type == "trend":
                channel = compute_trend_channel(candles)
            else:
                channel = None

            if channel:
                channels[channel_type] = channel

        if not confluence_sources:
            continue

        source_channels = asset.setdefault("confluence_channels", {})
        for source in confluence_sources:
            source_id = source["id"]
            if source_id in source_channels:
                if isinstance(source_channels[source_id], dict):
                    source_channels[source_id].setdefault("selection", source.get("selection"))
                continue

            channel = _compute_channel_for_source(candles, source)
            if not channel:
                continue

            source_channels[source_id] = {
                "channel_type": source["channel_type"],
                "selection": source.get("selection"),
                "channel": channel,
            }

    return data


def apply_selected_indicators(data, indicators):
    if not indicators:
        return data

    return apply_indicators(data, indicators)


def _normalize_scan_stage(scan_stage):
    normalized = str(scan_stage or "").strip().lower()
    if normalized in {"gate", "entry"}:
        return normalized
    return "single"


def _indicator_scope_for_stage(scan_stage):
    return {
        "single": "single",
        "gate": "primary",
        "entry": "secondary",
    }[_normalize_scan_stage(scan_stage)]


def _model_to_dict(value):
    if value is None:
        return None

    if isinstance(value, dict):
        return dict(value)

    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)

    if hasattr(value, "dict"):
        return value.dict(exclude_none=True)

    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }

    return None


def _make_json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, np.ndarray):
        return _make_json_safe(value.tolist())

    if isinstance(value, dict):
        return {
            key: _make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            _make_json_safe(item)
            for item in value
        ]

    if hasattr(value, "model_dump"):
        return _make_json_safe(value.model_dump(exclude_none=True))

    if hasattr(value, "dict"):
        return _make_json_safe(value.dict(exclude_none=True))

    if hasattr(value, "__dict__"):
        return {
            key: _make_json_safe(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return value


def _fallback_asset(symbol, asset_type):
    normalized_symbol = str(symbol or "").strip().upper()

    if asset_type == "crypto" and not normalized_symbol.endswith("-USD"):
        normalized_symbol = f"{normalized_symbol}-USD"

    return {
        "symbol": normalized_symbol,
        "asset_type": asset_type,
        "data_source": "manual",
        "exchange": "manual" if asset_type == "crypto" else None,
    }


def _build_price_range_detail(asset, price_range):
    if not price_range:
        return None

    config = _model_to_dict(price_range) or {}
    price = asset.get("price")
    passed = price is not None

    min_price = config.get("min_price")
    max_price = config.get("max_price")
    if min_price is not None and price is not None and float(price) < float(min_price):
        passed = False
    if max_price is not None and price is not None and float(price) > float(max_price):
        passed = False

    summary = _price_range_summary(price, min_price, max_price, passed=passed)
    sticker = build_indicator_sticker(
        "Price Range",
        summary,
        {"window": 1, "confirmation": False},
        window=1,
        decision="Tradeable Range",
    )

    return {
        "name": "price_range",
        "passed": passed,
        "summary": summary,
        "sticker": sticker if passed else None,
        "details": {
            **config,
            "price": price,
        },
    }


def _build_universe_filter_details(asset, request):
    details = []

    stock_sources = list(getattr(request, "stock_sources", None) or [])
    if stock_sources:
        passed = asset.get("data_source") in stock_sources
        details.append(
            {
                "name": "stock_sources",
                "passed": passed,
                "summary": (
                    f"Source {asset.get('data_source') or 'unknown'} accepted by universe filter."
                    if passed
                    else f"Source {asset.get('data_source') or 'unknown'} not in requested universe."
                ),
                "sticker": build_indicator_sticker(
                    "Source Filter",
                    f"Using {asset.get('data_source') or 'unknown'} universe source",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Universe Source Match",
                ) if passed else None,
                "details": {
                    "requested_sources": stock_sources,
                    "asset_source": asset.get("data_source"),
                },
            }
        )

    compliance_status = getattr(request, "compliance_status", None)
    if compliance_status:
        actual = str(asset.get("compliance_status") or "").strip().lower().replace("_", "-")
        expected = str(compliance_status).strip().lower().replace("_", "-")
        passed = actual == expected
        details.append(
            {
                "name": "compliance_status",
                "passed": passed,
                "summary": (
                    f"Compliance status {asset.get('compliance_status') or 'unknown'} matches request."
                    if passed
                    else f"Compliance status {asset.get('compliance_status') or 'unknown'} does not match request."
                ),
                "sticker": build_indicator_sticker(
                    "Compliance Filter",
                    f"Status {humanize_token(asset.get('compliance_status') or 'unknown')}",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Compliance Match",
                ) if passed else None,
                "details": {
                    "requested_status": compliance_status,
                    "asset_status": asset.get("compliance_status"),
                },
            }
        )

    asset_categories = [
        str(item).strip().lower().replace(" ", "_").replace("-", "_")
        for item in (getattr(request, "asset_categories", None) or [])
        if item
    ]
    if asset_categories:
        passed = matches_asset_categories(asset, asset_categories)
        actual = list(asset.get("asset_categories") or [])
        labels = [asset_category_label(item) for item in actual]
        details.append(
            {
                "name": "asset_categories",
                "passed": passed,
                "summary": (
                    f"Matches asset categories: {', '.join(labels) if labels else 'none assigned'}."
                    if passed
                    else f"No match for requested asset categories. Assigned: {', '.join(labels) if labels else 'none'}."
                ),
                "sticker": build_indicator_sticker(
                    "Asset Category",
                    f"Categories: {', '.join(labels) if labels else 'none'}",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Category Match",
                ) if passed else None,
                "details": {
                    "requested_categories": asset_categories,
                    "asset_categories": actual,
                },
            }
        )

    selected_sectors = [
        str(item).strip()
        for item in (getattr(request, "sectors", None) or [])
        if str(item).strip()
    ]
    if selected_sectors:
        passed = matches_sectors(asset, selected_sectors)
        sector = str(asset.get("sector") or "").strip()
        details.append(
            {
                "name": "sectors",
                "passed": passed,
                "summary": (
                    f"Sector {sector or 'unknown'} matches request."
                    if passed
                    else f"Sector {sector or 'unknown'} is outside requested sectors."
                ),
                "sticker": build_indicator_sticker(
                    "Sector Filter",
                    f"Sector {sector or 'unknown'}",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Sector Match",
                ) if passed else None,
                "details": {
                    "requested_sectors": selected_sectors,
                    "asset_sector": sector,
                },
            }
        )

    exchanges = [str(item).strip().lower() for item in (getattr(request, "exchanges", None) or []) if item]
    if exchanges:
        availability = [
            str(item).strip().lower()
            for item in (
                asset.get("exchange_availability")
                or ([asset.get("exchange")] if asset.get("exchange") else [])
            )
            if item
        ]
        passed = bool(set(exchanges).intersection(availability))
        details.append(
            {
                "name": "exchanges",
                "passed": passed,
                "summary": (
                    f"Available on {', '.join(availability) if availability else 'no known exchange metadata'}."
                    if passed
                    else f"No requested exchange match. Available on {', '.join(availability) if availability else 'no known exchange metadata'}."
                ),
                "sticker": build_indicator_sticker(
                    "Exchange Filter",
                    f"Available on {', '.join(availability)}",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Exchange Access Match",
                ) if passed else None,
                "details": {
                    "requested_exchanges": exchanges,
                    "available_exchanges": availability,
                },
            }
        )

    excluded_categories = [
        str(item).strip().lower()
        for item in (getattr(request, "excluded_categories", None) or [])
        if item
    ]
    if excluded_categories:
        category = str(asset.get("category") or "").strip().lower()
        passed = category not in excluded_categories
        details.append(
            {
                "name": "excluded_categories",
                "passed": passed,
                "summary": (
                    f"Category {asset.get('category') or 'unknown'} is allowed by the filter."
                    if passed
                    else f"Category {asset.get('category') or 'unknown'} is excluded by the filter."
                ),
                "sticker": build_indicator_sticker(
                    "Category Filter",
                    f"Category {humanize_token(asset.get('category') or 'unknown')} allowed",
                    {"window": 1, "confirmation": False},
                    window=1,
                    decision="Allowed Category",
                ) if passed else None,
                "details": {
                    "excluded_categories": excluded_categories,
                    "asset_category": asset.get("category"),
                },
            }
        )

    return details


def _price_range_summary(price, min_price, max_price, passed=True):
    if price is None:
        return "Price unavailable for range check."

    boundaries = []
    if min_price is not None:
        boundaries.append(f"above {format_price_value(min_price)}")
    if max_price is not None:
        boundaries.append(f"below {format_price_value(max_price)}")

    if not boundaries:
        return f"Price {format_price_value(price)} in active range."

    qualifier = "meets" if passed else "misses"
    return f"Price {format_price_value(price)} {qualifier} {' and '.join(boundaries)}"


def _build_request_filters(request, scan_stage, timeframe, selected_indicators):
    return {
        "asset_type": getattr(request, "asset_type", None),
        "scan_stage": _normalize_scan_stage(scan_stage),
        "timeframe_mode": getattr(request, "timeframe_mode", None),
        "timeframe": timeframe,
        "stock_sources": list(getattr(request, "stock_sources", None) or []),
        "compliance_status": getattr(request, "compliance_status", None),
        "compliance_standards": list(getattr(request, "compliance_standards", None) or []),
        "asset_categories": list(getattr(request, "asset_categories", None) or []),
        "sectors": list(getattr(request, "sectors", None) or []),
        "exchanges": list(getattr(request, "exchanges", None) or []),
        "excluded_categories": list(getattr(request, "excluded_categories", None) or []),
        "selected_indicators": [
            {
                "name": getattr(indicator, "name", None),
                "timeframe": getattr(indicator, "timeframe", None),
                "config": dict(getattr(indicator, "config", {}) or {}),
            }
            for indicator in selected_indicators or []
        ],
        "channel_respect": _model_to_dict(getattr(request, "channel_respect", None)) or {},
        "confluence": _model_to_dict(getattr(request, "confluence", None)) or {},
        "price_range": _model_to_dict(getattr(request, "price_range", None)) or {},
    }


async def get_asset_detail(symbol, asset_type, timeframe, request, scan_stage="single"):
    normalized_stage = _normalize_scan_stage(scan_stage)
    scope = _indicator_scope_for_stage(normalized_stage)
    selected_indicators = filter_indicators(getattr(request, "indicators", []) or [], scope)
    resolved_asset = resolve_asset_metadata(symbol, asset_type) or _fallback_asset(symbol, asset_type)
    need_fundamentals = asset_type == "stocks" or any(
        getattr(indicator, "name", None) in {"float", "shares_outstanding"}
        for indicator in selected_indicators
    )
    candles_limit = max(DETAIL_RECENT_CANDLES, required_candles_for_request(request, selected_indicators))
    data = await fetch_live_data(
        [resolved_asset["symbol"]],
        timeframe,
        include_fundamentals=need_fundamentals,
        candles_limit=candles_limit,
    )

    if not data:
        return None

    attach_asset_metadata(data, [resolved_asset])
    asset = data[0]
    asset["asset_metadata"] = dict(resolved_asset.get("asset_metadata") or {})
    attach_post_filter_channels([asset], request)

    indicator_details = evaluate_indicator_details(asset, selected_indicators, timeframe_scope=scope)
    filter_details = []

    price_range_detail = _build_price_range_detail(asset, getattr(request, "price_range", None))
    if price_range_detail:
        filter_details.append(price_range_detail)

    filter_details.extend(_build_universe_filter_details(asset, request))

    dead_assets_detail = evaluate_dead_assets_detail(asset, getattr(request, "dead_assets", None))
    if dead_assets_detail:
        filter_details.append(dead_assets_detail)

    channel_detail = evaluate_channel_respect_detail(asset, getattr(request, "channel_respect", None))
    if channel_detail:
        filter_details.append(channel_detail)

    confluence_detail = evaluate_confluence_detail(asset, getattr(request, "confluence", None))
    if confluence_detail:
        filter_details.append(confluence_detail)

    detail_stickers = [
        item["sticker"]
        for item in indicator_details + filter_details
        if item.get("passed") and item.get("sticker")
    ]
    detail_matches = [
        item["name"]
        for item in indicator_details + filter_details
        if item.get("passed")
    ]

    candles = asset.get("candles") or []
    return _make_json_safe({
        "symbol": asset["symbol"],
        "price": asset["price"],
        "asset_type": asset.get("asset_type"),
        "data_source": asset.get("data_source"),
        "exchange": asset.get("exchange"),
        "exchange_availability": asset.get("exchange_availability"),
        "timeframe": timeframe,
        "scan_stage": normalized_stage,
        "name": asset.get("name"),
        "category": asset.get("category"),
        "sector": asset.get("sector"),
        "asset_categories": asset.get("asset_categories"),
        "cmc_id": asset.get("cmc_id"),
        "rank": asset.get("rank"),
        "compliance_status": asset.get("compliance_status"),
        "report_date": asset.get("report_date"),
        "purification_ratio": asset.get("purification_ratio"),
        "candles_count": len(candles) if candles else None,
        "last_candle_time": candles[-1].get("time") if candles else None,
        "stickers": detail_stickers,
        "matched_indicators": detail_matches,
        "asset_metadata": asset.get("asset_metadata") or {},
        "request_filters": _build_request_filters(request, normalized_stage, timeframe, selected_indicators),
        "indicator_details": indicator_details,
        "filter_details": filter_details,
        "market_data": {
            "candles_provider": asset.get("candles_provider"),
            "next_refresh_at": asset.get("next_refresh_at"),
            "shares_outstanding": asset.get("shares_outstanding"),
            "float_shares": asset.get("float_shares"),
            "last_candle": candles[-1] if candles else None,
            "recent_candles": candles[-DETAIL_RECENT_CANDLES:],
        },
        "channels": asset.get("channels") or {},
        "confluence_channels": asset.get("confluence_channels") or {},
    })


# ---------------------------------------------------------
# SINGLE TIMEFRAME
# ---------------------------------------------------------

async def run_single(request):
    started = time.perf_counter()

    assets = await build_asset_universe(request)
    assets = limit_assets(assets, request=request)
    indicators = filter_indicators(
        request.indicators,
        "single"
    )
    need_candle_history = requires_candle_history(request, indicators)

    data = await fetch_screening_data(
        assets,
        request.single_timeframe,
        indicators,
        need_candle_history=need_candle_history,
        request=request,
    )

    if not data:
        return {"results": []}

    attach_asset_metadata(data, assets)
    data = apply_price_range(data, getattr(request, "price_range", None))
    data = apply_dead_assets(data, getattr(request, "dead_assets", None))

    if indicators:
        data = apply_selected_indicators(data, indicators)

    data = apply_post_filters(data, request)
    data = annotate_request_filter_stickers(data, request)

    logger.info(
        "run_single completed timeframe=%s assets=%s results=%s elapsed=%.2fs",
        request.single_timeframe,
        len(assets),
        len(data),
        time.perf_counter() - started,
    )

    return build_response(
        data,
        timeframe=request.single_timeframe,
        scan_stage="single",
    )


# ---------------------------------------------------------
# GATE
# ---------------------------------------------------------

async def run_gate(request, client_id=None):
    started = time.perf_counter()

    assets = await build_asset_universe(request)
    assets = limit_assets(assets, request=request)
    indicators = filter_indicators(
        request.indicators,
        "primary"
    )
    need_candle_history = requires_candle_history(request, indicators)

    data = await fetch_screening_data(
        assets,
        request.gate_timeframe,
        indicators,
        need_candle_history=need_candle_history,
        request=request,
    )

    if not data:
        return {"results": []}

    attach_asset_metadata(data, assets)
    data = apply_price_range(data, getattr(request, "price_range", None))
    data = apply_dead_assets(data, getattr(request, "dead_assets", None))

    if indicators:
        data = apply_selected_indicators(data, indicators)

    data = apply_post_filters(data, request)
    data = annotate_request_filter_stickers(data, request)

    passed_map = {a["symbol"]: a for a in assets}
    gate_metadata = [
        passed_map[a["symbol"]]
        for a in data
    ]
    gate_session_id = _store_gate_results(
        gate_metadata,
        scope_hash=_scope_hash_from_request(request),
        client_id=client_id,
    )
    logger.info(
        "run_gate completed timeframe=%s assets=%s gate_passed=%s elapsed=%.2fs",
        request.gate_timeframe,
        len(assets),
        len(data),
        time.perf_counter() - started,
    )

    return build_response(
        data,
        timeframe=request.gate_timeframe,
        scan_stage="gate",
        gate_session_id=gate_session_id,
    )


# ---------------------------------------------------------
# ENTRY
# ---------------------------------------------------------

async def run_entry(request, client_id=None):
    started = time.perf_counter()
    gate_session_id = request.gate_session_id or ""
    scope_hash = _scope_hash_from_request(request)
    metadata = _consume_gate_results(
        gate_session_id,
        scope_hash=scope_hash,
        client_id=client_id,
    )

    if not metadata:
        return {"results": []}

    try:
        indicators = filter_indicators(
            request.indicators,
            "secondary"
        )
        need_candle_history = requires_candle_history(request, indicators)
        data = await fetch_screening_data(
            metadata,
            request.entry_timeframe,
            indicators,
            need_candle_history=need_candle_history,
            request=request,
        )

        if not data:
            return {"results": []}

        attach_asset_metadata(data, metadata)
        data = apply_price_range(data, getattr(request, "price_range", None))
        data = apply_dead_assets(data, getattr(request, "dead_assets", None))

        if indicators:
            data = apply_selected_indicators(data, indicators)

        data = apply_post_filters(data, request)
        data = annotate_request_filter_stickers(data, request)
    except Exception:
        _restore_gate_results(gate_session_id, metadata, scope_hash=scope_hash, client_id=client_id)
        raise

    logger.info(
        "run_entry completed timeframe=%s gate_candidates=%s results=%s elapsed=%.2fs",
        request.entry_timeframe,
        len(metadata),
        len(data),
        time.perf_counter() - started,
    )

    return build_response(
        data,
        timeframe=request.entry_timeframe,
        scan_stage="entry",
    )


# ---------------------------------------------------------
# METADATA
# ---------------------------------------------------------

def attach_asset_metadata(data, assets):

    asset_map = {
        a["symbol"]: a
        for a in assets
    }

    for item in data:

        meta = asset_map.get(
            item["symbol"],
            {}
        )

        item["asset_type"] = meta.get(
            "asset_type"
        )

        item["data_source"] = meta.get(
            "data_source"
        )

        item["exchange"] = meta.get(
            "exchange"
        )
        item["exchange_availability"] = meta.get("exchange_availability")
        item["name"] = meta.get("name")
        item["category"] = meta.get("category")
        item["sector"] = meta.get("sector")
        item["asset_categories"] = meta.get("asset_categories")
        item["cmc_id"] = meta.get("cmc_id")
        item["rank"] = meta.get("rank")
        item["compliance_status"] = meta.get("compliance_status")
        item["report_date"] = meta.get("report_date")
        item["purification_ratio"] = meta.get("purification_ratio")


# ---------------------------------------------------------
# RESPONSE
# ---------------------------------------------------------

def build_response(filtered, timeframe, scan_stage, gate_session_id=None):

    return {
        "results": [
            {
                "symbol": a["symbol"],
                "price": a["price"],
                "asset_type": a.get("asset_type"),
                "data_source": a.get("data_source"),
                "exchange": a.get("exchange"),
                "exchange_availability": a.get("exchange_availability"),
                "timeframe": timeframe,
                "scan_stage": _normalize_scan_stage(scan_stage),
                "name": a.get("name"),
                "category": a.get("category"),
                "sector": a.get("sector"),
                "asset_categories": a.get("asset_categories"),
                "cmc_id": a.get("cmc_id"),
                "rank": a.get("rank"),
                "compliance_status": a.get("compliance_status"),
                "report_date": a.get("report_date"),
                "purification_ratio": a.get("purification_ratio"),
                "candles_count": len(a.get("candles", [])) if a.get("candles") else None,
                "last_candle_time": (
                    a.get("candles", [])[-1].get("time")
                    if a.get("candles")
                    else None
                ),
                "stickers": a.get("stickers", []),
                "matched_indicators": a.get("matched_indicators"),
            }
            for a in filtered
        ],
        "gate_session_id": gate_session_id,
    }

# services/asset_router.py
import json
from pathlib import Path
import re

from services.stock_reference import enrich_stock_row, filter_stock_universe
from services.integration_runtime import integration_runtime
from services.market_data import active_crypto_candle_provider

BASE_DIR = Path(__file__).resolve().parent.parent
ZOYA_CACHE = BASE_DIR / "data" / "zoya_universe.json"
CRYPTO_CACHE = BASE_DIR / "data" / "crypto_universe.json"
_JSON_CACHE = {}


def _normalize_values(values):
    if not values:
        return set()

    return {
        value.lower().strip()
        for value in values
        if value
    }


def _normalize_exchange_name(value):
    if not value:
        return ""
    return str(value).strip().lower()


def normalize_crypto_symbol(symbol):
    raw_symbol = str(symbol or "").strip()
    if not raw_symbol:
        return ""

    normalized = raw_symbol.upper()
    if normalized.startswith("X:") and normalized.endswith("USD") and len(normalized) > len("X:USD"):
        normalized = normalized[2:-3]
    elif normalized.endswith("-USD"):
        normalized = normalized[:-4]
    elif normalized.endswith("/USD"):
        normalized = normalized[:-4]
    elif normalized.endswith("_USD"):
        normalized = normalized[:-4]
    elif normalized.endswith(":USD"):
        normalized = normalized[:-4]

    base = re.sub(r"[^A-Z0-9]", "", normalized)
    if not base:
        return ""

    return f"{base}-USD"


def normalize_crypto_provider_symbol(symbol):
    normalized_symbol = normalize_crypto_symbol(symbol)
    if not normalized_symbol:
        return ""

    base = normalized_symbol[:-4].replace("-", "")
    return f"X:{base}USD"


def _normalize_crypto_universe_item(item):
    if not isinstance(item, dict):
        return None

    normalized_symbol = normalize_crypto_symbol(item.get("symbol"))
    if not normalized_symbol:
        return None

    normalized_item = dict(item)
    normalized_item["cmc_symbol"] = str(item.get("cmc_symbol") or item.get("symbol") or "").strip()
    normalized_item["symbol"] = normalized_symbol
    normalized_item["provider_symbol"] = normalize_crypto_provider_symbol(normalized_symbol)
    return normalized_item


def _load_cached_json(path):
    if not path.exists():
        _JSON_CACHE.pop(path, None)
        return []

    stat = path.stat()
    cache_key = (stat.st_mtime_ns, stat.st_size)
    cached = _JSON_CACHE.get(path)

    if cached and cached["key"] == cache_key:
        return cached["data"]

    with open(path) as f:
        data = json.load(f)

    _JSON_CACHE[path] = {
        "key": cache_key,
        "data": data,
    }
    return data


# =========================================================
# STOCK UNIVERSE
# =========================================================

def load_zoya_universe(status=None):
    data = _load_cached_json(ZOYA_CACHE)

    # filter compliance status
    if status:
        normalized = status.upper().replace("-", "_")
        return [
            item for item in data
            if item.get("status") == normalized
        ]

    return data


# =========================================================
# CRYPTO UNIVERSE
# =========================================================

def load_crypto_universe():
    data = _load_cached_json(CRYPTO_CACHE)
    normalized = []

    for item in data:
        normalized_item = _normalize_crypto_universe_item(item)
        if normalized_item is not None:
            normalized.append(normalized_item)

    return normalized


# =========================================================
# CRYPTO CATEGORY FILTER
# =========================================================

def filter_crypto_categories(universe, excluded_categories):

    if not excluded_categories:
        return universe

    excluded = _normalize_values(excluded_categories)
    return [
        coin for coin in universe
        if (coin.get("category") or "").lower().strip() not in excluded
    ]


def filter_by_exchange(universe, allowed_exchanges):

    if not allowed_exchanges:
        return universe

    allowed = _normalize_values(allowed_exchanges)
    return [
        item for item in universe
        if not item.get("exchange")
        or item.get("exchange").lower().strip() in allowed
    ]


def extract_exchange_availability(item):
    raw = item.get("exchanges")

    if isinstance(raw, list):
        normalized = [_normalize_exchange_name(v) for v in raw]
        return sorted({v for v in normalized if v})

    single = _normalize_exchange_name(item.get("exchange"))
    if single:
        return [single]

    return []


def extract_supported_exchange_availability(item):
    return extract_exchange_availability(item)


def extract_exchange_list_for_display(item):
    return extract_supported_exchange_availability(item)


def should_include_for_exchange(item, requested_exchanges):
    requested = _normalize_values(requested_exchanges)
    if not requested:
        return True

    availability = set(extract_exchange_availability(item))
    if not availability:
        return False

    return bool(availability.intersection(requested))


def required_crypto_provider_exchange():
    provider = active_crypto_candle_provider()

    if provider == "binance":
        return "binance"

    return None


def should_include_for_crypto_screening(item, requested_exchanges):
    availability = set(extract_exchange_availability(item))
    provider_exchange = required_crypto_provider_exchange()

    if provider_exchange and provider_exchange not in availability:
        return False

    return should_include_for_exchange(item, requested_exchanges)


def resolve_crypto_exchange(item, _requested_exchanges):
    availability = extract_supported_exchange_availability(item)
    requested = [
        exchange for exchange in _normalize_values(_requested_exchanges)
        if exchange in availability
    ]
    if requested:
        return ",".join(requested[:5])
    if availability:
        return ",".join(availability[:5])

    return "global"


def list_crypto_exchanges():
    exchanges = {}

    for item in load_crypto_universe():
        symbol = normalize_crypto_symbol(item.get("symbol"))
        if not symbol:
            continue

        for exchange in extract_exchange_availability(item):
            exchanges.setdefault(exchange, set()).add(symbol)

    return [
        {
            "exchange": exchange,
            "coin_count": len(symbols),
        }
        for exchange, symbols in sorted(exchanges.items())
    ]


def _normalize_manual_symbols(symbols, asset_type):
    normalized = []
    seen = set()

    for raw in symbols or []:
        if asset_type == "crypto":
            symbol = normalize_crypto_symbol(raw)
        else:
            symbol = str(raw).strip().upper()
        if not symbol:
            continue

        if symbol in seen:
            continue

        seen.add(symbol)
        normalized.append(symbol)

    return normalized


def _build_stock_asset_row(item):
    row = {
        "symbol": item["symbol"],
        "name": item.get("name"),
        "exchange": item.get("exchange"),
        "category": None,
        "compliance_status": item.get("status"),
        "report_date": item.get("reportDate"),
        "purification_ratio": item.get("purificationRatio"),
        "asset_type": "stocks",
        "data_source": "zoya",
    }
    return enrich_stock_row(row)


def _build_crypto_asset_row(coin):
    normalized_symbol = normalize_crypto_symbol(coin.get("symbol"))
    if not normalized_symbol:
        return None

    availability = extract_exchange_list_for_display(coin)
    row = {
        "symbol": normalized_symbol,
        "name": coin.get("name"),
        "category": coin.get("category"),
        "cmc_id": coin.get("id"),
        "rank": coin.get("rank"),
        "exchange": resolve_crypto_exchange(
            coin,
            None,
        ),
        "asset_type": "crypto",
        "data_source": "massive",
    }
    if availability:
        row["exchange_availability"] = availability
    return row


def resolve_asset_metadata(symbol, asset_type):
    normalized_asset_type = str(asset_type or "").strip().lower()
    normalized_symbol = str(symbol or "").strip().upper()

    if normalized_asset_type == "stocks":
        for item in load_zoya_universe():
            if str(item.get("symbol") or "").strip().upper() != normalized_symbol:
                continue
            resolved = _build_stock_asset_row(item)
            resolved["asset_metadata"] = dict(item)
            return resolved
        return None

    if normalized_asset_type == "crypto":
        target_symbol = normalize_crypto_symbol(normalized_symbol)
        if not target_symbol:
            return None

        for coin in load_crypto_universe():
            if normalize_crypto_symbol(coin.get("symbol")) != target_symbol:
                continue
            resolved = _build_crypto_asset_row(coin)
            if not resolved:
                continue
            resolved["asset_metadata"] = dict(coin)
            return resolved
        return None

    return None


# =========================================================
# BUILD ASSET UNIVERSE
# =========================================================

async def build_asset_universe(request):
    manual_symbols = _normalize_manual_symbols(
        getattr(request, "symbols", None),
        request.asset_type,
    )

    if manual_symbols:
        if request.asset_type == "stocks":
            return [
                {
                    "symbol": symbol,
                    "name": None,
                    "exchange": None,
                    "category": None,
                    "compliance_status": None,
                    "report_date": None,
                    "purification_ratio": None,
                    "asset_type": "stocks",
                    "data_source": "manual",
                }
                for symbol in manual_symbols
            ]

        if request.asset_type == "crypto":
            return [
                {
                    "symbol": symbol,
                    "name": None,
                    "category": None,
                    "cmc_id": None,
                    "exchange": "manual",
                    "asset_type": "crypto",
                    "data_source": "manual",
                }
                for symbol in manual_symbols
            ]

    # -----------------------------------------------------
    # STOCKS
    # -----------------------------------------------------
    if request.asset_type == "stocks":
        if not integration_runtime.is_enabled("stock_universe_cache"):
            return []

        if "zoya" not in _normalize_values(request.stock_sources):
            return []

        integration_runtime.record_call("stock_universe_cache")
        universe = load_zoya_universe(
            request.compliance_status
        )
        rows = [_build_stock_asset_row(item) for item in universe]
        return filter_stock_universe(
            rows,
            asset_categories=getattr(request, "asset_categories", None),
            sectors=getattr(request, "sectors", None),
        )


    # -----------------------------------------------------
    # CRYPTO
    # -----------------------------------------------------
    if request.asset_type == "crypto":
        if not integration_runtime.is_enabled("crypto_universe_cache"):
            return []

        integration_runtime.record_call("crypto_universe_cache")
        universe = load_crypto_universe()
        universe = [
            coin for coin in universe
            if should_include_for_crypto_screening(coin, request.exchanges)
        ]

        # Apply category exclusion
        universe = filter_crypto_categories(
            universe,
            request.excluded_categories
        )
        assets = []
        for coin in universe:
            availability = extract_exchange_list_for_display(coin)
            row = _build_crypto_asset_row(coin)
            if not row:
                continue
            row["exchange"] = resolve_crypto_exchange(
                coin,
                request.exchanges,
            )
            if availability:
                row["exchange_availability"] = availability
            assets.append(row)
        return assets

    return []

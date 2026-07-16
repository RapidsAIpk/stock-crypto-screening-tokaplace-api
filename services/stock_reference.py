# services/stock_reference.py
#
# Stock sector + asset-category metadata sourced from Massive reference APIs
# and cached index constituent lists.

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
METADATA_PATH = BASE_DIR / "data" / "stock_reference_metadata.json"
INDEX_CONSTITUENTS_PATH = BASE_DIR / "data" / "index_constituents.json"

ASSET_CATEGORY_IDS = (
    "nasdaq",
    "nyse",
    "amex",
    "etf",
    "sp500",
    "dow_jones",
    "russell_2000",
)

EXCHANGE_GROUP_BY_MIC = {
    "XNAS": "nasdaq",
    "NASDAQ": "nasdaq",
    "XNYS": "nyse",
    "NYSE": "nyse",
    "XASE": "amex",
    "AMEX": "amex",
}

SECTOR_ORDER = (
    "Technology",
    "Healthcare",
    "Financials",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Industrials",
    "Energy",
    "Utilities",
    "Real Estate",
    "Communication Services",
    "Basic Materials",
    "Other",
)

_METADATA_CACHE: dict[str, dict] | None = None
_INDEX_CACHE: dict[str, set[str]] | None = None


def _normalize_symbol(value) -> str:
    return str(value or "").strip().upper()


def _normalize_token(value) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def exchange_group_from_mic(value) -> str | None:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    return EXCHANGE_GROUP_BY_MIC.get(normalized)


def sector_from_sic(sic_code, sic_description=None) -> str:
    try:
        code = int(str(sic_code).strip()[:4])
    except (TypeError, ValueError):
        code = None

    description = str(sic_description or "").upper()

    if "COMPUTER" in description or "SOFTWARE" in description or "SEMICONDUCTOR" in description or "ELECTRONIC COMPUTERS" in description:
        return "Technology"
    if "PHARMACEUTICAL" in description or "MEDICAL" in description or "SURGICAL" in description or "HEALTH" in description or "HOSPITAL" in description:
        return "Healthcare"
    if "BANK" in description or "FINANCE" in description or "INSURANCE" in description or "INVESTMENT" in description:
        return "Financials"
    if "REAL ESTATE" in description or "REIT" in description:
        return "Real Estate"
    if "TELEPHONE" in description or "COMMUNICATION" in description or "BROADCAST" in description or "CABLE" in description:
        return "Communication Services"
    if "OIL" in description or "GAS" in description or "PETROLEUM" in description or "COAL" in description:
        return "Energy"
    if "ELECTRIC" in description or "WATER" in description or "UTILITY" in description:
        return "Utilities"
    if "FOOD" in description or "BEVERAGE" in description or "TOBACCO" in description:
        return "Consumer Defensive"
    if "RETAIL" in description or "APPAREL" in description or "RESTAURANT" in description or "HOTEL" in description:
        return "Consumer Cyclical"
    if "MINING" in description or "METAL" in description or "CHEMICAL" in description:
        return "Basic Materials"

    if code is None:
        return "Other"

    major = code // 100
    if major in {35, 36, 37, 73, 48} and major != 38:
        return "Technology"
    if major in {28, 29}:
        return "Energy"
    if major in {60, 61, 62, 63, 64, 65, 67}:
        return "Financials"
    if major in {20, 21}:
        return "Consumer Defensive"
    if major in {22, 23, 25, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59}:
        return "Consumer Cyclical"
    if major in {10, 11, 12, 13, 14}:
        return "Basic Materials"
    if major in {38}:
        return "Healthcare"
    if major in {49}:
        return "Utilities"
    if major in {15, 16, 17, 30, 31, 32, 33, 34, 39, 40, 41, 42, 43, 44, 45, 46, 47, 80, 81, 82, 83, 84, 86, 87, 88, 89}:
        return "Industrials"

    return "Other"


def load_stock_reference_metadata() -> dict[str, dict]:
    global _METADATA_CACHE
    if _METADATA_CACHE is not None:
        return _METADATA_CACHE

    if not METADATA_PATH.exists():
        _METADATA_CACHE = {}
        return _METADATA_CACHE

    with open(METADATA_PATH, encoding="utf-8") as handle:
        raw = json.load(handle)

    normalized: dict[str, dict] = {}
    if isinstance(raw, dict):
        for symbol, payload in raw.items():
            key = _normalize_symbol(symbol)
            if key and isinstance(payload, dict):
                normalized[key] = dict(payload)

    _METADATA_CACHE = normalized
    return _METADATA_CACHE


def load_index_constituents() -> dict[str, set[str]]:
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE

    if not INDEX_CONSTITUENTS_PATH.exists():
        _INDEX_CACHE = {key: set() for key in ("sp500", "dow_jones", "russell_2000")}
        return _INDEX_CACHE

    with open(INDEX_CONSTITUENTS_PATH, encoding="utf-8") as handle:
        raw = json.load(handle)

    _INDEX_CACHE = {
        "sp500": {_normalize_symbol(item) for item in (raw.get("sp500") or []) if _normalize_symbol(item)},
        "dow_jones": {_normalize_symbol(item) for item in (raw.get("dow_jones") or []) if _normalize_symbol(item)},
        "russell_2000": {_normalize_symbol(item) for item in (raw.get("russell_2000") or []) if _normalize_symbol(item)},
    }
    return _INDEX_CACHE


def lookup_stock_reference(symbol) -> dict:
    return dict(load_stock_reference_metadata().get(_normalize_symbol(symbol), {}))


def compute_asset_categories(symbol, metadata=None, index_sets=None) -> list[str]:
    meta = metadata if metadata is not None else lookup_stock_reference(symbol)
    categories: list[str] = []

    exchange_group = meta.get("exchange_group") or exchange_group_from_mic(meta.get("primary_exchange"))
    if exchange_group in {"nasdaq", "nyse", "amex"}:
        categories.append(exchange_group)

    ticker_type = str(meta.get("ticker_type") or meta.get("type") or "").strip().upper()
    if ticker_type == "ETF":
        categories.append("etf")

    index_data = index_sets if index_sets is not None else load_index_constituents()
    normalized_symbol = _normalize_symbol(symbol)
    if normalized_symbol in index_data.get("sp500", set()):
        categories.append("sp500")
    if normalized_symbol in index_data.get("dow_jones", set()):
        categories.append("dow_jones")
    if normalized_symbol in index_data.get("russell_2000", set()):
        categories.append("russell_2000")

    return sorted(set(categories))


def enrich_stock_row(row: dict) -> dict:
    symbol = _normalize_symbol(row.get("symbol"))
    meta = lookup_stock_reference(symbol)
    index_sets = load_index_constituents()

    primary_exchange = meta.get("primary_exchange") or row.get("primary_exchange") or row.get("exchange")
    exchange_group = meta.get("exchange_group") or exchange_group_from_mic(primary_exchange)
    sector = meta.get("sector") or sector_from_sic(meta.get("sic_code"), meta.get("sic_description"))
    ticker_type = meta.get("ticker_type") or meta.get("type")
    asset_categories = compute_asset_categories(symbol, metadata=meta, index_sets=index_sets)

    enriched = dict(row)
    enriched["primary_exchange"] = primary_exchange
    enriched["exchange_group"] = exchange_group
    enriched["exchange"] = primary_exchange or row.get("exchange")
    enriched["sector"] = sector
    enriched["sic_code"] = meta.get("sic_code")
    enriched["sic_description"] = meta.get("sic_description")
    enriched["ticker_type"] = ticker_type
    enriched["asset_categories"] = asset_categories
    enriched["category"] = sector or row.get("category")
    return enriched


ASSET_CATEGORY_LABELS = {
    "nasdaq": "NASDAQ",
    "nyse": "NYSE",
    "amex": "AMEX",
    "etf": "ETF",
    "sp500": "S&P 500",
    "dow_jones": "Dow Jones",
    "russell_2000": "Russell 2000",
}


def asset_category_label(category_id) -> str:
    normalized = _normalize_token(category_id)
    return ASSET_CATEGORY_LABELS.get(normalized, str(category_id or "").replace("_", " ").title())


def list_asset_category_options() -> list[dict[str, str]]:
    return [
        {"id": category_id, "label": asset_category_label(category_id)}
        for category_id in ASSET_CATEGORY_IDS
    ]


def list_stock_filter_options() -> dict[str, list]:
    return {
        "asset_categories": list_asset_category_options(),
        "sectors": list_available_sectors(),
    }


def list_available_sectors() -> list[str]:
    sectors = set(SECTOR_ORDER)
    for payload in load_stock_reference_metadata().values():
        sector = str(payload.get("sector") or "").strip()
        if sector:
            sectors.add(sector)

    ordered = [sector for sector in SECTOR_ORDER if sector in sectors]
    extras = sorted(sector for sector in sectors if sector not in SECTOR_ORDER)
    return ordered + extras


def filter_stock_universe(rows: Iterable[dict], asset_categories=None, sectors=None) -> list[dict]:
    selected_categories = {_normalize_token(item) for item in (asset_categories or []) if item}
    selected_sectors = {str(item).strip() for item in (sectors or []) if str(item).strip()}

    if not selected_categories and not selected_sectors:
        return [enrich_stock_row(dict(row)) for row in rows]

    filtered = []
    for row in rows:
        enriched = enrich_stock_row(dict(row))
        if selected_categories:
            asset_cats = {_normalize_token(item) for item in (enriched.get("asset_categories") or [])}
            if not asset_cats.intersection(selected_categories):
                continue
        if selected_sectors:
            sector = str(enriched.get("sector") or "").strip()
            if sector not in selected_sectors:
                continue
        filtered.append(enriched)

    return filtered


def matches_asset_categories(asset, selected_categories) -> bool:
    selected = {_normalize_token(item) for item in (selected_categories or []) if item}
    if not selected:
        return True
    actual = {_normalize_token(item) for item in (asset.get("asset_categories") or [])}
    return bool(actual.intersection(selected))


def matches_sectors(asset, selected_sectors) -> bool:
    selected = {str(item).strip() for item in (selected_sectors or []) if str(item).strip()}
    if not selected:
        return True
    return str(asset.get("sector") or "").strip() in selected

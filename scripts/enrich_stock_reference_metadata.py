#!/usr/bin/env python3
"""Enrich stock metadata (sector/exchange/type) from Massive and index constituent lists."""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.stock_reference import (  # noqa: E402
    METADATA_PATH,
    INDEX_CONSTITUENTS_PATH,
    exchange_group_from_mic,
    sector_from_sic,
)

load_dotenv(dotenv_path=BACKEND_DIR / ".env")

API_KEY = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
BASE_URL = str(os.getenv("MARKET_DATA_API_BASE_URL") or "https://api.massive.com").rstrip("/")
ZOYA_UNIVERSE_PATH = BACKEND_DIR / "data" / "zoya_universe.json"
LIST_LIMIT = int(os.getenv("MASSIVE_TICKERS_LIMIT", "1000") or "1000")
DETAIL_CONCURRENCY = int(os.getenv("MASSIVE_DETAIL_CONCURRENCY", "20") or "20")

DOW_JONES_30 = [
    "AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "TRV", "UNH", "V", "VZ", "WMT", "AMZN",
]

SP500_CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
RUSSELL_CSV_URL = "https://raw.githubusercontent.com/andonov7/financial-data/master/data/russell2000.csv"


def load_zoya_symbols() -> list[str]:
    with open(ZOYA_UNIVERSE_PATH, encoding="utf-8") as handle:
        rows = json.load(handle)
    symbols = []
    seen = set()
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def fetch_csv_symbols(url: str, symbol_column: str = "Symbol") -> list[str]:
    response = httpx.get(url, timeout=60.0)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    symbols = []
    for row in reader:
        symbol = str(row.get(symbol_column) or row.get("symbol") or row.get("ticker") or "").strip().upper()
        if symbol:
            symbols.append(symbol)
    return symbols


def build_index_constituents() -> dict[str, list[str]]:
    sp500 = fetch_csv_symbols(SP500_CSV_URL, symbol_column="Symbol")
    russell: list[str] = []
    try:
        russell = fetch_csv_symbols(RUSSELL_CSV_URL, symbol_column="Symbol")
    except Exception as exc:
        print(f"Russell 2000 download skipped: {exc}")

    return {
        "sp500": sorted(set(sp500)),
        "dow_jones": sorted(set(DOW_JONES_30)),
        "russell_2000": sorted(set(russell)),
    }


async def fetch_massive_list_metadata(client: httpx.AsyncClient) -> dict[str, dict]:
    metadata: dict[str, dict] = {}
    next_url = f"{BASE_URL}/v3/reference/tickers"
    params = {
        "market": "stocks",
        "locale": "us",
        "active": "true",
        "limit": max(1, LIST_LIMIT),
        "sort": "ticker",
        "order": "asc",
        "apiKey": API_KEY,
    }
    page = 1

    while next_url:
        response = await client.get(next_url, params=params, timeout=60.0)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") or []
        print(f"Fetched Massive list page {page}: {len(rows)} rows")

        for row in rows:
            symbol = str(row.get("ticker") or "").strip().upper()
            if not symbol:
                continue
            primary_exchange = row.get("primary_exchange")
            metadata[symbol] = {
                "primary_exchange": primary_exchange,
                "exchange_group": exchange_group_from_mic(primary_exchange),
                "ticker_type": row.get("type"),
            }

        next_url = payload.get("next_url")
        params = {"apiKey": API_KEY} if next_url else None
        page += 1

    return metadata


async def fetch_ticker_details(client: httpx.AsyncClient, symbol: str) -> dict:
    response = await client.get(
        f"{BASE_URL}/v3/reference/tickers/{symbol}",
        params={"apiKey": API_KEY},
        timeout=30.0,
    )
    response.raise_for_status()
    details = response.json().get("results") or {}
    sic_code = details.get("sic_code")
    sic_description = details.get("sic_description")
    primary_exchange = details.get("primary_exchange")
    return {
        "primary_exchange": primary_exchange,
        "exchange_group": exchange_group_from_mic(primary_exchange),
        "ticker_type": details.get("type"),
        "sic_code": sic_code,
        "sic_description": sic_description,
        "sector": sector_from_sic(sic_code, sic_description),
    }


async def enrich_symbols(symbols: list[str], list_metadata: dict[str, dict]) -> dict[str, dict]:
    semaphore = asyncio.Semaphore(max(1, DETAIL_CONCURRENCY))
    enriched: dict[str, dict] = {}
    total = len(symbols)

    async with httpx.AsyncClient() as client:
        async def worker(index: int, symbol: str):
            async with semaphore:
                base = dict(list_metadata.get(symbol, {}))
                try:
                    detail = await fetch_ticker_details(client, symbol)
                    base.update({key: value for key, value in detail.items() if value is not None})
                except Exception as exc:
                    print(f"detail failed {symbol}: {exc}")
                if "sector" not in base or not base.get("sector"):
                    base["sector"] = sector_from_sic(base.get("sic_code"), base.get("sic_description"))
                enriched[symbol] = base
                if (index + 1) % 100 == 0 or index + 1 == total:
                    print(f"Enriched {index + 1}/{total}")

        await asyncio.gather(*(worker(index, symbol) for index, symbol in enumerate(symbols)))

    return enriched


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


async def main_async(limit: int | None) -> None:
    if not API_KEY:
        raise SystemExit("MASSIVE_API_KEY or POLYGON_API_KEY is required in backend/.env")

    symbols = load_zoya_symbols()
    if limit and limit > 0:
        symbols = symbols[:limit]

    print(f"Building index constituents...")
    index_payload = build_index_constituents()
    save_json(INDEX_CONSTITUENTS_PATH, index_payload)
    print(
        "Index counts:",
        {key: len(value) for key, value in index_payload.items()},
    )

    list_metadata: dict[str, dict] = {}
    print(f"Fetching per-symbol details for {len(symbols)} Zoya symbols...")
    started = time.perf_counter()
    metadata = await enrich_symbols(symbols, list_metadata)
    save_json(METADATA_PATH, metadata)
    print(f"Saved metadata for {len(metadata)} symbols in {time.perf_counter() - started:.1f}s -> {METADATA_PATH}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on Zoya symbols to enrich")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main_async(args.limit if args.limit > 0 else None))

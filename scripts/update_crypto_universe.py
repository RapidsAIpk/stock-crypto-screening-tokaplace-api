# scripts/update_crypto_universe.py
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

API_KEY = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")
MASSIVE_BASE_URL = str(os.getenv("MARKET_DATA_API_BASE_URL") or "https://api.massive.com").rstrip("/")
REFERENCE_TICKERS_URL = f"{MASSIVE_BASE_URL}/v3/reference/tickers"
CRYPTOCOMPARE_ALL_EXCHANGES_URL = "https://min-api.cryptocompare.com/data/v4/all/exchanges"

OUTPUT_FILE = BASE_DIR / "data" / "crypto_universe.json"
INCLUDE_EXCHANGES = os.getenv(
    "CRYPTO_UNIVERSE_INCLUDE_EXCHANGES",
    os.getenv("CMC_INCLUDE_EXCHANGES", "true"),
).lower() == "true"
QUOTE_SYMBOL = str(os.getenv("CRYPTO_UNIVERSE_QUOTE_SYMBOL") or "USD").strip().upper() or "USD"
LIST_LIMIT = int(os.getenv("MASSIVE_TICKERS_LIMIT", "1000") or "1000")
CRYPTOCOMPARE_CALL_SLEEP_SECONDS = float(os.getenv("CRYPTOCOMPARE_CALL_SLEEP_SECONDS", "0.2") or "0.2")
REQUEST_TIMEOUT_SECONDS = int(
    os.getenv(
        "CRYPTO_UNIVERSE_REQUEST_TIMEOUT_SECONDS",
        os.getenv("CMC_REQUEST_TIMEOUT_SECONDS", "30"),
    )
    or "30"
)
REQUEST_MAX_RETRIES = int(
    os.getenv(
        "CRYPTO_UNIVERSE_REQUEST_MAX_RETRIES",
        os.getenv("CMC_REQUEST_MAX_RETRIES", "6"),
    )
    or "6"
)
REQUEST_RETRY_BACKOFF_SECONDS = float(
    os.getenv(
        "CRYPTO_UNIVERSE_REQUEST_RETRY_BACKOFF_SECONDS",
        os.getenv("CMC_REQUEST_RETRY_BACKOFF_SECONDS", "1.5"),
    )
    or "1.5"
)
REQUEST_RETRY_MAX_SLEEP_SECONDS = float(
    os.getenv(
        "CRYPTO_UNIVERSE_REQUEST_RETRY_MAX_SLEEP_SECONDS",
        os.getenv("CMC_REQUEST_RETRY_MAX_SLEEP_SECONDS", "60"),
    )
    or "60"
)

CRYPTOCOMPARE_HEADERS = {
    "authorization": f"Apikey {CRYPTOCOMPARE_API_KEY}"
} if CRYPTOCOMPARE_API_KEY else {}


def _retry_sleep_seconds(response: Optional[requests.Response], attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return min(parsed, REQUEST_RETRY_MAX_SLEEP_SECONDS)
            except ValueError:
                pass

    backoff = REQUEST_RETRY_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
    return min(backoff, REQUEST_RETRY_MAX_SLEEP_SECONDS)


def massive_get(url, params, context):
    last_exception = None

    for attempt in range(1, REQUEST_MAX_RETRIES + 1):
        response = None
        try:
            query = dict(params or {})
            query["apiKey"] = API_KEY
            response = requests.get(
                url,
                params=query,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                sleep_for = _retry_sleep_seconds(response, attempt)
                print(f"[rate-limit] {context}: attempt={attempt}/{REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue

            if response.status_code in {401, 403}:
                raise requests.HTTPError(
                    f"[forbidden] {context}: status={response.status_code}, endpoint/key permission denied",
                    response=response,
                )

            if 500 <= response.status_code < 600:
                sleep_for = _retry_sleep_seconds(response, attempt)
                print(
                    f"[server-error] {context}: status={response.status_code}, "
                    f"attempt={attempt}/{REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s"
                )
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exception = exc
            sleep_for = _retry_sleep_seconds(response, attempt)
            print(
                f"[request-error] {context}: attempt={attempt}/{REQUEST_MAX_RETRIES}, "
                f"sleep={sleep_for:.1f}s, error={exc}"
            )
            time.sleep(sleep_for)

    if last_exception is not None:
        raise last_exception

    raise RuntimeError(f"{context} failed without response")


def cryptocompare_get(url, params=None, context="", allow_soft_fail=False):
    last_exception = None

    for attempt in range(1, REQUEST_MAX_RETRIES + 1):
        response = None
        try:
            response = requests.get(
                url,
                headers=CRYPTOCOMPARE_HEADERS,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                sleep_for = _retry_sleep_seconds(response, attempt)
                print(f"[rate-limit] {context}: attempt={attempt}/{REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s")
                time.sleep(sleep_for)
                continue

            if response.status_code in {401, 402, 403}:
                message = f"[forbidden] {context}: status={response.status_code}, endpoint permission denied"
                if allow_soft_fail:
                    print(f"{message}. Continuing with fallback.")
                    return None
                raise requests.HTTPError(message, response=response)

            if 500 <= response.status_code < 600:
                sleep_for = _retry_sleep_seconds(response, attempt)
                print(
                    f"[server-error] {context}: status={response.status_code}, "
                    f"attempt={attempt}/{REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s"
                )
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exception = exc
            sleep_for = _retry_sleep_seconds(response, attempt)
            print(
                f"[request-error] {context}: attempt={attempt}/{REQUEST_MAX_RETRIES}, "
                f"sleep={sleep_for:.1f}s, error={exc}"
            )
            time.sleep(sleep_for)

    if allow_soft_fail:
        print(f"[warning] {context}: failed after {REQUEST_MAX_RETRIES} attempts, continuing with fallback")
        return None

    if last_exception is not None:
        raise last_exception

    raise RuntimeError(f"{context} failed without response")


def _normalize_exchange_name(value):
    if not value:
        return ""
    return str(value).strip().lower().replace(" ", "-")


def _normalize_symbol(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def _preferred_provider_ticker(symbol):
    return f"X:{symbol}{QUOTE_SYMBOL}"


def _coin_name_from_massive_row(row):
    base_name = str(row.get("base_currency_name") or "").strip()
    if base_name:
        return base_name

    full_name = str(row.get("name") or "").strip()
    if " - " in full_name:
        return full_name.split(" - ", 1)[0].strip()
    return full_name


def _normalize_massive_coin(row):
    if not isinstance(row, dict):
        return None

    if row.get("active") is False:
        return None

    quote_symbol = _normalize_symbol(row.get("currency_symbol"))
    if quote_symbol != QUOTE_SYMBOL:
        return None

    symbol = _normalize_symbol(row.get("base_currency_symbol"))
    if not symbol:
        return None

    ticker = str(row.get("ticker") or "").strip().upper()
    return {
        "symbol": symbol,
        "name": _coin_name_from_massive_row(row) or symbol,
        # Massive's reference-tickers endpoint does not expose tag/category metadata.
        "category": "general",
        "_ticker": ticker,
    }


def _should_replace_massive_coin(existing, candidate):
    if existing is None:
        return True

    preferred_ticker = _preferred_provider_ticker(candidate["symbol"])
    existing_is_preferred = existing.get("_ticker") == preferred_ticker
    candidate_is_preferred = candidate.get("_ticker") == preferred_ticker

    if candidate_is_preferred and not existing_is_preferred:
        return True
    if existing_is_preferred and not candidate_is_preferred:
        return False

    return (candidate.get("_ticker") or "") < (existing.get("_ticker") or "")


def fetch_coin_list():
    coins_by_symbol = {}
    next_url = REFERENCE_TICKERS_URL
    params = {
        "market": "crypto",
        "locale": "global",
        "active": "true",
        "limit": max(1, LIST_LIMIT),
        "sort": "ticker",
        "order": "asc",
    }
    page_number = 1

    while next_url:
        payload = massive_get(
            next_url,
            params=params,
            context=f"reference/tickers page={page_number}",
        )
        rows = payload.get("results", [])

        print(f"Fetched Massive page {page_number}: {len(rows)} rows")

        for row in rows:
            normalized = _normalize_massive_coin(row)
            if normalized is None:
                continue

            symbol = normalized["symbol"]
            existing = coins_by_symbol.get(symbol)
            if _should_replace_massive_coin(existing, normalized):
                coins_by_symbol[symbol] = normalized

        next_url = payload.get("next_url")
        params = None
        page_number += 1

    results = []
    for symbol in sorted(coins_by_symbol):
        coin = dict(coins_by_symbol[symbol])
        coin.pop("_ticker", None)
        results.append(coin)

    return results


def fetch_coin_exchanges_from_cryptocompare(symbol):
    fsym = _normalize_symbol(symbol)
    if not fsym:
        return []

    payload = cryptocompare_get(
        CRYPTOCOMPARE_ALL_EXCHANGES_URL,
        params={"fsym": fsym},
        context=f"cryptocompare/all-exchanges fsym={fsym}",
        allow_soft_fail=True,
    )
    if not payload:
        return []

    exchanges_data = ((payload.get("Data") or {}).get("exchanges") or {})
    exchanges = set()
    for exchange_name, exchange_info in exchanges_data.items():
        if isinstance(exchange_info, dict) and exchange_info.get("isActive") is False:
            continue
        exchange_name = _normalize_exchange_name(exchange_name)
        if exchange_name:
            exchanges.add(exchange_name)

    return sorted(exchanges)


def build_universe():
    coins = fetch_coin_list()
    results = []
    exchange_cache = {}

    print(f"Collected {len(coins)} active {QUOTE_SYMBOL}-quoted crypto symbols from Massive")

    for index, coin in enumerate(coins, start=1):
        exchanges = []

        if INCLUDE_EXCHANGES:
            symbol = coin["symbol"]
            if symbol not in exchange_cache:
                exchange_cache[symbol] = fetch_coin_exchanges_from_cryptocompare(symbol)
                if index < len(coins):
                    time.sleep(CRYPTOCOMPARE_CALL_SLEEP_SECONDS)
            exchanges = exchange_cache[symbol]

        results.append(
            {
                "symbol": coin["symbol"],
                "name": coin["name"],
                "category": coin["category"],
                "exchanges": exchanges,
            }
        )

        if index % 100 == 0 or index == len(coins):
            print(f"Processed {index}/{len(coins)} symbols")

    return results


def save(data):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)

    print("Saved:", OUTPUT_FILE)
    print("Total coins:", len(data))


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("MASSIVE_API_KEY or POLYGON_API_KEY is required in backend/.env")
    if INCLUDE_EXCHANGES and not CRYPTOCOMPARE_API_KEY:
        raise SystemExit("CRYPTOCOMPARE_API_KEY is required when exchange enrichment is enabled")

    print("Downloading Massive crypto universe...")

    universe = build_universe()

    save(universe)

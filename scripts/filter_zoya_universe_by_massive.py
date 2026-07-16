# scripts/filter_zoya_universe_by_massive.py
import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

API_KEY = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
MASSIVE_BASE_URL = str(os.getenv("MARKET_DATA_API_BASE_URL") or "https://api.massive.com").rstrip("/")
REFERENCE_TICKERS_URL = f"{MASSIVE_BASE_URL}/v3/reference/tickers"
DEFAULT_INPUT_FILE = BASE_DIR / "data" / "zoya_universe.json"
DEFAULT_REQUEST_TIMEOUT_SECONDS = int(os.getenv("ZOYA_UNIVERSE_REQUEST_TIMEOUT_SECONDS", "30") or "30")
DEFAULT_REQUEST_MAX_RETRIES = int(os.getenv("ZOYA_UNIVERSE_REQUEST_MAX_RETRIES", "6") or "6")
DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS = float(
    os.getenv("ZOYA_UNIVERSE_REQUEST_RETRY_BACKOFF_SECONDS", "1.5") or "1.5"
)
DEFAULT_REQUEST_RETRY_MAX_SLEEP_SECONDS = float(
    os.getenv("ZOYA_UNIVERSE_REQUEST_RETRY_MAX_SLEEP_SECONDS", "60") or "60"
)
LIST_LIMIT = int(os.getenv("MASSIVE_TICKERS_LIMIT", "1000") or "1000")


def _retry_sleep_seconds(response: Optional[requests.Response], attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                parsed = float(retry_after)
                if parsed > 0:
                    return min(parsed, DEFAULT_REQUEST_RETRY_MAX_SLEEP_SECONDS)
            except ValueError:
                pass

    backoff = DEFAULT_REQUEST_RETRY_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
    return min(backoff, DEFAULT_REQUEST_RETRY_MAX_SLEEP_SECONDS)


def massive_get(url, params, context):
    last_exception = None

    for attempt in range(1, DEFAULT_REQUEST_MAX_RETRIES + 1):
        response = None
        try:
            query = dict(params or {})
            query["apiKey"] = API_KEY
            response = requests.get(
                url,
                params=query,
                timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                sleep_for = _retry_sleep_seconds(response, attempt)
                print(f"[rate-limit] {context}: attempt={attempt}/{DEFAULT_REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s")
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
                    f"attempt={attempt}/{DEFAULT_REQUEST_MAX_RETRIES}, sleep={sleep_for:.1f}s"
                )
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_exception = exc
            sleep_for = _retry_sleep_seconds(response, attempt)
            print(
                f"[request-error] {context}: attempt={attempt}/{DEFAULT_REQUEST_MAX_RETRIES}, "
                f"sleep={sleep_for:.1f}s, error={exc}"
            )
            time.sleep(sleep_for)

    if last_exception is not None:
        raise last_exception

    raise RuntimeError(f"{context} failed without response")


def _normalize_symbol(value) -> str:
    return str(value or "").strip().upper()


def fetch_supported_stock_symbols() -> set[str]:
    supported = set()
    next_url = REFERENCE_TICKERS_URL
    params = {
        "market": "stocks",
        "locale": "us",
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
        print(f"Fetched Massive stock page {page_number}: {len(rows)} rows")

        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("active") is False:
                continue
            symbol = _normalize_symbol(row.get("ticker"))
            if symbol:
                supported.add(symbol)

        next_url = payload.get("next_url")
        params = None
        page_number += 1

    return supported


def filter_zoya_universe(items: Iterable[dict], supported_symbols: set[str]) -> Tuple[list[dict], list[dict]]:
    kept = []
    removed = []

    for item in items:
        symbol = _normalize_symbol((item or {}).get("symbol"))
        if symbol and symbol in supported_symbols:
            kept.append(item)
            continue
        removed.append(item)

    return kept, removed


def load_universe(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_universe(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(items, handle, indent=2)


def maybe_write_backup(input_path: Path, output_path: Path, create_backup: bool) -> Optional[Path]:
    if not create_backup or input_path.resolve() != output_path.resolve() or not input_path.exists():
        return None

    backup_path = input_path.with_suffix(f"{input_path.suffix}.bak")
    shutil.copy2(input_path, backup_path)
    return backup_path


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Filter backend/data/zoya_universe.json down to symbols that exist in "
            "Massive's active US stocks reference tickers list."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_FILE,
        help=f"Input Zoya universe JSON file. Default: {DEFAULT_INPUT_FILE}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_INPUT_FILE,
        help="Output JSON file. Defaults to in-place overwrite.",
    )
    parser.add_argument(
        "--removed-output",
        type=Path,
        default=None,
        help="Optional JSON file where removed rows will be written.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create a .bak file when writing in place.",
    )
    return parser.parse_args()


def main():
    if not API_KEY:
        raise SystemExit("MASSIVE_API_KEY or POLYGON_API_KEY is required in backend/.env")

    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    removed_output_path = args.removed_output.resolve() if args.removed_output else None

    print(f"Loading Zoya universe from: {input_path}")
    zoya_items = load_universe(input_path)
    print(f"Loaded {len(zoya_items)} rows")

    print("Downloading Massive stock reference tickers...")
    supported_symbols = fetch_supported_stock_symbols()
    print(f"Collected {len(supported_symbols)} Massive-supported active stock tickers")

    kept, removed = filter_zoya_universe(zoya_items, supported_symbols)
    backup_path = maybe_write_backup(input_path, output_path, create_backup=not args.no_backup)

    save_universe(output_path, kept)
    if removed_output_path is not None:
        save_universe(removed_output_path, removed)

    print(f"Kept: {len(kept)}")
    print(f"Removed: {len(removed)}")
    print(f"Saved filtered universe to: {output_path}")
    if backup_path is not None:
        print(f"Created backup: {backup_path}")
    if removed_output_path is not None:
        print(f"Saved removed rows to: {removed_output_path}")
    if removed:
        sample_symbols = [_normalize_symbol(item.get('symbol')) for item in removed[:20]]
        print(f"Sample removed symbols: {', '.join(symbol for symbol in sample_symbols if symbol)}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from production_screener_validation.capture import MassiveFixtureCapture  # noqa: E402
from production_screener_validation.fixture_store import FixtureStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Permanently freeze Massive candles for production screener validation.")
    parser.add_argument("--fixture-id", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--timeframes", nargs="+", default=["1day"])
    parser.add_argument("--metadata", type=Path, required=True, help="JSON object keyed by symbol")
    parser.add_argument("--root", type=Path, default=BACKEND / "production_screener_validation" / "data")
    args = parser.parse_args()
    load_dotenv(BACKEND / ".env")
    key = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or ""
    capture = MassiveFixtureCapture(key, base_url=os.getenv("MARKET_DATA_API_BASE_URL", "https://api.massive.com"))
    candles: dict[str, dict[str, list[dict]]] = {timeframe: {} for timeframe in args.timeframes}
    raw: dict[str, dict] = {}
    requests_used = 0
    try:
        for timeframe in args.timeframes:
            raw[timeframe] = {}
            for symbol in args.symbols:
                payload, rows = capture.fetch(symbol, args.start, args.end, timeframe)
                raw[timeframe][symbol.upper()] = payload
                candles[timeframe][symbol.upper()] = rows
                requests_used += 1
                print(f"Fetched {symbol.upper()} {timeframe}: {len(rows)} candles")
    finally:
        capture.close()
    metadata = json.loads(args.metadata.read_text("utf-8"))
    path = FixtureStore(args.root).create(
        args.fixture_id,
        candles,
        metadata,
        provider_requests=requests_used,
        provider_raw=raw,
    )
    print(f"Frozen fixture: {path}")
    print(f"API requests used: {requests_used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

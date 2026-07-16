import json
import sqlite3
import threading
import time
from pathlib import Path


TTL_BY_TIMEFRAME = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1day": 24 * 60 * 60,
    "2day": 2 * 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
    "1mo": 30 * 24 * 60 * 60,
}

RETENTION_BY_TIMEFRAME = {
    "1m": 2 * 60 * 60,
    "5m": 6 * 60 * 60,
    "15m": 24 * 60 * 60,
    "30m": 2 * 24 * 60 * 60,
    "1h": 7 * 24 * 60 * 60,
    "4h": 14 * 24 * 60 * 60,
    "1day": 30 * 24 * 60 * 60,
    "2day": 45 * 24 * 60 * 60,
    "1w": 120 * 24 * 60 * 60,
    "1mo": 365 * 24 * 60 * 60,
}

DEFAULT_TTL = 60 * 60
DEFAULT_RETENTION = 7 * 24 * 60 * 60

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "market_data_cache.db"


class MarketDataStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data_cache (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indicator_cache (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_data_interest (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    last_requested_at INTEGER NOT NULL,
                    last_refreshed_at INTEGER,
                    next_refresh_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indicator_interest (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    last_requested_at INTEGER NOT NULL,
                    last_refreshed_at INTEGER,
                    next_refresh_at INTEGER NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_interest_refresh
                ON market_data_interest (next_refresh_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_indicator_interest_refresh
                ON indicator_interest (next_refresh_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_indicator_interest_requested
                ON indicator_interest (last_requested_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_data_interest_requested
                ON market_data_interest (last_requested_at)
                """
            )
            conn.commit()

    def ttl_for(self, timeframe: str) -> int:
        return TTL_BY_TIMEFRAME.get(timeframe, DEFAULT_TTL)

    def retention_for(self, timeframe: str) -> int:
        return RETENTION_BY_TIMEFRAME.get(timeframe, DEFAULT_RETENTION)

    def register_interest(self, symbols, timeframe: str, next_refresh_map=None):
        if not symbols:
            return

        now = int(time.time())
        next_refresh_map = next_refresh_map or {}

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO market_data_interest (
                    symbol,
                    timeframe,
                    last_requested_at,
                    last_refreshed_at,
                    next_refresh_at
                )
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    last_requested_at = excluded.last_requested_at,
                    next_refresh_at = MIN(market_data_interest.next_refresh_at, excluded.next_refresh_at)
                """,
                [
                    (
                        symbol,
                        timeframe,
                        now,
                        int(next_refresh_map.get(symbol, now + self.ttl_for(timeframe))),
                    )
                    for symbol in symbols
                ],
            )
            conn.commit()

    def get_cached(self, symbols, timeframe: str):
        if not symbols:
            return {}

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, payload, updated_at
                FROM market_data_cache
                WHERE timeframe = ?
                AND symbol IN ({",".join("?" for _ in symbols)})
                """,
                [timeframe, *symbols],
            ).fetchall()

        return {
            row["symbol"]: {
                "payload": json.loads(row["payload"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def store_snapshots(self, items, timeframe: str):
        if not items:
            return

        now = int(time.time())

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO market_data_cache (
                    symbol,
                    timeframe,
                    payload,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        item["symbol"],
                        timeframe,
                        json.dumps(item),
                        now,
                    )
                    for item in items
                ],
            )
            conn.executemany(
                """
                INSERT INTO market_data_interest (
                    symbol,
                    timeframe,
                    last_requested_at,
                    last_refreshed_at,
                    next_refresh_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    last_refreshed_at = excluded.last_refreshed_at,
                    next_refresh_at = excluded.next_refresh_at
                """,
                [
                    (
                        item["symbol"],
                        timeframe,
                        now,
                        now,
                        int(item.get("next_refresh_at", now + self.ttl_for(timeframe))),
                    )
                    for item in items
                ],
            )
            conn.commit()

    def due_symbols(self, limit: int = 500):
        now = int(time.time())

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, timeframe
                FROM market_data_interest
                WHERE next_refresh_at <= ?
                ORDER BY next_refresh_at ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()

        due = {}
        for row in rows:
            due.setdefault(row["timeframe"], []).append(row["symbol"])
        return due

    def update_interest_schedule(self, symbols, timeframe: str, next_refresh_map):
        if not symbols or not next_refresh_map:
            return

        now = int(time.time())

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO market_data_interest (
                    symbol,
                    timeframe,
                    last_requested_at,
                    last_refreshed_at,
                    next_refresh_at
                )
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    last_requested_at = excluded.last_requested_at,
                    next_refresh_at = excluded.next_refresh_at
                """,
                [
                    (
                        symbol,
                        timeframe,
                        now,
                        int(next_refresh_map[symbol]),
                    )
                    for symbol in symbols
                    if symbol in next_refresh_map
                ],
            )
            conn.commit()

    def clear_interest(self, symbols, timeframe: str):
        if not symbols:
            return

        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                DELETE FROM market_data_interest
                WHERE timeframe = ?
                AND symbol IN ({",".join("?" for _ in symbols)})
                """,
                [timeframe, *symbols],
            )
            conn.commit()

    def clear_interest_for_timeframes(self, timeframes):
        if not timeframes:
            return

        normalized = [str(timeframe) for timeframe in timeframes if str(timeframe)]
        if not normalized:
            return

        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                DELETE FROM market_data_interest
                WHERE timeframe IN ({",".join("?" for _ in normalized)})
                """,
                normalized,
            )
            conn.commit()

    def register_indicator_interest(self, symbols, timeframe: str, next_refresh_map=None):
        if not symbols:
            return

        now = int(time.time())
        next_refresh_map = next_refresh_map or {}

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO indicator_interest (
                    symbol,
                    timeframe,
                    last_requested_at,
                    last_refreshed_at,
                    next_refresh_at
                )
                VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    last_requested_at = excluded.last_requested_at,
                    next_refresh_at = MIN(indicator_interest.next_refresh_at, excluded.next_refresh_at)
                """,
                [
                    (
                        symbol,
                        timeframe,
                        now,
                        int(next_refresh_map.get(symbol, now + self.ttl_for(timeframe))),
                    )
                    for symbol in symbols
                ],
            )
            conn.commit()

    def get_cached_indicators(self, symbols, timeframe: str):
        if not symbols:
            return {}

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT symbol, payload, updated_at
                FROM indicator_cache
                WHERE timeframe = ?
                AND symbol IN ({",".join("?" for _ in symbols)})
                """,
                [timeframe, *symbols],
            ).fetchall()

        return {
            row["symbol"]: {
                "payload": json.loads(row["payload"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def store_indicator_snapshots(self, items, timeframe: str):
        if not items:
            return

        now = int(time.time())

        with self._lock, self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO indicator_cache (
                    symbol,
                    timeframe,
                    payload,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        item["symbol"],
                        timeframe,
                        json.dumps(item),
                        now,
                    )
                    for item in items
                ],
            )
            conn.executemany(
                """
                INSERT INTO indicator_interest (
                    symbol,
                    timeframe,
                    last_requested_at,
                    last_refreshed_at,
                    next_refresh_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe) DO UPDATE SET
                    last_refreshed_at = excluded.last_refreshed_at,
                    next_refresh_at = excluded.next_refresh_at
                """,
                [
                    (
                        item["symbol"],
                        timeframe,
                        now,
                        now,
                        int(item.get("next_refresh_at", now + self.ttl_for(timeframe))),
                    )
                    for item in items
                ],
            )
            conn.commit()

    def prune(self):
        now = int(time.time())

        with self._lock, self._connect() as conn:
            interest_rows = conn.execute(
                """
                SELECT symbol, timeframe, last_requested_at
                FROM market_data_interest
                """
            ).fetchall()

            stale_pairs = [
                (row["symbol"], row["timeframe"])
                for row in interest_rows
                if now - row["last_requested_at"] > self.retention_for(row["timeframe"])
            ]

            if stale_pairs:
                conn.executemany(
                    """
                    DELETE FROM market_data_interest
                    WHERE symbol = ? AND timeframe = ?
                    """,
                    stale_pairs,
                )
                conn.executemany(
                    """
                    DELETE FROM market_data_cache
                    WHERE symbol = ? AND timeframe = ?
                    """,
                    stale_pairs,
                )

            indicator_rows = conn.execute(
                """
                SELECT symbol, timeframe, last_requested_at
                FROM indicator_interest
                """
            ).fetchall()

            stale_indicator_pairs = [
                (row["symbol"], row["timeframe"])
                for row in indicator_rows
                if now - row["last_requested_at"] > self.retention_for(row["timeframe"])
            ]

            if stale_indicator_pairs:
                conn.executemany(
                    """
                    DELETE FROM indicator_interest
                    WHERE symbol = ? AND timeframe = ?
                    """,
                    stale_indicator_pairs,
                )
                conn.executemany(
                    """
                    DELETE FROM indicator_cache
                    WHERE symbol = ? AND timeframe = ?
                    """,
                    stale_indicator_pairs,
                )

            conn.commit()


store = MarketDataStore()

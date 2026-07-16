import json
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "market_data_cache.db"


class GateSessionStore:
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
                CREATE TABLE IF NOT EXISTS gate_sessions (
                    session_id TEXT PRIMARY KEY,
                    scope_hash TEXT NOT NULL,
                    client_id TEXT,
                    metadata TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gate_sessions_expires_at
                ON gate_sessions (expires_at)
                """
            )
            conn.commit()

    def prune(self, now=None):
        reference = int(time.time()) if now is None else int(now)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                DELETE FROM gate_sessions
                WHERE expires_at <= ?
                """,
                (reference,),
            )
            conn.commit()

    def store(self, metadata, ttl_seconds: int, scope_hash: str, client_id: str | None):
        now = int(time.time())
        session_id = str(uuid4())
        expires_at = now + int(ttl_seconds)

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gate_sessions (
                    session_id,
                    scope_hash,
                    client_id,
                    metadata,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    scope_hash,
                    client_id,
                    json.dumps(metadata),
                    now,
                    expires_at,
                ),
            )
            conn.commit()

        return session_id

    def consume(self, session_id: str, scope_hash: str, client_id: str | None, delete: bool = True):
        now = int(time.time())
        self.prune(now=now)

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, scope_hash, client_id, metadata, expires_at
                FROM gate_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            if row is None:
                return []

            if row["expires_at"] <= now:
                conn.execute(
                    "DELETE FROM gate_sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                return []

            if row["scope_hash"] != scope_hash:
                return []

            stored_client_id = row["client_id"]
            if stored_client_id and stored_client_id != client_id:
                return []

            if delete:
                conn.execute(
                    "DELETE FROM gate_sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()

            return json.loads(row["metadata"])

    def restore(self, session_id: str, metadata, scope_hash: str, client_id: str | None, ttl_seconds: int):
        now = int(time.time())
        expires_at = now + int(ttl_seconds)

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO gate_sessions (
                    session_id,
                    scope_hash,
                    client_id,
                    metadata,
                    created_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    scope_hash,
                    client_id,
                    json.dumps(metadata),
                    now,
                    expires_at,
                ),
            )
            conn.commit()

    def delete(self, session_id: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM gate_sessions WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()


store = GateSessionStore()

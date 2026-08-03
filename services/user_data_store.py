import json
import sqlite3
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "auth.db"


class UserDataStore:
    """Per-user settings/presets/watchlist blob, keyed by our own user_id.

    Mirrors the shallow-merge semantics of the Firestore setDoc(..., {merge:
    true}) call this replaces: a save only touches the top-level keys it
    supplies, leaving the rest of the stored document untouched.
    """

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
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def get(self, user_id: str) -> dict:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if row is None:
            return {}

        try:
            parsed = json.loads(row["data"])
        except (TypeError, ValueError):
            return {}

        return parsed if isinstance(parsed, dict) else {}

    def save(self, user_id: str, partial: dict) -> dict:
        now = int(time.time())

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM user_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            try:
                current = json.loads(row["data"]) if row else {}
                if not isinstance(current, dict):
                    current = {}
            except (TypeError, ValueError):
                current = {}

            merged = {**current, **(partial or {})}

            conn.execute(
                """
                INSERT INTO user_settings (user_id, data, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (user_id, json.dumps(merged), now),
            )
            conn.commit()

        return merged


store = UserDataStore()

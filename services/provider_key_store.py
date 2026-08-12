import sqlite3
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "auth.db"

SUPPORTED_PROVIDERS = ("massive", "zoya")


class ProviderKeyStore:
    """Per-user provider API keys, stored separately from the general
    settings blob so they are never echoed back to the frontend on a
    normal settings fetch. Only status (configured + last 4 chars) is
    ever returned; the raw key is only read back out server-side, for
    making the actual provider request.
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
                CREATE TABLE IF NOT EXISTS provider_api_keys (
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, provider)
                )
                """
            )
            conn.commit()

    def _require_provider(self, provider: str) -> str:
        normalized = str(provider or "").strip().lower()
        if normalized not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        return normalized

    def save(self, user_id: str, provider: str, api_key: str) -> None:
        provider = self._require_provider(provider)
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("api_key is required")

        now = int(time.time())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_api_keys (user_id, provider, api_key, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    api_key = excluded.api_key,
                    updated_at = excluded.updated_at
                """,
                (user_id, provider, key, now),
            )
            conn.commit()

    def get_raw(self, user_id: str, provider: str) -> str | None:
        """Server-side only. Never expose this value to the frontend."""
        provider = self._require_provider(provider)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT api_key FROM provider_api_keys WHERE user_id = ? AND provider = ?",
                (user_id, provider),
            ).fetchone()
        return row["api_key"] if row else None

    def status(self, user_id: str) -> dict:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT provider, api_key, updated_at FROM provider_api_keys WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        by_provider = {row["provider"]: row for row in rows}
        result = {}
        for provider in SUPPORTED_PROVIDERS:
            row = by_provider.get(provider)
            if row is None:
                result[provider] = {"configured": False, "last4": None, "updated_at": None}
            else:
                key = row["api_key"]
                result[provider] = {
                    "configured": True,
                    "last4": key[-4:] if len(key) >= 4 else None,
                    "updated_at": row["updated_at"],
                }
        return result


store = ProviderKeyStore()

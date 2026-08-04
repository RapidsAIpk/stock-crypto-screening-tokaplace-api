import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "auth.db"

MAX_ACCOUNTS = 2
PBKDF2_ITERATIONS = 260_000


def _hash_key(plaintext: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", plaintext.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex()


class SignupGateStore:
    """Gates Firebase account creation behind a single shared invite key and
    a hard cap of MAX_ACCOUNTS registered Firebase UIDs.

    Firebase Auth remains the actual identity provider - this store never
    sees passwords. It only holds the hashed invite key and the list of
    Firebase UIDs that have been allowed to register.
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
                CREATE TABLE IF NOT EXISTS signup_gate (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    key_salt TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS registered_accounts (
                    uid TEXT PRIMARY KEY,
                    email TEXT,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def set_invite_key(self, plaintext: str) -> None:
        salt = secrets.token_bytes(16)
        key_hash = _hash_key(plaintext, salt)
        now = int(time.time())

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signup_gate (id, key_salt, key_hash, created_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    key_salt = excluded.key_salt,
                    key_hash = excluded.key_hash,
                    created_at = excluded.created_at
                """,
                (salt.hex(), key_hash, now),
            )
            conn.commit()

    def verify_invite_key(self, candidate: str) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT key_salt, key_hash FROM signup_gate WHERE id = 1"
            ).fetchone()

        if row is None:
            return False

        salt = bytes.fromhex(row["key_salt"])
        candidate_hash = _hash_key(candidate or "", salt)
        return secrets.compare_digest(candidate_hash, row["key_hash"])

    def account_count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM registered_accounts").fetchone()
        return row["c"]

    def slot_available(self) -> bool:
        return self.account_count() < MAX_ACCOUNTS

    def register_account(self, uid: str, email: str | None) -> None:
        """Raises ValueError if the account cap has been reached."""
        now = int(time.time())

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT uid FROM registered_accounts WHERE uid = ?", (uid,)
            ).fetchone()
            if existing:
                return  # already registered - idempotent on retry

            count = conn.execute(
                "SELECT COUNT(*) AS c FROM registered_accounts"
            ).fetchone()["c"]
            if count >= MAX_ACCOUNTS:
                raise ValueError(f"Account limit reached ({MAX_ACCOUNTS} max).")

            conn.execute(
                "INSERT INTO registered_accounts (uid, email, created_at) VALUES (?, ?, ?)",
                (uid, email, now),
            )
            conn.commit()


store = SignupGateStore()

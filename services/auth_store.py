import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from uuid import uuid4

import bcrypt

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "auth.db"

MAX_ACCOUNTS = 2
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for any rejected auth operation (bad credentials, validation, etc.)."""


class AccountLimitError(AuthError):
    """Raised when registration is attempted after MAX_ACCOUNTS already exist."""


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _normalize_answer(answer: str) -> str:
    return (answer or "").strip().lower()


def _hash_secret(value: str) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_secret(value: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class AuthStore:
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
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    security_question TEXT NOT NULL,
                    security_answer_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at "
                "ON auth_sessions (expires_at)"
            )
            conn.commit()

    # ---------------- accounts ----------------

    def register(
        self,
        email: str,
        password: str,
        security_question: str,
        security_answer: str,
    ) -> dict:
        normalized_email = _normalize_email(email)
        if not EMAIL_RE.match(normalized_email):
            raise AuthError("Enter a valid email address.")
        if not password or len(password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        question = (security_question or "").strip()
        if not question:
            raise AuthError("Security question is required.")
        if not (security_answer or "").strip():
            raise AuthError("Security answer is required.")

        password_hash = _hash_secret(password)
        answer_hash = _hash_secret(_normalize_answer(security_answer))
        user_id = str(uuid4())
        now = int(time.time())

        with self._lock, self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM auth_users").fetchone()["c"]
            if count >= MAX_ACCOUNTS:
                raise AccountLimitError(
                    f"Account limit reached ({MAX_ACCOUNTS} max). No new accounts can be created."
                )

            existing = conn.execute(
                "SELECT user_id FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            if existing:
                raise AuthError("An account with that email already exists.")

            conn.execute(
                """
                INSERT INTO auth_users (
                    user_id, email, password_hash, security_question,
                    security_answer_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, normalized_email, password_hash, question, answer_hash, now),
            )
            conn.commit()

        return {"user_id": user_id, "email": normalized_email}

    def verify_login(self, email: str, password: str) -> dict:
        normalized_email = _normalize_email(email)

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, email, password_hash FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        if row is None or not _verify_secret(password, row["password_hash"]):
            raise AuthError("Invalid email or password.")

        return {"user_id": row["user_id"], "email": row["email"]}

    def get_security_question(self, email: str) -> dict:
        normalized_email = _normalize_email(email)

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT security_question FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()

        if row is None:
            raise AuthError("No account found for that email.")

        return {"question": row["security_question"]}

    def reset_password(self, email: str, security_answer: str, new_password: str) -> None:
        """Forgot-password flow: verify the security answer, then set a new password."""
        normalized_email = _normalize_email(email)
        if not new_password or len(new_password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, security_answer_hash FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()

            if row is None or not _verify_secret(
                _normalize_answer(security_answer), row["security_answer_hash"]
            ):
                raise AuthError("Incorrect answer to security question.")

            new_hash = _hash_secret(new_password)
            conn.execute(
                "UPDATE auth_users SET password_hash = ? WHERE user_id = ?",
                (new_hash, row["user_id"]),
            )
            # A password reset invalidates every existing session for this
            # account, so a stolen/expired browser session can't linger past
            # a deliberate password change.
            conn.execute(
                "DELETE FROM auth_sessions WHERE user_id = ?",
                (row["user_id"],),
            )
            conn.commit()

    def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        """Logged-in flow: verify the current password, then set a new one."""
        if not new_password or len(new_password) < 8:
            raise AuthError("Password must be at least 8 characters.")

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM auth_users WHERE user_id = ?",
                (user_id,),
            ).fetchone()

            if row is None or not _verify_secret(current_password, row["password_hash"]):
                raise AuthError("Current password is incorrect.")

            new_hash = _hash_secret(new_password)
            conn.execute(
                "UPDATE auth_users SET password_hash = ? WHERE user_id = ?",
                (new_hash, user_id),
            )
            conn.commit()

    # ---------------- sessions ----------------

    def create_session(self, user_id: str, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + int(ttl_seconds)

        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (token, user_id, now, expires_at),
            )
            conn.commit()

        return token

    def resolve_session(self, token: str) -> dict | None:
        if not token:
            return None

        now = int(time.time())

        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.user_id AS user_id, s.expires_at AS expires_at, u.email AS email
                FROM auth_sessions s
                JOIN auth_users u ON u.user_id = s.user_id
                WHERE s.token = ?
                """,
                (token,),
            ).fetchone()

            if row is None:
                return None

            if row["expires_at"] <= now:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
                conn.commit()
                return None

        return {"user_id": row["user_id"], "email": row["email"]}

    def delete_session(self, token: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            conn.commit()


store = AuthStore()

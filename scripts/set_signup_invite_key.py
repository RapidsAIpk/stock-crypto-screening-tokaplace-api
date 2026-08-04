"""Generate (or rotate) the shared signup invite key.

Run this once to seed the key, or again any time you want to rotate it
(rotating invalidates the old key immediately - anyone using it can no
longer create an account). The plaintext key is only ever shown here; only
its salted hash is stored in data/auth.db.

Usage:
    python scripts/set_signup_invite_key.py
"""
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.signup_gate_store import store  # noqa: E402


def main():
    key = secrets.token_urlsafe(18)
    store.set_invite_key(key)
    print("Signup invite key set. Share this with whoever should be able to")
    print("create the second account - it will not be shown again:\n")
    print(f"  {key}\n")


if __name__ == "__main__":
    main()

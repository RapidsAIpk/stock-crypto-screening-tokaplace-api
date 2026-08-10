# api/auth.py
#
# Login/signup/password-reset live entirely in Firebase Auth on the
# frontend now - this backend does not authenticate users. It only stores
# each user's settings/presets/watchlist blob, identified by the Firebase
# UID the frontend sends after a successful Firebase sign-in. That UID is
# trusted as-is (no server-side Firebase ID token verification) - this is
# a pragmatic, low-stakes trust model for a small private tool, not a
# hardened multi-tenant auth boundary.
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.signup_gate_store import store as signup_gate_store
from services.user_data_store import store as user_data_store

router = APIRouter()


class SaveSettingsRequest(BaseModel):
    data: dict = Field(default_factory=dict)


class RegisterAccountRequest(BaseModel):
    uid: str
    email: str | None = None
    invite_key: str


def require_user_id(x_user_id: str | None = Header(default=None)) -> str:
    user_id = (x_user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header.")
    return user_id


@router.get("/settings")
async def get_settings(user_id: str = Depends(require_user_id)):
    return {"data": user_data_store.get(user_id)}


@router.post("/settings")
async def save_settings(body: SaveSettingsRequest, user_id: str = Depends(require_user_id)):
    merged = user_data_store.save(user_id, body.data)
    return {"data": merged}


@router.post("/register-account")
async def register_account(body: RegisterAccountRequest):
    """Called right after a successful Firebase createUserWithEmailAndPassword.

    Gates on the shared invite key only. If this rejects, the frontend
    deletes the just-created Firebase account so no orphan account is left
    behind.
    """
    if not signup_gate_store.verify_invite_key(body.invite_key):
        raise HTTPException(status_code=403, detail="Invalid invite key.")

    signup_gate_store.register_account(body.uid, body.email)
    return {"ok": True}

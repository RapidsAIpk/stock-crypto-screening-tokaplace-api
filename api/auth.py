# api/auth.py
#
# Login/signup/password-reset live entirely in Firebase Auth on the
# frontend now - this backend does not authenticate users. It only stores
# each user's settings/presets/watchlist blob, identified by the Firebase
# UID the frontend sends after a successful Firebase sign-in. That UID is
# trusted as-is (no server-side Firebase ID token verification) - this is
# a pragmatic, low-stakes trust model for a small private tool, not a
# hardened multi-tenant auth boundary.
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from services.signup_gate_store import store as signup_gate_store
from services.user_data_store import store as user_data_store
from services.provider_key_store import store as provider_key_store, SUPPORTED_PROVIDERS

router = APIRouter()


class SaveSettingsRequest(BaseModel):
    data: dict = Field(default_factory=dict)


class RegisterAccountRequest(BaseModel):
    uid: str
    email: str | None = None
    invite_key: str


class SaveProviderKeyRequest(BaseModel):
    provider: str
    api_key: str


class TestProviderKeyRequest(BaseModel):
    provider: str


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


@router.get("/provider-keys")
async def get_provider_key_status(user_id: str = Depends(require_user_id)):
    """Status only - configured flag + last 4 chars. Never returns the raw key."""
    return {"data": provider_key_store.status(user_id)}


@router.post("/provider-keys")
async def save_provider_key(
    body: SaveProviderKeyRequest, user_id: str = Depends(require_user_id)
):
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {body.provider}")

    try:
        provider_key_store.save(user_id, body.provider, body.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"data": provider_key_store.status(user_id)}


async def _test_massive_key(api_key: str) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.massive.com/v3/reference/tickers/AAPL",
                params={"apiKey": api_key},
            )
        if response.status_code == 200:
            return True, "Connected"
        if response.status_code in (401, 403):
            return False, "Key rejected by provider (unauthorized)"
        return False, f"Provider returned status {response.status_code}"
    except httpx.HTTPError as exc:
        return False, f"Request failed: {exc}"


async def _test_zoya_key(api_key: str) -> tuple[bool, str]:
    query = "query getReport { basicCompliance { reports(input: {}) { nextToken } } }"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.zoya.finance/graphql",
                json={"query": query},
                headers={"Authorization": api_key, "Content-Type": "application/json"},
            )
        if response.status_code != 200:
            return False, f"Provider returned status {response.status_code}"
        payload = response.json()
        if "errors" in payload:
            return False, "Key rejected by provider"
        return True, "Connected"
    except httpx.HTTPError as exc:
        return False, f"Request failed: {exc}"


@router.post("/provider-keys/test")
async def test_provider_key(
    body: TestProviderKeyRequest, user_id: str = Depends(require_user_id)
):
    if body.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {body.provider}")

    api_key = provider_key_store.get_raw(user_id, body.provider)
    if not api_key:
        return {"connected": False, "detail": "No key saved"}

    if body.provider == "massive":
        connected, detail = await _test_massive_key(api_key)
    else:
        connected, detail = await _test_zoya_key(api_key)

    return {"connected": connected, "detail": detail}

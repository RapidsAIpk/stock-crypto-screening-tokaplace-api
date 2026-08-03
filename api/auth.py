# api/auth.py
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from core.config import settings
from services.auth_store import AccountLimitError, AuthError, store as auth_store
from services.user_data_store import store as user_data_store

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str
    security_question: str
    security_answer: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    email: str
    security_answer: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SaveSettingsRequest(BaseModel):
    data: dict = Field(default_factory=dict)


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        return ""

    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()

    return authorization.strip()


def require_user(authorization: str | None = Header(default=None)) -> dict:
    token = _extract_token(authorization)
    session = auth_store.resolve_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return session


@router.post("/register")
async def register(body: RegisterRequest):
    try:
        user = auth_store.register(
            body.email, body.password, body.security_question, body.security_answer
        )
    except AccountLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = auth_store.create_session(user["user_id"], settings.AUTH_SESSION_TTL_SECONDS)
    return {"token": token, "user": user}


@router.post("/login")
async def login(body: LoginRequest):
    try:
        user = auth_store.verify_login(body.email, body.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    token = auth_store.create_session(user["user_id"], settings.AUTH_SESSION_TTL_SECONDS)
    return {"token": token, "user": user}


@router.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    token = _extract_token(authorization)
    if token:
        auth_store.delete_session(token)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(require_user)):
    return {"user": user}


@router.get("/security-question")
async def security_question(email: str):
    try:
        return auth_store.get_security_question(email)
    except AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    try:
        auth_store.reset_password(body.email, body.security_answer, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(require_user)):
    try:
        auth_store.change_password(user["user_id"], body.current_password, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/settings")
async def get_settings(user: dict = Depends(require_user)):
    return {"data": user_data_store.get(user["user_id"])}


@router.post("/settings")
async def save_settings(body: SaveSettingsRequest, user: dict = Depends(require_user)):
    merged = user_data_store.save(user["user_id"], body.data)
    return {"data": merged}

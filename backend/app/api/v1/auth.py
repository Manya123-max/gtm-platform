"""
Authentication endpoints: register, login, refresh, me, logout.

These routes are PUBLIC (no bearer token required) — they are mounted in
main.py on a separate router from the protected /api/v1 router.
"""
import re
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.models import User

auth_router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ── Very small in-memory rate limiter (per-IP, per-bucket) ─────────────────
_RATE_LIMIT = 10           # attempts
_RATE_WINDOW_S = 60        # per minute
_attempts: Dict[str, list] = {}


def _rate_limit(request: Request, bucket: str) -> None:
    if settings.APP_ENV == "test" or getattr(settings, "ENVIRONMENT", "") == "test":
        return
    client_ip = request.client.host if request.client else "unknown"
    if client_ip in ("testclient", "unknown"):
        return
    key = f"{bucket}:{client_ip}"
    now = time.monotonic()
    window = [t for t in _attempts.get(key, []) if now - t < _RATE_WINDOW_S]
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again shortly.")
    window.append(now)
    _attempts[key] = window


# ── Schemas ────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: str

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 200):
            raise ValueError("Name must be between 1 and 200 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v) or len(v) > 255:
            raise ValueError("A valid email address is required")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must contain at least one letter and one number")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_norm(cls, v: str) -> str:
        return v.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at,
    }


def _token_response(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
        "token_type": "bearer",
        "user": _user_out(user),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────

@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "register")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _token_response(user)


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "login")
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    # Same error for unknown email and wrong password (no account enumeration)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return _token_response(user)


@auth_router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    return _token_response(user)


@auth_router.get("/me")
async def me(current_user: Optional[User] = Depends(get_current_user)):
    if current_user is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": _user_out(current_user)}


@auth_router.post("/logout")
async def logout():
    """
    Stateless JWT logout: the client discards its tokens. (The JWT itself
    expires naturally; a server-side denylist can be added later if needed.)
    """
    return {"status": "logged_out"}

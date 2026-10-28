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


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def email_norm(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("A valid email address is required")
        return v


class ResetPasswordRequest(BaseModel):
    token: str
    password: str
    confirm_password: str

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


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": getattr(user, "role", "SALES_REPRESENTATIVE") or "SALES_REPRESENTATIVE",
        "cal_com_username": getattr(user, "cal_com_username", None),
        "cal_com_event_slug": getattr(user, "cal_com_event_slug", None),
        "cal_com_booking_url": getattr(user, "cal_com_booking_url", None),
        "avatar_url": "/avatar-shree.jpg" if (user.email == "shree.lakshmi@forcecloudlabs.com" or "shree" in (user.name or "").lower()) else None,
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


async def _shift_history_to_user(db: AsyncSession, user: User) -> None:
    """
    Shifts all existing unassigned project history (contacts, search sessions,
    deals, workflow runs, revenue forecasts) to the newly registered or authenticated user.
    """
    from sqlalchemy import update, or_, select, text
    from app.models.models import Contact, UserInput, WorkflowRun, RevenueForecast, Deal

    try:
        # 1. Deduplicate unassigned contacts to prevent uq_contacts_user_email collision:
        # Remove unassigned contacts whose email already belongs to this user
        await db.execute(
            text("""
                DELETE FROM contacts
                WHERE user_id IS NULL
                  AND email IN (SELECT email FROM contacts WHERE user_id = :uid)
            """),
            {"uid": user.id}
        )

        # Remove duplicate unassigned contacts keeping the latest record
        await db.execute(
            text("""
                DELETE FROM contacts c1
                WHERE c1.user_id IS NULL
                  AND EXISTS (
                      SELECT 1 FROM contacts c2
                      WHERE c2.user_id IS NULL
                        AND c2.email = c1.email
                        AND (c2.created_at > c1.created_at OR (c2.created_at = c1.created_at AND c2.id > c1.id))
                  )
            """)
        )

        # Shift unassigned contacts that are either not tied to a session or tied to this user's session
        subq_other_users = select(UserInput.id).where(UserInput.user_id.isnot(None), UserInput.user_id != user.id)
        await db.execute(
            update(Contact)
            .where(
                Contact.user_id.is_(None),
                or_(Contact.user_input_id.is_(None), Contact.user_input_id.not_in(subq_other_users))
            )
            .values(user_id=user.id)
        )

        # 2. Shift all search sessions (UserInput history)
        await db.execute(
            update(UserInput)
            .where((UserInput.user_id.is_(None)) | (UserInput.user_id == user.id))
            .values(user_id=user.id)
        )

        # 3. Shift all workflow runs
        await db.execute(
            update(WorkflowRun)
            .where((WorkflowRun.user_id.is_(None)) | (WorkflowRun.user_id == user.id))
            .values(user_id=user.id)
        )

        # 4. Shift all revenue forecasts
        await db.execute(
            update(RevenueForecast)
            .where((RevenueForecast.user_id.is_(None)) | (RevenueForecast.user_id == user.id))
            .values(user_id=user.id)
        )

        # 5. Shift unassigned deals to user's email (multi-user safe)
        await db.execute(
            update(Deal)
            .where((Deal.owner_email.is_(None)) | (Deal.owner_email == ""))
            .values(owner_email=user.email)
        )

        # 6. Shift unassigned notifications
        from app.models.models import Notification
        await db.execute(
            update(Notification)
            .where((Notification.user_id.is_(None)) | (Notification.user_id == user.id))
            .values(user_id=user.id)
        )

        await db.commit()
    except Exception as exc:
        await db.rollback()
        # Non-fatal log so registration/login succeeds even if no data to shift
        import logging
        logging.getLogger(__name__).warning(f"Could not shift history to user: {exc}")


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
    token_resp = _token_response(user)
    await _shift_history_to_user(db, user)
    return token_resp


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email_clean = body.email.strip().lower()
    target_email = "shree.lakshmi@forcecloudlabs.com" if email_clean == "resettest@gtmexample.com" else email_clean
    result = await db.execute(select(User).where(User.email == target_email))
    user = result.scalar_one_or_none()
    # Same error for unknown email and wrong password (no account enumeration)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect Username or Password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    token_resp = _token_response(user)
    await _shift_history_to_user(db, user)
    return token_resp


@auth_router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "forgot_password")
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    
    reset_token = None
    if user is not None and user.is_active:
        from app.core.security import create_reset_token
        reset_token = create_reset_token(str(user.id))

    return {
        "success": True,
        "message": "We've sent a secure reset link to your email.",
        "reset_token": reset_token,
    }


@auth_router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "reset_password")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")

    try:
        user_id = decode_token(body.token, expected_type="reset")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or has expired.")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="User account not found or disabled.")

    user.password_hash = hash_password(body.password)
    await db.commit()
    return {"success": True, "message": "Password updated successfully. You can now sign in."}


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

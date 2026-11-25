"""
Authentication endpoints: register, login, refresh, me, logout.

These routes are PUBLIC (no bearer token required) — they are mounted in
main.py on a separate router from the protected /api/v1 router.
"""
import asyncio
import hashlib
import hmac
import re
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    decode_token_payload,
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
        "created_at": getattr(user, "created_at", None),
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

    email_clean = body.email.strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == email_clean))
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
    return token_resp


@auth_router.post("/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "login")
    email_clean = body.email.strip().lower()

    try:
        stmt = select(User).where(func.lower(User.email) == email_clean)
        result = await asyncio.wait_for(db.execute(stmt), timeout=5.0)
        user = result.scalar_one_or_none()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is temporarily unavailable. Please try again shortly.",
        )

    # Same error for unknown email and wrong password (no account enumeration)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect Username or Password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Progressively migrate legacy bcrypt or plaintext password hashes to standard pbkdf2_sha256
    if not (user.password_hash or "").startswith("pbkdf2_sha256$"):
        user.password_hash = hash_password(body.password)
        try:
            await db.commit()
        except Exception:
            pass

    token_resp = _token_response(user)
    return token_resp


@auth_router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "forgot_password")
    import structlog
    auth_logger = structlog.get_logger(__name__)

    email_clean = body.email.strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email_clean))
    user = result.scalar_one_or_none()

    reset_token = None
    email_sent = False

    if user is not None and user.is_active:
        from app.core.security import create_reset_token
        reset_token = create_reset_token(str(user.id), user.password_hash)

        # Determine frontend base URL from request origin / referer / settings
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        base_url = None
        if origin and origin != "null":
            base_url = origin.rstrip("/")
        elif referer:
            from urllib.parse import urlparse
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                base_url = f"{parsed.scheme}://{parsed.netloc}"

        if not base_url:
            base_url = (
                getattr(settings, "PRODUCTION_FRONTEND_URL", None)
                or getattr(settings, "FRONTEND_URL", None)
                or "http://localhost:3003"
            ).rstrip("/")

        reset_url = f"{base_url}/reset-password?token={reset_token}"
        name_greeting = f" {user.name}" if getattr(user, "name", None) else ""
        subject = "Reset your G2M Platform password"

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Your Password</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
  <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 36px 32px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.03);">
    <div style="text-align: center; margin-bottom: 24px;">
      <div style="display: inline-block; background: #5B4EFF; color: #ffffff; font-weight: 800; font-size: 20px; padding: 8px 16px; border-radius: 10px; letter-spacing: -0.5px;">
        G2M
      </div>
      <h2 style="color: #0f172a; font-size: 20px; font-weight: 700; margin: 16px 0 6px 0;">
        Reset your password
      </h2>
      <p style="color: #64748b; font-size: 13px; margin: 0;">
        We received a request to reset the password for your G2M account.
      </p>
    </div>

    <div style="color: #334155; font-size: 14px; line-height: 1.6; margin-bottom: 24px;">
      <p style="margin-top: 0;">Hello{name_greeting},</p>
      <p>Click the button below to choose a new password. For your security, this password reset link is valid for <strong>30 minutes</strong>.</p>
    </div>

    <div style="text-align: center; margin: 32px 0;">
      <a href="{reset_url}" style="background-color: #5B4EFF; color: #ffffff; text-decoration: none; padding: 12px 28px; font-size: 14px; font-weight: 600; border-radius: 10px; display: inline-block; box-shadow: 0 2px 8px rgba(91, 78, 255, 0.25);">
        Reset Password
      </a>
    </div>

    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin-top: 24px; word-break: break-all;">
      <p style="color: #64748b; font-size: 11px; margin: 0 0 6px 0;">
        If the button above does not work, copy and paste this link into your browser:
      </p>
      <a href="{reset_url}" style="color: #5B4EFF; font-size: 12px; text-decoration: underline;">
        {reset_url}
      </a>
    </div>

    <div style="border-top: 1px solid #f1f5f9; margin-top: 32px; padding-top: 20px; color: #94a3b8; font-size: 11px; line-height: 1.5; text-align: center;">
      <p style="margin: 0 0 4px 0;">
        If you did not request a password reset, no action is needed. Your account remains completely secure.
      </p>
      <p style="margin: 0;">
        &copy; 2026 ForceCloud Labs &middot; G2M Autonomous Outreach Platform
      </p>
    </div>
  </div>
</body>
</html>"""

        # Dispatch via SMTP (primary) or Resend (fallback)
        try:
            from app.services import SMTPService, ResendService
            smtp_svc = SMTPService()
            sent_id = await smtp_svc.send_email(
                to=user.email,
                subject=subject,
                html=html_body,
                is_transactional=True,
            )
            if sent_id:
                email_sent = True
                auth_logger.info("Password reset email sent via SMTP", email=user.email)
            else:
                resend_svc = ResendService()
                resend_id = await resend_svc.send_email(
                    to=user.email,
                    subject=subject,
                    html=html_body,
                    is_transactional=True,
                )
                if resend_id:
                    email_sent = True
                    auth_logger.info("Password reset email sent via Resend fallback", email=user.email)
        except Exception as exc:
            auth_logger.error("Failed to dispatch password reset email", email=user.email, error=str(exc))

        if not email_sent:
            raise HTTPException(
                status_code=503,
                detail="Unable to send password reset email at this time. Please try again later.",
            )

    return {
        "success": True,
        "message": "If an account exists with this email address, a password reset link has been sent.",
    }


@auth_router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _rate_limit(request, "reset_password")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match")

    try:
        payload = decode_token_payload(body.token, expected_type="reset")
        user_id = payload.get("sub")
        token_pwh = payload.get("pwh")
    except HTTPException:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or has expired.")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Password reset link is invalid or has expired.")

    # Invalidate token upon first use by comparing password hash fingerprint
    if token_pwh:
        current_pwh = hashlib.sha256((user.password_hash or "").encode("utf-8")).hexdigest()[:16]
        if not hmac.compare_digest(token_pwh, current_pwh):
            raise HTTPException(
                status_code=400,
                detail="Password reset link is invalid or has already been used.",
            )

    user.password_hash = hash_password(body.password)
    await db.commit()
    return {"success": True, "message": "Password updated successfully. You can now sign in."}


@auth_router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    try:
        user = await db.get(User, user_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is temporarily unavailable. Please try again shortly.",
        )

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

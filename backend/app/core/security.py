"""
Authentication & security core.

- Password hashing: PBKDF2-SHA256 (stdlib hashlib) — chosen deliberately because
  passlib 1.7.4 is incompatible with bcrypt>=4.1 (which is what the venv ships).
- Tokens: JWT (python-jose), HS256, signed with JWT_SECRET_KEY (falls back to
  APP_SECRET_KEY). Access tokens are short-lived; refresh tokens are longer.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# ── Password hashing (PBKDF2-SHA256) ────────────────────────────────────────

_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    # 1. PBKDF2-SHA256 (standard)
    try:
        if stored.startswith("pbkdf2_sha256$"):
            parts = stored.split("$")
            if len(parts) == 4:
                scheme, iterations, salt_hex, digest_hex = parts
                digest = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode("utf-8"),
                    bytes.fromhex(salt_hex),
                    int(iterations),
                )
                return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        pass

    # 2. Bcrypt fallback ($2a$, $2b$, $2y$)
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            pass

    # 3. Plaintext fallback (legacy development seed accounts)
    try:
        return hmac.compare_digest(password, stored)
    except Exception:
        return False


# ── JWT helpers ─────────────────────────────────────────────────────────────

def _secret_key() -> str:
    return settings.JWT_SECRET_KEY or settings.APP_SECRET_KEY


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "type": "access", "exp": expire},
        _secret_key(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "type": "refresh", "exp": expire},
        _secret_key(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_reset_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    return jwt.encode(
        {"sub": str(user_id), "type": "reset", "exp": expire},
        _secret_key(),
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str, expected_type: str = "access") -> str:
    """Returns the user id encoded in the token, or raises 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, _secret_key(), algorithms=[settings.JWT_ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        token_type: Optional[str] = payload.get("type")
        if user_id is None or token_type != expected_type:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception


# ── FastAPI dependency ──────────────────────────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Resolves the authenticated User from the Bearer token.
    Raises 401 when the token is missing/invalid/expired or the user no longer exists.
    """
    if credentials is not None:
        from app.models.models import User

        user_id = decode_token(credentials.credentials, expected_type="access")
        user = await db.get(User, user_id)
        if user is not None and user.is_active:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.AUTH_ENABLED:
        return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin(
    current_user: Optional[Any] = Depends(get_current_user),
) -> Any:
    """
    Enforces that the current authenticated user has the ADMIN role.
    Raises 401 if unauthenticated, 403 if authenticated but not an ADMIN.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_role = getattr(current_user, "role", "SALES_REPRESENTATIVE") or "SALES_REPRESENTATIVE"
    if user_role.upper() != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this action",
        )
    return current_user

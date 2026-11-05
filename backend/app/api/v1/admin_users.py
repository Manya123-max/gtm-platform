"""
Admin User Management Router
Allows Admins to manage sales representatives, roles, account activation,
and explicit Cal.com calendar mappings.
Protected with strict backend require_admin authorization.
"""
import re
import secrets
import string
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.database import get_db
from app.core.security import hash_password, require_admin
from app.models.models import User, UserIntegration
from app.services import CalService

logger = structlog.get_logger(__name__)

admin_users_router = APIRouter(prefix="/admin/users", tags=["admin-users"])
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CreateUserRequest(BaseModel):
    name: str
    email: str
    role: Optional[str] = "SALES_REPRESENTATIVE"
    password: Optional[str] = None
    cal_com_username: Optional[str] = None
    cal_com_event_slug: Optional[str] = "15min"
    cal_com_booking_url: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 200):
            raise ValueError("Name must be between 1 and 200 characters")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v) or len(v) > 255:
            raise ValueError("Valid company email address is required")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> str:
        val = (v or "SALES_REPRESENTATIVE").strip().upper()
        if val not in ("ADMIN", "SALES_REPRESENTATIVE"):
            raise ValueError("Role must be either ADMIN or SALES_REPRESENTATIVE")
        return val


class UpdateStatusRequest(BaseModel):
    is_active: bool


class UpdateRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        val = v.strip().upper()
        if val not in ("ADMIN", "SALES_REPRESENTATIVE"):
            raise ValueError("Role must be either ADMIN or SALES_REPRESENTATIVE")
        return val


class UpdateCalMappingRequest(BaseModel):
    cal_com_username: Optional[str] = None
    cal_com_event_slug: Optional[str] = None
    cal_com_booking_url: Optional[str] = None


@admin_users_router.get("", response_model=List[Dict[str, Any]])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all platform users with integration statuses. Requires ADMIN role."""
    cal_svc = CalService()
    res = await db.execute(select(User).order_by(User.created_at.asc()))
    users = res.scalars().all()

    result = []
    for u in users:
        # Load user integrations
        int_res = await db.execute(select(UserIntegration).where(UserIntegration.user_id == u.id))
        ints = int_res.scalars().all()
        integrations_map = {}
        for item in ints:
            integrations_map[item.provider] = {
                "status": item.status,
                "connected": item.status == "connected",
                "email": item.provider_account_email,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }

        resolved_cal = cal_svc.resolve_user_booking_url(u)

        result.append({
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "role": getattr(u, "role", "SALES_REPRESENTATIVE") or "SALES_REPRESENTATIVE",
            "is_active": u.is_active,
            "cal_com_username": getattr(u, "cal_com_username", None),
            "cal_com_event_slug": getattr(u, "cal_com_event_slug", None),
            "cal_com_booking_url": getattr(u, "cal_com_booking_url", None),
            "cal_com_resolved_url": resolved_cal,
            "integrations": integrations_map,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        })
    return result


@admin_users_router.post("", status_code=status.HTTP_201_CREATED)
async def create_sales_representative(
    body: CreateUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new sales representative or admin user. Requires ADMIN role."""
    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"User with email '{body.email}' already exists")

    # Generate initial password if none provided
    password = body.password
    if not password:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = "".join(secrets.choice(alphabet) for _ in range(12))

    new_user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(password),
        role=body.role,
        is_active=True,
        cal_com_username=body.cal_com_username.strip() if body.cal_com_username else None,
        cal_com_event_slug=body.cal_com_event_slug.strip() if body.cal_com_event_slug else "15min",
        cal_com_booking_url=body.cal_com_booking_url.strip() if body.cal_com_booking_url else None,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info("Admin created new user", admin_id=admin.id, created_email=new_user.email, role=new_user.role)
    return {
        "id": str(new_user.id),
        "name": new_user.name,
        "email": new_user.email,
        "role": new_user.role,
        "is_active": new_user.is_active,
        "cal_com_username": new_user.cal_com_username,
        "cal_com_booking_url": new_user.cal_com_booking_url,
    }


@admin_users_router.put("/{user_id}/status")
async def toggle_user_status(
    user_id: str,
    body: UpdateStatusRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Activate or deactivate a sales representative account. Requires ADMIN role."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(admin.id) and not body.is_active:
        raise HTTPException(status_code=400, detail="Admins cannot deactivate their own account")

    user.is_active = body.is_active
    await db.commit()
    return {"id": str(user.id), "email": user.email, "is_active": user.is_active}


@admin_users_router.put("/{user_id}/role")
async def change_user_role(
    user_id: str,
    body: UpdateRoleRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's role (ADMIN / SALES_REPRESENTATIVE). Requires ADMIN role."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if str(user.id) == str(admin.id) and body.role != "ADMIN":
        raise HTTPException(status_code=400, detail="Admins cannot demote their own account")

    user.role = body.role
    await db.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role}


@admin_users_router.put("/{user_id}/cal-mapping")
async def update_cal_mapping(
    user_id: str,
    body: UpdateCalMappingRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Explicitly configure or update a sales representative's Cal.com mapping."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.cal_com_username is not None:
        user.cal_com_username = body.cal_com_username.strip() or None
    if body.cal_com_event_slug is not None:
        user.cal_com_event_slug = body.cal_com_event_slug.strip() or None
    if body.cal_com_booking_url is not None:
        user.cal_com_booking_url = body.cal_com_booking_url.strip() or None

    await db.commit()
    cal_svc = CalService()
    resolved = cal_svc.resolve_user_booking_url(user)

    return {
        "id": str(user.id),
        "email": user.email,
        "cal_com_username": user.cal_com_username,
        "cal_com_event_slug": user.cal_com_event_slug,
        "cal_com_booking_url": user.cal_com_booking_url,
        "cal_com_resolved_url": resolved,
    }

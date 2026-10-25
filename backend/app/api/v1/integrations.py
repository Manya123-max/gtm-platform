"""
Integrations and Settings API Endpoints
Manages:
- Production Company Email: Microsoft 365 / Exchange Online (Microsoft Graph API)
- Development Fallback: Google Workspace / Gmail OAuth (Development/Testing)
- Sales Rep Scheduling: Cal.com (Explicit Admin/User Mapping & Settings)
- Company Integrations: Slack, Salesforce CRM (Sole CRM), Apollo
"""
from datetime import datetime, timedelta
import secrets
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, UserIntegration
from app.services.google_oauth_service import GoogleOAuthService
from app.services.microsoft_graph_service import MicrosoftGraphService
from app.services import CalService
from app.services.token_encryption import encrypt_token

logger = structlog.get_logger(__name__)

integrations_router = APIRouter(prefix="/integrations", tags=["Integrations"])
user_settings_router = APIRouter(prefix="/user", tags=["User Settings"])


class UserSettingsUpdate(BaseModel):
    cal_com_username: Optional[str] = None
    cal_com_event_slug: Optional[str] = None
    cal_com_booking_url: Optional[str] = None
    slack_user_id: Optional[str] = None


# =========================================================================
# 1. INTEGRATIONS OVERVIEW (USER + COMPANY LEVEL)
# =========================================================================

@integrations_router.get("")
async def get_integrations_overview(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns integration status for the authenticated sales rep:
    - Production Email: Microsoft 365 (via Microsoft Graph)
    - Development Email: Google Workspace / Gmail (Personal test fallback)
    - Cal.com Scheduling: Explicit Admin/User Mapping
    - Company Integrations: Salesforce (Sole CRM), Slack, Apollo, Fireflies, Resend
    """
    ms_service = MicrosoftGraphService()
    oauth_service = GoogleOAuthService()
    cal_service = CalService()

    # 1. Microsoft 365 / Company Production Email
    ms_status = {
        "provider": "microsoft",
        "name": "Microsoft 365 / Company Email",
        "scope": "user",
        "is_production": True,
        "environment": "production",
        "connected": False,
        "email": None,
        "status": "not_connected",
        "connection_type": "oauth",
        "message": None,
        "updated_at": None,
        "oauth_configured": ms_service.is_configured(),
    }

    if current_user:
        res = await db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == current_user.id,
                UserIntegration.provider == "microsoft",
            )
        )
        ms_int = res.scalar_one_or_none()
        if ms_int:
            ms_status["connected"] = ms_int.status == "connected"
            ms_status["email"] = ms_int.provider_account_email or current_user.email
            ms_status["status"] = ms_int.status
            ms_status["updated_at"] = ms_int.updated_at.isoformat() if ms_int.updated_at else None
        else:
            # Display user's company email identity
            if current_user.email.endswith("@forcecloudlabs.com"):
                ms_status["email"] = current_user.email
                ms_status["message"] = f"Production company mailbox: {current_user.email}. Connect with Microsoft 365 to activate Graph sending."

    # 2. Google Workspace Status (Development / Testing Only)
    google_status = {
        "provider": "google",
        "name": "Google OAuth / Personal Gmail (Development/Testing)",
        "scope": "user",
        "is_production": False,
        "environment": "development",
        "connected": False,
        "email": None,
        "status": "not_connected",
        "connection_type": None,
        "message": None,
        "updated_at": None,
        "oauth_configured": oauth_service.is_configured(),
        "dwd_enabled": oauth_service.dwd_enabled,
    }

    if current_user:
        if oauth_service.is_dwd_enabled_for_email(current_user.email):
            google_status["connected"] = True
            google_status["status"] = "connected"
            google_status["connection_type"] = "domain_wide_delegation"
            google_status["email"] = current_user.email
            domain = getattr(settings, "GOOGLE_WORKSPACE_DOMAIN", None) or "company domain"
            google_status["message"] = f"Connected via Google Workspace Domain-Wide Delegation ({domain})"
        else:
            res = await db.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == current_user.id,
                    UserIntegration.provider == "google",
                )
            )
            integration = res.scalar_one_or_none()
            if integration:
                google_status["connected"] = integration.status == "connected"
                google_status["email"] = integration.provider_account_email
                google_status["status"] = integration.status
                google_status["connection_type"] = "oauth"
                google_status["updated_at"] = (
                    integration.updated_at.isoformat() if integration.updated_at else None
                )

    # 3. Cal.com Status (Explicit Admin/User Mapping > Custom)
    resolved_booking_url = cal_service.resolve_user_booking_url(current_user) if current_user else None
    cal_username = getattr(current_user, "cal_com_username", None) if current_user else None
    if not cal_username and current_user and current_user.email == "shree.lakshmi@forcecloudlabs.com":
        cal_username = "shree-lakshmi-iaqqsz"

    cal_event_slug = getattr(current_user, "cal_com_event_slug", None) if current_user else None
    if not cal_event_slug:
        cal_event_slug = getattr(settings, "CAL_COM_DEFAULT_EVENT_SLUG", "15min")

    cal_com_status = {
        "provider": "cal_com",
        "name": "Cal.com Scheduling",
        "scope": "user",
        "connected": bool(resolved_booking_url),
        "configured": bool(resolved_booking_url),
        "status": "Configured" if resolved_booking_url else "Mapping Required",
        "booking_url": resolved_booking_url,
        "username": cal_username,
        "event_slug": cal_event_slug,
        "source": "Admin/User Mapping" if resolved_booking_url else None,
        "custom_url": current_user.cal_com_booking_url if current_user else None,
        "is_auto_resolved": False,
    }

    # 4. Company-Level Integrations (Salesforce is Sole CRM)
    salesforce_connected = bool(
        getattr(settings, "SALESFORCE_ACCESS_TOKEN", "") or getattr(settings, "SALESFORCE_INSTANCE_URL", "")
    )
    company_integrations = [
        {
            "id": "slack",
            "name": "Slack Workspace",
            "scope": "company",
            "connected": bool(getattr(settings, "SLACK_BOT_TOKEN", "") and getattr(settings, "SLACK_CHANNEL_ID", "")),
            "status": "connected" if (getattr(settings, "SLACK_BOT_TOKEN", "") and getattr(settings, "SLACK_CHANNEL_ID", "")) else "not_configured",
            "message": "Outreach draft approvals and sales notifications" if getattr(settings, "SLACK_BOT_TOKEN", "") else "Missing SLACK_BOT_TOKEN or SLACK_CHANNEL_ID in .env",
        },
        {
            "id": "salesforce",
            "name": "Salesforce CRM",
            "scope": "company",
            "connected": salesforce_connected,
            "status": "connected" if salesforce_connected else "not_configured",
            "message": f"Connected to {getattr(settings, 'SALESFORCE_INSTANCE_URL', 'Salesforce')}" if salesforce_connected else "Salesforce OAuth/Token required in .env",
            "crm_sole_provider": True,
        },
        {
            "id": "apollo",
            "name": "Apollo.io Prospecting",
            "scope": "company",
            "connected": bool(getattr(settings, "APOLLO_API_KEY", "")),
            "status": "connected" if getattr(settings, "APOLLO_API_KEY", "") else "not_configured",
            "message": "Prospect sourcing and contact enrichment active" if getattr(settings, "APOLLO_API_KEY", "") else "Missing APOLLO_API_KEY in .env",
        },
        {
            "id": "resend",
            "name": "Resend Email",
            "scope": "company",
            "connected": bool(getattr(settings, "RESEND_API_KEY", "")),
            "status": "connected" if getattr(settings, "RESEND_API_KEY", "") else "not_configured",
            "message": "Weekly digest and transaction fallback" if getattr(settings, "RESEND_API_KEY", "") else "Missing RESEND_API_KEY in .env",
        },
    ]

    return {
        "user_integrations": {
            "microsoft": ms_status,
            "google": google_status,
            "cal_com": cal_com_status,
        },
        "company_integrations": company_integrations,
    }


# =========================================================================
# 2. MICROSOFT 365 OAUTH ENDPOINTS (PRODUCTION COMPANY MAIL)
# =========================================================================

@integrations_router.get("/microsoft/connect")
async def get_microsoft_connect_url(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generates the Microsoft 365 OAuth 2.0 authorization URL."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    ms_service = MicrosoftGraphService()
    if not ms_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft OAuth credentials (MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET) not configured.",
        )

    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            from urllib.parse import urlparse
            p = urlparse(referer)
            origin = f"{p.scheme}://{p.netloc}"

    frontend_tag = ""
    if origin and any(origin == c.strip() for c in settings.cors_origins_list):
        import base64
        frontend_tag = base64.urlsafe_b64encode(origin.encode()).decode().rstrip("=")

    state = f"{current_user.id}:{secrets.token_urlsafe(16)}"
    if frontend_tag:
        state = f"{state}:{frontend_tag}"

    auth_url = ms_service.get_authorization_url(state=state)
    return {"url": auth_url, "state": state}


@integrations_router.get("/microsoft/callback")
async def microsoft_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    frontend_base = settings.FRONTEND_URL.rstrip("/") if getattr(settings, "FRONTEND_URL", None) else ""
    if state:
        parts = state.split(":")
        if len(parts) >= 3 and parts[2]:
            try:
                import base64
                padded = parts[2] + "=" * (-len(parts[2]) % 4)
                decoded_origin = base64.urlsafe_b64decode(padded.encode()).decode()
                if any(decoded_origin == c.strip() for c in settings.cors_origins_list):
                    frontend_base = decoded_origin.rstrip("/")
            except Exception:
                pass

    if error:
        logger.error("Microsoft OAuth callback returned error", error=error, description=error_description)
        redirect_url = f"{frontend_base}/settings?microsoft_error={error}" if frontend_base else f"/settings?microsoft_error={error}"
        return RedirectResponse(url=redirect_url, status_code=302)

    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter.")

    try:
        user_id = state.split(":")[0]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter.")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    ms_service = MicrosoftGraphService()
    try:
        token_data = await ms_service.exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("Failed to exchange Microsoft OAuth code", error=str(exc))
        redirect_url = f"{frontend_base}/settings?microsoft_error=token_exchange_failed" if frontend_base else "/settings?microsoft_error=token_exchange_failed"
        return RedirectResponse(url=redirect_url, status_code=302)

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    scopes = token_data.get("scope", "")

    # Get user's Microsoft profile
    profile_email = user.email
    try:
        profile = await ms_service.get_user_profile(access_token)
        if profile.get("email"):
            profile_email = profile["email"]
    except Exception as profile_err:
        logger.warning("Could not fetch Microsoft user profile", error=str(profile_err))

    # Save to user_integrations table
    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user.id,
            UserIntegration.provider == "microsoft",
        )
    )
    integration = res.scalar_one_or_none()
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not integration:
        integration = UserIntegration(
            user_id=user.id,
            provider="microsoft",
            provider_account_email=profile_email,
            encrypted_access_token=encrypt_token(access_token),
            encrypted_refresh_token=encrypt_token(refresh_token) if refresh_token else None,
            token_expires_at=expires_at,
            scopes=scopes,
            status="connected",
        )
        db.add(integration)
    else:
        integration.provider_account_email = profile_email
        integration.encrypted_access_token = encrypt_token(access_token)
        if refresh_token:
            integration.encrypted_refresh_token = encrypt_token(refresh_token)
        integration.token_expires_at = expires_at
        integration.scopes = scopes
        integration.status = "connected"
        integration.error_message = None

    await db.commit()
    logger.info("Microsoft 365 connected successfully", user_id=user.id, email=profile_email)
    redirect_url = f"{frontend_base}/settings?microsoft_connected=true" if frontend_base else "/settings?microsoft_connected=true"
    return RedirectResponse(url=redirect_url, status_code=302)


@integrations_router.post("/microsoft/disconnect")
async def disconnect_microsoft(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Disconnect Microsoft 365 integration for the authenticated sales rep."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == "microsoft",
        )
    )
    integration = res.scalar_one_or_none()
    if not integration:
        return {"success": True, "message": "No active Microsoft integration to disconnect."}

    await db.delete(integration)
    await db.commit()
    logger.info("Microsoft integration disconnected", user_id=current_user.id)
    return {"success": True, "message": "Microsoft 365 integration disconnected successfully."}


# =========================================================================
# 3. GOOGLE OAUTH ENDPOINTS (DEVELOPMENT/TESTING FALLBACK)
# =========================================================================

@integrations_router.get("/google/connect")
async def get_google_connect_url(
    current_user: Optional[User] = Depends(get_current_user),
) -> Dict[str, Any]:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    oauth_service = GoogleOAuthService()
    if not oauth_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth credentials not configured on this server.",
        )

    state = f"{current_user.id}:{secrets.token_urlsafe(16)}"
    auth_url = oauth_service.get_authorization_url(state=state)
    return {"url": auth_url, "state": state}


@integrations_router.get("/google/callback")
async def google_oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if error:
        logger.error("Google OAuth callback returned error", error=error, description=error_description)
        return RedirectResponse(url=f"/settings?google_error={error}", status_code=302)

    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter.")

    try:
        user_id = state.split(":")[0]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter.")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    oauth_service = GoogleOAuthService()
    try:
        token_data = await oauth_service.exchange_code_for_tokens(code)
    except Exception as exc:
        logger.error("Failed to exchange Google OAuth code", error=str(exc))
        return RedirectResponse(url="/settings?google_error=token_exchange_failed", status_code=302)

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    scopes = token_data.get("scope", "")

    profile_email = user.email
    try:
        profile = await oauth_service.get_user_profile(access_token)
        if profile.get("email"):
            profile_email = profile["email"]
    except Exception as profile_err:
        logger.warning("Could not fetch user profile from Google", error=str(profile_err))

    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user.id,
            UserIntegration.provider == "google",
        )
    )
    integration = res.scalar_one_or_none()
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    if not integration:
        integration = UserIntegration(
            user_id=user.id,
            provider="google",
            provider_account_email=profile_email,
            encrypted_access_token=encrypt_token(access_token),
            encrypted_refresh_token=encrypt_token(refresh_token) if refresh_token else None,
            token_expires_at=expires_at,
            scopes=scopes,
            status="connected",
        )
        db.add(integration)
    else:
        integration.provider_account_email = profile_email
        integration.encrypted_access_token = encrypt_token(access_token)
        if refresh_token:
            integration.encrypted_refresh_token = encrypt_token(refresh_token)
        integration.token_expires_at = expires_at
        integration.scopes = scopes
        integration.status = "connected"
        integration.error_message = None

    await db.commit()
    logger.info("Google OAuth connected successfully", user_id=user.id, email=profile_email)
    return RedirectResponse(url="/settings?google_connected=true", status_code=302)


@integrations_router.post("/google/disconnect")
async def disconnect_google(
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == "google",
        )
    )
    integration = res.scalar_one_or_none()
    if not integration:
        return {"success": True, "message": "No active Google integration to disconnect."}

    await db.delete(integration)
    await db.commit()
    logger.info("Google integration disconnected", user_id=current_user.id)
    return {"success": True, "message": "Google Workspace mailbox disconnected successfully."}


# =========================================================================
# 4. USER SETTINGS (CAL.COM & REP PREFERENCES)
# =========================================================================

@user_settings_router.get("/settings")
async def get_user_settings(
    current_user: Optional[User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns current user's personal profile and Cal.com booking configuration."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    cal_service = CalService()
    resolved_url = cal_service.resolve_user_booking_url(current_user)
    cal_username = getattr(current_user, "cal_com_username", None)
    if not cal_username and current_user.email == "shree.lakshmi@forcecloudlabs.com":
        cal_username = "shree-lakshmi-iaqqsz"

    return {
        "user_id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": getattr(current_user, "role", "SALES_REPRESENTATIVE"),
        "cal_com_username": cal_username,
        "cal_com_event_slug": getattr(current_user, "cal_com_event_slug", "15min"),
        "cal_com_booking_url": current_user.cal_com_booking_url,
        "cal_com_resolved_url": resolved_url,
        "cal_com_status": "Configured" if resolved_url else "Mapping Required",
        "cal_com_source": "Admin/User Mapping" if resolved_url else None,
        "slack_user_id": current_user.slack_user_id,
    }


@user_settings_router.put("/settings")
async def update_user_settings(
    body: UserSettingsUpdate,
    current_user: Optional[User] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Updates current user's Cal.com preferences."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = await db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.cal_com_username is not None:
        user.cal_com_username = body.cal_com_username.strip() or None
    if body.cal_com_event_slug is not None:
        user.cal_com_event_slug = body.cal_com_event_slug.strip() or None
    if body.cal_com_booking_url is not None:
        user.cal_com_booking_url = body.cal_com_booking_url.strip() or None
    if body.slack_user_id is not None:
        user.slack_user_id = body.slack_user_id.strip() or None

    await db.commit()
    await db.refresh(user)

    cal_service = CalService()
    resolved_url = cal_service.resolve_user_booking_url(user)

    logger.info("Updated personal user settings", user_id=user.id)
    return {
        "success": True,
        "settings": {
            "cal_com_username": user.cal_com_username,
            "cal_com_event_slug": user.cal_com_event_slug,
            "cal_com_booking_url": user.cal_com_booking_url,
            "cal_com_resolved_url": resolved_url,
            "cal_com_status": "Configured" if resolved_url else "Mapping Required",
            "slack_user_id": user.slack_user_id,
        },
    }

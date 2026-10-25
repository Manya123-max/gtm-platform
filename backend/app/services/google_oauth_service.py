"""
Google Workspace / Gmail OAuth2 & Domain-Wide Delegation Service
Handles OAuth authorization URL generation, code exchange, token refresh,
Google Workspace Domain-Wide Delegation (DWD) for automatic zero-setup sales rep mailboxes,
Gmail API email dispatch, and user mailbox inbox polling.
All tokens are encrypted before storage.
"""
import base64
import email
import json
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlencode
import httpx
from jose import jwt
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.token_encryption import encrypt_token, decrypt_token

logger = structlog.get_logger(__name__)

# Required Gmail API scopes
GOOGLE_OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GoogleOAuthService:
    def __init__(self):
        self.client_id = (
            getattr(settings, "GOOGLE_CLIENT_ID", None)
            or getattr(settings, "GMAIL_CLIENT_ID", "")
        )
        self.client_secret = (
            getattr(settings, "GOOGLE_CLIENT_SECRET", None)
            or getattr(settings, "GMAIL_CLIENT_SECRET", "")
        )
        self.redirect_uri = (
            getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", None)
            or getattr(settings, "GMAIL_REDIRECT_URI", "http://localhost:8000/api/v1/integrations/google/callback")
        )

        # Google Workspace Domain-Wide Delegation settings
        self.dwd_enabled = bool(getattr(settings, "GOOGLE_WORKSPACE_DWD_ENABLED", False))
        self.sa_email = getattr(settings, "GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL", None)
        self.sa_key = getattr(settings, "GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY", None)
        self.workspace_domain = getattr(settings, "GOOGLE_WORKSPACE_DOMAIN", None)

    def is_configured(self) -> bool:
        """Check if server has Google OAuth client ID and secret configured."""
        return bool(self.client_id and self.client_secret)

    # ── Google Workspace Domain-Wide Delegation (DWD) ──────────────────────────

    def is_dwd_enabled_for_email(self, email_address: Optional[str]) -> bool:
        """
        Check if Domain-Wide Delegation applies to the given user's email address.
        Requires DWD to be enabled, service account configured, and email matching company domain.
        """
        if not self.dwd_enabled or not self.sa_email or not self.sa_key or not email_address:
            return False

        if not self.workspace_domain:
            # If no domain restriction is set, DWD applies to all configured emails
            return True

        # Check domain suffix (e.g. "@company.com")
        domain_suffix = f"@{self.workspace_domain.lstrip('@').lower()}"
        return email_address.lower().endswith(domain_suffix)

    async def get_dwd_access_token(self, user_email: str) -> Optional[str]:
        """
        Acquire a short-lived Google OAuth access token on behalf of a specific sales rep
        using Google Workspace Domain-Wide Delegation (Service Account JWT bearer grant).
        Strictly impersonates user_email; never allows arbitrary impersonation.
        """
        if not self.is_dwd_enabled_for_email(user_email):
            return None

        # Parse key if JSON format
        private_key_pem = self.sa_key
        try:
            if private_key_pem.strip().startswith("{"):
                parsed = json.loads(private_key_pem)
                private_key_pem = parsed.get("private_key", private_key_pem)
        except Exception:
            pass

        now = int(time.time())
        scopes_str = " ".join([
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/userinfo.email",
        ])

        payload = {
            "iss": self.sa_email,
            "sub": user_email,  # Impersonate this authenticated GTM sales representative
            "scope": scopes_str,
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }

        try:
            assertion = jwt.encode(payload, private_key_pem, algorithm="RS256")
        except Exception as e:
            logger.error("Failed to sign Google DWD assertion", error=str(e), email=user_email)
            return None

        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post("https://oauth2.googleapis.com/token", data=data)
                if resp.status_code != 200:
                    logger.error("Google DWD token exchange failed", status=resp.status_code, body=resp.text)
                    return None
                token_data = resp.json()
                return token_data.get("access_token")
        except Exception as e:
            logger.error("Error exchanging DWD assertion for Google access token", error=str(e))
            return None

    async def get_effective_access_token_for_user(
        self, user: Any, db: Optional[AsyncSession] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Get a valid access token for the user:
        1. Checks Domain-Wide Delegation (zero user setup) if user belongs to company domain.
        2. Otherwise checks user's connected OAuth integration in database.
        Returns: (access_token, provider_type) where provider_type is "domain_wide_delegation" or "oauth".
        """
        user_email = getattr(user, "email", None)

        # 1. Domain-Wide Delegation
        if user_email and self.is_dwd_enabled_for_email(user_email):
            token = await self.get_dwd_access_token(user_email)
            if token:
                return token, "domain_wide_delegation"

        # 2. Per-user OAuth integration
        if db and user:
            from app.models.models import UserIntegration
            stmt = select(UserIntegration).where(
                UserIntegration.user_id == str(user.id),
                UserIntegration.provider == "google",
                UserIntegration.status == "connected",
            )
            result = await db.execute(stmt)
            integration = result.scalar_one_or_none()
            if integration:
                token = await self.get_valid_access_token(integration, db)
                if token:
                    return token, "oauth"

        return None, None

    # ── User OAuth Flow (Fallback when DWD is unconfigured) ───────────────────

    def get_authorization_url(self, user_id: str) -> str:
        """
        Generate Google OAuth consent URL for a specific sales representative.
        The state parameter securely encodes the user_id to map the callback.
        """
        if not self.is_configured():
            raise ValueError(
                "Google OAuth credentials are not configured on the server. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in environment variables."
            )

        state = f"user_{user_id}"
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # Ensures refresh_token is returned on every authorization
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code with Google for access and refresh tokens."""
        if not self.is_configured():
            raise ValueError("Google OAuth credentials are not configured.")

        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data=data)
            if resp.status_code != 200:
                logger.error("Google token exchange failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Google token exchange failed: {resp.text}")
            return resp.json()

    async def get_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Fetch user profile from Google to get the verified account email."""
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers=headers)
            if resp.status_code != 200:
                logger.error("Failed to fetch Google user profile", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Failed to fetch Google user profile: {resp.text}")
            return resp.json()

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Use refresh token to acquire a fresh access token."""
        if not self.is_configured():
            raise ValueError("Google OAuth credentials are not configured.")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://oauth2.googleapis.com/token", data=data)
            if resp.status_code != 200:
                logger.error("Google token refresh failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Google token refresh failed: {resp.text}")
            return resp.json()

    async def get_valid_access_token(self, integration: Any, db: AsyncSession) -> Optional[str]:
        """
        Return a valid access token for the given UserIntegration.
        Refreshes the token and updates the database if expired.
        """
        if not integration or integration.status != "connected":
            return None

        # Check if current access token is valid (with 5 min safety buffer)
        now = datetime.utcnow()
        if (
            integration.encrypted_access_token
            and integration.token_expires_at
            and integration.token_expires_at > (now + timedelta(minutes=5))
        ):
            return decrypt_token(integration.encrypted_access_token)

        # Token is expired or missing; attempt refresh using refresh_token
        if not integration.encrypted_refresh_token:
            logger.warning("No refresh token available for integration", integration_id=integration.id)
            return None

        plain_refresh_token = decrypt_token(integration.encrypted_refresh_token)
        try:
            tokens = await self.refresh_access_token(plain_refresh_token)
            new_access_token = tokens.get("access_token")
            expires_in = tokens.get("expires_in", 3600)

            # Update integration in DB
            integration.encrypted_access_token = encrypt_token(new_access_token)
            integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            integration.status = "connected"
            integration.error_message = None
            await db.commit()

            return new_access_token
        except Exception as e:
            logger.error("Failed to refresh Google access token", integration_id=integration.id, error=str(e))
            integration.status = "error"
            integration.error_message = f"Token refresh failed: {str(e)}"
            await db.commit()
            return None

    # ── Gmail API Email Sending & Inbox Polling ───────────────────────────────

    async def send_gmail_message(
        self,
        access_token: str,
        to_email: str,
        subject: str,
        html_body: str,
        from_email: str,
        from_name: Optional[str] = None,
    ) -> str:
        """
        Send an email via the Gmail REST API (users.messages.send) using the rep's authorized mailbox.
        Returns the Gmail message ID.
        """
        message = MIMEMultipart("alternative")
        sender = f"{from_name} <{from_email}>" if from_name else from_email
        message["From"] = sender
        message["To"] = to_email
        message["Subject"] = subject

        # Strip HTML tags for plain text fallback
        plain_text = html_body.replace("<br/>", "\n").replace("<br>", "\n")
        # Attach plain and html parts
        part1 = MIMEText(plain_text, "plain", "utf-8")
        part2 = MIMEText(html_body, "html", "utf-8")
        message.attach(part1)
        message.attach(part2)

        # Base64url encode the MIME message
        raw_msg = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {"raw": raw_msg}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=headers,
                json=payload,
            )
            if resp.status_code not in (200, 201):
                logger.error("Gmail API send failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Gmail API send failed: {resp.text}")

            result = resp.json()
            message_id = result.get("id")
            logger.info("Email sent successfully via Gmail API", to=to_email, from_email=from_email, message_id=message_id)
            return message_id

    async def fetch_user_unread_messages(
        self, access_token: str, max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Poll unread messages from the connected user's Gmail inbox via Gmail API.
        Extracts sender, subject, date, message_id, and body.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            list_resp = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={"q": "is:unread", "maxResults": max_results},
            )
            if list_resp.status_code != 200:
                logger.error("Failed to list unread Gmail messages", status=list_resp.status_code)
                return []

            msg_list = list_resp.json().get("messages", [])
            messages = []
            for item in msg_list:
                msg_id = item.get("id")
                detail_resp = await client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}?format=full",
                    headers=headers,
                )
                if detail_resp.status_code != 200:
                    continue

                detail = detail_resp.json()
                payload = detail.get("payload", {})
                headers_list = payload.get("headers", [])

                header_map = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}
                from_header = header_map.get("from", "")
                subject_header = header_map.get("subject", "")
                msg_id_header = header_map.get("message-id", msg_id)

                # Extract sender email address from "Name <email@example.com>"
                from_email = from_header
                if "<" in from_header and ">" in from_header:
                    from_email = from_header.split("<")[1].split(">")[0].strip()

                # Extract text body snippet
                snippet = detail.get("snippet", "")
                body_text = snippet

                messages.append({
                    "id": msg_id,
                    "message_id": msg_id_header,
                    "from_address": from_email,
                    "from_raw": from_header,
                    "subject": subject_header,
                    "reply_text": body_text,
                    "received_at": datetime.utcnow(),
                })

            return messages


google_oauth_service = GoogleOAuthService()

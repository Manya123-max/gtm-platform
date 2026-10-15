"""
Microsoft Graph Service
Handles Microsoft 365 / Exchange Online OAuth and Graph API interactions for:
- Delegated Mail Sending (A3 Outreach via POST /me/sendMail, Mail.Send scope)
- Delegated Inbound Reply Reading (A4 Inbound via GET /me/messages, Mail.Read scope)
- Token refresh and encrypted persistence in user_integrations table.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.models import User, UserIntegration
from app.services.token_encryption import encrypt_token, decrypt_token

logger = structlog.get_logger(__name__)

MICROSOFT_DEFAULT_SCOPES = [
    "offline_access",
    "User.Read",
    "Mail.Send",
    "Mail.Read",
]


class MicrosoftGraphService:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        self.client_id = client_id or getattr(settings, "MICROSOFT_CLIENT_ID", None)
        self.client_secret = client_secret or getattr(settings, "MICROSOFT_CLIENT_SECRET", None)
        self.tenant_id = tenant_id or getattr(settings, "MICROSOFT_TENANT_ID", "common") or "common"
        self.redirect_uri = redirect_uri or getattr(
            settings, "MICROSOFT_REDIRECT_URI", "http://localhost:8000/api/v1/integrations/microsoft/callback"
        )
        self.graph_base = getattr(settings, "MICROSOFT_GRAPH_ENDPOINT", "https://graph.microsoft.com/v1.0")
        if scopes:
            self.scopes = scopes
        else:
            configured_scopes = getattr(settings, "MICROSOFT_SCOPES", None)
            if configured_scopes:
                self.scopes = [s.strip() for s in configured_scopes.split() if s.strip()]
            else:
                self.scopes = list(MICROSOFT_DEFAULT_SCOPES)

    def is_configured(self) -> bool:
        """Returns True if client_id and client_secret are provided."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: str) -> str:
        """Generates Microsoft OAuth 2.0 authorization URL."""
        if not self.client_id:
            raise RuntimeError("MICROSOFT_CLIENT_ID is not configured")

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(self.scopes),
            "state": state,
            "prompt": "consent",
        }
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/authorize?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchanges an authorization code for Microsoft Graph access & refresh tokens."""
        if not self.is_configured():
            raise RuntimeError("Microsoft OAuth credentials not fully configured")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(self.scopes),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                logger.error("Microsoft token exchange failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Microsoft token exchange error: {resp.text}")
            return resp.json()

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refreshes an expired access token using the stored refresh token."""
        if not self.is_configured():
            raise RuntimeError("Microsoft OAuth credentials not configured")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(self.scopes),
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                logger.error("Microsoft token refresh failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Microsoft token refresh error: {resp.text}")
            return resp.json()

    async def get_user_profile(self, access_token: str) -> Dict[str, Any]:
        """Fetches the authenticated user profile from Microsoft Graph /me."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.graph_base}/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch Microsoft profile: {resp.text}")
            data = resp.json()
            email = data.get("mail") or data.get("userPrincipalName", "")
            return {
                "id": data.get("id"),
                "display_name": data.get("displayName"),
                "email": email.lower().strip() if email else "",
                "given_name": data.get("givenName"),
                "surname": data.get("surname"),
            }

    async def get_valid_access_token(
        self,
        integration: UserIntegration,
        db: AsyncSession,
    ) -> Optional[str]:
        """
        Retrieves a valid decrypted access token for this user's Microsoft integration.
        Refreshes token automatically if expired and updates database record.
        """
        if integration.status != "connected":
            return None

        now = datetime.utcnow()
        if (
            integration.encrypted_access_token
            and integration.token_expires_at
            and integration.token_expires_at > (now + timedelta(minutes=5))
        ):
            return decrypt_token(integration.encrypted_access_token)

        # Token expired or missing; attempt refresh
        if not integration.encrypted_refresh_token:
            logger.warning("No Microsoft refresh token found", integration_id=integration.id)
            return None

        plain_refresh_token = decrypt_token(integration.encrypted_refresh_token)
        try:
            tokens = await self.refresh_access_token(plain_refresh_token)
            new_access_token = tokens.get("access_token")
            expires_in = tokens.get("expires_in", 3600)

            integration.encrypted_access_token = encrypt_token(new_access_token)
            integration.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            if "refresh_token" in tokens:
                integration.encrypted_refresh_token = encrypt_token(tokens["refresh_token"])
            integration.status = "connected"
            integration.error_message = None
            await db.commit()
            return new_access_token
        except Exception as refresh_err:
            logger.error("Failed to refresh Microsoft token", error=str(refresh_err), integration_id=integration.id)
            integration.status = "error"
            integration.error_message = f"Token refresh failed: {refresh_err}"
            await db.commit()
            return None

    async def send_mail(
        self,
        access_token: str,
        to_email: str,
        subject: str,
        html_body: str,
        from_email: Optional[str] = None,
        save_to_sent_items: bool = True,
    ) -> str:
        """
        Sends an email via Microsoft Graph POST /me/sendMail.
        Uses delegated least-privileged Mail.Send permission.
        The authenticated user's mailbox automatically serves as the sender.
        Returns a provider message ID or transmission identifier.
        """
        url = f"{self.graph_base}/me/sendMail"
        message_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body,
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email,
                        }
                    }
                ],
            },
            "saveToSentItems": save_to_sent_items,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=message_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code not in (200, 202):
                logger.error("Microsoft Graph sendMail failed", status=resp.status_code, body=resp.text)
                raise RuntimeError(f"Microsoft Graph sendMail failed ({resp.status_code}): {resp.text}")

            # /me/sendMail returns 202 Accepted on success with no JSON body
            # We return a generated transaction id or header request-id
            req_id = resp.headers.get("request-id") or f"msg_graph_{int(datetime.utcnow().timestamp())}"
            logger.info("Microsoft Graph email sent successfully", to=to_email, request_id=req_id)
            return req_id

    async def fetch_user_unread_messages(
        self,
        access_token: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Reads unread inbound messages from Microsoft Graph GET /me/messages.
        Uses delegated least-privileged Mail.Read permission.
        Returns standardized list of prospect replies.
        """
        params = {
            "$filter": "isRead eq false",
            "$top": str(max_results),
            "$select": "id,conversationId,subject,from,bodyPreview,body,receivedDateTime",
            "$orderby": "receivedDateTime desc",
        }
        url = f"{self.graph_base}/me/messages?{urlencode(params)}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                logger.error("Failed to fetch Microsoft Graph messages", status=resp.status_code, body=resp.text)
                return []

            data = resp.json()
            messages: List[Dict[str, Any]] = []
            for item in data.get("value", []):
                from_entry = item.get("from", {}).get("emailAddress", {})
                from_addr = (from_entry.get("address") or "").strip().lower()
                body_content = item.get("body", {}).get("content", "") or item.get("bodyPreview", "")

                messages.append({
                    "id": item.get("id"),
                    "conversation_id": item.get("conversationId"),
                    "from_address": from_addr,
                    "from_name": from_entry.get("name", ""),
                    "subject": item.get("subject", ""),
                    "reply_text": body_content,
                    "received_at": item.get("receivedDateTime"),
                })
            return messages

    async def mark_message_read(self, access_token: str, message_id: str) -> bool:
        """Marks a processed inbound message as read in Microsoft Graph."""
        url = f"{self.graph_base}/me/messages/{message_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                url,
                json={"isRead": True},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
            return resp.status_code == 200

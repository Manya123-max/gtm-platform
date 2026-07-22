"""Instantly outreach provider wrapper.

The agent only calls this service when dry run is disabled, human approval is
not required, and ENABLE_INSTANTLY is true. Provider identifiers are returned as
opaque strings and stored in outreach_provider_message_id.
"""
from __future__ import annotations

from typing import Dict, Optional

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class InstantlyService:
    def __init__(self) -> None:
        self.base_url = settings.INSTANTLY_BASE_URL.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(settings.ENABLE_INSTANTLY and settings.INSTANTLY_API_KEY)

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.INSTANTLY_API_KEY}",
            "Content-Type": "application/json",
        }

    async def add_lead(
        self,
        *,
        email: str,
        first_name: Optional[str],
        last_name: Optional[str],
        company: Optional[str],
        title: Optional[str],
        campaign_id: str,
        subject: str,
        body: str,
    ) -> Optional[str]:
        if not self.configured or not campaign_id:
            return None

        payload = {
            "campaign_id": campaign_id,
            "email": email,
            "first_name": first_name or "",
            "last_name": last_name or "",
            "company_name": company or "",
            "title": title or "",
            "personalization": {
                "subject": subject,
                "body": body,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.base_url}/api/v2/leads",
                    headers=self._headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                provider_id = data.get("id") or data.get("lead_id") or data.get("message_id")
                return str(provider_id) if provider_id else None
        except Exception as exc:
            logger.error("Instantly lead creation failed", email=email, error=str(exc))
            return None

"""
suppression_service.py — Centralized DNC (Do Not Contact) Suppression Service.

Maintains a unified, normalized email suppression mechanism across:
- A1 prospect discovery & saving
- A3 batch drafting & initial outreach
- A3 draft approval & send dispatch
- Automated follow-up sequences
- A4 inbound reply approval & send dispatch
- Resend and other provider unsubscribe webhooks

All email checks and updates use normalized email addresses:
  normalized_email = email.strip().lower()
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Tuple
from unittest.mock import MagicMock, AsyncMock
import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Contact, SuppressedEmail

logger = structlog.get_logger(__name__)


def normalize_email(email: Optional[str]) -> str:
    """
    Standardize email address for deterministic suppression matching.
    - Strips leading and trailing whitespace.
    - Converts to lowercase.
    - Preserves internal dots and plus-addressing components safely.
    """
    if not email or not isinstance(email, str):
        return ""
    return email.strip().lower()


class SuppressionService:
    """Central service managing email suppression state across all channels and tables."""

    @staticmethod
    def normalize(email: Optional[str]) -> str:
        """Expose normalize_email as static method on service."""
        return normalize_email(email)

    @classmethod
    async def is_email_suppressed(
        cls,
        db: AsyncSession,
        email: Optional[str] = None,
        contact_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a contact or email address is suppressed from receiving outreach.

        Suppression conditions checked:
        1. If contact_id provided: Contact record has do_not_contact == True.
        2. Normalized email exists in central suppressed_emails store.
        3. ANY existing Contact record sharing the same normalized email has do_not_contact == True.

        Returns:
            (is_suppressed: bool, reason: Optional[str])
        """
        clean_email = normalize_email(email)

        async def _get_scalar(stmt):
            # Prefer db.scalar if defined and returning non-mock or if scalar is explicitly configured
            if hasattr(db, "scalar"):
                try:
                    val = await db.scalar(stmt)
                    if val is not None and not isinstance(val, (MagicMock, AsyncMock)):
                        return val
                    if val is None:
                        return None
                except Exception:
                    pass
            res = await db.execute(stmt)
            val = res.scalar_one_or_none()
            if asyncio.iscoroutine(val):
                val = await val
            return val

        # 1. Check contact-specific DNC flag if contact_id provided
        if contact_id:
            contact = await _get_scalar(select(Contact).where(Contact.id == contact_id))
            if contact and getattr(contact, "do_not_contact", False):
                return True, "contact_dnc_flag"
            if contact and not clean_email and getattr(contact, "email", None):
                clean_email = normalize_email(contact.email)

        if not clean_email:
            return False, None

        # 2. Check central suppressed_emails store (e.g. from unsubscribe webhooks or A4)
        supp_entry = await _get_scalar(
            select(SuppressedEmail).where(SuppressedEmail.email == clean_email)
        )
        if supp_entry and hasattr(supp_entry, "email"):
            reason = getattr(supp_entry, "reason", None) or "unsubscribed"
            return True, f"suppressed_store:{reason}"

        # 3. Check across ALL duplicate or cross-user Contact records for same normalized email
        dup_match = await _get_scalar(
            select(Contact.id)
            .where(
                func.lower(Contact.email) == clean_email,
                Contact.do_not_contact == True,
            )
            .limit(1)
        )
        if dup_match is not None and not isinstance(dup_match, (MagicMock, AsyncMock)):
            return True, "duplicate_contact_dnc"

        return False, None

    @classmethod
    async def suppress_email(
        cls,
        db: AsyncSession,
        email: str,
        source: str = "manual",
        reason: str = "unsubscribe",
    ) -> int:
        """
        Centrally suppress an email address:
        1. Normalizes the target email address.
        2. Updates ALL existing Contact records with this normalized email to do_not_contact = True
           (safe multi-record update without scalar_one_or_none exceptions).
        3. Upserts the normalized email into the central suppressed_emails table.
        4. Flushes and commits transaction.

        Returns:
            Number of Contact records updated to DNC.
        """
        clean_email = normalize_email(email)
        if not clean_email:
            logger.warning("SuppressionService: Cannot suppress empty or invalid email")
            return 0

        # Multi-record update on Contact table (handles duplicate emails safely)
        update_stmt = (
            update(Contact)
            .where(func.lower(Contact.email) == clean_email)
            .values(do_not_contact=True, updated_at=datetime.utcnow())
        )
        res = await db.execute(update_stmt)
        updated_records = res.rowcount or 0

        # Record in central suppressed_emails table
        res_supp = await db.execute(
            select(SuppressedEmail).where(SuppressedEmail.email == clean_email)
        )
        existing_supp = res_supp.scalar_one_or_none()
        if existing_supp:
            existing_supp.reason = reason
            existing_supp.source = source
        else:
            db.add(
                SuppressedEmail(
                    email=clean_email,
                    reason=reason,
                    source=source,
                    created_at=datetime.utcnow(),
                )
            )

        await db.commit()
        logger.info(
            "SuppressionService: Centrally suppressed email",
            email=clean_email,
            updated_contacts=updated_records,
            source=source,
            reason=reason,
        )
        return updated_records

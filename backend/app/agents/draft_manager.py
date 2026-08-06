from datetime import datetime
from typing import List, Dict, Any, Optional
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.config import settings
from app.models.models import Contact, SignalEvent, OutreachLog, PendingAction, ActionStatus, OutreachDraft
from app.services.instantly_service import InstantlyService
from app.services.llm_service import LLMService

logger = structlog.get_logger()

class DraftManager:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.instantly = InstantlyService()
        self.llm = LLMService()

    async def create_draft(
        self,
        contact_id: str,
        signal_id: Optional[str],
        subject: str,
        body: str,
        business_case: str,
        matched_services: List[str],
        channel: str
    ) -> OutreachDraft:
        """Create and persist an OutreachDraft."""
        draft = OutreachDraft(
            contact_id=contact_id,
            signal_id=signal_id,
            subject=subject,
            body=body,
            business_case=business_case,
            matched_services=matched_services,
            channel=channel,
            status="pending",
            approval_state="pending"
        )
        self.db.add(draft)
        await self.db.flush()
        return draft

    async def has_pending_draft(self, contact_id: str, signal_id: Optional[str]) -> bool:
        """Check if there is already a pending draft for this contact-signal pair."""
        result = await self.db.execute(
            select(OutreachDraft)
            .where(and_(
                OutreachDraft.contact_id == contact_id,
                OutreachDraft.signal_id == signal_id,
                OutreachDraft.approval_state == "pending"
            ))
        )
        return result.scalars().first() is not None

    async def approve_draft(self, draft_id: str) -> dict:
        """Approve a draft and trigger send logic."""
        result = await self.db.execute(select(OutreachDraft).where(OutreachDraft.id == draft_id))
        draft = result.scalar_one_or_none()
        if not draft or draft.approval_state != "pending":
            return {"success": False, "sent_directly": False, "error": "Draft not found or not pending"}

        # Load contact and signal
        contact_res = await self.db.execute(select(Contact).where(Contact.id == draft.contact_id))
        contact = contact_res.scalar_one_or_none()
        
        signal = None
        if draft.signal_id:
            signal_res = await self.db.execute(select(SignalEvent).where(SignalEvent.id == draft.signal_id))
            signal = signal_res.scalar_one_or_none()

        if not contact or (not settings.AGENT3_TEST_MODE and not signal):
            draft.status = "failed"
            draft.approval_state = "approved"
            await self.db.flush()
            return {"success": False, "sent_directly": False, "error": "Missing contact or signal in production mode"}

        draft.approval_state = "approved"
        
        # Dispatch outreach using the existing send logic (via Instantly or Resend)
        provider_id = None
        sent_directly = False
        error_msg = None
        
        if settings.ENABLE_INSTANTLY:
            try:
                provider_id = await self.instantly.add_lead(
                    email=contact.email,
                    first_name=contact.first_name,
                    last_name=contact.last_name,
                    company=contact.company,
                    title=contact.title,
                    campaign_id=settings.INSTANTLY_CAMPAIGN_ID,
                    subject=draft.subject,
                    body=draft.body,
                )
                sent_directly = bool(provider_id)
                if not sent_directly:
                    error_msg = "Instantly API returned empty lead ID"
            except Exception as e:
                logger.error("Instantly API dispatch failed", error=str(e))
                sent_directly = False
                error_msg = f"Instantly error: {str(e)}"
        elif settings.ENABLE_EMAIL_SENDING and settings.RESEND_API_KEY:
            from app.services.resend_service import ResendService
            resend = ResendService()
            try:
                provider_id = await resend.send_email(
                    to=contact.email,
                    subject=draft.subject,
                    html=draft.body.replace("\n", "<br>"),
                )
                sent_directly = bool(provider_id)
                if not sent_directly:
                    error_msg = "Resend API returned empty message ID"
            except Exception as e:
                logger.error("Resend API send failed", error=str(e))
                sent_directly = False
                error_msg = f"Resend error: {str(e)}"
        else:
            logger.info("Outreach sending not enabled; mock-sending draft", email=contact.email)
            sent_directly = False
            error_msg = "Direct sending not enabled in config (ENABLE_INSTANTLY and ENABLE_EMAIL_SENDING are false)"

        # Mark draft as sent (since it's approved and we will either deliver it directly or via Gmail compose fallback)
        draft.status = "sent"
        
        # Log the outreach in OutreachLog
        campaign_type_val = "fallback:none:step0"
        if signal:
            sig_type = signal.signal_type.value if hasattr(signal.signal_type, 'value') else signal.signal_type
            campaign_type_val = f"{sig_type}:{signal.id}"[:40] + f":step{signal.sequence_step}"
        
        log = OutreachLog(
            contact_id=contact.id,
            campaign_type=campaign_type_val,
            channel=draft.channel,
            subject=draft.subject,
            body_preview=draft.body[:500],
            signal_id=signal.id if signal else None,
            outreach_provider_message_id=provider_id or "gmail_fallback",
            sequence_step=signal.sequence_step if signal else 0,
            sent_at=datetime.utcnow(),
        )
        self.db.add(log)
        
        # Step progression logic
        if signal:
            from app.agents.a3_outreach import SEQUENCE_TEMPLATES
            from datetime import timedelta
            
            steps = SEQUENCE_TEMPLATES.get(signal.signal_type, SEQUENCE_TEMPLATES["default"])["steps"]
            current_step_idx = signal.sequence_step
            signal.sequence_step += 1
            signal.triggered_outreach = True
            
            if signal.sequence_step >= len(steps):
                signal.processed = True
                signal.next_step_due_at = None
            else:
                next_step = steps[signal.sequence_step]
                current_step = steps[current_step_idx]
                delay_days = next_step["day"] - current_step["day"]
                if delay_days <= 0:
                    delay_days = 2
                signal.next_step_due_at = datetime.utcnow() + timedelta(days=delay_days)

        await self.db.flush()
        return {
            "success": True,
            "sent_directly": sent_directly,
            "error": error_msg
        }

    async def approve_pending_draft(self, contact_id: str) -> bool:
        """Helper to find and approve the most recent pending draft for a contact."""
        result = await self.db.execute(
            select(OutreachDraft)
            .where(and_(OutreachDraft.contact_id == contact_id, OutreachDraft.approval_state == "pending"))
            .order_by(OutreachDraft.created_at.desc())
            .limit(1)
        )
        draft = result.scalar_one_or_none()
        if draft:
            res = await self.approve_draft(draft.id)
            return res.get("success", False) if isinstance(res, dict) else bool(res)
        return False

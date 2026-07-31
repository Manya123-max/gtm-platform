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
        return result.scalar_one_or_none() is not None

    async def approve_draft(self, draft_id: str) -> bool:
        """Approve a draft and trigger send logic."""
        result = await self.db.execute(select(OutreachDraft).where(OutreachDraft.id == draft_id))
        draft = result.scalar_one_or_none()
        if not draft or draft.approval_state != "pending":
            return False

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
            return False

        draft.approval_state = "approved"
        
        # Dispatch outreach using the existing send logic (via Instantly)
        provider_id = None
        success = False
        if settings.ENABLE_INSTANTLY:
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
            success = bool(provider_id)
        else:
            # Safe default fallback for development/staging
            logger.info("Instantly not enabled; mock-sending draft", email=contact.email)
            success = True

        if success:
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
                outreach_provider_message_id=provider_id,
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
        else:
            draft.status = "failed"

        await self.db.flush()
        return success

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
            return await self.approve_draft(draft.id)
        return False

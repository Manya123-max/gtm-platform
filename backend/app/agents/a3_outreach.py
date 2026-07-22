"""
A3 — Multi-Channel Outreach Agent
Signal-matched sequences. Second-order personalisation using industry benchmarks.
Deduplication enforced before every send.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.config import settings
from app.models.models import (
    Contact, SignalEvent, OutreachLog, PromptVariant,
    FunnelEvent, SignalType, PendingAction, ActionStatus
)
from app.services.llm_service import LLMService
from app.services.instantly_service import InstantlyService

logger = structlog.get_logger()

# Signal-matched sequence templates
# Defines: channel order, timing, message angle per signal type
SEQUENCE_TEMPLATES = {
    SignalType.TECH_STACK_CHANGE: {
        "steps": [
            {"channel": "email", "day": 1, "angle": "tech_stack_reference"},
            {"channel": "linkedin", "day": 3, "angle": "connection_request"},
            {"channel": "email", "day": 7, "angle": "follow_up"},
        ],
        "urgency": "high",
    },
    SignalType.NEW_HIRE: {
        "steps": [
            {"channel": "email", "day": 2, "angle": "new_leader_evaluation"},
            {"channel": "linkedin", "day": 4, "angle": "connection_request"},
        ],
        "urgency": "high",
    },
    SignalType.FUNDING_ROUND: {
        "steps": [
            {"channel": "email", "day": 1, "angle": "funding_milestone"},
            {"channel": "linkedin", "day": 2, "angle": "connection_request"},
            {"channel": "email", "day": 6, "angle": "scale_focus"},
        ],
        "urgency": "high",
    },
    SignalType.JOB_POSTING: {
        "steps": [
            {"channel": "email", "day": 3, "angle": "hiring_pattern"},
        ],
        "urgency": "medium",
    },
    SignalType.EARNINGS_CALL: {
        "steps": [
            {"channel": "email", "day": 1, "angle": "earnings_reference"},
        ],
        "urgency": "high",
    },
    "default": {
        "steps": [
            {"channel": "email", "day": 5, "angle": "general_value"},
        ],
        "urgency": "low",
    },
}


class OutreachAgent:
    """
    A3: Generates and sends signal-matched, personalised outreach.

    Key behaviours:
    - Checks outreach_log before every send (60-day dedup window)
    - Selects highest-performing prompt variant per signal type
    - Second-order personalisation: industry benchmarks, not just prospect activity
    - Sends via Instantly only when dry run and human approval are disabled
    - Generates call script and LinkedIn note alongside every email draft
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.instantly = InstantlyService()

    async def run(self, contact_signal_pairs: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Process qualified contacts with signals and send outreach.
        """
        logger.info("A3 starting")

        # Get contacts with qualifying signals if not provided
        if not contact_signal_pairs:
            contact_signal_pairs = await self._get_qualified_contacts()

        logger.info("Processing contacts", count=len(contact_signal_pairs))

        sent = 0
        drafts_created = 0
        skip_reasons = {
            "do_not_contact": 0,
            "deduplicated": 0,
            "missing_email": 0,
            "invalid_email": 0,
            "missing_contact_or_signal": 0,
            "generation_failed": 0,
            "send_failed": 0,
        }

        for pair in contact_signal_pairs:
            contact, signal = await self._resolve_pair(pair)
            if not contact or not signal:
                skip_reasons["missing_contact_or_signal"] += 1
                continue
            if contact.do_not_contact:
                skip_reasons["do_not_contact"] += 1
                continue
            if not contact.email:
                skip_reasons["missing_email"] += 1
                continue
            if contact.email_valid is False:
                skip_reasons["invalid_email"] += 1
                continue
            if await self._already_contacted(contact.id, signal.id):
                skip_reasons["deduplicated"] += 1
                continue

            # Generate message
            message = await self._generate_message(contact, signal)
            if not message:
                skip_reasons["generation_failed"] += 1
                continue

            # Send or draft
            if settings.DRY_RUN_OUTREACH or settings.REQUIRE_HUMAN_APPROVAL:
                await self._save_draft(contact, message, signal)
                drafts_created += 1
            elif settings.ENABLE_INSTANTLY:
                success = await self._send_via_instantly(contact, message, signal)
                if success:
                    sent += 1
                else:
                    skip_reasons["send_failed"] += 1
            else:
                # Save as draft — safe default for dev/staging
                await self._save_draft(contact, message, signal)
                drafts_created += 1

        await self._log_funnel_event("outreach_batch_completed", {
            "processed": len(contact_signal_pairs),
            "sent": sent,
            "drafts": drafts_created,
            "skip_reasons": skip_reasons,
        })

        return {
            "agent": "A3",
            "processed": len(contact_signal_pairs),
            "sent": sent,
            "drafts_created": drafts_created,
            "skipped": sum(skip_reasons.values()),
            "skip_reasons": skip_reasons,
            "reason": (
                "No qualifying signal/contact pairs found"
                if not contact_signal_pairs else
                "Drafts created for human approval"
                if drafts_created else
                "Outreach sent via Instantly"
                if sent else
                "No outreach sent; see skip_reasons"
            ),
        }

    async def _resolve_pair(self, pair: Dict[str, Any]):
        if pair.get("contact") is not None and pair.get("signal") is not None:
            return pair["contact"], pair["signal"]
        contact_id = pair.get("contact_id")
        if not contact_id:
            return None, None
        contact_result = await self.db.execute(select(Contact).where(Contact.id == contact_id))
        contact = contact_result.scalar_one_or_none()
        signal_query = select(SignalEvent).where(SignalEvent.contact_id == contact_id)
        if pair.get("signal_type"):
            signal_query = signal_query.where(SignalEvent.signal_type == pair["signal_type"])
        signal_query = signal_query.order_by(SignalEvent.detected_at.desc()).limit(1)
        signal_result = await self.db.execute(signal_query)
        return contact, signal_result.scalar_one_or_none()

    async def _get_qualified_contacts(self) -> List[Dict]:
        """
        Pull contacts with signals above threshold that haven't been contacted recently.
        """
        result = await self.db.execute(
            select(Contact, SignalEvent)
            .join(SignalEvent, SignalEvent.contact_id == Contact.id)
            .where(
                and_(
                    Contact.do_not_contact == False,
                    Contact.icp_score >= settings.ICP_SCORE_THRESHOLD,
                    SignalEvent.confidence >= settings.SIGNAL_SCORE_THRESHOLD / 100,
                    SignalEvent.processed == False,
                    SignalEvent.detected_at >= datetime.utcnow() - timedelta(days=30),
                )
            )
            .order_by(SignalEvent.confidence.desc())
            .limit(100)
        )
        pairs = []
        for contact, signal in result.all():
            pairs.append({"contact": contact, "signal": signal})
        return pairs

    async def _already_contacted(self, contact_id: str, signal_id: str) -> bool:
        """
        Check outreach_log. Hard block if contacted within EMAIL_DEDUP_DAYS.
        """
        result = await self.db.execute(
            select(OutreachLog).where(
                and_(
                    OutreachLog.contact_id == contact_id,
                    OutreachLog.signal_id == signal_id,
                    OutreachLog.sent_at >= datetime.utcnow() - timedelta(days=settings.EMAIL_DEDUP_DAYS),
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def _get_best_variant(self, signal_type: str) -> Optional[PromptVariant]:
        """
        Select the prompt variant with the highest reply_rate for this signal type.
        Falls back to first active variant if no performance data yet.
        """
        result = await self.db.execute(
            select(PromptVariant).where(
                and_(
                    PromptVariant.signal_type == signal_type,
                    PromptVariant.is_active == True,
                )
            ).order_by(PromptVariant.reply_rate.desc())
        )
        return result.scalars().first()

    async def _generate_message(self, contact: Contact, signal: SignalEvent) -> Optional[Dict]:
        """
        Generate personalised email using Claude.
        Haiku for standard contacts, Sonnet for ICP score > 85.
        Includes second-order personalisation via industry benchmarks.
        """
        variant = await self._get_best_variant(signal.signal_type)
        template = SEQUENCE_TEMPLATES.get(signal.signal_type, SEQUENCE_TEMPLATES["default"])

        # Build context for personalisation
        context = {
            "first_name": contact.first_name or "there",
            "company": contact.company or "",
            "title": contact.title or "",
            "signal_type": signal.signal_type,
            "signal_data": signal.raw_data or {},
            "industry": contact.industry or "",
            "company_size": contact.company_size or "",
            "funding_stage": contact.funding_stage or "",
            "angle": template["steps"][0]["angle"],
        }

        system_prompt = variant.system_prompt if variant else self._default_system_prompt(signal.signal_type)
        user_prompt = self._build_user_prompt(context, signal.signal_type)

        # Use Sonnet for high-value prospects, Haiku for standard
        use_sonnet = (contact.icp_score or 0) > 85

        try:
            response = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=use_sonnet,
                response_format={"subject": "string", "body": "string"},
            )
            return {
                "subject": response.get("subject", ""),
                "body": response.get("body", ""),
                "variant_id": variant.id if variant else "default",
                "channel": "email",
            }
        except Exception as e:
            logger.error("Message generation failed", contact_email=contact.email, error=str(e))
            return None

    # ── NEW: Call script generation ───────────────────────────────────────

    async def _generate_call_script(
        self, contact: Contact, signal: SignalEvent, services: str = ""
    ) -> str:
        """Generate a short cold call script for the contact."""
        system = (
            "You are a B2B sales rep. Write a 60-second cold call script. "
            "Be concise, reference the signal, ask for a meeting. "
            "Format: Opener → Signal reference → Value prop → Ask."
        )
        user = (
            f"Contact: {contact.first_name} {contact.last_name}, "
            f"{contact.title} at {contact.company}. "
            f"Signal: {signal.signal_type}. "
            f"Our services: {services or 'GTM automation platform'}."
        )
        try:
            return await self.llm.complete_raw(system, user, max_tokens=300)
        except Exception:
            return (
                f"Hi {contact.first_name}, this is [Your Name] from [Company]. "
                f"I noticed {contact.company} recently {signal.signal_type.replace('_', ' ')} "
                f"and wanted to discuss how we help similar companies. "
                f"Do you have 15 minutes this week?"
            )

    # ── NEW: LinkedIn connection note generation ──────────────────────────

    async def _generate_linkedin_connect(
        self, contact: Contact, signal: SignalEvent
    ) -> str:
        """Generate a LinkedIn connection request note under 300 characters."""
        system = (
            "Write a LinkedIn connection request note under 300 characters. "
            "Professional, personalised, no hard sell."
        )
        user = (
            f"Connect with {contact.first_name} {contact.last_name}, "
            f"{contact.title} at {contact.company}. "
            f"Context: {signal.signal_type.replace('_', ' ')}."
        )
        try:
            return await self.llm.complete_raw(system, user, max_tokens=100)
        except Exception:
            return (
                f"Hi {contact.first_name}, I came across {contact.company} "
                f"and would love to connect. Looking forward to it!"
            )

    # ── End new methods ───────────────────────────────────────────────────

    def _default_system_prompt(self, signal_type: str) -> str:
        return f"""You are a professional B2B sales rep writing a personalised cold email.

Rules:
- Maximum 150 words in the body
- Reference the specific trigger signal naturally, do not be creepy about it
- Focus on a single specific value point, not a list of features
- End with one clear, low-friction call to action (a question, not a meeting request)
- Do not use phrases like: "I hope this email finds you well", "quick question", "I wanted to reach out"
- Sound like a human, not a template
- Signal type context: {signal_type.replace('_', ' ')}

Return valid JSON with exactly two fields: "subject" and "body"."""

    def _build_user_prompt(self, context: Dict, signal_type: str) -> str:
        angle_descriptions = {
            "tech_stack_reference": f"Reference that {context['company']} recently changed their tech stack (data: {context['signal_data']}). Frame your product as complementary.",
            "new_leader_evaluation": f"{context['company']} just hired a new {context['title']}. New leaders typically re-evaluate vendor relationships.",
            "funding_milestone": f"{context['company']} recently raised funding. Frame around what's needed at their new stage.",
            "hiring_pattern": f"{context['company']} is hiring SDRs/BDRs (data: {context['signal_data']}). Reference the specific roles.",
            "earnings_reference": f"Reference a specific pain they mentioned publicly.",
            "general_value": "Focus on a specific problem common in their industry at their stage.",
        }
        angle_desc = angle_descriptions.get(context["angle"], angle_descriptions["general_value"])

        return f"""Write an email to {context['first_name']} at {context['company']}.

Their context:
- Title: {context['title']}
- Industry: {context['industry']}
- Company size: {context['company_size']}
- Funding stage: {context['funding_stage']}

Personalisation angle: {angle_desc}

Return JSON: {{"subject": "...", "body": "..."}}"""

    async def _send_via_instantly(self, contact: Contact, message: Dict, signal: SignalEvent) -> bool:
        provider_id = await self.instantly.add_lead(
            email=contact.email,
            first_name=contact.first_name,
            last_name=contact.last_name,
            company=contact.company,
            title=contact.title,
            campaign_id=settings.INSTANTLY_CAMPAIGN_ID,
            subject=message.get("subject", ""),
            body=message.get("body", ""),
        )
        if not provider_id:
            logger.error("Instantly send failed", email=contact.email)
            return False

        logger.info("Instantly send ok", email=contact.email, provider_id=provider_id)
        await self._log_outreach(contact, message, signal, provider_id)
        return True

    async def _save_draft(self, contact: Contact, message: Dict, signal: SignalEvent):
        """Save generated message as draft — used in dev/staging."""
        await self._log_outreach(contact, message, signal, None, is_draft=True)

    async def _log_outreach(
        self, contact: Contact, message: Dict, signal: SignalEvent,
        provider_message_id: Optional[str], is_draft: bool = False
    ):
        # NEW: generate call script and LinkedIn note alongside the email
        call_script = await self._generate_call_script(contact, signal)
        linkedin_note = await self._generate_linkedin_connect(contact, signal)

        log = OutreachLog(
            contact_id=contact.id,
            campaign_type=f"{signal.signal_type}:{signal.id}",
            channel=message.get("channel", "email"),
            subject=message.get("subject"),
            body_preview=message.get("body", "")[:500],
            prompt_variant_id=message.get("variant_id"),
            signal_id=signal.id,
            outreach_provider_message_id=provider_message_id,
            sent_at=datetime.utcnow(),
        )
        self.db.add(log)

        if is_draft or settings.REQUIRE_HUMAN_APPROVAL:
            self.db.add(PendingAction(
                action_type="approve_outreach",
                entity_type="contact",
                entity_id=str(contact.id),
                recommended_value=message.get("subject"),
                current_value="draft",
                reason=(
                    f"Review A3 draft for {contact.email}. "
                    f"Call script: {call_script[:180]} "
                    f"LinkedIn note: {linkedin_note[:180]}"
                ),
                agent_id="A3",
                status=ActionStatus.PENDING,
            ))

        # Mark signal as processed
        signal.processed = True
        signal.triggered_outreach = not is_draft

        funnel_event = FunnelEvent(
            event_type="email_draft_created" if is_draft else "email_sent",
            contact_id=contact.id,
            agent_id="A3",
            event_metadata={
                "signal_type": signal.signal_type,
                "variant_id": message.get("variant_id"),
                "is_draft": is_draft,
                "provider": "instantly" if provider_message_id else "draft",
            },
        )
        self.db.add(funnel_event)
        await self.db.commit()

    async def update_variant_performance(self, variant_id: str, replied: bool, meeting_booked: bool):
        """
        Called by A4 when a reply arrives or meeting is booked.
        Updates reply_rate for prompt variant selection.
        """
        result = await self.db.execute(
            select(PromptVariant).where(PromptVariant.id == variant_id)
        )
        variant = result.scalar_one_or_none()
        if not variant:
            return

        variant.send_count += 0  # already counted at send time
        if replied:
            variant.reply_count += 1
        if meeting_booked:
            variant.meeting_count += 1

        if variant.send_count > 0:
            variant.reply_rate = variant.reply_count / variant.send_count

        variant.updated_at = datetime.utcnow()
        await self.db.commit()

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A3", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()

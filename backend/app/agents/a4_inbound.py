"""
A4 — Conversation Intelligence Agent
Full conversation thread memory loaded before every reply.
Rolling readiness score 0-100. Meeting request fires at threshold, not any positive reply.
Human-in-the-loop via Slack with 2-hour timeout.
"""
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, asc

from app.core.config import settings
from app.models.models import (
    Contact, ConversationThread, OutreachLog,
    FunnelEvent, PendingAction
)
from app.services.llm_service import LLMService
from app.services.slack_service import SlackService
from app.services.cal_service import CalService
from app.services.notification_service import NtfyService 
from app.services.resend_service import ResendService

logger = structlog.get_logger()


def _clean_json_str(content: str) -> str:
    """Strip markdown code fences from JSON strings."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    return content.strip()


# Readiness score deltas per event type
READINESS_DELTAS = {
    "reply_interested": 15,
    "reply_meeting_request": 25,
    "reply_pricing": 15,
    "reply_technical_question": 10,
    "reply_referral": 10,
    "reply_not_interested": -15,
    "reply_unsubscribe": -100,
    "reply_unknown": 0,
    "email_opened_3x": 5,
    "no_engagement_14d": -15,
}

REPLY_INTENT_CLASSES = [
    "interested",
    "meeting_request",
    "pricing",
    "technical_question",
    "referral",
    "not_interested",
    "unsubscribe",
    "unknown",
]


class InboundAgent:
    """
    A4: Handles all inbound replies from the inbound-reply webhook.

    Flow:
    1. Load full conversation thread for context
    2. Classify reply intent (7 classes) using Claude Haiku
    3. Update readiness score
    4. If score >= threshold: generate draft response, send to Slack for approval
    5. On approval: send reply + Cal.com booking link
    6. On 2h timeout: send safe default response
    7. Auto-suppress non-interested/unsubscribe reply types
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.slack = SlackService()
        self.ntfy = NtfyService() 
        self.cal = CalService()
        self.resend = ResendService()

    async def handle_reply(self, webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Entry point. Called by webhook handler when an inbound reply is received.
        """
        email = webhook_payload.get("from_address", "")
        reply_text = webhook_payload.get("reply_text", "")
        campaign_id = webhook_payload.get("campaign_id", "")

        logger.info("A4: Received inbound reply", email=email, reply_text=reply_text[:100])

        # Find contact
        contact = await self._find_contact(email)
        if not contact:
            logger.warning("A4: Contact not found for reply email", email=email)
            return {"status": "contact_not_found", "email": email}

        # Load conversation thread
        logger.info("A4: Loading conversation history", contact_id=contact.id)
        thread = await self._load_thread(contact.id)

        # Classify intent using Claude Haiku (cheap — ~$0.001 per classification)
        logger.info("A4: Classifying reply intent using Claude Haiku", contact_id=contact.id)
        intent, confidence = await self._classify_intent(reply_text, thread)
        logger.info("A4: Reply classified", contact_id=contact.id, intent=intent, confidence=confidence)

        # Handle non-interested / suppression types immediately (no human loop needed)
        if intent == "unsubscribe":
            contact.do_not_contact = True
            delta = READINESS_DELTAS["reply_unsubscribe"]
            new_score = max(0, (contact.readiness_score or 0) + delta)
            contact.readiness_score = new_score
            await self.db.commit()
            await self._record_thread_event(
                contact.id, reply_text, intent, confidence,
                delta=delta, score_after=new_score
            )
            logger.info("A4: Unsubscribe reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "unsubscribed", "email": email, "readiness_score": new_score}

        if intent == "not_interested":
            delta = READINESS_DELTAS["reply_not_interested"]
            new_score = max(0, (contact.readiness_score or 0) + delta)
            contact.readiness_score = new_score
            await self.db.commit()
            await self._record_thread_event(contact.id, reply_text, intent, confidence, delta=delta, score_after=new_score)
            logger.info("A4: Not interested reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "not_interested", "readiness_score": new_score}

        if intent == "unknown":
            delta = READINESS_DELTAS["reply_unknown"]
            new_score = contact.readiness_score or 0
            await self._record_thread_event(contact.id, reply_text, intent, confidence, delta=delta, score_after=new_score)
            logger.info("A4: Unknown reply intent, logged for manual review", contact_id=contact.id, email=email)
            return {"status": "unknown_intent", "queued_for_review": True}

        # Handle interested, meeting_request, pricing, technical_question, referral
        delta = READINESS_DELTAS.get(f"reply_{intent}", 10)
        old_score = contact.readiness_score or 0
        new_score = min(100, old_score + delta)
        contact.readiness_score = new_score
        logger.info(
            "A4: Gradual readiness score updated",
            contact_id=contact.id,
            intent=intent,
            old_score=old_score,
            new_score=new_score,
            delta=delta
        )

        # Generate draft response
        logger.info("A4: Generating draft reply via Claude Haiku", contact_id=contact.id, intent=intent)
        draft = await self._generate_draft(contact, reply_text, thread, intent)

        # Record thread event (ConversationThread is the single source of truth)
        logger.info("A4: Storing event in ConversationThread", contact_id=contact.id)
        thread_event = await self._record_thread_event(
            contact.id, reply_text, intent, confidence,
            delta=delta, score_after=new_score, draft=draft
        )

        # Log funnel event
        await self._log_funnel_event("reply_received", contact.id, {
            "intent": intent,
            "readiness_score": new_score,
        })

        # Check if meeting threshold crossed
        should_request_meeting = new_score >= settings.READINESS_SCORE_MEETING_THRESHOLD

        # Notify a human — Slack (interactive) or ntfy (heads-up only)
        logger.info("A4: Sending draft response for manual approval", contact_id=contact.id, thread_event_id=thread_event.id)
        if settings.ENABLE_SLACK_APPROVALS or settings.NOTIFICATION_PROVIDER == "slack":
            slack_ts = await self.slack.send_approval_request(
                contact=contact,
                reply_text=reply_text,
                draft_response=draft,
                intent=intent,
                readiness_score=new_score,
                should_include_calendar=should_request_meeting,
                thread_event_id=thread_event.id,
            )
            if slack_ts:
                thread_event.slack_message_ts = slack_ts
                await self.db.commit()
        else:
            await self.ntfy.send_approval_alert(
                contact=contact,
                reply_text=reply_text,
                draft_response=draft,
                intent=intent,
                readiness_score=new_score,
                thread_event_id=thread_event.id,
            )

        # Schedule fallback task (2-hour timeout) — ALWAYS, regardless of
        # notification provider, so a reply can never sit unanswered forever.
        logger.info("A4: Scheduling 2-hour fallback timeout task", thread_event_id=thread_event.id)
        from app.core.celery_app import celery_app
        celery_app.send_task(
            "app.workers.agent_tasks.reply_approval_timeout",
            args=[thread_event.id],
            countdown=7200,  # 2 hours
        )

        await self.db.commit()

        logger.info(
            "A4: Reply processing complete. Awaiting manual approval.",
            contact_id=contact.id,
            thread_event_id=thread_event.id,
            readiness_score=new_score
        )

        return {
            "agent": "A4",
            "status": "pending_approval",
            "intent": intent,
            "readiness_score": new_score,
            "meeting_threshold_reached": should_request_meeting,
            "thread_event_id": thread_event.id,
        }

    async def approve_reply(
        self, thread_event_id: str, approved_by: str, custom_content: Optional[str] = None
    ) -> bool:
        """
        Called by Slack action handler when rep approves a draft (or saves an edited response).
        Sends the reply and optionally adds a booking link.
        """
        result = await self.db.execute(
            select(ConversationThread).where(ConversationThread.id == thread_event_id)
        )
        thread_event = result.scalar_one_or_none()
        if not thread_event or thread_event.approved_at or thread_event.rejected_at:
            return False

        if custom_content:
            thread_event.draft_content = custom_content

        contact_result = await self.db.execute(
            select(Contact).where(Contact.id == thread_event.contact_id)
        )
        contact = contact_result.scalar_one_or_none()

        # Get booking link if readiness score is high enough
        booking_link = None
        if (contact and contact.readiness_score >= settings.READINESS_SCORE_MEETING_THRESHOLD):
            booking_link = await self.cal.get_booking_link(
                contact_email=contact.email,
                contact_name=f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
            )

        # Send the approved reply via Resend
        if settings.ENABLE_EMAIL_SENDING and contact:
            final_response = thread_event.draft_content or ""
            if booking_link:
                final_response += f"\n\nHere's my calendar if you'd like to find a time: {booking_link}"
            await self._send_reply_via_resend(contact, final_response)

        thread_event.approved_by = approved_by
        thread_event.approved_at = datetime.utcnow()
        thread_event.sent_at = datetime.utcnow()
        await self.db.commit()

        if contact and booking_link:
            await self._log_funnel_event("booking_link_sent", contact.id, {"booking_link": booking_link})

        # Trigger A5 (Deal Intelligence scan) as configured in AGENT_GRAPH["A4"]["next"] = ["A5"]
        from app.core.celery_app import celery_app
        celery_app.send_task("app.workers.scheduler_tasks.run_deal_scan")

        return True

    async def reject_reply(self, thread_event_id: str, rejected_by: str) -> bool:
        """
        Called by Slack action handler when rep rejects a draft.
        Marks the draft as rejected and prevents any auto-send timeout.
        """
        result = await self.db.execute(
            select(ConversationThread).where(ConversationThread.id == thread_event_id)
        )
        thread_event = result.scalar_one_or_none()
        if not thread_event or thread_event.approved_at or thread_event.rejected_at:
            return False

        thread_event.rejected_by = rejected_by
        thread_event.rejected_at = datetime.utcnow()
        await self.db.commit()

        if thread_event.contact_id:
            await self._log_funnel_event("reply_rejected", thread_event.contact_id, {"rejected_by": rejected_by})

        logger.info("Reply rejected by rep", thread_event_id=thread_event_id, rejected_by=rejected_by)
        return True

    async def handle_timeout(self, thread_event_id: str):
        """
        Called 2 hours after Slack message if no approval received.
        Sends safe default response with calendar link if REQUIRE_HUMAN_APPROVAL is False.
        """
        result = await self.db.execute(
            select(ConversationThread).where(ConversationThread.id == thread_event_id)
        )
        thread_event = result.scalar_one_or_none()

        if not thread_event or thread_event.approved_at or thread_event.rejected_at:
            return  # Already handled or explicitly rejected

        contact_result = await self.db.execute(
            select(Contact).where(Contact.id == thread_event.contact_id)
        )
        contact = contact_result.scalar_one_or_none()

        # If REQUIRE_HUMAN_APPROVAL is enabled, suppress auto-send fallback
        if settings.REQUIRE_HUMAN_APPROVAL:
            logger.info(
                "Timeout auto-send suppressed due to REQUIRE_HUMAN_APPROVAL=True",
                thread_event_id=thread_event_id
            )
            if contact:
                await self._log_funnel_event(
                    "timeout_approval_required",
                    contact.id,
                    {"thread_event_id": thread_event_id}
                )
            return

        booking_link = await self.cal.get_booking_link(
            contact_email=contact.email if contact else "",
            contact_name=contact.first_name or "" if contact else "",
        )

        default_response = f"Thanks for getting back to me. Happy to find a time to connect — here's my calendar: {booking_link}"

        if settings.ENABLE_EMAIL_SENDING and contact:
            await self._send_reply_via_resend(contact, default_response)

        thread_event.approved_by = "auto_timeout"
        thread_event.approved_at = datetime.utcnow()
        thread_event.sent_at = datetime.utcnow()
        await self.db.commit()

        logger.info("Timeout default response sent", thread_event_id=thread_event_id)

        # Trigger A5 (Deal Intelligence scan) as configured in AGENT_GRAPH["A4"]["next"] = ["A5"]
        from app.core.celery_app import celery_app
        celery_app.send_task("app.workers.scheduler_tasks.run_deal_scan")

    async def _classify_intent(self, reply_text: str, thread: List[ConversationThread]) -> tuple[str, float]:
        """
        Claude Haiku: fast, cheap (~$0.001 per call) intent classification.
        Returns (intent_class, confidence).
        """
        thread_context = "\n".join([
            f"[{t.direction.upper()}] {(t.content or '')[:200]}" for t in thread[-5:]
        ]) if thread else "No prior context"

        prompt = f"""Classify the intent of this email reply. Return JSON only.

Conversation context (last 5 messages):
{thread_context}

Latest reply to classify:
"{reply_text}"

Return exactly this JSON:
{{"intent": "<class>", "confidence": <0.0-1.0>}}

Intent classes:
- interested: prospect wants to learn more, positive engagement, but hasn't explicitly requested a meeting yet
- meeting_request: prospect explicitly asks to schedule a meeting, call, or demo
- pricing: prospect asks about pricing, rates, quotes, or costs
- technical_question: prospect asks technical questions about integration, stack, or capabilities
- referral: prospect forwards to someone else or asks to contact another team member
- not_interested: clearly not interested, wrong time, no fit
- unsubscribe: prospect wants to opt-out, be removed, unsubscribe, or stop emails
- unknown: unclear, ambiguous, or non-standard reply (e.g. out of office, delivery failure)"""

        try:
            result = await self.llm.complete_raw(prompt, use_haiku=True)
            cleaned_result = _clean_json_str(result)
            import json
            parsed = json.loads(cleaned_result)
            return parsed.get("intent", "unknown"), parsed.get("confidence", 0.5)
        except Exception as e:
            logger.error("Intent classification failed", error=str(e))
            return "unknown", 0.0

    async def _generate_draft(
        self, contact: Contact, reply_text: str,
        thread: List[ConversationThread], intent: str
    ) -> str:
        """Generate a contextual draft response using Claude Haiku."""
        thread_context = "\n".join([
            f"[{t.direction.upper()}]: {(t.content or '')[:300]}" for t in thread[-8:]
        ]) if thread else "No prior context"

        prompt = f"""Write a short, natural reply to this prospect's email.

Contact: {contact.first_name or 'there'} at {contact.company or 'their company'}
Intent detected: {intent}

Conversation history:
{thread_context}

Their latest reply:
"{reply_text}"

Rules:
- Maximum 100 words
- Sound human, not templated
- If intent is interested: acknowledge their interest, offer specific value, end with one question OR calendar invite
- If intent is referral: thank them and ask for the right contact's details
- Do NOT include a calendar link (that will be added separately if needed)

Return only the email body text, no subject line."""

        try:
            return await self.llm.complete_raw(prompt, use_haiku=True)
        except Exception as e:
            logger.error("Draft generation failed", error=str(e))
            return "Thank you for getting back to me. I'd love to find a time to connect — here's my calendar link."

    async def _load_thread(self, contact_id: str) -> List[ConversationThread]:
        result = await self.db.execute(
            select(ConversationThread)
            .where(ConversationThread.contact_id == contact_id)
            .order_by(asc(ConversationThread.occurred_at))
        )
        return list(result.scalars().all())

    async def _find_contact(self, email: str) -> Optional[Contact]:
        result = await self.db.execute(
            select(Contact).where(Contact.email == email)
        )
        return result.scalar_one_or_none()

    async def _record_thread_event(
        self, contact_id: str, content: str, intent: str,
        confidence: float, delta: float, score_after: float = 0,
        draft: Optional[str] = None
    ) -> ConversationThread:
        event = ConversationThread(
            contact_id=contact_id,
            event_type="reply_received",
            direction="inbound",
            channel="email",
            content=content,
            intent=intent,
            intent_confidence=confidence,
            readiness_score_delta=delta,
            readiness_score_after=score_after,
            draft_generated=bool(draft),
            draft_content=draft,
            occurred_at=datetime.utcnow(),
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def _send_reply_via_resend(self, contact: Contact, body: str):
        """Send the reply email via Resend (free tier)."""
        html = "<br>".join(body.splitlines()) or body
        message_id = await self.resend.send_email(
            to=contact.email,
            subject="Re: your message",
            html=html,
        )
        if message_id:
            logger.info("Resend reply sent", email=contact.email, message_id=message_id)
        else:
            logger.error("Resend reply send failed", email=contact.email)

    async def _log_funnel_event(self, event_type: str, contact_id: str, metadata: Dict):
        event = FunnelEvent(
            event_type=event_type,
            contact_id=contact_id,
            agent_id="A4",
            event_metadata=metadata,
        )
        self.db.add(event)
        await self.db.commit()

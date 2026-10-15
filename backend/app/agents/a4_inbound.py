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
    Contact, ConversationThread, User, OutreachLog,
    FunnelEvent, PendingAction, Notification, ContactUserInputAssociation, UserInput
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

    async def handle_reply(self, webhook_payload: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Entry point. Called by webhook handler or IMAP poller when an inbound reply is received.
        If user_id is provided, strictly associates reply with contacts owned by that sales rep.
        """
        email = webhook_payload.get("from_address", "")
        reply_text = webhook_payload.get("reply_text", "")
        campaign_id = webhook_payload.get("campaign_id", "")
        subject = webhook_payload.get("subject", "")
        message_id = webhook_payload.get("message_id") or webhook_payload.get("email_id") or webhook_payload.get("id")

        logger.info("A4: Received inbound reply", email=email, subject=subject, reply_text=reply_text[:100], user_id=user_id)

        # Find contact scoped to user if user_id is specified
        contact = await self._find_contact(email, subject=subject, user_id=user_id)
        if not contact:
            logger.warning("A4: Contact not found for reply email, safely ignoring", email=email)
            return {"status": "contact_not_found", "email": email}

        # Idempotency check: prevent duplicate processing of the same inbound email
        if message_id:
            ref_id = f"reply_{contact.id}_{message_id}"
            existing_notif = await self.db.scalar(
                select(Notification.id).where(Notification.reference_id == ref_id)
            )
            if existing_notif:
                logger.info("A4: Duplicate reply detected, skipping processing", ref_id=ref_id, contact_id=contact.id)
                return {"status": "already_processed", "reference_id": ref_id}

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
            thread_event = await self._record_thread_event(
                contact.id, reply_text, intent, confidence,
                delta=delta, score_after=new_score, subject=subject
            )
            await self._create_reply_notification(contact, thread_event, webhook_payload)
            await self.db.commit()
            logger.info("A4: Unsubscribe reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "unsubscribed", "email": email, "readiness_score": new_score}

        if intent == "not_interested":
            delta = READINESS_DELTAS["reply_not_interested"]
            new_score = max(0, (contact.readiness_score or 0) + delta)
            contact.readiness_score = new_score
            thread_event = await self._record_thread_event(
                contact.id, reply_text, intent, confidence,
                delta=delta, score_after=new_score, subject=subject
            )
            await self._create_reply_notification(contact, thread_event, webhook_payload)
            await self.db.commit()
            logger.info("A4: Not interested reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "not_interested", "readiness_score": new_score}

        if intent == "unknown":
            delta = READINESS_DELTAS["reply_unknown"]
            new_score = contact.readiness_score or 0
            thread_event = await self._record_thread_event(
                contact.id, reply_text, intent, confidence,
                delta=delta, score_after=new_score, subject=subject
            )
            await self._create_reply_notification(contact, thread_event, webhook_payload)
            await self.db.commit()
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

        # Check if meeting threshold crossed or positive interest
        should_request_meeting = (
            intent in ["meeting_request", "interested", "pricing", "technical_question"]
            or new_score >= settings.READINESS_SCORE_MEETING_THRESHOLD
        )

        # Embed Cal.com link directly in the draft body so it is visible in Slack and in the email
        if should_request_meeting:
            try:
                rep_user = await self.db.get(User, contact.user_id) if (contact and contact.user_id) else None
                booking_link = await self.cal.get_booking_link(
                    contact_email=contact.email,
                    contact_name=f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                    user=rep_user,
                )
                if booking_link and "cal.com" not in draft.lower():
                    draft = draft.rstrip() + f"\n\nHere's my calendar if you'd like to select a date and time that works best: {booking_link}"
            except Exception as cal_err:
                logger.warning("A4: Failed to append Cal.com booking link", error=str(cal_err))

        # Record thread event (ConversationThread is the single source of truth)
        logger.info("A4: Storing event in ConversationThread", contact_id=contact.id)
        thread_event = await self._record_thread_event(
            contact.id, reply_text, intent, confidence,
            delta=delta, score_after=new_score, draft=draft, subject=subject
        )
        await self._create_reply_notification(contact, thread_event, webhook_payload)

        # Log funnel event
        await self._log_funnel_event("reply_received", contact.id, {
            "intent": intent,
            "readiness_score": new_score,
        })

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

        # Get booking link if readiness score is high enough and not already in draft
        booking_link = None
        final_response = thread_event.draft_content or ""
        if "cal.com" not in final_response.lower() and (contact and contact.readiness_score >= settings.READINESS_SCORE_MEETING_THRESHOLD):
            rep_user = await self.db.get(User, contact.user_id) if (contact and contact.user_id) else None
            booking_link = await self.cal.get_booking_link(
                contact_email=contact.email,
                contact_name=f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                user=rep_user,
            )
            if booking_link:
                final_response += f"\n\nHere's my calendar if you'd like to select a date and time that works best: {booking_link}"

        # Determine subject
        reply_subject = "Re: Your inquiry"
        if thread_event.subject:
            sub = thread_event.subject.strip()
            reply_subject = sub if sub.lower().startswith("re:") else f"Re: {sub}"

        # Send the approved reply via SMTP/Resend
        if settings.ENABLE_EMAIL_SENDING and contact:
            await self._send_reply_via_resend(contact, final_response, subject=reply_subject)

        thread_event.approved_by = approved_by
        thread_event.approved_at = datetime.utcnow()
        thread_event.sent_at = datetime.utcnow()

        # Insert outbound reply event into ConversationThread history
        outbound_reply_event = ConversationThread(
            contact_id=contact.id if contact else thread_event.contact_id,
            event_type="reply_sent",
            direction="outbound",
            channel="email",
            content=final_response,
            readiness_score_after=contact.readiness_score if contact else 100,
            approved_by=approved_by,
            approved_at=datetime.utcnow(),
            sent_at=datetime.utcnow(),
            occurred_at=datetime.utcnow(),
        )
        self.db.add(outbound_reply_event)
        await self.db.commit()

        # Update Slack message UI in-place if tracking ID exists
        if thread_event.slack_message_ts:
            from app.services import SlackService
            slack = SlackService()
            await slack.update_to_approved(thread_event.slack_message_ts, approved_by)

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

        # Update Slack message UI in-place if tracking ID exists
        if thread_event.slack_message_ts:
            from app.services import SlackService
            slack = SlackService()
            await slack.update_to_rejected(thread_event.slack_message_ts, rejected_by)
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
            intent = parsed.get("intent", "unknown")
            confidence = parsed.get("confidence", 0.5)
            if intent and intent in REPLY_INTENT_CLASSES and intent != "unknown":
                return intent, confidence
        except Exception as e:
            logger.error("Intent classification LLM call failed", error=str(e))

        # Robust rule-based fallback heuristic if LLM returns unknown or fails
        text_lower = reply_text.lower()
        if any(w in text_lower for w in ["demo", "schedule", "meeting", "call", "book a time", "calendar", "time to talk"]):
            logger.info("A4: Rule-based fallback classified meeting_request", text_snippet=reply_text[:60])
            return "meeting_request", 0.9
        elif any(w in text_lower for w in ["interested", "pricing", "cost", "quote", "rates", "tell me more"]):
            logger.info("A4: Rule-based fallback classified interested", text_snippet=reply_text[:60])
            return "interested", 0.85
        elif any(w in text_lower for w in ["unsubscribe", "opt out", "remove me", "stop email"]):
            logger.info("A4: Rule-based fallback classified unsubscribe", text_snippet=reply_text[:60])
            return "unsubscribe", 0.95
        elif any(w in text_lower for w in ["not interested", "no thanks", "pass"]):
            logger.info("A4: Rule-based fallback classified not_interested", text_snippet=reply_text[:60])
            return "not_interested", 0.9
        
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

    async def _find_contact(self, email: str, subject: Optional[str] = None, user_id: Optional[str] = None) -> Optional[Contact]:
        import os
        test_override = (getattr(settings, "TEST_EMAIL_OVERRIDE", "") or os.getenv("TEST_EMAIL_OVERRIDE", "")).strip().lower()

        # When rep user_id is provided, strictly isolate lookup to contacts belonging to this rep
        if user_id:
            # 1. Exact match for this rep
            res = await self.db.execute(
                select(Contact).where(Contact.email == email, Contact.user_id == user_id)
            )
            contact = res.scalar_one_or_none()
            if contact:
                return contact

            # 2. Case-insensitive match for this rep
            res = await self.db.execute(
                select(Contact).where(Contact.email.ilike(email), Contact.user_id == user_id)
            )
            contact = res.scalar_one_or_none()
            if contact:
                return contact

            # 3. Test override scoped to this rep
            if test_override and (email.lower() == test_override or "forcecloudlabs" in email.lower()):
                res = await self.db.execute(
                    select(Contact).where(Contact.user_id == user_id).order_by(Contact.updated_at.desc()).limit(1)
                )
                contact = res.scalar_one_or_none()
                if contact:
                    return contact

            # Unknown sender for this rep's mailbox -> safely reject
            return None

        # Fallback for global single-mailbox mode (user_id is None):
        # 1. In TEST MODE, if sender is the configured test override, resolve to the intended prospect
        if test_override and (email.lower() == test_override or "forcecloudlabs" in email.lower()):
            # If subject is provided, match by subject against OutreachLog or ConversationThread
            if subject:
                clean_sub = subject.strip()
                for prefix in ["re:", "fwd:", "fw:"]:
                    if clean_sub.lower().startswith(prefix):
                        clean_sub = clean_sub[len(prefix):].strip()

                if clean_sub:
                    # Match by OutreachLog subject
                    sub_res = await self.db.execute(
                        select(Contact).join(OutreachLog, Contact.id == OutreachLog.contact_id)
                        .where(OutreachLog.subject.ilike(f"%{clean_sub}%"))
                        .order_by(OutreachLog.sent_at.desc())
                        .limit(1)
                    )
                    sub_contact = sub_res.scalar_one_or_none()
                    if sub_contact:
                        logger.info("A4: Matched test prospect via email subject in OutreachLog", subject=subject, contact_id=sub_contact.id)
                        return sub_contact

                    # Match by ConversationThread content or subject
                    ct_res = await self.db.execute(
                        select(Contact).join(ConversationThread, Contact.id == ConversationThread.contact_id)
                        .where(
                            (ConversationThread.subject.ilike(f"%{clean_sub}%")) |
                            (ConversationThread.content.ilike(f"%{clean_sub}%"))
                        )
                        .order_by(ConversationThread.occurred_at.desc())
                        .limit(1)
                    )
                    ct_contact = ct_res.scalar_one_or_none()
                    if ct_contact:
                        logger.info("A4: Matched test prospect via subject in ConversationThread", subject=subject, contact_id=ct_contact.id)
                        return ct_contact

            # Fallback to latest contacted prospect
            sub_res = await self.db.execute(
                select(Contact).join(OutreachLog, Contact.id == OutreachLog.contact_id)
                .order_by(OutreachLog.sent_at.desc())
                .limit(1)
            )
            latest_contact = sub_res.scalar_one_or_none()
            if latest_contact:
                logger.info("A4: Fallback test contact matched latest emailed contact", email=email, contact_id=latest_contact.id)
                return latest_contact

        # 2. Exact match
        result = await self.db.execute(
            select(Contact).where(Contact.email == email)
        )
        contact = result.scalar_one_or_none()
        if contact:
            return contact

        # 3. Case insensitive match
        result = await self.db.execute(
            select(Contact).where(Contact.email.ilike(email))
        )
        contact = result.scalar_one_or_none()
        if contact:
            return contact

        # 4. Unknown sender who is not a prospect and not the test override -> ignore
        logger.info("A4: Inbound email sender is neither a known contact nor TEST_EMAIL_OVERRIDE, ignoring", email=email)
        return None

    async def _create_reply_notification(
        self, contact: Contact, thread_event: ConversationThread, webhook_payload: Dict[str, Any]
    ) -> Optional[Notification]:
        """
        Creates exactly ONE reply_received notification when a genuine inbound reply is processed.
        Scopes user_input_id to the existing ContactUserInputAssociation, with duplicate protection.
        """
        try:
            # 1. Resolve user_input_id from ContactUserInputAssociation
            assoc_res = await self.db.execute(
                select(ContactUserInputAssociation.user_input_id)
                .where(ContactUserInputAssociation.contact_id == contact.id)
                .order_by(ContactUserInputAssociation.user_input_id.desc())
                .limit(1)
            )
            user_input_id = assoc_res.scalar_one_or_none()
            if not user_input_id:
                user_input_id = contact.user_input_id
            if not user_input_id and contact.user_id:
                user_input_id = await self.db.scalar(
                    select(UserInput.id)
                    .where(UserInput.user_id == contact.user_id)
                    .order_by(UserInput.id.desc())
                    .limit(1)
                )

            if not user_input_id:
                logger.warning("A4: No user_input_id found to scope reply notification for contact user", contact_id=contact.id)
                return None

            # 2. Duplicate protection: reference_id
            message_id = webhook_payload.get("message_id") or webhook_payload.get("email_id") or webhook_payload.get("id")
            ref_id = f"reply_{contact.id}_{message_id}" if message_id else f"reply_{contact.id}_{thread_event.id}"

            existing = await self.db.execute(
                select(Notification.id).where(Notification.reference_id == ref_id)
            )
            if existing.scalar_one_or_none():
                logger.info("A4: Reply notification already exists for reference_id", ref_id=ref_id)
                return None

            first_name = contact.first_name or "Prospect"
            if contact.company:
                msg = f"{first_name} at {contact.company} replied"
            else:
                msg = f"{first_name} replied"

            notif = Notification(
                type="reply_received",
                contact_id=contact.id,
                user_input_id=user_input_id,
                message=msg,
                action_url=f"/contacts/{contact.id}",
                reference_id=ref_id,
                expires_at=None,
            )
            self.db.add(notif)
            await self.db.flush()
            logger.info("A4: Created reply_received notification", notification_id=notif.id, contact_id=contact.id, user_input_id=user_input_id)
            return notif
        except Exception as exc:
            logger.error("A4: Failed to create reply notification", contact_id=contact.id, error=str(exc))
            return None

    async def _record_thread_event(
        self, contact_id: str, content: str, intent: str,
        confidence: float, delta: float, score_after: float = 0,
        draft: Optional[str] = None, subject: Optional[str] = None
    ) -> ConversationThread:
        event = ConversationThread(
            contact_id=contact_id,
            event_type="reply_received",
            direction="inbound",
            channel="email",
            content=content,
            subject=subject,
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

    async def _send_reply_via_resend(self, contact: Optional[Contact], body: str, subject: str = "Re: Your inquiry"):
        """Send the reply email via SMTP (primary) or Resend (fallback)."""
        import re
        html_body = body
        # Convert any http/https URL into a clean, clickable anchor tag
        html_body = re.sub(
            r'(https?://[^\s<>"]+)',
            r'<a href="\1" style="color: #2563eb; font-weight: 500; text-decoration: underline;">\1</a>',
            html_body
        )
        formatted_html = f"<div style='font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.6; color: #1e293b;'>{'<br/>'.join(html_body.splitlines())}</div>"
        
        target_to = getattr(settings, "TEST_EMAIL_OVERRIDE", "") or (contact.email if contact else "")

        # Priority 1: Rep's authorized Microsoft 365 mailbox via Microsoft Graph
        if contact and contact.user_id:
            rep_user = await self.db.get(User, contact.user_id)
            if rep_user:
                ms_int_res = await self.db.execute(
                    select(UserIntegration).where(
                        UserIntegration.user_id == rep_user.id,
                        UserIntegration.provider == "microsoft",
                        UserIntegration.status == "connected",
                    )
                )
                ms_int = ms_int_res.scalar_one_or_none()
                if ms_int:
                    from app.services.microsoft_graph_service import MicrosoftGraphService
                    ms_svc = MicrosoftGraphService()
                    token = await ms_svc.get_valid_access_token(ms_int, self.db)
                    if token:
                        sender_email = ms_int.provider_account_email or rep_user.email
                        try:
                            msg_id = await ms_svc.send_mail(
                                access_token=token,
                                to_email=target_to,
                                subject=subject,
                                html_body=formatted_html,
                                from_email=sender_email,
                            )
                            if msg_id:
                                logger.info("A4: Reply email dispatched via Microsoft Graph", rep_email=sender_email, to=target_to)
                                return msg_id
                        except Exception as ms_err:
                            logger.error("A4: Failed to send reply via Microsoft Graph", error=str(ms_err))

        # 1. Try SMTP if configured
        if getattr(settings, "SMTP_USER", "") and getattr(settings, "SMTP_PASSWORD", ""):
            from app.services import SMTPService
            smtp_svc = SMTPService()
            provider_id = await smtp_svc.send_email(
                to=target_to,
                subject=subject,
                html=formatted_html,
            )
            if provider_id:
                logger.info("A4: Reply email successfully dispatched via SMTP", target=target_to, original_contact=contact.email if contact else "", subject=subject, provider_id=provider_id)
                return provider_id

        # 2. Try Resend if configured
        if settings.RESEND_API_KEY:
            message_id = await self.resend.send_email(
                to=target_to,
                subject=subject,
                html=formatted_html,
            )
            if message_id:
                logger.info("A4: Reply email successfully dispatched via Resend", target=target_to, original_contact=contact.email if contact else "", subject=subject, message_id=message_id)
                return message_id

        logger.error("A4: Email dispatch failed — neither SMTP nor Resend succeeded", target=target_to)
        return None

    async def _log_funnel_event(self, event_type: str, contact_id: str, metadata: Dict):
        event = FunnelEvent(
            event_type=event_type,
            contact_id=contact_id,
            agent_id="A4",
            event_metadata=metadata,
        )
        self.db.add(event)
        await self.db.commit()

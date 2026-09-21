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
from app.services.interest_scoring_service import InterestScorer, InterestStatus

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
    3. Update readiness score & Interest Engine score/status/summary
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
        self.interest_scorer = InterestScorer()

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
            await self._record_thread_event(
                contact.id, reply_text, intent, confidence,
                delta=delta, score_after=new_score
            )
            await self._update_prospect_interest(contact, intent)
            await self.db.commit()
            logger.info("A4: Unsubscribe reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "unsubscribed", "email": email, "readiness_score": new_score}

        if intent == "not_interested":
            delta = READINESS_DELTAS["reply_not_interested"]
            new_score = max(0, (contact.readiness_score or 0) + delta)
            contact.readiness_score = new_score
            await self._record_thread_event(contact.id, reply_text, intent, confidence, delta=delta, score_after=new_score)
            await self._update_prospect_interest(contact, intent)
            await self.db.commit()
            logger.info("A4: Not interested reply auto-suppressed", contact_id=contact.id, email=email, readiness_score=new_score)
            return {"status": "not_interested", "readiness_score": new_score}

        if intent == "unknown":
            delta = READINESS_DELTAS["reply_unknown"]
            new_score = contact.readiness_score or 0
            await self._record_thread_event(contact.id, reply_text, intent, confidence, delta=delta, score_after=new_score)
            await self._update_prospect_interest(contact, intent)
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
                booking_link = await self.cal.get_booking_link(
                    contact_email=contact.email,
                    contact_name=f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                )
                if booking_link and "cal.com" not in draft.lower():
                    draft = draft.rstrip() + f"\n\nHere's my calendar if you'd like to select a date and time that works best: {booking_link}"
            except Exception as cal_err:
                logger.warning("A4: Failed to append Cal.com booking link", error=str(cal_err))

        # Record thread event (ConversationThread is the single source of truth)
        logger.info("A4: Storing event in ConversationThread", contact_id=contact.id)
        thread_event = await self._record_thread_event(
            contact.id, reply_text, intent, confidence,
            delta=delta, score_after=new_score, draft=draft
        )

        # Update Prospect Interest Score, Status, Breakdown, and AI Executive Summary
        await self._update_prospect_interest(contact, intent)

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
            booking_link = await self.cal.get_booking_link(
                contact_email=contact.email,
                contact_name=f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
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

    async def _find_contact(self, email: str) -> Optional[Contact]:
        import os
        # 1. Exact match
        result = await self.db.execute(
            select(Contact).where(Contact.email == email)
        )
        contact = result.scalar_one_or_none()
        if contact:
            return contact

        # 2. Case insensitive match
        result = await self.db.execute(
            select(Contact).where(Contact.email.ilike(email))
        )
        contact = result.scalar_one_or_none()
        if contact:
            return contact

        # 3. Fallback for test override email
        test_override = getattr(settings, "TEST_EMAIL_OVERRIDE", "") or os.getenv("TEST_EMAIL_OVERRIDE", "")
        if test_override and (email.lower() == test_override.lower() or "forcecloudlabs" in email.lower()):
            sub_res = await self.db.execute(
                select(Contact).join(OutreachLog, Contact.id == OutreachLog.contact_id)
                .order_by(OutreachLog.sent_at.desc())
                .limit(1)
            )
            latest_contact = sub_res.scalar_one_or_none()
            if latest_contact:
                logger.info("A4: Fallback test contact matched latest emailed contact", email=email, contact_id=latest_contact.id)
                return latest_contact

        # 4. If not found in contacts, auto-create a new inbound contact so every client reply triggers Slack approval
        if email and "@" in email:
            try:
                name_part = email.split("@")[0]
                domain_part = email.split("@")[1]
                first_name = name_part.replace(".", " ").replace("_", " ").title().split()[0] if name_part else "Lead"
                company = domain_part.split(".")[0].title() if domain_part.lower() not in ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com"] else "Inbound Company"
                
                from app.models.models import UserInput
                user_input_res = await self.db.execute(select(UserInput.id).order_by(UserInput.id.desc()).limit(1))
                active_session_id = user_input_res.scalar_one_or_none()
                
                new_contact = Contact(
                    email=email.strip().lower(),
                    first_name=first_name,
                    company=company,
                    user_input_id=active_session_id,
                    readiness_score=50.0,
                )
                self.db.add(new_contact)
                await self.db.flush()
                logger.info("A4: Auto-created new contact for inbound email", email=email, contact_id=new_contact.id)
                return new_contact
            except Exception as ex:
                logger.error("A4: Failed to auto-create contact", email=email, error=str(ex))

        return None

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
        
        target_to = getattr(settings, "TEST_EMAIL_OVERRIDE", "") or (contact.email if contact else "") or "ibmsuriya@gmail.com"

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

    async def _update_prospect_interest(self, contact: Contact, intent: str) -> Dict[str, Any]:
        """Calculates interest score, updates contact fields, generates AI summary, and sends alerts."""
        contact.last_response_at = datetime.utcnow()
        contact.response_count = (contact.response_count or 0) + 1

        # Fetch conversation threads and outreach logs for contact
        threads_res = await self.db.execute(
            select(ConversationThread)
            .where(ConversationThread.contact_id == contact.id)
            .order_by(ConversationThread.occurred_at.asc())
        )
        threads = threads_res.scalars().all()
        thread_dicts = [
            {
                "direction": t.direction,
                "content": t.content,
                "intent": t.intent,
                "occurred_at": t.occurred_at,
            }
            for t in threads
        ]

        outreach_res = await self.db.execute(
            select(OutreachLog)
            .where(OutreachLog.contact_id == contact.id)
            .order_by(OutreachLog.sent_at.asc())
        )
        outreaches = outreach_res.scalars().all()
        outreach_dicts = [{"sent_at": o.sent_at} for o in outreaches]

        contact_dict = {
            "do_not_contact": contact.do_not_contact,
            "last_response_at": contact.last_response_at,
            "last_outreach_at": contact.last_outreach_at,
            "response_count": contact.response_count,
            "outreach_count": contact.outreach_count,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "company": contact.company,
            "title": contact.title,
        }

        prev_score = contact.interest_score or 0.0
        prev_status = contact.interest_status or InterestStatus.INACTIVE

        score, status, breakdown = self.interest_scorer.score(
            contact_dict, thread_dicts, outreach_dicts
        )

        contact.interest_score = score
        contact.interest_status = status
        contact.interest_score_breakdown = breakdown
        contact.interest_updated_at = datetime.utcnow()

        if status == InterestStatus.REJECTED:
            contact.do_not_contact = True

        # Generate AI Conversation Summary
        summary = await self.interest_scorer.generate_conversation_summary(
            contact_dict, thread_dicts
        )
        contact.conversation_summary = summary

        await self.db.commit()

        # Trigger notifications if HIGH_INTEREST or score jumped +25 pts
        score_jump = score - prev_score
        if (score >= 80.0 and prev_status != InterestStatus.HIGH_INTEREST) or score_jump >= 25.0:
            alert_msg = (
                f"🔥 *HIGH PROSPECT INTEREST ALERT*\n"
                f"*Contact:* {contact.first_name or ''} {contact.last_name or ''} ({contact.email})\n"
                f"*Company:* {contact.company or 'Unknown'} | *Title:* {contact.title or 'N/A'}\n"
                f"*Interest Score:* {score:.0f}/100 ({status}) | *Jump:* +{score_jump:.0f} pts\n"
                f"*Latest Intent:* `{intent}`\n"
                f"*AI Summary:* {summary}"
            )
            try:
                await self.slack.send_alert(alert_msg)
                await self.ntfy.send_alert(f"HIGH INTEREST: {contact.email} ({contact.company}) - Score {score:.0f}/100")
            except Exception as e:
                logger.warning("A4: Failed to send high-interest notification", error=str(e))

        return {
            "interest_score": score,
            "interest_status": status,
            "breakdown": breakdown,
            "summary": summary,
        }


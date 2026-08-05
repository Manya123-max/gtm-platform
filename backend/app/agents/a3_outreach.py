"""
A3 — Multi-Channel Outreach Agent
Signal-matched sequences. Second-order personalisation using industry benchmarks.
Deduplication enforced before every send.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.models.models import (
    Contact, SignalEvent, OutreachLog, PromptVariant,
    FunnelEvent, SignalType, PendingAction, ActionStatus
)
from app.services.llm_service import LLMService
from app.services.instantly_service import InstantlyService
from app.agents.service_matcher import ServiceMatcher
from app.agents.business_case_detector import BusinessCaseDetector
from app.agents.channel_selector import ChannelSelector
from app.agents.outreach_templates import TEMPLATES
from app.agents.draft_manager import DraftManager

logger = structlog.get_logger()


class OutreachDecisionEngine:
    """
    Evaluates whether a contact-signal pair should receive outreach.
    """

    def __init__(self, db: AsyncSession, llm: LLMService = None):
        self.db = db
        self.llm = llm or LLMService()
        self.matcher = ServiceMatcher(self.llm)
        self.detector = BusinessCaseDetector(self.llm)
        self.channel_selector = ChannelSelector(self.llm)

    async def decide(self, contact: Contact, signal: Optional[SignalEvent] = None) -> Dict[str, Any]:
        """
        Analyze the contact and trigger signal to decide if we should do outreach.
        """
        vendor_services = "Salesforce integration, CRM consulting, GTM automation, and cloud migration services"

        signal_type = signal.signal_type if signal else "fallback"
        signal_raw_data = signal.raw_data if signal else {}
        signal_confidence = signal.confidence if signal else 1.0

        # Match services first using the Service Matching Module
        try:
            match_result = await self.matcher.match(
                our_services=vendor_services,
                industry=contact.industry,
                title=contact.title,
                hiring_info=signal_raw_data if signal and signal.signal_type in [SignalType.JOB_POSTING, SignalType.NEW_HIRE] else None,
                buying_signal=signal_raw_data if signal else None
            )
        except Exception as matcher_err:
            logger.error("ServiceMatcher call failed", error=str(matcher_err))
            match_result = {
                "matched_services": ["CRM consulting"],
                "match_score": 50.0,
                "reason": f"Matcher exception: {str(matcher_err)}"
            }

        # Classify business case using the Business Case Detector
        try:
            case_result = await self.detector.detect(
                industry=contact.industry,
                title=contact.title,
                signal_type=signal_type,
                signal_data=signal_raw_data if signal else None
            )
        except Exception as detector_err:
            logger.error("BusinessCaseDetector call failed", error=str(detector_err))
            case_result = {
                "business_case": "General Sales Outreach",
                "confidence": 0.5,
                "reason": f"Detector exception: {str(detector_err)}"
            }

        # Select communication channels using the Channel Selection Module
        try:
            channel_result = await self.channel_selector.select_channels(
                email=contact.email,
                email_valid=contact.email_valid,
                linkedin_url=contact.linkedin_url,
                title=contact.title,
                signal_type=signal_type
            )
        except Exception as channel_err:
            logger.error("ChannelSelector call failed", error=str(channel_err))
            channel_result = {
                "primary_channel": "Email",
                "secondary_channel": "LinkedIn",
                "available_channels": ["Email", "LinkedIn"],
                "reason": f"Channel selector exception: {str(channel_err)}"
            }

        system_prompt = f"""You are the Outreach Decision Engine for a B2B GTM platform.
Your job is to analyze a contact, a trigger signal, a service-matching evaluation, an opportunity classification, and a channel selection to determine if it makes business sense to contact this person/company.

We sell these services: {vendor_services}.

Evaluate the prospect's details:
- Title: {contact.title or 'N/A'}
- Company: {contact.company or 'N/A'}
- Industry: {contact.industry or 'N/A'}
- Company Size: {contact.company_size or 'N/A'}
- Funding Stage: {contact.funding_stage or 'N/A'}

Evaluate the trigger signal:
- Type: {signal_type}
- Raw Data: {signal_raw_data or {}}
- Confidence: {signal_confidence}

Service Matching evaluation:
- Matched Services: {match_result.get('matched_services', [])}
- Match Score (0-100): {match_result.get('match_score', 50)}
- Match Reason: {match_result.get('reason', '')}

Opportunity Classification:
- Classified Business Case: {case_result.get('business_case')}
- Classification Confidence (0.0-1.0): {case_result.get('confidence')}
- Classification Reason: {case_result.get('reason')}

Channel Selection evaluation:
- Primary Outreach Channel: {channel_result.get('primary_channel')}
- Secondary Outreach Channel: {channel_result.get('secondary_channel')}
- Available Channels: {channel_result.get('available_channels')}
- Selection Reason: {channel_result.get('reason')}

You must return a structured JSON object with the following fields:
- should_contact (boolean): True if there is a strong relevance and we should proceed with outreach, False otherwise.
- why_contact (string): A short, specific reason why we should contact them.
- business_case (string): Must align with the classified business case above.
- matched_services (array of strings): Sub-list of matched services from the matcher evaluation.
- recommended_channel (string): Must align with the primary outreach channel above.
- confidence_score (number): A score between 0.0 and 1.0 representing your confidence in this decision.
- explanation (string): A human-readable explanation of why this decision was made.

Be rigorous. If the Service Match Score is low (e.g. < 50) or there is no logical connection between our services and the prospect's title, industry, or signal trigger, set should_contact to False.
"""
        user_prompt = f"""Evaluate prospect: {contact.first_name or 'there'} {contact.last_name or ''} at {contact.company or 'N/A'} (Title: {contact.title or 'N/A'}, Industry: {contact.industry or 'N/A'})
Trigger Signal: {signal_type} (Details: {signal_raw_data or {}})"""

        try:
            decision = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Haiku is fast and cheap
                response_format={
                    "should_contact": "boolean",
                    "why_contact": "string",
                    "business_case": "string",
                    "matched_services": ["string"],
                    "recommended_channel": "string",
                    "confidence_score": "number",
                    "explanation": "string",
                },
            )
            # Mix in ServiceMatcher, BusinessCaseDetector & ChannelSelector results if missing
            return {
                "should_contact": bool(decision.get("should_contact", True)),
                "why_contact": str(decision.get("why_contact", "")),
                "business_case": str(decision.get("business_case", case_result.get("business_case", "General Sales Outreach"))),
                "matched_services": list(decision.get("matched_services", match_result.get("matched_services", []))),
                "recommended_channel": str(decision.get("recommended_channel", channel_result.get("primary_channel", "email"))),
                "confidence_score": float(decision.get("confidence_score", 0.8)),
                "explanation": str(decision.get("explanation", "")) + f" (Service Match Score: {match_result.get('match_score')})"
            }
        except Exception as e:
            logger.error("Outreach Decision Engine failed, falling back to True", error=str(e))
            return {
                "should_contact": True,
                "why_contact": "Fallback decision due to engine error.",
                "business_case": case_result.get("business_case", "General Sales Outreach"),
                "matched_services": match_result.get("matched_services", ["CRM consulting"]),
                "recommended_channel": channel_result.get("primary_channel", "email"),
                "confidence_score": 1.0,
                "explanation": f"Decision engine encountered an error: {str(e)}",
            }


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
        self.decision_engine = OutreachDecisionEngine(db, self.llm)
        self.draft_manager = DraftManager(db)

    async def run(self, contact_signal_pairs: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Process qualified contacts with signals and send outreach.
        """
        logger.info("A3 starting")

        # Get contacts with qualifying signals if not provided
        if not contact_signal_pairs:
            if settings.AGENT3_TEST_MODE:
                contact_signal_pairs = await self._get_test_contacts()
            else:
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
            "decision_engine_rejected": 0,
        }

        for pair in contact_signal_pairs:
            contact, signal = await self._resolve_pair(pair)
            if not contact or (not settings.AGENT3_TEST_MODE and not signal):
                skip_reasons["missing_contact_or_signal"] += 1
                continue

            # Skip if we already have a pending draft to prevent duplicates
            if await self.draft_manager.has_pending_draft(contact.id, signal.id if signal else None):
                continue

            # Fetch steps from SEQUENCE_TEMPLATES
            signal_type = signal.signal_type if signal else "fallback"
            sequence_step = signal.sequence_step if signal else 0

            steps = SEQUENCE_TEMPLATES.get(signal_type, SEQUENCE_TEMPLATES["default"])["steps"]
            if sequence_step >= len(steps):
                if signal:
                    signal.processed = True
                    await self.db.commit()
                continue
            
            step_def = steps[sequence_step]
            if contact.do_not_contact:
                skip_reasons["do_not_contact"] += 1
                continue
            if not contact.email:
                skip_reasons["missing_email"] += 1
                continue
            if contact.email_valid is False:
                skip_reasons["invalid_email"] += 1
                continue
            if await self._already_contacted(contact.id, signal.id if signal else None, sequence_step):
                skip_reasons["deduplicated"] += 1
                continue

            # Run Outreach Decision Engine
            decision = await self.decision_engine.decide(contact, signal)
            logger.info("Outreach Decision Engine evaluation", contact_email=contact.email, decision=decision)
            if not decision.get("should_contact", True):
                skip_reasons["decision_engine_rejected"] += 1
                continue

            # Generate message
            message = await self._generate_message(
                contact,
                signal,
                decision,
                channel=step_def["channel"],
                angle=step_def["angle"]
            )
            if not message:
                skip_reasons["generation_failed"] += 1
                continue

            # Create outreach draft
            draft = await self.draft_manager.create_draft(
                contact_id=contact.id,
                signal_id=signal.id if signal else None,
                subject=message.get("subject", ""),
                body=message.get("body", ""),
                business_case=decision.get("business_case", "General Sales Outreach"),
                matched_services=decision.get("matched_services", []),
                channel=message.get("channel", "email")
            )
            drafts_created += 1

            if settings.DRY_RUN_OUTREACH or settings.REQUIRE_HUMAN_APPROVAL:
                # Add review task PendingAction
                self.db.add(PendingAction(
                    action_type="approve_outreach",
                    entity_type="contact",
                    entity_id=str(contact.id),
                    recommended_value=message.get("subject"),
                    current_value="draft",
                    reason=f"Review A3 draft for {contact.email}. Business Case: {decision.get('business_case')}",
                    agent_id="A3",
                    status=ActionStatus.PENDING,
                ))
                await self.db.commit()
            else:
                # Direct approval and dispatch
                success = await self.draft_manager.approve_draft(draft.id)
                if success:
                    sent += 1
                    drafts_created -= 1
                else:
                    skip_reasons["send_failed"] += 1

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

    async def _get_test_contacts(self) -> List[Dict]:
        """
        Query contacts directly when AGENT3_TEST_MODE is enabled.
        Filters:
          icp_score >= settings.TEST_MODE_ICP_SCORE_THRESHOLD
          email IS NOT NULL
          do_not_contact = False
        """
        threshold = getattr(settings, "TEST_MODE_ICP_SCORE_THRESHOLD", 60)
        result = await self.db.execute(
            select(Contact)
            .where(
                and_(
                    Contact.do_not_contact == False,
                    Contact.email != None,
                    Contact.icp_score >= threshold
                )
            )
            .order_by(Contact.icp_score.desc())
            .limit(100)
        )
        contacts = result.scalars().all()
        pairs = []
        for contact in contacts:
            pairs.append({"contact": contact, "signal": None})
        return pairs

    async def _resolve_pair(self, pair: Dict[str, Any]):
        if pair.get("contact") is not None:
            return pair["contact"], pair.get("signal")
        contact_id = pair.get("contact_id")
        if not contact_id:
            return None, None
        contact_result = await self.db.execute(select(Contact).where(Contact.id == contact_id))
        contact = contact_result.scalar_one_or_none()
        if settings.AGENT3_TEST_MODE:
            return contact, None
        signal_query = select(SignalEvent).where(SignalEvent.contact_id == contact_id)
        if pair.get("signal_type"):
            signal_query = signal_query.where(SignalEvent.signal_type == pair["signal_type"])
        signal_query = signal_query.order_by(SignalEvent.detected_at.desc()).limit(1)
        signal_result = await self.db.execute(signal_query)
        return contact, signal_result.scalar_one_or_none()

    async def _get_qualified_contacts(self) -> List[Dict]:
        """
        Pull contacts with signals above threshold that haven't been contacted recently.
        Includes sequence timing logic.
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
                    or_(
                        SignalEvent.next_step_due_at == None,
                        SignalEvent.next_step_due_at <= datetime.utcnow()
                    )
                )
            )
            .order_by(SignalEvent.confidence.desc())
            .limit(100)
        )
        pairs = []
        for contact, signal in result.all():
            pairs.append({"contact": contact, "signal": signal})
        return pairs

    async def _already_contacted(self, contact_id: str, signal_id: str, sequence_step: int = 0) -> bool:
        """
        Check outreach_log. Hard block if contacted within EMAIL_DEDUP_DAYS for the same sequence step.
        """
        result = await self.db.execute(
            select(OutreachLog).where(
                and_(
                    OutreachLog.contact_id == contact_id,
                    OutreachLog.signal_id == signal_id,
                    OutreachLog.sequence_step == sequence_step,
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

    async def _generate_message(
        self, contact: Contact, signal: Optional[SignalEvent] = None, decision: Optional[Dict] = None,
        channel: str = "email", angle: str = ""
    ) -> Optional[Dict]:
        """
        Generate personalised email or LinkedIn connect request using Claude.
        Loads corresponding template based on business case/channel and personalizes it.
        """
        signal_type = signal.signal_type if signal else "fallback"
        variant = await self._get_best_variant(signal_type)
        bc = decision.get("business_case", "General Sales Outreach") if decision else "General Sales Outreach"
        
        if channel == "linkedin":
            base_template = {
                "subject": "",
                "body": "Hi {first_name},\n\nI noticed you are {title} at {company} in {industry}.\n\nSince you are focusing on {role_details}, I wanted to connect to share how we help companies automate Salesforce data workflows.\n\nBest,\n[Your Name]"
            }
        else:
            base_template = TEMPLATES.get(bc, TEMPLATES["General Sales Outreach"])

        role_details = ""
        if signal:
            if signal.signal_type == SignalType.JOB_POSTING:
                roles = (signal.raw_data or {}).get("roles", [])
                role_details = ", ".join(roles) if roles else "open roles"
            elif signal.signal_type == SignalType.NEW_HIRE:
                roles = (signal.raw_data or {}).get("roles", [])
                role_details = ", ".join(roles) if roles else "leadership roles"
            else:
                role_details = contact.title or "team members"
        else:
            role_details = contact.title or "team members"

        # Construct prompt requesting structured personalization
        if channel == "linkedin":
            system_prompt = f"""You are a professional B2B copywriter.
Your job is to personalize a short LinkedIn connection request note for a target prospect.

Rules:
- Personalize the base template by replacing placeholders (like {{first_name}}, {{company}}, etc.) with real prospect details.
- Adapt the phrasing slightly to sound natural, conversational, and personalized.
- You MUST keep the entire note under 280 characters so it fits the LinkedIn limit.
- Do NOT generate a subject line. Set "subject" to an empty string.
- Return valid JSON with exactly two fields: "subject" (empty string) and "body".

Base Template:
{base_template['body']}
"""
        else:
            system_prompt = f"""You are a professional B2B copywriter.
Your job is to personalize an email template for a target prospect.

Rules:
- You must use the provided Email Template as the base.
- Personalize it by replacing the placeholders in brackets (like {{first_name}}, {{company}}, etc.) with real prospect details.
- Adapt the phrasing slightly to sound natural, conversational, and highly personalized based on the prospect's title, industry, and any signal details if present.
- Do NOT rewrite the email from scratch. Stick to the tone, structure, and main value proposition of the template.
- Keep the final message under 150 words.
- Do not use phrases like "I hope this email finds you well" or "quick question".
- Return valid JSON with exactly two fields: "subject" and "body".

Email Template:
Subject: {base_template['subject']}
Body:
{base_template['body']}
"""

        user_prompt = f"""Prospect Context:
- First Name: {contact.first_name or 'there'}
- Company: {contact.company or 'N/A'}
- Title: {contact.title or 'N/A'}
- Industry: {contact.industry or 'N/A'}
- Company Size: {contact.company_size or 'N/A'}
- Funding Stage: {contact.funding_stage or 'N/A'}
- Role Details (Hiring): {role_details}

Trigger Signal:
- Type: {signal_type}
- Details: {signal.raw_data if signal else {}}

Decision Engine Context:
- Business Case: {bc}
- Why Contact: {decision.get('why_contact', '') if decision else ''}
- Recommended Outreach Channel: {decision.get('recommended_channel', 'email') if decision else 'email'}
"""

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
                "channel": channel,
            }
        except Exception as e:
            logger.error("Message generation failed", contact_email=contact.email, error=str(e))
            return None

    # ── NEW: Call script generation ───────────────────────────────────────

    async def _generate_call_script(
        self, contact: Contact, signal: Optional[SignalEvent] = None, services: str = ""
    ) -> str:
        """Generate a short cold call script for the contact."""
        signal_type_str = signal.signal_type if signal else "general business growth"
        system = (
            "You are a B2B sales rep. Write a 60-second cold call script. "
            "Be concise, reference the reasons to contact, ask for a meeting. "
            "Format: Opener → Value prop → Ask."
        )
        user = (
            f"Contact: {contact.first_name} {contact.last_name}, "
            f"{contact.title} at {contact.company}. "
            f"Context: {signal_type_str}. "
            f"Our services: {services or 'GTM automation platform'}."
        )
        try:
            return await self.llm.complete_raw(system, user, max_tokens=300)
        except Exception:
            return (
                f"Hi {contact.first_name}, this is [Your Name] from [Company]. "
                f"I came across {contact.company} "
                f"and wanted to discuss how we help similar companies. "
                f"Do you have 15 minutes this week?"
            )

    # ── NEW: LinkedIn connection note generation ──────────────────────────

    async def _generate_linkedin_connect(
        self, contact: Contact, signal: Optional[SignalEvent] = None
    ) -> str:
        """Generate a LinkedIn connection request note under 300 characters."""
        signal_type_str = signal.signal_type.replace('_', ' ') if signal else "general business growth"
        system = (
            "Write a LinkedIn connection request note under 300 characters. "
            "Professional, personalised, no hard sell."
        )
        user = (
            f"Connect with {contact.first_name} {contact.last_name}, "
            f"{contact.title} at {contact.company}. "
            f"Context: {signal_type_str}."
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

    async def _send_via_instantly(self, contact: Contact, message: Dict, signal: Optional[SignalEvent]) -> bool:
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

    async def _save_draft(self, contact: Contact, message: Dict, signal: Optional[SignalEvent]):
        """Save generated message as draft — used in dev/staging."""
        await self._log_outreach(contact, message, signal, None, is_draft=True)

    async def _log_outreach(
        self, contact: Contact, message: Dict, signal: Optional[SignalEvent],
        provider_message_id: Optional[str], is_draft: bool = False
    ):
        # NEW: generate call script and LinkedIn note alongside the email
        call_script = await self._generate_call_script(contact, signal)
        linkedin_note = await self._generate_linkedin_connect(contact, signal)

        log = OutreachLog(
            contact_id=contact.id,
            campaign_type=f"{signal.signal_type}:{signal.id}" if signal else "fallback:none",
            channel=message.get("channel", "email"),
            subject=message.get("subject"),
            body_preview=message.get("body", "")[:500],
            prompt_variant_id=message.get("variant_id"),
            signal_id=signal.id if signal else None,
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
        if signal:
            signal.processed = True
            signal.triggered_outreach = not is_draft

        funnel_event = FunnelEvent(
            event_type="email_draft_created" if is_draft else "email_sent",
            contact_id=contact.id,
            agent_id="A3",
            event_metadata={
                "signal_type": signal.signal_type if signal else "fallback",
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
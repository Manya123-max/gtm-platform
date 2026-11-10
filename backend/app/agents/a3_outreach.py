"""
A3 — Multi-Channel Outreach Agent

Consolidated into a single file (previously scattered across draft_manager.py,
business_case_detector.py, channel_selector.py, outreach_templates.py, and
service_matcher.py) so everything belonging to A3 lives in one place, matching
the A1/A2 convention. Nothing was dropped in the merge — see the notes below
for the two things that changed shape, not behavior.

Merge notes:
- industry_tag_map.py was intentionally NOT merged in — it's never imported
  by any A3 file. It's Apollo industry-tag resolution for prospect search,
  which belongs with A1, not here.
- Removed _send_via_instantly / _save_draft / _log_outreach (the old direct-send
  path). They were dead code — run() now always goes through
  DraftManager.create_draft(), and the real send happens in
  DraftManager.approve_draft() instead. Nothing currently calls the old path.
- DraftManager.approve_draft() previously did a deferred import of
  SEQUENCE_TEMPLATES from this same file to dodge a circular import. Now that
  everything is in one module, that workaround is gone — it just references
  SEQUENCE_TEMPLATES directly.

Contents, in dependency order:
  TEMPLATES               — static email/LinkedIn copy per business case
  ServiceMatcher           } LLM-driven helpers used by OutreachDecisionEngine
  BusinessCaseDetector     }
  ChannelSelector          }
  OutreachDecisionEngine  — decides IF/how/why to contact a given contact+signal
  SEQUENCE_TEMPLATES      — multi-step, multi-channel sequence timing per signal
  DraftManager            — persists OutreachDraft rows, sends on approval
  OutreachAgent           — orchestrates: qualify contacts -> decide -> draft
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.core.config import settings
from app.models.models import (
    Contact, SignalEvent, OutreachLog, PromptVariant,
    FunnelEvent, SignalType, PendingAction, ActionStatus, UserInput, OutreachDraft,
    ContactUserInputAssociation, User, UserIntegration
)
from app.services.llm_service import LLMService
from app.services.instantly_service import InstantlyService

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# Static outreach copy, per business case (was outreach_templates.py)
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATES = {
    "Recruitment Partnership": {
        "subject": "Helping {company} scale its {role_details} team",
        "body": "Hi {first_name},\n\nI noticed that {company} is currently expanding and hiring for {role_details}. Building out a high-performing engineering/sales team at this stage can be a bottleneck.\n\nWe specialize in Salesforce integration and CRM automation to help scale operations. I wanted to see if you have considered automating parts of your onboarding flow to free up your new hires' time?\n\nBest,\n[Your Name]"
    },
    "Funding Round": {
        "subject": "Congrats on the {funding_stage} milestone, {first_name}!",
        "body": "Hi {first_name},\n\nCongratulations to you and the team at {company} on the recent {funding_stage} announcement! That's a major milestone.\n\nTypically, after a funding round, companies focus on scaling their CRM systems and GTM automation to support rapid expansion. We help companies like yours integrate Salesforce and automate outreach.\n\nAre you open to a brief chat next week to share how we can support your growth milestones?\n\nBest,\n[Your Name]"
    },
    "Partnership": {
        "subject": "Strategic partnership query for {company}",
        "body": "Hi {first_name},\n\nI came across {company}'s work in {industry} and was impressed by your focus on technology change. As a CRM and Salesforce integration consulting partner, we see a lot of overlap between our GTM automation solutions and your services.\n\nI wanted to explore if there is room for a strategic partnership between our teams to help mutual clients optimize their cloud migrations.\n\nBest,\n[Your Name]"
    },
    "AI Consulting": {
        "subject": "Optimizing AI operations at {company}",
        "body": "Hi {first_name},\n\nWith your role as {title} at {company}, I imagine scaling tech processes is top of mind. Many companies in the {industry} space are trying to integrate AI capabilities into their workflows but struggle with database integration.\n\nWe provide AI consulting and Salesforce integration services to bring automation directly into your CRM.\n\nWould you be open to a low-pressure conversation on how we can streamline this for {company}?\n\nBest,\n[Your Name]"
    },
    "Product Demo": {
        "subject": "Quick demo request: CRM & GTM automation for {company}",
        "body": "Hi {first_name},\n\nI noticed {company} recently triggered a tech stack update. Integrating new tools into your existing CRM workflows can be time-consuming.\n\nWe've built a GTM automation platform that automates CRM data enrichment. I'd love to run a quick 10-minute demo to show you how it works and see if it aligns with {company}'s needs.\n\nDo you have some time for a quick demo this week?\n\nBest,\n[Your Name]"
    },
    "AI Automation": {
        "subject": "Automating workflows at {company} via AI agents",
        "body": "Hi {first_name},\n\nAs the {title} at {company}, I know that productivity and operational efficiency are key. We help companies in {industry} automate repetitive data entry, CRM logging, and outreach pipelines using AI agents.\n\nSince {company} is growing (size: {company_size}), automating these processes can save hundreds of hours.\n\nAre you open to a brief call to see which of your workflows are best suited for AI automation?\n\nBest,\n[Your Name]"
    },
    "RAG Development": {
        "subject": "Leveraging private data at {company} via RAG systems",
        "body": "Hi {first_name},\n\nMany technology leaders at {company_size}-sized companies are looking at how to safely search and retrieve information from internal docs.\n\nWe build custom Retrieval-Augmented Generation (RAG) models that integrate directly with Salesforce and other CRM databases, letting your team query docs in natural language.\n\nWould you be open to a brief chat to see how we might apply this for {company}?\n\nBest,\n[Your Name]"
    },
    "Digital Transformation": {
        "subject": "Accelerating digital transformation at {company}",
        "body": "Hi {first_name},\n\nManaging cloud migrations and digital transformations is a major effort for growing teams in the {industry} sector.\n\nWe partner with firms like {company} to migrate legacy systems to modern cloud CRMs and set up robust GTM automations to ensure business continuity.\n\nDo you have 10 minutes next week to discuss how we can help speed up {company}'s digital initiatives?\n\nBest,\n[Your Name]"
    },
    "Managed Services": {
        "subject": "Reliable CRM & Cloud Systems Managed Services for {company}",
        "body": "Hi {first_name},\n\nMany {industry} firms with {company_size} employees struggle with the high cost and overhead of hiring full-time CRM administrators.\n\nWe offer CRM Managed Services—giving you access to certified systems architects and automation specialists on demand, for a fraction of the cost of a full-time hire.\n\nWould you be open to a brief chat about how we can support {company}'s CRM admin needs?\n\nBest,\n[Your Name]"
    },
    "General Sales Outreach": {
        "subject": "Streamlining CRM & GTM operations at {company}",
        "body": "Hi {first_name},\n\nI'm reaching out because we help companies in the {industry} sector automate their GTM operations and integrate cloud CRM systems.\n\nWe noticed {company} has been scaling, and wanted to see how you are currently handling CRM data enrichment and lead pipelines.\n\nDo you have 10 minutes for a brief introductory call?\n\nBest,\n[Your Name]"
    }
}


# ═════════════════════════════════════════════════════════════════════════════
# Service matching — compares our services against prospect context (was service_matcher.py)
# ═════════════════════════════════════════════════════════════════════════════

class ServiceMatcher:
    """
    Compares our services with detected company needs, hiring information, and buying signals.
    """

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def match(
        self,
        our_services: str,
        industry: Optional[str],
        title: Optional[str],
        hiring_info: Optional[Dict[str, Any]],
        buying_signal: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compare services, hiring info, and signals.
        Returns:
            matched_services (list of strings)
            match_score (number between 0 and 100)
            reason (string explanation)
        """
        system_prompt = f"""You are a Service Matching Engine for a B2B GTM platform.
Your job is to compare a vendor's services with a prospect company's context, hiring information, and buying signals to evaluate product-market alignment.

We sell these services: {our_services}.

Prospect Context:
- Industry: {industry or 'N/A'}
- Job Title of Target: {title or 'N/A'}

Hiring Information:
- Active Roles/Searches: {hiring_info or 'None detected'}

Buying Signals:
- Signals details: {buying_signal or 'None detected'}

You must evaluate how well our services align with their business needs, hiring patterns, and trigger signals.
Return a structured JSON object with exactly three fields:
- matched_services (array of strings): Sub-list of our services that are highly relevant to this prospect.
- match_score (number from 0 to 100): An alignment score (0 = no match, 100 = perfect alignment).
- reason (string): A brief, analytical explanation of why these services were matched or why the score is low.
"""
        user_prompt = f"""Evaluate alignment for:
Industry: {industry or 'N/A'}
Title: {title or 'N/A'}
Hiring: {hiring_info or 'N/A'}
Signal: {buying_signal or 'N/A'}"""

        try:
            result = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Use Haiku for cost efficiency
                response_format={
                    "matched_services": ["string"],
                    "match_score": "number",
                    "reason": "string"
                }
            )
            return {
                "matched_services": list(result.get("matched_services", [])),
                "match_score": float(result.get("match_score", 50)),
                "reason": str(result.get("reason", ""))
            }
        except Exception as e:
            logger.error("ServiceMatcher match failed, falling back to general values", error=str(e))
            return {
                "matched_services": ["CRM consulting"],
                "match_score": 50.0,
                "reason": f"ServiceMatcher encountered an error during evaluation: {str(e)}"
            }


# ═════════════════════════════════════════════════════════════════════════════
# Business case classification (was business_case_detector.py)
# ═════════════════════════════════════════════════════════════════════════════

class BusinessCaseDetector:
    """
    Classifies B2B GTM opportunities into predefined business cases using contact and signal details.
    """

    BUSINESS_CASES = [
        "Recruitment Partnership",
        "AI Consulting",
        "Product Demo",
        "AI Automation",
        "RAG Development",
        "Digital Transformation",
        "Managed Services",
        "General Sales Outreach"
    ]

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def detect(
        self,
        industry: Optional[str],
        title: Optional[str],
        signal_type: str,
        signal_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Classifies the opportunity based on contact context and signal triggers.
        Returns:
            business_case (string)
            confidence (number 0.0-1.0)
            reason (string explanation)
        """
        system_prompt = f"""You are a B2B GTM Business Case Detector.
Your job is to analyze a prospect's firmographic context and their trigger signals to classify the sales opportunity into exactly one of these business cases:

Allowed Business Cases:
{chr(10).join(f'- {bc}' for bc in self.BUSINESS_CASES)}

Prospect Context:
- Industry: {industry or 'N/A'}
- Job Title: {title or 'N/A'}

Trigger Signal:
- Type: {signal_type}
- Signal Data: {signal_data or {}}

Evaluate which business case is the most fitting match for this opportunity.
Return a structured JSON object with exactly three fields:
- business_case (string): Must be EXACTLY one of the allowed business cases listed above.
- confidence (number): A confidence score between 0.0 and 1.0 representing your classification confidence.
- reason (string): A short, professional explanation of why this business case applies.
"""
        user_prompt = f"""Classify opportunity:
Industry: {industry or 'N/A'}
Title: {title or 'N/A'}
Signal Type: {signal_type}
Signal Data: {signal_data or {}}"""

        try:
            result = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=False,  # Haiku is fast and cost-efficient
                response_format={
                    "business_case": "string",
                    "confidence": "number",
                    "reason": "string"
                }
            )
            val = result.get("business_case", "General Sales Outreach")
            if val not in self.BUSINESS_CASES:
                val = "General Sales Outreach"

            return {
                "business_case": val,
                "confidence": float(result.get("confidence", 0.5)),
                "reason": str(result.get("reason", "Fallback classification."))
            }
        except Exception as e:
            logger.error("BusinessCaseDetector detection failed, falling back", error=str(e))
            return {
                "business_case": "General Sales Outreach",
                "confidence": 0.5,
                "reason": f"Detector exception: {str(e)}"
            }


# ═════════════════════════════════════════════════════════════════════════════
# Channel selection (was channel_selector.py)
# ═════════════════════════════════════════════════════════════════════════════

class ChannelSelector:
    """
    Selects the primary and secondary outreach channels based on available contact info,
    job titles, and signal details.
    """

    CHANNELS = ["Email", "LinkedIn", "Phone", "Outlook"]

    def __init__(self, llm: LLMService = None):
        self.llm = llm or LLMService()

    async def select_channels(
        self,
        email: Optional[str],
        email_valid: Optional[bool],
        linkedin_url: Optional[str],
        title: Optional[str],
        signal_type: str
    ) -> Dict[str, Any]:
        """
        Evaluate and select channels.
        Returns:
            primary_channel (string)
            secondary_channel (string)
            available_channels (list of strings)
            reason (string explanation)
        """
        available = []
        if email and email_valid is not False:
            available.append("Email")
            available.append("Outlook")
        if linkedin_url:
            available.append("LinkedIn")

        # Phone is always a possible fallback option
        available.append("Phone")

        title_lower = (title or "").lower()
        is_exec = any(w in title_lower for w in ["vp", "vice president", "chief", "director", "head", "manager"])
        is_social = any(w in title_lower for w in ["sales", "marketing", "recruiting", "talent", "hr", "growth"])

        prim = "Email"
        sec = "None"

        if is_social and "LinkedIn" in available:
            prim = "LinkedIn"
            sec = "Email" if "Email" in available else "None"
        elif is_exec and "Email" in available:
            prim = "Email"
            sec = "LinkedIn" if "LinkedIn" in available else "None"
        else:
            prim = "Email" if "Email" in available else "LinkedIn" if "LinkedIn" in available else "Phone"
            sec = "LinkedIn" if prim == "Email" and "LinkedIn" in available else "None"

        return {
            "primary_channel": prim,
            "secondary_channel": sec,
            "available_channels": available,
            "reason": f"Deterministic channel selection (Exec: {is_exec}, Social: {is_social}) avoiding unnecessary LLM calls."
        }


# ═════════════════════════════════════════════════════════════════════════════
# Outreach decision engine — combines the three modules above (was in a3_outreach.py)
# ═════════════════════════════════════════════════════════════════════════════

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
        Consolidated into a single high-accuracy, fast LLM evaluation step.
        """
        vendor_services = "Salesforce integration, CRM consulting, GTM automation, and cloud migration services"

        signal_type = signal.signal_type if signal else "fallback"
        signal_raw_data = signal.raw_data if signal else {}
        signal_confidence = signal.confidence if signal else 1.0

        # Fast deterministic channel selection
        channel_result = await self.channel_selector.select_channels(
            email=contact.email,
            email_valid=contact.email_valid,
            linkedin_url=contact.linkedin_url,
            title=contact.title,
            signal_type=signal_type
        )

        system_prompt = f"""You are the Outreach Decision Engine for a B2B GTM platform.
Your job is to analyze a prospect and trigger signal, identify matched services, classify the business case, and determine if it makes commercial sense to contact this prospect.

OUR OFFERINGS: {vendor_services}

ALLOWED BUSINESS CASES:
- Recruitment Partnership
- Funding Round
- Partnership
- AI Consulting
- Product Demo
- AI Automation
- RAG Development
- Digital Transformation
- Managed Services
- General Sales Outreach

PROSPECT CONTEXT:
- Title: {contact.title or 'Decision Maker'}
- Company: {contact.company or 'Target Company'}
- Industry: {contact.industry or 'N/A'}
- Company Size: {contact.company_size or 'N/A'}

TRIGGER SIGNAL:
- Type: {signal_type}
- Signal Details: {signal_raw_data or {}}
- Signal Confidence: {signal_confidence}

RECOMMENDED CHANNEL PREFERENCE:
- Primary: {channel_result.get('primary_channel', 'Email')}
- Secondary: {channel_result.get('secondary_channel', 'None')}

Evaluate relevance and return a JSON object with:
{{
  "should_contact": true/false (true if relevant and good commercial fit, false otherwise),
  "why_contact": "concise 1-sentence value-driven hook",
  "business_case": "one of the allowed business cases listed above",
  "matched_services": ["relevant services from our offerings"],
  "recommended_channel": "Email or LinkedIn",
  "confidence_score": 0.85,
  "explanation": "analytical explanation of fit"
}}"""

        user_prompt = f"Evaluate prospect {contact.first_name or ''} {contact.last_name or ''} at {contact.company or 'Target'} for signal {signal_type}."

        try:
            decision = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=500,
            )
            return {
                "should_contact": bool(decision.get("should_contact", True)),
                "why_contact": str(decision.get("why_contact", "Reaching out regarding GTM automation.")),
                "business_case": str(decision.get("business_case", "General Sales Outreach")),
                "matched_services": list(decision.get("matched_services", ["CRM consulting"])),
                "recommended_channel": str(decision.get("recommended_channel", channel_result.get("primary_channel", "email"))),
                "confidence_score": float(decision.get("confidence_score", 0.85)),
                "explanation": str(decision.get("explanation", "Qualified match based on title and buying signal.")),
            }
        except Exception as e:
            logger.error("Outreach Decision Engine failed, falling back to True", error=str(e))
            return {
                "should_contact": True,
                "why_contact": "Salesforce and GTM automation alignment.",
                "business_case": "General Sales Outreach",
                "matched_services": ["CRM consulting", "GTM automation"],
                "recommended_channel": channel_result.get("primary_channel", "email"),
                "confidence_score": 0.8,
                "explanation": f"Fallback rule evaluation: {str(e)}",
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


# ═════════════════════════════════════════════════════════════════════════════
# Draft persistence + approval-triggered sending (was draft_manager.py)
# ═════════════════════════════════════════════════════════════════════════════

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
        matched_services: Any,
        channel: str,
        traceability: Optional[Dict[str, Any]] = None,
    ) -> OutreachDraft:
        """Create and persist an OutreachDraft with traceability metadata."""
        # Lookup contact to determine rep ownership
        contact_res = await self.db.execute(select(Contact).where(Contact.id == contact_id))
        contact = contact_res.scalar_one_or_none()
        rep_user_id = contact.user_id if contact else None

        # Resolve rep identity and Cal.com booking link from backend source of truth
        if rep_user_id:
            user = await self.db.get(User, rep_user_id)
            if user:
                from app.services import CalService
                cal_svc = CalService()
                contact_full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() if contact else ""
                booking_link = await cal_svc.get_booking_link(
                    contact_email=contact.email if contact else "",
                    contact_name=contact_full_name,
                    user=user,
                )
                if user.name and "[Your Name]" in body:
                    body = body.replace("[Your Name]", user.name)
                if booking_link and "cal.com" not in body.lower():
                    body = body.rstrip() + f"\n\nFeel free to select a convenient time on my calendar: {booking_link}"

        services_list = matched_services if isinstance(matched_services, list) else ([matched_services] if isinstance(matched_services, str) else (matched_services.get("services", []) if isinstance(matched_services, dict) else []))

        meta_payload = {
            "services": services_list,
            "personalisation_reasoning": (traceability.get("personalisation_reasoning") if traceability else None) or business_case,
            "selected_primary_signal": (traceability.get("selected_primary_signal") if traceability else None) or (signal_id if signal_id else None),
            "signal_category": (traceability.get("signal_category") if traceability else None) or "general_icp",
            "signal_summary_used": (traceability.get("signal_summary_used") if traceability else None) or "",
            "referenced_signal_ids": (traceability.get("referenced_signal_ids") if traceability else None) or ([signal_id] if signal_id else []),
        }

        draft = OutreachDraft(
            contact_id=contact_id,
            user_id=rep_user_id,
            signal_id=signal_id,
            subject=subject,
            body=body,
            business_case=business_case,
            matched_services=meta_payload,
            channel=channel,
            status="pending",
            approval_state="pending"
        )
        self.db.add(draft)
        await self.db.flush()

        if getattr(settings, "ENABLE_SLACK_APPROVALS", True):
            try:
                from app.services.slack_service import SlackService
                contact_res = await self.db.execute(select(Contact).where(Contact.id == contact_id))
                contact = contact_res.scalar_one_or_none()
                if contact:
                    slack = SlackService()
                    await slack.send_draft_approval_card(contact, draft)
            except Exception as e:
                logger.error("Failed to send Slack draft approval card", error=str(e))

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

    async def has_any_pending_draft(self, contact_id: str) -> bool:
        """Check if there is already any pending draft for this contact."""
        result = await self.db.execute(
            select(OutreachDraft)
            .where(and_(
                OutreachDraft.contact_id == contact_id,
                OutreachDraft.approval_state == "pending"
            ))
        )
        return result.scalars().first() is not None

    async def has_pending_draft_for_business_case(self, contact_id: str, business_case: str) -> bool:
        """Check if there is already a pending draft for this contact and business case."""
        result = await self.db.execute(
            select(OutreachDraft)
            .where(and_(
                OutreachDraft.contact_id == contact_id,
                OutreachDraft.business_case == business_case,
                OutreachDraft.approval_state == "pending"
            ))
        )
        return result.scalars().first() is not None

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

        if not contact or (not settings.AGENT3_TEST_MODE and draft.signal_id is not None and not signal):
            draft.status = "failed"
            draft.approval_state = "approved"
            await self.db.flush()
            return False

        # Immediate pre-send DNC suppression check
        from app.services.suppression_service import SuppressionService
        is_suppressed, supp_reason = await SuppressionService.is_email_suppressed(
            self.db, contact.email if contact else None, contact_id=contact.id if contact else None
        )
        if is_suppressed:
            logger.warning(
                "A3: Draft approval blocked immediately before send: recipient is suppressed (DNC)",
                draft_id=draft_id,
                contact_id=contact.id if contact else None,
                email=contact.email if contact else None,
                reason=supp_reason,
            )
            draft.status = "suppressed"
            draft.approval_state = "rejected"
            await self.db.commit()
            return False

        draft.approval_state = "approved"

        # Dispatch outreach using owner rep's authorized mailbox
        provider_id = None
        success = False

        # Identify assigned sales rep
        rep_user_id = getattr(draft, "user_id", None) or (contact.user_id if contact else None)
        user = None
        if rep_user_id:
            user = await self.db.get(User, rep_user_id)

        # Check if user is a production company user
        is_production_user = bool(
            user and (
                user.email.endswith("@forcecloudlabs.com")
                or user.email == getattr(settings, "COMPANY_PRODUCTION_EMAIL", "shree.lakshmi@forcecloudlabs.com")
            )
        )

        # Priority 1 (Production Company Mailbox): Microsoft 365 / Microsoft Graph (POST /me/sendMail)
        if rep_user_id and user:
            from app.services.microsoft_graph_service import MicrosoftGraphService
            ms_svc = MicrosoftGraphService()
            ms_int_res = await self.db.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == rep_user_id,
                    UserIntegration.provider == "microsoft",
                    UserIntegration.status == "connected",
                )
            )
            ms_integration = ms_int_res.scalar_one_or_none()
            if ms_integration:
                token = await ms_svc.get_valid_access_token(ms_integration, self.db)
                if token:
                    sender_email = ms_integration.provider_account_email or user.email
                    formatted_body = draft.body.replace("\n", "<br/>")
                    try:
                        provider_id = await ms_svc.send_mail(
                            access_token=token,
                            to_email=contact.email,
                            subject=draft.subject,
                            html_body=f"<div style='font-family: sans-serif; font-size: 14px; line-height: 1.6;'>{formatted_body}</div>",
                            from_email=sender_email,
                        )
                        success = bool(provider_id)
                        logger.info(
                            "A3: Outbound email sent via sales rep Microsoft 365 mailbox",
                            rep_email=sender_email,
                            to=contact.email,
                            provider_id=provider_id,
                        )
                    except Exception as ms_send_err:
                        logger.error(
                            "A3: Failed to send via Microsoft 365 mailbox; falling back",
                            rep_email=sender_email,
                            error=str(ms_send_err),
                        )
                        success = False

            elif is_production_user:
                # Production rep without connected Microsoft 365 mailbox MUST NOT fall back to personal Gmail
                err_msg = f"Microsoft 365 mailbox is not connected for this sales representative ({user.email})."
                logger.error("A3: Outreach blocked - production email requires Microsoft 365 connection", error=err_msg)
                draft.status = "failed"
                await self.db.commit()
                return False

        # Priority 2 (Development/Testing Fallback ONLY for non-production accounts): Google Workspace / Gmail OAuth
        if not success and rep_user_id and user and not is_production_user:
            from app.services.google_oauth_service import GoogleOAuthService
            oauth_svc = GoogleOAuthService()
            g_int_res = await self.db.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == rep_user_id,
                    UserIntegration.provider == "google",
                    UserIntegration.status == "connected",
                )
            )
            g_integration = g_int_res.scalar_one_or_none()
            token, token_type = await oauth_svc.get_effective_access_token_for_user(user, self.db)
            if token and user and user.email:
                sender_email = (g_integration.provider_account_email if g_integration else None) or user.email
                try:
                    formatted_body = draft.body.replace("\n", "<br/>")
                    rep_name = user.name if user else None
                    provider_id = await oauth_svc.send_gmail_message(
                        access_token=token,
                        to_email=contact.email,
                        subject=draft.subject,
                        html_body=f"<div style='font-family: sans-serif; font-size: 14px; line-height: 1.6;'>{formatted_body}</div>",
                        from_email=sender_email,
                        from_name=rep_name,
                    )
                    success = bool(provider_id)
                    logger.info(
                        "A3: Outbound email sent via sales rep Google mailbox (Development Fallback)",
                        rep_email=sender_email,
                        token_type=token_type,
                        to=contact.email,
                        provider_id=provider_id,
                    )
                except Exception as oauth_send_err:
                    logger.error(
                        "A3: Failed to send via user's Google mailbox; falling back",
                        rep_email=sender_email,
                        error=str(oauth_send_err),
                    )
                    success = False

        # Safety Gate: If test mode, dry run, pytest, or ENABLE_EMAIL_SENDING is False, mock send safely
        if (
            not success
            and (
                getattr(settings, "AGENT3_TEST_MODE", False)
                or getattr(settings, "DRY_RUN_OUTREACH", False)
                or os.environ.get("PYTEST_CURRENT_TEST")
                or not getattr(settings, "ENABLE_EMAIL_SENDING", False)
            )
        ):
            logger.info("Safe/Test mode active; mock-sending draft without live dispatch", email=contact.email)
            success = True
            provider_id = "mock_msg_safe_test"

        # Priority 3: Instantly (if enabled and live sending permitted)
        if not success and settings.ENABLE_INSTANTLY:
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
        elif not success and getattr(settings, "SMTP_USER", "") and getattr(settings, "SMTP_PASSWORD", ""):
            from app.services import SMTPService
            smtp_svc = SMTPService()
            formatted_body = draft.body.replace("\n", "<br/>")
            provider_id = await smtp_svc.send_email(
                to=contact.email,
                subject=draft.subject,
                html=f"<div style='font-family: sans-serif; font-size: 14px; line-height: 1.6;'>{formatted_body}</div>"
            )
            success = bool(provider_id)
            if not success:
                logger.error("SMTP email dispatch returned failure", email=contact.email)
        elif not success and getattr(settings, "ENABLE_EMAIL_SENDING", False) and settings.RESEND_API_KEY:
            from app.services.resend_service import ResendService
            resend = ResendService()
            formatted_body = draft.body.replace("\n", "<br/>")
            provider_id = await resend.send_email(
                to=contact.email,
                subject=draft.subject,
                html=f"<div style='font-family: sans-serif; font-size: 14px; line-height: 1.6;'>{formatted_body}</div>"
            )
            success = bool(provider_id)
            if not success:
                logger.error("Resend email dispatch returned failure", email=contact.email)
        elif not success:
            # Safe default fallback for development/staging
            logger.info("Email sending not enabled; mock-sending draft", email=contact.email)
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

            # Record outbound outreach email in ConversationThread history
            from app.models.models import ConversationThread
            outbound_thread = ConversationThread(
                contact_id=contact.id,
                event_type="email_sent",
                direction="outbound",
                channel=draft.channel or "email",
                content=f"Subject: {draft.subject}\n\n{draft.body}",
                occurred_at=datetime.utcnow(),
                sent_at=datetime.utcnow(),
            )
            self.db.add(outbound_thread)

            # Step progression logic
            if signal:
                # SEQUENCE_TEMPLATES + timedelta are defined/imported earlier in
                # this same module now — no more deferred import needed.
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


# ═════════════════════════════════════════════════════════════════════════════
# Main orchestrator
# ═════════════════════════════════════════════════════════════════════════════

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

    async def run(
        self,
        contact_signal_pairs: Optional[List[Dict]] = None,
        user_input_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process qualified contacts with signals and send outreach.
        """
        logger.info("A3 starting")

        # Resolve active session ID from context, fallback to database if standalone
        active_session_id = user_input_id
        if active_session_id is None:
            active_session_result = await self.db.execute(
                select(UserInput.id).order_by(UserInput.id.desc()).limit(1)
            )
            active_session_id = active_session_result.scalar_one_or_none()

        if active_session_id is None:
            logger.warning("No active session ID resolved. Skipping A3 run.")
            return {
                "agent": "A3",
                "processed": 0,
                "sent": 0,
                "drafts_created": 0,
                "skipped": 0,
                "skip_reasons": {},
                "reason": "No active session ID resolved"
            }
        # Get contacts with qualifying signals if not provided
        if not contact_signal_pairs:
            if settings.AGENT3_TEST_MODE:
                contact_signal_pairs = await self._get_test_contacts()
            else:
                contact_signal_pairs = await self._get_qualified_contacts(user_input_id=active_session_id)

        logger.info("Processing contacts", count=len(contact_signal_pairs), active_session_id=active_session_id)

        sent = 0
        drafts_created = 0
        drafted_contact_business_cases = set()
        skip_reasons = {
            "do_not_contact": 0,
            "deduplicated": 0,
            "missing_email": 0,
            "invalid_email": 0,
            "missing_contact_or_signal": 0,
            "generation_failed": 0,
            "send_failed": 0,
            "decision_engine_rejected": 0,
            "inactive_session": 0,
            "signal_score_below_threshold": 0,
            "icp_score_below_threshold": 0,
            "sequence_completed": 0,
        }

        for pair in contact_signal_pairs:
            contact, signal = await self._resolve_pair(pair)
            if not contact:
                skip_reasons["missing_contact_or_signal"] += 1
                logger.info("Outreach skipped: missing contact in pair", pair=pair)
                continue


            # Enforce strict current-session checks
            assoc_check = await self.db.execute(
                select(ContactUserInputAssociation).where(
                    ContactUserInputAssociation.contact_id == contact.id,
                    ContactUserInputAssociation.user_input_id == active_session_id
                )
            )
            if not assoc_check.scalars().first() and contact.user_input_id != active_session_id:
                skip_reasons["inactive_session"] += 1
                logger.info(
                    "Outreach skipped: contact does not belong to active session",
                    contact_id=contact.id,
                    active_session_id=active_session_id
                )
                continue

            # Enforce Signal Score threshold check
            if signal and signal.confidence < settings.SIGNAL_SCORE_THRESHOLD / 100:
                skip_reasons["signal_score_below_threshold"] += 1
                logger.info(
                    "Outreach skipped: signal score below threshold",
                    contact_id=contact.id,
                    signal_id=signal.id,
                    confidence=signal.confidence,
                    threshold=settings.SIGNAL_SCORE_THRESHOLD / 100
                )
                continue

            # Enforce ICP Score threshold check
            if contact.icp_score is None or contact.icp_score < settings.ICP_SCORE_THRESHOLD:
                skip_reasons["icp_score_below_threshold"] += 1
                logger.info(
                    "Outreach skipped: ICP score below threshold",
                    contact_id=contact.id,
                    icp_score=contact.icp_score,
                    threshold=settings.ICP_SCORE_THRESHOLD
                )
                continue

            # Verify one contact never receives two drafts for the same signal or pending draft
            if signal and await self.draft_manager.has_pending_draft(contact.id, signal.id):
                skip_reasons["deduplicated"] += 1
                logger.info(
                    "Outreach skipped: pending draft already exists for this contact-signal pair",
                    contact_id=contact.id,
                    signal_id=signal.id
                )
                continue
            if not signal and await self.draft_manager.has_any_pending_draft(contact.id):
                skip_reasons["deduplicated"] += 1
                logger.info(
                    "Outreach skipped: pending draft already exists for this contact",
                    contact_id=contact.id
                )
                continue

            # Fetch steps from SEQUENCE_TEMPLATES
            signal_type = signal.signal_type if signal else "fallback"
            sequence_step = signal.sequence_step if signal else 0

            steps = SEQUENCE_TEMPLATES.get(signal_type, SEQUENCE_TEMPLATES["default"])["steps"]
            if sequence_step >= len(steps):
                if signal:
                    signal.processed = True
                    await self.db.commit()
                skip_reasons["sequence_completed"] += 1
                logger.info(
                    "Outreach skipped: sequence already completed for signal",
                    contact_id=contact.id,
                    signal_id=signal.id,
                    sequence_step=sequence_step,
                    total_steps=len(steps)
                )
                continue

            step_def = steps[sequence_step]
            from app.services.suppression_service import SuppressionService
            is_suppressed, supp_reason = await SuppressionService.is_email_suppressed(
                self.db, contact.email, contact_id=contact.id
            )
            if is_suppressed or contact.do_not_contact:
                skip_reasons["do_not_contact"] += 1
                logger.info(
                    "Outreach skipped: contact email is suppressed (DNC)",
                    contact_id=contact.id,
                    email=contact.email,
                    reason=supp_reason,
                )
                continue
            if not contact.email:
                skip_reasons["missing_email"] += 1
                logger.info("Outreach skipped: missing contact email", contact_id=contact.id)
                continue
            if contact.email_valid is False:
                skip_reasons["invalid_email"] += 1
                logger.info("Outreach skipped: email validated as invalid", contact_id=contact.id, email=contact.email)
                continue
            if await self._already_contacted(contact.id, signal.id if signal else None, sequence_step):
                skip_reasons["deduplicated"] += 1
                logger.info(
                    "Outreach skipped: already contacted for this step",
                    contact_id=contact.id,
                    signal_id=signal.id,
                    sequence_step=sequence_step
                )
                continue

            # Run Outreach Decision Engine
            decision = await self.decision_engine.decide(contact, signal)
            logger.info("Outreach Decision Engine evaluation", contact_email=contact.email, decision=decision)
            if not decision.get("should_contact", True):
                skip_reasons["decision_engine_rejected"] += 1
                logger.info(
                    "Outreach skipped: decision engine rejected contact",
                    contact_id=contact.id,
                    reason=decision.get("explanation")
                )
                continue

            bc = decision.get("business_case", "General Sales Outreach")
            if (contact.id, bc) in drafted_contact_business_cases or await self.draft_manager.has_pending_draft_for_business_case(contact.id, bc):
                skip_reasons["deduplicated"] += 1
                logger.info(
                    "Outreach skipped: pending draft or duplicate business case draft exists for contact",
                    contact_id=contact.id,
                    business_case=bc
                )
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
                logger.warning("Outreach skipped: failed to generate message via LLM", contact_id=contact.id)
                continue

            # Create outreach draft with rich traceability metadata
            draft = await self.draft_manager.create_draft(
                contact_id=contact.id,
                signal_id=signal.id if signal else None,
                subject=message.get("subject", ""),
                body=message.get("body", ""),
                business_case=decision.get("business_case", "General Sales Outreach"),
                matched_services=decision.get("matched_services", []),
                channel=message.get("channel", "email"),
                traceability=message.get("traceability", {}),
            )
            drafts_created += 1
            drafted_contact_business_cases.add((contact.id, bc))

            # Add review task PendingAction (all drafts require explicit manual approval)
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

            if drafts_created >= 10:
                logger.info("Batch draft limit reached", drafts_created=drafts_created)
                break

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

    @staticmethod
    def _select_primary_signal(signals: List[SignalEvent]) -> Optional[SignalEvent]:
        if not signals:
            return None
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        def score_signal(s: SignalEvent) -> float:
            rd = s.raw_data or {}
            dt = None
            d_str = rd.get("event_date") or rd.get("published_at")
            if d_str:
                try:
                    dt = datetime.fromisoformat(str(d_str).strip().replace("Z", "+00:00"))
                    if dt.tzinfo is not None:
                        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass
            if not dt:
                dt = s.occurred_at or s.detected_at or datetime.min

            days_ago = max(0, (now - dt).days)
            # Prioritize signals within last 30 days
            recency_score = 100.0 if days_ago <= 30 else (50.0 if days_ago <= 90 else 10.0)
            conf_score = (s.confidence or 0.8) * 50.0
            st_val = s.signal_type.value if hasattr(s.signal_type, "value") else str(s.signal_type)
            cat_weights = {
                "funding_round": 40.0,
                "tech_stack_change": 35.0,
                "job_posting": 30.0,
                "new_hire": 25.0,
                "news_expansion": 20.0,
            }
            type_score = cat_weights.get(st_val.lower(), 15.0)
            return recency_score + conf_score + type_score

        return max(signals, key=score_signal)

    async def _resolve_pair(self, pair: Dict[str, Any]):
        if pair.get("contact") is not None:
            contact = pair["contact"]
            signal = pair.get("signal")
            if signal is None and not settings.AGENT3_TEST_MODE:
                signals_q = select(SignalEvent).where(SignalEvent.contact_id == contact.id).order_by(SignalEvent.detected_at.desc())
                sig_res = await self.db.execute(signals_q)
                contact_signals = sig_res.scalars().all()
                signal = self._select_primary_signal(contact_signals)
            return contact, signal

        contact_id = pair.get("contact_id")
        if not contact_id:
            return None, None
        contact_result = await self.db.execute(select(Contact).where(Contact.id == contact_id))
        contact = contact_result.scalar_one_or_none()
        if not contact:
            return None, None
        if settings.AGENT3_TEST_MODE:
            return contact, None
        signal_query = select(SignalEvent).where(SignalEvent.contact_id == contact_id)
        if pair.get("signal_type"):
            signal_query = signal_query.where(SignalEvent.signal_type == pair["signal_type"])
        sig_res = await self.db.execute(signal_query)
        signals = sig_res.scalars().all()
        signal = self._select_primary_signal(signals)
        return contact, signal

    async def _get_qualified_contacts(self, user_input_id: Optional[int] = None) -> List[Dict]:
        """
        Pull contacts with signals above threshold that haven't been contacted recently.
        Includes sequence timing logic.
        """
        # Resolve active session ID from context, fallback to database if standalone
        active_session_id = user_input_id
        if active_session_id is None:
            active_session_result = await self.db.execute(
                select(UserInput.id).order_by(UserInput.id.desc()).limit(1)
            )
            active_session_id = active_session_result.scalar_one_or_none()

        if active_session_id is None:
            return []

        assoc_ids_q = select(ContactUserInputAssociation.contact_id).where(ContactUserInputAssociation.user_input_id == active_session_id)
        result = await self.db.execute(
            select(Contact, SignalEvent)
            .join(SignalEvent, SignalEvent.contact_id == Contact.id)
            .where(
                and_(
                    or_(Contact.user_input_id == active_session_id, Contact.id.in_(assoc_ids_q)),
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
            .limit(25)
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

    @staticmethod
    def _classify_persona(title: Optional[str]) -> str:
        if not title:
            return "general"
        t = title.lower()
        if any(k in t for k in ["cto", "chief technology", "vp of engineering", "vp engineering", "head of engineering", "architect", "engineering lead", "tech lead", "chief information", "cio", "vp technology"]):
            return "technical"
        if any(k in t for k in ["cro", "chief revenue", "vp of sales", "vp sales", "head of sales", "director of sales", "sales director", "vp revenue", "revops", "revenue operations", "sales development"]):
            return "sales_revenue"
        if any(k in t for k in ["ceo", "founder", "co-founder", "president", "managing director", "chief executive", "coo", "chief operating", "vp operations"]):
            return "executive"
        return "general"

    @staticmethod
    def _categorize_signal(signal: Optional[SignalEvent]) -> str:
        if not signal:
            return "general_icp"
        st = (signal.signal_type.value if hasattr(signal.signal_type, "value") else str(signal.signal_type)).lower()
        rd = signal.raw_data or {}
        text = f"{st} {rd.get('headline', '')} {rd.get('description', '')} {signal.summary or ''} {rd.get('category', '')}".lower()

        if any(k in st for k in ["job_posting", "new_hire"]) or any(k in text for k in ["hiring", "job posting", "open role", "careers", "recruiting", "new hire"]):
            return "hiring"
        if "funding" in st or any(k in text for k in ["funding", "seed round", "series a", "series b", "series c", "series d", "raised $", "venture round", "capital raise", "investment"]):
            return "funding"
        if "tech_stack" in st or any(k in text for k in ["tech stack", "salesforce", "hubspot", "snowflake", "databricks", "migrat", "adopting", "software"]):
            return "tech_stack"
        if any(k in text for k in ["launch", "product release", "unveils", "introduces", "new feature", "announces new product"]):
            return "product_launch"
        if any(k in text for k in ["merger", "acquisition", "acquires", "partner", "alliance", "collaboration"]):
            return "partnerships_ma"
        if any(k in text for k in ["appoints", "named as", "joins as", "new cto", "new cro", "new ceo", "new vp"]):
            return "leadership"
        if "expansion" in st or any(k in text for k in ["expansion", "expands", "new office", "new market", "international expansion"]):
            return "expansion"
        return "general_icp"

    @staticmethod
    def _extract_signal_details(signal: Optional[SignalEvent]) -> Dict[str, Any]:
        rd = (signal.raw_data or {}) if signal else {}
        headline = rd.get("headline") or ""
        desc = rd.get("description") or (signal.summary if signal else "") or ""

        # Roles
        roles = rd.get("roles") or []
        roles_str = ", ".join(roles[:2]) if isinstance(roles, list) and roles else (roles if isinstance(roles, str) else "")

        # Round & amount (strictly from signal, never hallucinated)
        round_type = rd.get("round_type") or rd.get("funding_stage") or rd.get("category") or ""
        amount = rd.get("amount") or ""

        # Technology
        technology = rd.get("technology") or ""
        if not technology:
            techs = rd.get("technologies") or []
            if isinstance(techs, list) and techs:
                technology = techs[0]
            elif isinstance(techs, str):
                technology = techs
        if not technology:
            for tech in ["Salesforce", "HubSpot", "Snowflake", "Databricks", "AWS", "GCP", "PostgreSQL"]:
                if tech.lower() in (headline + " " + desc).lower():
                    technology = tech
                    break

        # Location
        loc_val = rd.get("location") or rd.get("locations") or []
        loc_str = loc_val[0] if isinstance(loc_val, list) and loc_val else (loc_val if isinstance(loc_val, str) else "")

        return {
            "headline": headline,
            "description": desc,
            "roles": roles_str,
            "round_type": round_type,
            "amount": amount,
            "technology": technology,
            "location": loc_str,
        }

    def _generate_deterministic_message(
        self,
        contact: Contact,
        signal: Optional[SignalEvent],
        category: str,
        persona: str,
        details: Dict[str, Any],
        channel: str = "email"
    ) -> Dict[str, str]:
        fn = contact.first_name or "there"
        comp = contact.company or "your company"
        ind = contact.industry or "your industry"

        if channel == "linkedin":
            if persona == "technical":
                body = f"Hi {fn}, noticed your engineering leadership at {comp}. We help tech teams automate data workflows and CRM integrations without custom code. Open to connecting?"
            elif persona == "sales_revenue":
                body = f"Hi {fn}, saw your role leading sales at {comp}. We help revenue teams automate prospect research and CRM data hygiene to speed up pipeline. Open to connecting?"
            elif persona == "executive":
                body = f"Hi {fn}, noticed {comp}'s growth in {ind}. We help executive teams automate revenue workflows and scale operations without linear headcount. Open to connecting?"
            else:
                body = f"Hi {fn}, saw your work at {comp}. We help companies automate routine data pipelines and CRM operations. Open to connecting?"
            return {"subject": "", "body": body[:280], "reasoning": f"LinkedIn connection request tailored for {persona} at {comp}."}

        # Email generation per category and persona
        if category == "hiring":
            role_mention = f"open roles ({details['roles']})" if details.get("roles") else "open positions"
            reasoning = f"Targeting {persona} at {comp} based on active hiring for {role_mention}. Focus on eliminating scaling bottlenecks."
            if persona == "technical":
                subject = f"Supporting engineering ramp at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp} is actively recruiting for {role_mention}.\n\n"
                    f"As engineering headcount grows, data integration and developer tooling friction often slow down sprint velocity. "
                    f"We provide automated integration pipelines that connect developer workflows directly to core systems, saving senior engineers hours of manual setup.\n\n"
                    f"Would you be open to a 10-minute technical exchange next week?"
                )
            elif persona == "sales_revenue":
                subject = f"Accelerating rep ramp-time at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp} is actively scaling the team with {role_mention}.\n\n"
                    f"When onboarding new sales hires, shortening the time to first closed deal is critical. "
                    f"We help revenue teams automate prospect intelligence and CRM data hygiene so new reps can focus 100% on pipeline generation.\n\n"
                    f"Are you open to a brief chat this Thursday on accelerating rep ramp-time?"
                )
            elif persona == "executive":
                subject = f"Scaling {comp}'s operational leverage"
                body = (
                    f"Hi {fn},\n\n"
                    f"I saw that {comp} is actively expanding headcount with {role_mention}.\n\n"
                    f"Scaling headcount without proportional administrative overhead is always challenging. "
                    f"We help high-growth leadership teams automate cross-functional GTM workflows and customer data syncs to maximize revenue per employee.\n\n"
                    f"Do you have 10 minutes next week for an introductory conversation?"
                )
            else:
                subject = f"Streamlining operations during {comp}'s team expansion"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp} is actively hiring for {role_mention}.\n\n"
                    f"During periods of team expansion, automating routine data workflows helps new hires ramp faster without administrative bottlenecks. "
                    f"We help growing companies streamline operations through targeted workflow automation.\n\n"
                    f"Would you be open to a brief introductory chat next week?"
                )

        elif category == "funding":
            milestone = details.get("round_type") or "recent funding"
            if details.get("amount"):
                milestone += f" ({details['amount']})"
            reasoning = f"Targeting {persona} at {comp} following {milestone}. Focus on post-raise scaling."
            if persona == "technical":
                subject = f"Scaling {comp}'s data architecture post-raise"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congrats on {comp}'s {milestone} announcement!\n\n"
                    f"Following a capital raise, technical debt in CRM data pipelines and custom scripts often threatens data integrity. "
                    f"We help engineering leaders automate data pipelines between databases and business systems with zero maintenance.\n\n"
                    f"Would you be open to a brief 10-minute technical walkthrough next week?"
                )
            elif persona == "sales_revenue":
                subject = f"Scaling {comp}'s sales velocity post-funding"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congrats to you and the team at {comp} on the {milestone} milestone!\n\n"
                    f"Post-funding, hitting ambitious revenue targets requires predictable outbound pipeline and zero rep time lost to manual admin. "
                    f"We help revenue leaders automate prospect research and CRM enrichment to keep pipeline full.\n\n"
                    f"Are you open to a brief conversation this week on scaling sales velocity?"
                )
            elif persona == "executive":
                subject = f"Capital efficiency and GTM scale for {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congratulations on {comp}'s {milestone} milestone!\n\n"
                    f"As you deploy this capital, building scalable GTM infrastructure early ensures revenue growth doesn't require linear headcount bloat. "
                    f"We partner with executive teams to automate revenue workflows and data intelligence.\n\n"
                    f"Could we connect for a brief 10-minute exchange next Tuesday?"
                )
            else:
                subject = f"Supporting {comp}'s growth post-funding"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congrats on {comp}'s {milestone} milestone!\n\n"
                    f"Following a funding milestone, streamlining operational workflows is key to supporting rapid scaling. "
                    f"We help growing companies automate core business processes and CRM systems.\n\n"
                    f"Do you have 10 minutes next week for a brief conversation?"
                )

        elif category == "tech_stack":
            tech = details.get("technology") or "modern cloud stack"
            reasoning = f"Targeting {persona} at {comp} based on {tech} adoption. Focus on workflow integration."
            if persona == "technical":
                subject = f"Optimizing {tech} data integrations at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s adoption of {tech}.\n\n"
                    f"Connecting {tech} into existing data pipelines often requires custom glue code that consumes engineering bandwidth. "
                    f"We build automated data connectors that sync {tech} bi-directionally with your core databases.\n\n"
                    f"Would you be open to a quick technical discussion on streamlining this integration?"
                )
            elif persona == "sales_revenue":
                subject = f"Maximizing rep adoption of {tech} at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp} has been modernizing its stack with {tech}.\n\n"
                    f"The key to getting ROI from sales technology is eliminating double-entry and keeping customer data actionable for reps. "
                    f"We automate {tech} workflows so your team gets clean intelligence without manual updates.\n\n"
                    f"Are you open to a brief chat on getting the most out of {tech}?"
                )
            elif persona == "executive":
                subject = f"Accelerating ROI on {comp}'s {tech} investment"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s strategic focus on modernizing your tech stack with {tech}.\n\n"
                    f"Maximizing ROI on software investments requires ensuring data flows seamlessly into executive decision-making. "
                    f"We help leadership teams automate reporting and operational workflows across core platforms.\n\n"
                    f"Do you have 10 minutes for a brief call next week?"
                )
            else:
                subject = f"Streamlining {tech} workflows at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s adoption of {tech}.\n\n"
                    f"Integrating modern software into daily workflows can significantly boost team efficiency. "
                    f"We help companies automate data syncs and operations around {tech}.\n\n"
                    f"Would you be open to a brief introductory chat next week?"
                )

        elif category == "expansion":
            loc = f" in {details['location']}" if details.get("location") else ""
            reasoning = f"Targeting {persona} at {comp} based on geographic/market expansion{loc}."
            if persona == "technical":
                subject = f"Centralized data architecture for {comp}'s expansion"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s recent expansion initiatives{loc}.\n\n"
                    f"As operations expand into new territories, maintaining consistent data pipelines and access controls across regions becomes critical. "
                    f"We provide automated systems integration to keep distributed environments unified.\n\n"
                    f"Would you be open to a 10-minute technical chat next week?"
                )
            elif persona == "sales_revenue":
                subject = f"Coordinating multi-market pipeline for {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I saw {comp}'s recent market expansion{loc}.\n\n"
                    f"Expanding into new territories requires localized prospect intelligence and fast lead distribution to avoid territory friction. "
                    f"We help sales leaders automate multi-region lead routing and outreach.\n\n"
                    f"Are you open to a brief chat on coordinating expansion pipeline?"
                )
            elif persona == "executive":
                subject = f"Operational consistency during {comp}'s expansion"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congratulations on {comp}'s recent expansion{loc}.\n\n"
                    f"Scaling into new markets demands standardized operational metrics and automated reporting across business units. "
                    f"We help executive teams maintain operational visibility during rapid geographic scaling.\n\n"
                    f"Do you have 10 minutes next week for an introductory conversation?"
                )
            else:
                subject = f"Supporting {comp}'s expansion initiatives"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s recent expansion{loc}.\n\n"
                    f"Supporting growth across new regions requires streamlined operations and reliable data workflows. "
                    f"We help growing companies automate multi-office business processes.\n\n"
                    f"Would you be open to a brief chat next week?"
                )

        elif category == "product_launch":
            reasoning = f"Targeting {persona} at {comp} following new product/feature launch. Focus on commercial acceleration."
            if persona == "technical":
                subject = f"Scalable data infrastructure for {comp}'s product launch"
                body = (
                    f"Hi {fn},\n\n"
                    f"I saw the recent product announcements coming out of {comp}.\n\n"
                    f"Accelerating adoption for new releases requires robust data pipelines that capture product analytics and sync user intent back to sales systems. "
                    f"We help technical teams automate product-to-CRM telemetry with minimal overhead.\n\n"
                    f"Would you be open to a brief technical chat next week?"
                )
            elif persona == "sales_revenue":
                subject = f"Ramping pipeline for {comp}'s new offering"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congratulations on {comp}'s latest product release!\n\n"
                    f"Taking a new product to market requires arming reps with high-intent prospect data and automated outreach to early adopters. "
                    f"We help revenue leaders accelerate pipeline generation for newly launched offerings.\n\n"
                    f"Are you open to a brief 10-minute exchange this Thursday?"
                )
            else:
                subject = f"Commercial acceleration for {comp}'s new launch"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congratulations on {comp}'s recent product milestone!\n\n"
                    f"Scaling revenue around a new product requires tight alignment between market demand and GTM execution. "
                    f"We help leadership teams automate outbound pipeline and customer intelligence.\n\n"
                    f"Do you have 10 minutes next week for an introductory conversation?"
                )

        elif category == "partnerships_ma":
            reasoning = f"Targeting {persona} at {comp} following partnership/M&A milestone. Focus on systems unification and co-selling."
            if persona == "technical":
                subject = f"Systems consolidation post-partnership at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I noticed {comp}'s recent strategic partnership announcement.\n\n"
                    f"Consolidating customer data across partner platforms often introduces data silos and integration overhead. "
                    f"We build automated data connectors that harmonize disparate platforms seamlessly.\n\n"
                    f"Would you be open to a brief technical chat next week?"
                )
            else:
                subject = f"Maximizing joint pipeline for {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"Congratulations on {comp}'s recent partnership announcement!\n\n"
                    f"Turning strategic alliances into revenue requires coordinated lead routing and automated co-selling workflows. "
                    f"We help GTM teams automate partner pipeline tracking and outreach.\n\n"
                    f"Are you open to a brief 10-minute exchange on accelerating partner revenue?"
                )

        else: # general_icp
            reasoning = f"Targeting {persona} at {comp} based on ICP profile (no recent signals). Focus on core operational efficiency."
            if persona == "technical":
                subject = f"Automating data workflows at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I'm reaching out because we help engineering leaders eliminate custom data integration scripts and fragile sync jobs.\n\n"
                    f"With {comp}'s scale, senior developers frequently lose hours debugging customer data pipelines between databases and business tools. "
                    f"We provide automated, zero-maintenance data pipelines.\n\n"
                    f"Would you be open to a brief 10-minute technical chat next week?"
                )
            elif persona == "sales_revenue":
                subject = f"Driving pipeline efficiency at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I'm reaching out because we help sales leaders eliminate administrative overhead and accelerate outbound pipeline.\n\n"
                    f"Given {comp}'s market segment, automating prospect enrichment and CRM data hygiene can unlock hours of high-value selling time per rep each week. "
                    f"We help revenue teams scale pipeline predictably.\n\n"
                    f"Are you open to a brief 10-minute exchange this Thursday?"
                )
            elif persona == "executive":
                subject = f"GTM operational leverage for {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I'm reaching out because we help leadership teams build scalable GTM infrastructure and automate revenue operations.\n\n"
                    f"At {comp}'s stage, driving efficient revenue without adding operational overhead is key to sustainable margins. "
                    f"We provide automated workflow solutions that give executive teams complete revenue predictability.\n\n"
                    f"Do you have 10 minutes next week for an introductory conversation?"
                )
            else:
                subject = f"Streamlining operations at {comp}"
                body = (
                    f"Hi {fn},\n\n"
                    f"I'm reaching out because we help growing companies automate routine business processes and CRM data workflows.\n\n"
                    f"We work with companies like {comp} to eliminate manual data entry and connect operational tools into unified workflows.\n\n"
                    f"Would you be open to a brief 10-minute chat next week?"
                )

        return {
            "subject": subject,
            "body": body,
            "reasoning": reasoning,
        }

    async def _generate_message(
        self, contact: Contact, signal: Optional[SignalEvent] = None, decision: Optional[Dict] = None,
        channel: str = "email", angle: str = ""
    ) -> Optional[Dict]:
        """
        Generate bespoke personalised email or LinkedIn request.
        Analyzes actual signal facts and prospect role persona.
        """
        signal_type = signal.signal_type if signal else "fallback"
        variant = await self._get_best_variant(signal_type)
        persona = self._classify_persona(contact.title)
        category = self._categorize_signal(signal)
        details = self._extract_signal_details(signal)

        sf_ver = getattr(contact, "salesforce_verification", None)
        sf_status = getattr(sf_ver, "verification_status", None) if sf_ver else None
        if sf_status == "verified":
            sf_context = f"Verified: {getattr(sf_ver, 'verification_summary', 'Credible evidence of Salesforce adoption')}"
        else:
            sf_context = "Not verified (do NOT claim or assume that company uses Salesforce unless explicitly mentioned in the signal)"

        if channel == "linkedin":
            system_prompt = f"""You are a senior B2B copywriter crafting a personalized LinkedIn connection request note.
Target Persona: {persona}
Signal Category: {category}

Rules:
- Keep the entire note under 280 characters so it fits the LinkedIn limit.
- Conversational, peer-to-peer tone.
- Do NOT generate a subject line (set "subject" to an empty string).
- Return valid JSON with "subject", "body", and "personalisation_reasoning".
"""
        else:
            system_prompt = f"""You are an elite B2B sales copywriter generating a bespoke, highly personalized 1-to-1 cold outreach email.
Prospect Persona: {persona} (tailor value proposition specifically to this function: technical reliability/data pipelines for engineering, pipeline velocity/rep ramp-time for sales, operational leverage/margins for executive).
Signal Category: {category}

Rules:
1. Grounding: Rely strictly on verified facts. Never fabricate funding amounts, unverified round types, dates, or technologies.
2. Structure (3 short paragraphs):
   - Hook: Direct, specific opening acknowledging their current situation or recent trigger signal without cliché openers like "I hope this email finds you well" or "quick question".
   - Value Bridge: Connect their situation to our GTM workflow automation platform tailored to their role ({persona}).
   - CTA: Low-friction, conversational call to action (e.g. asking for a 10-minute introductory exchange).
3. Length: Under 130 words.
4. Tone: Natural, peer-to-peer, concise.
5. Salesforce Context Policy: {sf_context}
6. Return valid JSON with exactly three fields: "subject", "body", and "personalisation_reasoning".
"""

        user_prompt = f"""Prospect Details:
- Name: {contact.first_name or 'there'} {contact.last_name or ''}
- Company: {contact.company or 'N/A'}
- Title: {contact.title or 'N/A'}
- Industry: {contact.industry or 'N/A'}
- Company Size: {contact.company_size or 'N/A'}

Trigger Signal:
- Category: {category}
- Details: {details}
- Signal Summary: {signal.summary if signal else 'None'}
"""

        use_sonnet = (contact.icp_score or 0) > 85

        try:
            response = await self.llm.complete(
                system=system_prompt,
                user=user_prompt,
                use_sonnet=use_sonnet,
                response_format={"subject": "string", "body": "string", "personalisation_reasoning": "string"},
            )
            subj = (response.get("subject") or "").strip()
            body = (response.get("body") or "").strip()
            reasoning = (response.get("personalisation_reasoning") or "").strip()
            if subj and body:
                return {
                    "subject": subj,
                    "body": body,
                    "variant_id": variant.id if variant else "default",
                    "channel": channel,
                    "traceability": {
                        "personalisation_reasoning": reasoning or f"Personalized for {persona} based on {category}.",
                        "selected_primary_signal": signal.signal_type.value if (signal and hasattr(signal.signal_type, "value")) else (signal.signal_type if signal else None),
                        "signal_category": category,
                        "signal_summary_used": details.get("headline") or details.get("description") or (signal.summary if signal else ""),
                        "referenced_signal_ids": [signal.id] if signal else [],
                    }
                }
        except Exception as e:
            logger.warning("LLM completion failed, falling back to deterministic personalization strategy", contact_email=contact.email, error=str(e))

        fallback = self._generate_deterministic_message(
            contact=contact,
            signal=signal,
            category=category,
            persona=persona,
            details=details,
            channel=channel
        )

        return {
            "subject": fallback["subject"],
            "body": fallback["body"],
            "variant_id": variant.id if variant else "default",
            "channel": channel,
            "traceability": {
                "personalisation_reasoning": fallback["reasoning"],
                "selected_primary_signal": signal.signal_type.value if (signal and hasattr(signal.signal_type, "value")) else (signal.signal_type if signal else None),
                "signal_category": category,
                "signal_summary_used": details.get("headline") or details.get("description") or (signal.summary if signal else ""),
                "referenced_signal_ids": [signal.id] if signal else [],
            }
        }

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

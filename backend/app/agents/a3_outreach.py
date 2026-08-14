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
    FunnelEvent, SignalType, PendingAction, ActionStatus, UserInput, OutreachDraft
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
        "subject": "Quick demo request: Salesforce & GTM automation for {company}",
        "body": "Hi {first_name},\n\nI noticed {company} recently triggered a stack change event. Integrating new tools into your existing Salesforce setup can be highly time-consuming.\n\nWe've built a GTM automation platform that automates CRM data enrichment. I'd love to run a quick 10-minute demo to show you how it works and see if it aligns with {company}'s needs.\n\nDo you have some time for a quick demo this week?\n\nBest,\n[Your Name]"
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
        "subject": "Reliable CRM & Salesforce Managed Services for {company}",
        "body": "Hi {first_name},\n\nMany {industry} firms with {company_size} employees struggle with the high cost and overhead of hiring full-time Salesforce administrators.\n\nWe offer CRM Managed Services—giving you access to certified Salesforce architects and admins on demand, for a fraction of the cost of a full-time hire.\n\nWould you be open to a brief chat about how we can support {company}'s CRM admin needs?\n\nBest,\n[Your Name]"
    },
    "General Sales Outreach": {
        "subject": "Streamlining CRM & GTM operations at {company}",
        "body": "Hi {first_name},\n\nI'm reaching out because we help companies in the {industry} sector automate their GTM operations and integrate cloud CRM systems.\n\nWe noticed {company} has been scaling, and wanted to see how you are currently handling Salesforce data enrichment and lead enrichment.\n\nDo you have 10 minutes for a brief introductory call?\n\nBest,\n[Your Name]"
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
            if not contact or not signal:
                skip_reasons["missing_contact_or_signal"] += 1
                logger.info("Outreach skipped: missing contact or signal in pair", pair=pair)
                continue

            # Enforce strict current-session checks
            if contact.user_input_id != active_session_id:
                skip_reasons["inactive_session"] += 1
                logger.info(
                    "Outreach skipped: contact belongs to historical session",
                    contact_id=contact.id,
                    contact_session_id=contact.user_input_id,
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

            # Verify one contact never receives two drafts for the same signal
            if signal and await self.draft_manager.has_pending_draft(contact.id, signal.id):
                skip_reasons["deduplicated"] += 1
                logger.info(
                    "Outreach skipped: pending draft already exists for this contact-signal pair",
                    contact_id=contact.id,
                    signal_id=signal.id
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
            if contact.do_not_contact:
                skip_reasons["do_not_contact"] += 1
                logger.info("Outreach skipped: contact marked do_not_contact", contact_id=contact.id)
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
        result = await self.db.execute(
            select(Contact, SignalEvent)
            .join(SignalEvent, SignalEvent.contact_id == Contact.id)
            .where(
                and_(
                    Contact.user_input_id == active_session_id,
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
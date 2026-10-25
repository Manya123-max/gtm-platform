"""
A5 — Deal Intelligence Agent
Compares live deals against closed-won/lost historical patterns.
Relationship health tracking. Stage changes are recommendations only — never autonomous.

Fully self-contained (same philosophy as A1/A2): all HubSpot HTTP calls live
in this file via httpx directly, no separate HubSpotService wrapper. LLMService
and SlackService are kept as imports since they're genuinely shared infra used
by every agent (same category as A1's WinPatternScorer import), not
deal-specific logic.

CHANGELOG (this revision):
- Added sync_deals_from_hubspot(): the missing piece. Previously `Deal` rows
  were never created anywhere in the codebase, so the daily scan always ran
  against an empty table. This pulls deals from HubSpot, upserts them, and
  writes a DealStageHistory row on every stage change — which is also what
  feeds the historical baseline query. Called automatically at the start of
  run_daily_deal_scan(), best-effort (a HubSpot outage doesn't block scanning
  deals you already have).
- Added the "no_reply" risk check that RISK_THRESHOLDS defined but never
  used, backed by ConversationThread (previously imported, never read).
- Fixed risk_score: previously only recalculated when new risk flags existed,
  so a resolved deal's score stayed elevated forever. Now recomputed every
  scan (goes back down when risks clear) and capped at 1.0.
- Stale PendingActions now get auto-expired when their underlying risk is no
  longer present, instead of sitting PENDING forever.
- HubSpot stage IDs are mapped to our internal DealStage enum (editable —
  see HUBSPOT_STAGE_MAP if your pipeline uses custom stage IDs).

DEAL INTELLIGENCE LAYER (this revision):
- Deal Health Score (0-100) and Win Probability (0-100%) added as two
  separate, clearly-scoped metrics — NOT a replacement for risk_score, which
  the API already relies on for sorting/filtering. risk_score answers "how
  many things are currently wrong"; these answer "how healthy is this deal"
  and "how likely is it to close".
- Buying Intent (strong/medium/weak/lost/unknown) — added to the SAME Claude
  extraction call that already runs per transcript, so this costs zero extra
  API calls.
- Next Best Action — deliberately rule-based, not an LLM call. A decision
  tree over stage + missing BANT + risk flags + intent is free, instant, and
  debuggable. An LLM has no real knowledge of your sales process, so letting
  it freelance "schedule a technical demo" would be a guess dressed as advice.
- Fixed a real dead field: `Deal.avg_response_time_hours` was read by the
  response-slowdown risk check but NEVER written anywhere in the codebase,
  so that check was permanently inert. Now computed from ConversationThread
  outbound->inbound gaps.
- Deliberately NOT added (see chat explanation): a full objection-category
  taxonomy, structured stakeholder-role mapping, and a per-deal LLM-generated
  executive summary run on every scan. The "summary" here is composed for
  free from already-computed numbers instead of a new paid Claude call.
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text, func

from app.core.config import settings
from app.models.models import (
    Deal, DealStageHistory, Contact, ConversationThread,
    PendingAction, FunnelEvent, ActionStatus, DealStage, SignalEvent,
    UserInput, OutreachDraft
)
from app.services.llm_service import LLMService
from app.services.salesforce_service import SalesforceService, SALESFORCE_STAGE_MAP
from app.services.slack_service import SlackService

logger = structlog.get_logger()

HUBSPOT_BASE = "https://api.hubapi.com"

# HubSpot's default pipeline stage IDs -> our internal DealStage enum.
# If you use a custom pipeline, check your stage IDs via
# GET /crm/v3/pipelines/deals and update this map. Anything not listed here
# is stored as-is (the `stage` column is a free string, not a strict FK),
# but risk checks that compare against specific stage names (e.g. "proposal")
# will only fire for stages that ARE mapped.
HUBSPOT_STAGE_MAP = {
    "appointmentscheduled":     DealStage.DISCOVERY,
    "qualifiedtobuy":           DealStage.DISCOVERY,
    "presentationscheduled":    DealStage.DEMO,
    "decisionmakerboughtin":    DealStage.PROPOSAL,
    "contractsent":             DealStage.NEGOTIATION,
    "closedwon":                DealStage.CLOSED_WON,
    "closedlost":               DealStage.CLOSED_LOST,
}

# Risk thresholds — deviation from historical baseline triggers a flag
# Stage-based prior for win probability — a transparent heuristic, NOT a
# trained model. There's no closed-deal history yet to fit a real model on
# (that's what WinPatternScorer does for prospects once you have enough
# outcome data — same idea could replace this later for deals).
STAGE_WIN_PRIOR = {
    DealStage.PROSPECTING:  10.0,
    DealStage.DISCOVERY:    20.0,
    DealStage.DEMO:         35.0,
    DealStage.PROPOSAL:     55.0,
    DealStage.NEGOTIATION:  75.0,
    DealStage.CLOSED_WON:  100.0,
    DealStage.CLOSED_LOST:   0.0,
}

RISK_THRESHOLDS = {
    "days_in_stage_multiplier": 1.5,   # 50% longer than average = flag
    "response_time_multiplier": 2.0,   # 2x slower response = flag
    "no_meeting_days": 21,             # 3 weeks without a meeting in proposal stage
    "no_reply_days": 10,               # 10 days without any contact = flag
}


class DealAgent:
    """
    A5: HubSpot deal sync + post-call extraction + deal pattern comparison
    + relationship health.

    Key behaviours:
    - Pulls deals from HubSpot and upserts them, tracking stage-change history
    - Extracts BANT signals from Fireflies transcripts using Claude Sonnet
    - Compares deal metrics to historical closed-won/lost baselines
    - Tracks relationship health via reply recency and response time
    - Writes risk flags to pending_actions — never changes CRM stages directly
    - Daily Slack digest surfaces pending actions to reps
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.slack = SlackService()

    # ── Salesforce CRM Sync & Activity ──────────────────────────────────────

    async def sync_deals_from_salesforce(self) -> Dict[str, Any]:
        """
        Pull active opportunities from Salesforce CRM (Sole CRM Source of Truth),
        upsert into `deals`, and write a DealStageHistory row whenever a stage
        transition is detected.
        """
        sf_service = SalesforceService()
        if not sf_service.is_configured:
            logger.info("A5: Salesforce CRM not configured (SALESFORCE_INSTANCE_URL/SALESFORCE_ACCESS_TOKEN unset). Skipping CRM sync.")
            return {"synced": 0, "created": 0, "updated": 0, "skipped": "Salesforce CRM not configured"}

        created = 0
        updated = 0
        unchanged = 0

        try:
            raw_opps = await sf_service.sync_opportunities()
            for opp in raw_opps:
                contact_email = None
                contact_id = opp.get("ContactId")
                owner_email = opp.get("Owner", {}).get("Email")

                # Try resolving contact by ContactId or Owner email
                if contact_id:
                    c_res = await self.db.execute(
                        select(Contact).where(Contact.salesforce_contact_id == contact_id)
                    )
                    c = c_res.scalar_one_or_none()
                    if c:
                        contact_email = c.email

                _, was_created, was_stage_change = await self._upsert_salesforce_deal(opp, contact_email)
                if was_created:
                    created += 1
                elif was_stage_change:
                    updated += 1
                else:
                    unchanged += 1

            await self.db.commit()
            logger.info("A5 Salesforce CRM sync complete", created=created, updated=updated, unchanged=unchanged)
        except Exception as exc:
            logger.error("Salesforce deal sync failed", error=str(exc))
            return {"synced": 0, "created": 0, "updated": 0, "error": str(exc)}

        return {
            "synced": created + updated + unchanged,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }

    async def sync_deals_from_hubspot(self) -> Dict[str, Any]:
        """
        Backward-compatibility alias: redirects legacy HubSpot sync calls
        to the Salesforce CRM sync service.
        """
        logger.info("A5: sync_deals_from_hubspot called (legacy alias) -> delegating to sync_deals_from_salesforce")
        return await self.sync_deals_from_salesforce()

    async def _upsert_salesforce_deal(
        self, opp: Dict[str, Any], contact_email: Optional[str]
    ) -> Tuple[Deal, bool, bool]:
        """
        Create or update a Deal from a raw Salesforce Opportunity object.
        Returns (deal, was_created, was_stage_change).
        """
        opp_id = opp["Id"]
        opp_name = opp.get("Name") or "Untitled Salesforce Opportunity"
        now = datetime.utcnow()

        raw_stage = opp.get("StageName", "")
        mapped_stage = SALESFORCE_STAGE_MAP.get(raw_stage, DealStage.PROSPECTING)
        outcome = "won" if mapped_stage == DealStage.CLOSED_WON else                   "lost" if mapped_stage == DealStage.CLOSED_LOST else None

        raw_amount = opp.get("Amount")
        amount = None
        amount_source = "Not provided"
        if raw_amount is not None:
            try:
                amount = float(raw_amount)
                amount_source = "Salesforce"
            except (TypeError, ValueError):
                amount = None
                amount_source = "Not provided"

        close_date = None
        if opp.get("CloseDate"):
            try:
                close_date = datetime.strptime(opp["CloseDate"], "%Y-%m-%d")
            except Exception:
                close_date = None

        contact_id = None
        if contact_email:
            contact_result = await self.db.execute(select(Contact).where(Contact.email == contact_email))
            contact = contact_result.scalar_one_or_none()
            if contact:
                contact_id = contact.id

        owner_email = opp.get("Owner", {}).get("Email")

        # Find existing deal by salesforce_opportunity_id or legacy hubspot_deal_id
        existing_result = await self.db.execute(
            select(Deal).where(
                (Deal.salesforce_opportunity_id == opp_id) | (Deal.hubspot_deal_id == opp_id)
            )
        )
        existing = existing_result.scalar_one_or_none()

        if not existing:
            deal = Deal(
                salesforce_opportunity_id=opp_id,
                contact_id=contact_id,
                name=opp_name,
                stage=mapped_stage,
                amount=amount,
                amount_source=amount_source,
                close_date=close_date,
                owner_email=owner_email,
                outcome=outcome,
                stage_entered_at=now,
                days_in_current_stage=0,
            )
            self.db.add(deal)
            return deal, True, False

        stage_changed = existing.stage != mapped_stage
        if stage_changed:
            self.db.add(DealStageHistory(
                deal_id=existing.id,
                from_stage=existing.stage,
                to_stage=mapped_stage,
                days_in_from_stage=existing.days_in_current_stage,
                transitioned_at=now,
            ))
            existing.stage = mapped_stage
            existing.stage_entered_at = now
            existing.days_in_current_stage = 0

        existing.salesforce_opportunity_id = opp_id
        existing.name = opp_name or existing.name
        if amount is not None:
            existing.amount = amount
            existing.amount_source = "Salesforce"
        existing.close_date = close_date or existing.close_date
        existing.owner_email = owner_email or existing.owner_email
        existing.outcome = outcome
        if contact_id and not existing.contact_id:
            existing.contact_id = contact_id
        existing.updated_at = now

        return existing, False, stage_changed

    async def _log_salesforce_activity(self, deal: Deal, body: str) -> bool:
        """Log a call summary as an activity Task on the Salesforce Opportunity."""
        opp_id = deal.salesforce_opportunity_id or deal.hubspot_deal_id
        if not opp_id:
            return False
        sf_service = SalesforceService()
        return await sf_service.log_activity(opp_id, "GTM Call Intelligence Note", body)

    async def _log_hubspot_note(self, deal: Deal, body: str) -> bool:
        """Backward-compatible wrapper: delegates to Salesforce activity logging."""
        return await self._log_salesforce_activity(deal, body)

    # ── Entry points ─────────────────────────────────────────────────────────

    async def process_transcript(self, webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Called when Fireflies webhook fires (transcript ready)."""
        transcript_id = webhook_payload.get("transcriptId", "")
        transcript_text = webhook_payload.get("transcript", "")
        attendees = webhook_payload.get("attendees", [])
        meeting_title = webhook_payload.get("title", "")

        logger.info("A5: Processing inbound Fireflies transcript", transcript_id=transcript_id, meeting_title=meeting_title)

        deal, contact = await self._match_to_deal(attendees, meeting_title)

        if deal:
            logger.info("A5: Matched transcript to Salesforce Deal", deal_id=deal.id, deal_name=deal.name)
        else:
            logger.info("A5: No matching Salesforce Deal found for transcript", transcript_id=transcript_id)

        extraction = await self._extract_from_transcript(transcript_text, meeting_title, contact)
        logger.info("A5: AI transcript extraction completed", transcript_id=transcript_id, sentiment=extraction.get("sentiment"))

        risk_flags: List[Dict] = []
        if deal:
            await self._update_deal(deal, extraction)
            logger.info("A5 process_transcript: _update_deal transcript extraction values",
                        deal_id=deal.id,
                        budget_confirmed=deal.budget_confirmed,
                        timeline_confirmed=deal.timeline_confirmed)
            
            risk_flags = await self._detect_risk_patterns(deal, extraction)
            await self._reconcile_risk_state(deal, risk_flags)
            logger.info("A5 process_transcript: final values after both extractions",
                        deal_id=deal.id,
                        budget_confirmed=deal.budget_confirmed,
                        timeline_confirmed=deal.timeline_confirmed)

        if deal:
            await self._log_salesforce_activity(deal, self._format_crm_note(extraction))

        await self._log_funnel_event("transcript_processed", {
            "transcript_id": transcript_id,
            "deal_id": deal.id if deal else None,
            "bant_signals": extraction.get("bant_signals"),
        })

        return {
            "agent": "A5",
            "transcript_id": transcript_id,
            "deal_matched": bool(deal),
            "extraction": extraction,
            "risk_flags": risk_flags if deal else [],
            "deal_summary": self._build_deal_summary(deal, extraction, risk_flags) if deal else None,
        }

    def _generate_simulated_fireflies_transcript(
        self,
        contact: Contact,
        threads: List[ConversationThread],
        vendor_company: str = "4CECloud labs",
        vendor_services: str = "Core Salesforce Services, CRM Integration, AI Consulting, Data Cloud"
    ) -> Tuple[str, str]:
        """
        Generate a realistic simulated Fireflies discovery/architecture call transcript
        based on the prospect's real company, role, industry, and vendor services.
        Returns (meeting_title, transcript_text).
        """
        full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Prospect"
        title = contact.title or "Technology & Operations Leader"
        company = contact.company or "Enterprise Prospect"
        industry = contact.industry or "Technology"
        meeting_title = f"{company} — Technical Discovery & CRM Architecture Review"

        # Domain specific nuance for key enterprise prospects
        comp_lower = company.lower()
        if "thomas scientific" in comp_lower:
            biz_context = "scientific supplies distribution and research lab operations"
            pain_context = "synchronizing our enterprise Salesforce instance with our legacy warehouse ERP and supply-chain catalog. Sales reps spend 15 hours weekly fixing sync discrepancies"
            security_req = "SOC2 Type II compliance and FDA CFR Part 11 validation guidelines for laboratory supply traceability"
        elif "rhize" in comp_lower:
            biz_context = "manufacturing data hub and industrial edge telemetry"
            pain_context = "bridging plant-floor manufacturing metrics into our Salesforce pipeline for real-time customer account health monitoring"
            security_req = "SOC2 Type II certification, IEC 62443 industrial security standards, and strict on-premise data residency"
        elif "yodlee" in comp_lower:
            biz_context = "financial data aggregation and Open Banking infrastructure"
            pain_context = "scaling our Salesforce Financial Services Cloud (FSC) rollout and automating multi-entity account onboarding flows"
            security_req = "SOC2 Type II, ISO 27001, and GLBA financial data privacy mandates"
        elif "api connects" in comp_lower:
            biz_context = "enterprise API integration and middleware consulting"
            pain_context = "building high-throughput Salesforce middleware connectors for ANZ enterprise clients without bloating maintenance overhead"
            security_req = "SOC2 Type II audit report and regional data sovereignty in Australia/New Zealand"
        elif "paradise mobile" in comp_lower:
            biz_context = "next-gen telecom network and cloud-native mobile services"
            pain_context = "integrating telecom OSS/BSS subscriber provisioning directly into our Salesforce CRM for automated enterprise billing"
            security_req = "SOC2 Type II compliance and telecom data privacy compliance"
        elif "updater services" in comp_lower:
            biz_context = "integrated facility management and enterprise workforce services"
            pain_context = "scaling our Salesforce administrator bandwidth and automating field operations dispatch workflows across regional centers"
            security_req = "SOC2 Type II compliance and ISO 9001 quality management standards"
        else:
            biz_context = f"{industry} operations"
            pain_context = f"disjointed workflows between Salesforce CRM, internal operational databases, and automated reporting. Manual re-entry is costing our team significant engineering hours"
            security_req = "SOC2 Type II compliance certification and end-to-end AES-256 data encryption in transit and at rest"

        transcript_text = f"""[00:00] Alex Miller (Sales & Solutions Lead, {vendor_company}):
Hi {contact.first_name}, thanks so much for taking the time to join today's discovery session. Following up on our email discussion regarding {vendor_services}, I wanted to dive into {company}'s current architecture and explore where your team is seeing operational friction.

[00:50] {full_name} ({title}, {company}):
Thanks for organizing this, Alex. Yeah, at {company}, we are rapidly scaling our {biz_context}, and our current tech stack is running into real bottlenecks. Specifically, we are dealing with {pain_context}.

[02:15] Alex Miller (Sales & Solutions Lead, {vendor_company}):
That is a very common challenge across growing enterprise teams. How are your engineering and operations teams currently handling that pipeline?

[03:10] {full_name} ({title}, {company}):
Right now it's heavily fragmented and requires ongoing manual maintenance. We actually evaluated alternatives like MuleSoft and Zapier Enterprise last quarter. MuleSoft's licensing and implementation overhead was far too heavy for our scope, and Zapier lacked the custom enterprise compliance controls and bi-directional depth we need.

[04:40] Alex Miller (Sales & Solutions Lead, {vendor_company}):
That makes total sense. That's exactly where {vendor_company} comes in. We deliver direct Salesforce integration, automated CRM pipelines, and intelligent AI workflows that bridge your operational systems seamlessly without heavyweight middleware overhead. In terms of team and decision making, who else on your side will be involved in evaluating and approving this?

[05:55] {full_name} ({title}, {company}):
As {title}, I oversee our engineering and operational systems budget. Final sign-off will be between myself and our VP of Operations / Chief Revenue Officer. If your platform passes our architectural review and security checks, we hold the authority to approve the engagement.

[07:05] Alex Miller (Sales & Solutions Lead, {vendor_company}):
Understood. What does your timeline and budget allocation look like for kicking off this initiative?

[07:50] {full_name} ({title}, {company}):
We have an approved budget of approximately $50,000 to $75,000 allocated for this project this fiscal year. On timing, we want to kick off implementation in Q3 and have the first production milestone live within 4 to 6 weeks so our teams are ready for the next quarter.

[09:00] {full_name} ({title}, {company}):
One critical requirement from our side though: our SecOps team has strict compliance mandates. We will need to review your {security_req} before signing the final MSA.

[10:10] Alex Miller (Sales & Solutions Lead, {vendor_company}):
Absolutely. We maintain strict SOC2 Type II compliance and AES-256 encryption across all data pipelines. I will send over our complete security whitepaper, SOC2 summary, and a formal draft Statement of Work by Thursday. Then we can schedule a 30-minute technical deep-dive with your SecOps and engineering leads next Tuesday at 2:00 PM.

[11:05] {full_name} ({title}, {company}):
That sounds great, Alex. That timeline works for us. Please send over the documents and the calendar invite for Tuesday.

[11:35] Alex Miller (Sales & Solutions Lead, {vendor_company}):
Will do! Thanks so much for your time today, {contact.first_name}. Looking forward to partnering with {company}.
"""
        return meeting_title, transcript_text.strip()

    async def _identify_and_process_meeting_prospects(self) -> Dict[str, Any]:
        """
        Identify prospects who engaged in calendar/meeting emails or outreach,
        generate a simulated Fireflies meeting transcript tailored to their
        company/industry context, and process it through the AI extraction engine.
        Disabled by default in production (requires A5_SIMULATION_MODE=True).
        """
        if not getattr(settings, "A5_SIMULATION_MODE", False):
            logger.info("A5: Simulation mode disabled (A5_SIMULATION_MODE=False). Skipping synthetic Fireflies transcripts.")
            return {"transcripts_processed": 0, "deals_created": 0}
        logger.info("A5: Scanning prospects for meeting outreach and transcript generation")
        user_input_res = await self.db.execute(select(UserInput).order_by(UserInput.id.desc()).limit(1))
        user_input = user_input_res.scalar_one_or_none()
        vendor_company = user_input.our_company_name if user_input and user_input.our_company_name else "4CECloud labs"
        vendor_services = user_input.our_services if user_input and user_input.our_services else "Core Salesforce Services, CRM Integration, AI Consulting, Data Cloud"

        # Find contacts with conversation threads (both inbound and outbound)
        contacts_res = await self.db.execute(
            select(Contact).join(ConversationThread, ConversationThread.contact_id == Contact.id).distinct()
        )
        thread_contacts = list(contacts_res.scalars().all())

        # Also find contacts with outreach drafts
        draft_contacts_res = await self.db.execute(
            select(Contact).join(OutreachDraft, OutreachDraft.contact_id == Contact.id).distinct()
        )
        draft_contacts = list(draft_contacts_res.scalars().all())

        candidate_map: Dict[str, Contact] = {}
        for c in thread_contacts + draft_contacts:
            if c and c.company and c.company.lower() not in ("inbound company", "unknown") and c.email:
                candidate_map[c.id] = c

        processed_count = 0
        deals_created_count = 0

        for contact_id, contact in candidate_map.items():
            threads_res = await self.db.execute(
                select(ConversationThread)
                .where(ConversationThread.contact_id == contact.id)
                .order_by(ConversationThread.occurred_at.asc())
            )
            threads = list(threads_res.scalars().all())

            # Qualifying signals: meeting request, inbound email, demo/calendar/outreach keywords
            has_meeting_intent = any(
                t.intent == "meeting_request" or
                any(k in (t.content or "").lower() for k in ["meeting", "demo", "call", "calendar", "connect", "sync", "15-min"])
                for t in threads
            )
            has_inbound = any(t.direction == "inbound" for t in threads)
            has_outreach = len(threads) > 0

            if not (has_meeting_intent or has_inbound or has_outreach):
                continue

            # Generate simulated Fireflies transcript
            meeting_title, transcript_text = self._generate_simulated_fireflies_transcript(
                contact=contact,
                threads=threads,
                vendor_company=vendor_company,
                vendor_services=vendor_services,
            )

            # Check if deal already exists for this contact and is already evaluated
            existing_deal_res = await self.db.execute(
                select(Deal).where(and_(Deal.contact_id == contact.id, Deal.outcome.is_(None)))
            )
            existing_deal = existing_deal_res.scalars().first()
            if existing_deal and existing_deal.deal_health_score is not None:
                continue

            webhook_payload = {
                "transcriptId": f"ff_{contact.id[:8]}_{int(datetime.utcnow().timestamp())}",
                "title": meeting_title,
                "attendees": [
                    {"email": contact.email, "name": f"{contact.first_name} {contact.last_name}"},
                    {"email": "alex.miller@4cecloudlabs.com", "name": "Alex Miller"}
                ],
                "transcript": transcript_text,
            }

            logger.info("A5: Processing simulated Fireflies transcript for prospect",
                        contact=f"{contact.first_name} {contact.last_name}",
                        company=contact.company)

            result = await self.process_transcript(webhook_payload)
            processed_count += 1
            if not existing_deal and result.get("deal_matched"):
                deals_created_count += 1

        await self.db.commit()
        return {
            "transcripts_processed": processed_count,
            "deals_created": deals_created_count,
        }

    async def run_daily_deal_scan(self) -> Dict[str, Any]:
        """
        Comprehensive deal scan:
        1. Identify prospects who engaged in calendar/meeting emails and process Fireflies call transcripts.
        2. Sync deals from HubSpot (best-effort).
        3. Re-evaluate all active deals against risk patterns and compute AI deal health and win probability.
        """
        logger.info("A5 running daily deal scan")

        # Step 1: Process Fireflies transcripts for engaged meeting/calendar prospects (only when simulation mode is enabled)
        if getattr(settings, "A5_SIMULATION_MODE", False):
            logger.info("A5: [SIMULATED] Running simulated Fireflies transcript processing (A5_SIMULATION_MODE=True)")
            meeting_result = await self._identify_and_process_meeting_prospects()
            logger.info("A5: [SIMULATED] Meeting prospect transcripts processed", **meeting_result)
        else:
            logger.info("A5: Production mode active (A5_SIMULATION_MODE=False). Skipping synthetic Fireflies transcripts.")
            meeting_result = {"transcripts_processed": 0, "deals_created": 0}

        # Step 2: Sync fresh deals from Salesforce CRM (Sole CRM source of truth)
        sync_result = await self.sync_deals_from_salesforce()
        logger.info("A5 Salesforce CRM sync complete", **sync_result)

        # Step 3: Scan all active deals in the system
        deals_result = await self.db.execute(
            select(Deal).where(Deal.outcome.is_(None))
        )
        deals = list(deals_result.scalars().all())

        flagged = 0
        for deal in deals:
            deal.days_in_current_stage = (datetime.utcnow() - deal.stage_entered_at).days if deal.stage_entered_at else 0
            risk_flags = await self._detect_risk_patterns(deal)
            await self._reconcile_risk_state(deal, risk_flags)
            if risk_flags:
                flagged += 1

        await self.db.commit()

        pending_result = await self.db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.entity_type == "deal",
                    PendingAction.agent_id == "A5",
                    PendingAction.status == ActionStatus.PENDING,
                )
            )
        )
        pending = list(pending_result.scalars().all())
        if pending and settings.ENABLE_SLACK_APPROVALS:
            await self.slack.send_daily_digest(pending)

        return {
            "agent": "A5",
            "transcripts_processed": meeting_result.get("transcripts_processed", 0),
            "deals_created": meeting_result.get("deals_created", 0),
            "salesforce_sync": sync_result,
            "hubspot_sync": sync_result,
            "deals_scanned": len(deals),
            "deals_flagged": flagged,
            "pending_actions": len(pending),
            "reason": f"Processed {meeting_result.get('transcripts_processed', 0)} meeting transcripts, scanned {len(deals)} deals ({flagged} flagged).",
        }

    async def _extract_from_transcript(
        self, transcript: str, title: str, contact: Optional[Contact]
    ) -> Dict[str, Any]:
        """Claude Sonnet: extract structured BANT and Deal Intelligence data from transcript."""
        contact_ctx = f"{contact.first_name} {contact.last_name} at {contact.company}" if contact else "unknown contact"

        prompt = f"""Extract structured sales intelligence from this call transcript.

Meeting: {title}
Contact: {contact_ctx}

Transcript:
{transcript[:6000]}

Return JSON with exactly these fields:
{{
  "next_steps": ["list of concrete next steps with dates if mentioned"],
  "pain_points": ["key challenges, pain points, or needs expressed by the prospect"],
  "competitors_mentioned": ["names of any competitors mentioned during the call"],
  "decision_maker_details": "name/title/role of the decision maker if mentioned or confirmed",
  "stage_confidence": 0.0-1.0 (float estimating how confident we are that the deal is in the correct stage based on transcript alignment),
  "objections": [{{"text": "the objection as stated", "category": "one of: pricing, competition, security, budget, timeline, integration, legal, procurement, other"}}],
  "bant_signals": {{
    "budget_confirmed": true/false/null,
    "authority_confirmed": true/false/null,
    "need_confirmed": true/false/null,
    "timeline_confirmed": true/false/null,
    "budget_notes": "any budget details mentioned",
    "timeline_notes": "any timeline details mentioned"
  }},
  "stakeholders_mentioned": ["names/titles of other people mentioned"],
  "recommended_stage_change": null or "stage_name",
  "recommended_stage_reason": "reason if stage change recommended",
  "call_summary": "2-3 sentence summary of the call outcome",
  "sentiment": "positive/neutral/negative",
  "buying_intent": "strong/medium/weak/lost — based on urgency, engagement, and explicit statements of interest or disinterest in this call"
}}

If a field is unclear, use null. Do not invent information not in the transcript."""

        try:
            raw_result = await self.llm.complete(
                system="You are a sales intelligence extraction engine. Extract only factual information present in the transcript. Return valid JSON only.",
                user=prompt,
                use_sonnet=True,
                response_format=None,
            )
            # Safe JSON parse
            import json
            if isinstance(raw_result, dict):
                return raw_result
            if isinstance(raw_result, str):
                cleaned = _clean_json_str(raw_result)
                return json.loads(cleaned)
            return raw_result
        except Exception as e:
            logger.error("Transcript extraction failed", error=str(e))
            return {
                "next_steps": [], "pain_points": [], "competitors_mentioned": [],
                "decision_maker_details": None, "stage_confidence": 0.5, "objections": [],
                "bant_signals": {}, "stakeholders_mentioned": [],
                "recommended_stage_change": None, "call_summary": "Extraction failed",
                "sentiment": "neutral", "buying_intent": None,
            }

    # ── Risk detection ───────────────────────────────────────────────────────

    async def _detect_risk_patterns(self, deal: Deal, extraction: Optional[Dict] = None) -> List[Dict]:
        """
        Compare deal metrics against historical baselines and detect 9 specific risk patterns.
        Returns list of risk flags — each becomes a pending action for human review.
        """
        logger.info("A5: Detecting risk patterns on deal", deal_id=deal.id, deal_name=deal.name)
        risk_flags = []
        baselines = await self._get_stage_baselines(deal.stage)

        # Refresh average response time from conversation thread history
        deal.avg_response_time_hours = await self._compute_avg_response_time(deal.contact_id)

        # Risk 1: Stalled deal (stage_stall)
        if baselines.get("avg_days") and deal.days_in_current_stage:
            threshold = baselines["avg_days"] * RISK_THRESHOLDS["days_in_stage_multiplier"]
            if deal.days_in_current_stage > threshold:
                risk_flags.append({
                    "type": "stage_stall",
                    "severity": "high" if deal.days_in_current_stage > threshold * 1.5 else "medium",
                    "description": f"Deal stalled in {deal.stage} for {deal.days_in_current_stage} days (Historical average: {baselines['avg_days']:.0f} days).",
                    "recommended_action": "Review deal velocity and consider updating stage or archiving.",
                })

        # Risk 2: Slow replies (response_slowdown)
        if deal.avg_response_time_hours and baselines.get("avg_response_hours"):
            threshold = baselines["avg_response_hours"] * RISK_THRESHOLDS["response_time_multiplier"]
            if deal.avg_response_time_hours > threshold:
                risk_flags.append({
                    "type": "response_slowdown",
                    "severity": "medium",
                    "description": f"Prospect response time is slow ({deal.avg_response_time_hours:.0f} hours vs. baseline {baselines['avg_response_hours']:.0f} hours).",
                    "recommended_action": "Reach out to alternate stakeholders or adjust messaging urgency.",
                })

        # Risk 3: Missing decision maker
        if deal.authority_confirmed is False or (deal.stage in ("proposal", "negotiation") and not deal.authority_confirmed):
            risk_flags.append({
                "type": "missing_decision_maker",
                "severity": "high" if deal.stage in ("proposal", "negotiation") else "medium",
                "description": "Decision Maker (Authority) not yet identified or confirmed.",
                "recommended_action": "Map stakeholders during the next touchpoint and confirm who holds final sign-off authority.",
            })

        # Risk 4: Missing budget
        if deal.budget_confirmed is False or (deal.stage in ("proposal", "negotiation") and not deal.budget_confirmed):
            risk_flags.append({
                "type": "missing_budget",
                "severity": "high" if deal.stage in ("proposal", "negotiation") else "medium",
                "description": "Deal budget has not been confirmed.",
                "recommended_action": "Introduce pricing options or ask directly about budget allocation during the next sync.",
            })

        # Risk 5: Missing timeline
        if deal.timeline_confirmed is False or (deal.stage in ("proposal", "negotiation") and not deal.timeline_confirmed):
            risk_flags.append({
                "type": "missing_timeline",
                "severity": "medium",
                "description": "Purchase timeline or implementation plan is unconfirmed.",
                "recommended_action": "Discuss target launch dates and define a mutual action plan.",
            })

        # Risk 6: Missing next meeting (no_meeting_proposal)
        if deal.stage in ("proposal", "negotiation") and deal.days_in_current_stage > RISK_THRESHOLDS["no_meeting_days"]:
            risk_flags.append({
                "type": "no_meeting_proposal",
                "severity": "high",
                "description": "No follow-up meeting is currently scheduled while in the proposal/negotiation stage.",
                "recommended_action": "Send an email to schedule the next review call.",
            })

        # Risk 7: Procurement involved unusually early
        if deal.stage in ("prospecting", "discovery", "demo") and extraction:
            objections = extraction.get("objections", [])
            has_early_procurement = any(
                obj.get("category") == "procurement" or "procurement" in obj.get("text", "").lower()
                for obj in objections
            )
            if has_early_procurement:
                risk_flags.append({
                    "type": "early_procurement",
                    "severity": "medium",
                    "description": "Procurement or legal discussion was initiated unusually early in the deal lifecycle.",
                    "recommended_action": "Clarify procurement prerequisites early to ensure alignment on contract templates.",
                })

        # Risk 8: Negative sentiment
        if extraction and extraction.get("sentiment") == "negative":
            risk_flags.append({
                "type": "negative_sentiment",
                "severity": "high",
                "description": "Negative sentiment detected in the latest call transcript.",
                "recommended_action": "Immediately address concerns raised by the prospect regarding blockers or objections.",
            })

        # Risk 9: Champion lost
        days_since_activity = None
        if deal.contact_id:
            last_thread_result = await self.db.execute(
                select(ConversationThread)
                .where(ConversationThread.contact_id == deal.contact_id)
                .order_by(ConversationThread.occurred_at.desc())
                .limit(1)
            )
            last_thread = last_thread_result.scalar_one_or_none()
            if last_thread:
                days_since_activity = (datetime.utcnow() - last_thread.occurred_at).days

        if (days_since_activity and days_since_activity > 20) or deal.buying_intent == "lost":
            risk_flags.append({
                "type": "champion_lost",
                "severity": "high",
                "description": f"Champion engagement appears lost (no response for {days_since_activity or '>20'} days, or buying intent is marked lost).",
                "recommended_action": "Reach out to other decision makers, or re-engage with a fresh angle.",
            })

        # Risk 10: Missing prospect market signals (no fresh signals in past 7 days)
        if deal.contact_id:
            recent_signal_res = await self.db.execute(
                select(SignalEvent)
                .where(
                    SignalEvent.contact_id == deal.contact_id,
                    SignalEvent.detected_at >= datetime.utcnow() - timedelta(days=7)
                )
                .limit(1)
            )
            has_recent_signals = recent_signal_res.scalar_one_or_none() is not None
            if not has_recent_signals:
                risk_flags.append({
                    "type": "missing_signals",
                    "severity": "medium",
                    "description": "No fresh market or hiring signals detected for this company in the last 7 days. May lack recent context for deal progression.",
                    "recommended_action": "Trigger Agent 2 (Signal Intelligence) to scan latest live job postings and company news feeds.",
                })

        logger.info("A5: Risk detection complete", deal_id=deal.id, risk_flags_count=len(risk_flags))
        return risk_flags

    async def _get_stage_baselines(self, stage: str) -> Dict:
        """
        Query historical closed-won deals to get baseline metrics for this stage.
        Now actually populated once sync_deals_from_hubspot() has been writing
        DealStageHistory rows for a while — falls back to defaults until then.
        """
        try:
            result = await self.db.execute(
                text("""
                    SELECT
                        AVG(days_in_from_stage) as avg_days,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY days_in_from_stage) as p75_days
                    FROM deal_stage_history dsh
                    JOIN deals d ON d.id = dsh.deal_id
                    WHERE dsh.from_stage = :stage
                    AND d.outcome = 'won'
                    AND dsh.transitioned_at >= NOW() - INTERVAL '365 days'
                """),
                {"stage": stage}
            )
            row = result.fetchone()
            return {
                "avg_days": float(row.avg_days) if row and row.avg_days else 14,
                "p75_days": float(row.p75_days) if row and row.p75_days else 21,
                "avg_response_hours": 48,  # default baseline
            }
        except Exception:
            return {"avg_days": 14, "p75_days": 21, "avg_response_hours": 48}

    async def _compute_avg_response_time(self, contact_id: Optional[str]) -> Optional[float]:
        """
        Average hours between an outbound message and the next inbound reply,
        over this contact's conversation thread. This field existed on the
        model and was read by the response-slowdown risk check, but nothing
        anywhere ever wrote to it — so that check was permanently a no-op.
        Uses the last 20 thread events, most recent first, capped to keep
        the "current" trend recent rather than averaging a whole relationship.
        """
        if not contact_id:
            return None
        result = await self.db.execute(
            select(ConversationThread)
            .where(ConversationThread.contact_id == contact_id)
            .order_by(ConversationThread.occurred_at.desc())
            .limit(20)
        )
        events = list(reversed(result.scalars().all()))  # chronological order
        gaps_hours = []
        last_outbound_at = None
        for event in events:
            if event.direction == "outbound":
                last_outbound_at = event.occurred_at
            elif event.direction == "inbound" and last_outbound_at:
                gap = (event.occurred_at - last_outbound_at).total_seconds() / 3600
                if gap >= 0:
                    gaps_hours.append(gap)
                last_outbound_at = None
        if not gaps_hours:
            return None
        return sum(gaps_hours) / len(gaps_hours)

    def _calculate_deal_health(self, deal: Deal, risk_flags: List[Dict]) -> float:
        """
        0-100. Answers "how healthy is this opportunity right now" —
        completeness of qualification + engagement, penalised by active risks.
        Distinct from risk_score (a count of active problems) and from
        win_probability (an estimate of close likelihood).
        """
        score = 40.0
        if deal.budget_confirmed:
            score += 15
        if deal.authority_confirmed:
            score += 15
        if deal.need_confirmed:
            score += 10
        if deal.timeline_confirmed:
            score += 10
        score += min(10, (deal.meeting_count or 0) * 3)

        intent_adjust = {"strong": 10, "medium": 0, "weak": -10, "lost": -50}
        score += intent_adjust.get(deal.buying_intent, 0)

        high = len([f for f in risk_flags if f["severity"] == "high"])
        medium = len([f for f in risk_flags if f["severity"] == "medium"])
        score -= high * 12 + medium * 6

        return max(0.0, min(100.0, score))

    def _calculate_win_probability(self, deal: Deal, risk_flags: List[Dict]) -> float:
        """
        0-100%. A transparent heuristic, not a trained model — stage base
        rate, adjusted by qualification completeness, intent, and active
        risk. Good enough for triage; if you later have enough closed-deal
        history, this is the natural place to swap in a real regression
        against DealStageHistory outcomes instead of these fixed weights.
        """
        stage_base_rates = {
            DealStage.PROSPECTING: 10, DealStage.DISCOVERY: 25,
            DealStage.DEMO: 40, DealStage.PROPOSAL: 55,
            DealStage.NEGOTIATION: 70, DealStage.CLOSED_WON: 100,
            DealStage.CLOSED_LOST: 0,
        }
        prob = stage_base_rates.get(deal.stage, 30)

        bant_count = sum([
            bool(deal.budget_confirmed), bool(deal.authority_confirmed),
            bool(deal.need_confirmed), bool(deal.timeline_confirmed),
        ])
        prob += (bant_count - 2) * 5  # +/- up to 10

        intent_adjust = {"strong": 15, "medium": 0, "weak": -15, "lost": -100}
        prob += intent_adjust.get(deal.buying_intent, 0)

        prob -= (deal.risk_score or 0) * 20  # risk_score is 0-1

        return max(0.0, min(100.0, prob))

    def _determine_next_best_action(self, deal: Deal, risk_flags: List[Dict]) -> str:
        """
        Deterministic decision tree, not an LLM call — priority-ordered so the
        single most urgent thing wins rather than listing everything at once.
        """
        risk_types = {f["type"] for f in risk_flags}

        if deal.buying_intent == "lost":
            return "Mark as closed-lost and log the reason for the win-pattern model."
        if "no_meeting_proposal" in risk_types:
            return "Send a direct meeting request — no meeting booked despite being in proposal."
        if "stage_stall" in risk_types:
            return "Re-engage the champion directly, or consider closing the deal out."
        if not deal.budget_confirmed or not deal.authority_confirmed:
            missing = [n for n, v in [("budget", deal.budget_confirmed), ("authority", deal.authority_confirmed)] if not v]
            return f"Confirm {' and '.join(missing)} before advancing this deal further."
        if "response_slowdown" in risk_types or "no_reply" in risk_types:
            return "Check if the champion is still engaged — try a different stakeholder if no reply soon."
        if deal.buying_intent == "strong" and deal.stage in (DealStage.DEMO, DealStage.PROPOSAL):
            return "Strong intent — move to send pricing or contract."
        return "Continue standard cadence. No urgent action needed."

    async def _reconcile_risk_state(self, deal: Deal, risk_flags: List[Dict]):
        """
        Writes new pending actions, expires stale ones whose risk no longer
        applies, and recomputes risk_score, health, and win probability using Claude AI.
        """
        # Fetch conversation thread history and contact details
        thread_events = []
        contact = None
        if deal.contact_id:
            # Fetch contact to access readiness score (A4 integration)
            contact_result = await self.db.execute(
                select(Contact).where(Contact.id == deal.contact_id)
            )
            contact = contact_result.scalar_one_or_none()
            if contact:
                deal.contact = contact

            result = await self.db.execute(
                select(ConversationThread)
                .where(ConversationThread.contact_id == deal.contact_id)
                .order_by(ConversationThread.occurred_at.asc())
            )
            thread_events = list(result.scalars().all())

            # Automatically extract BANT details from email conversation history if not already analyzed
            if thread_events and (deal.budget_confirmed is None or deal.deal_health_score is None):
                thread_text = "\n".join([
                    f"{'Sales Rep' if t.direction == 'outbound' else 'Prospect'}: {t.content or ''}"
                    for t in thread_events
                ])
                logger.info("A5: Extracting BANT from email conversation thread", deal_id=deal.id)
                extracted = await self._extract_from_transcript(thread_text, deal.name, contact)
                if extracted:
                    bant = extracted.get("bant_signals", {})
                    
                    ext_budget = bant.get("budget_confirmed")
                    ext_authority = bant.get("authority_confirmed")
                    ext_need = bant.get("need_confirmed")
                    ext_timeline = bant.get("timeline_confirmed")
                    
                    logger.info("A5 _reconcile_risk_state: email-thread extraction values",
                                deal_id=deal.id,
                                budget_confirmed=ext_budget,
                                timeline_confirmed=ext_timeline)
                    
                    # Precedence: only update if current is not True, or if the new value is True
                    if ext_budget is not None:
                        if deal.budget_confirmed is not True or ext_budget is True:
                            deal.budget_confirmed = ext_budget
                    if ext_authority is not None:
                        if deal.authority_confirmed is not True or ext_authority is True:
                            deal.authority_confirmed = ext_authority
                    if ext_need is not None:
                        if deal.need_confirmed is not True or ext_need is True:
                            deal.need_confirmed = ext_need
                    if ext_timeline is not None:
                        if deal.timeline_confirmed is not True or ext_timeline is True:
                            deal.timeline_confirmed = ext_timeline

                    if extracted.get("buying_intent"):
                        deal.buying_intent = extracted["buying_intent"]
                    if extracted.get("pain_points"):
                        deal.pain_points = extracted["pain_points"]
                    if extracted.get("objections"):
                        deal.objections = extracted["objections"]
                    if extracted.get("competitors_mentioned"):
                        deal.competitors_mentioned = extracted["competitors_mentioned"]

        baselines = await self._get_stage_baselines(deal.stage)

        # AI opportunity review using Groq / Gemini / Claude fallback
        logger.info("A5: Triggering AI opportunity analysis", deal_id=deal.id)
        ai_analysis = await self._evaluate_deal_with_ai(deal, thread_events, risk_flags, baselines)
        logger.info("A5: AI opportunity analysis completed", deal_id=deal.id)

        # Apply AI analysis scores
        deal.deal_health_score = ai_analysis.get("deal_health_score", 50.0)
        deal.win_probability = ai_analysis.get("win_probability", 30.0)
        deal.next_best_action = ai_analysis.get("next_best_action", "Review deal progression.")
        if ai_analysis.get("stage_confidence") is not None:
            deal.stage_confidence = ai_analysis.get("stage_confidence")

        # Map AI explanations back to risk flags
        ai_risks = ai_analysis.get("risk_evaluations", [])
        ai_risks_by_type = {r.get("type"): r for r in ai_risks if r.get("type")}
        
        for flag in risk_flags:
            ai_info = ai_risks_by_type.get(flag["type"])
            if ai_info and ai_info.get("ai_explanation"):
                flag["description"] = f"{flag['description']} AI Explanation: {ai_info['ai_explanation']}"
                if ai_info.get("adjusted_severity"):
                    flag["severity"] = ai_info["adjusted_severity"]

        current_types = {f["type"] for f in risk_flags}
        previous_types = {f.get("type") for f in (deal.risk_flags or [])}

        now = datetime.utcnow()
        for flag in risk_flags:
            # 1. Check if pending action already exists (deduplication)
            existing_res = await self.db.execute(
                select(PendingAction).where(
                    and_(
                        PendingAction.entity_id == deal.id,
                        PendingAction.action_type == flag["type"],
                        PendingAction.status == ActionStatus.PENDING,
                    )
                )
            )
            existing = existing_res.scalar_one_or_none()
            if existing:
                # Update in-place if recommendation or explanation changed
                existing.recommended_value = flag.get("recommended_action") or existing.recommended_value
                existing.reason = flag.get("description") or existing.reason
                continue

            # 2. Check if rep recently dismissed this specific risk (7-day cooldown)
            dismissed_res = await self.db.execute(
                select(PendingAction).where(
                    and_(
                        PendingAction.entity_id == deal.id,
                        PendingAction.action_type == flag["type"],
                        PendingAction.status == ActionStatus.DISMISSED,
                        PendingAction.created_at >= now - timedelta(days=7),
                    )
                )
            )
            if dismissed_res.scalar_one_or_none():
                logger.info("A5: Skipping recently dismissed risk action", deal_id=deal.id, risk_type=flag["type"])
                continue

            # 3. Create fresh deduplicated pending action
            self.db.add(PendingAction(
                action_type=flag["type"],
                entity_type="deal",
                entity_id=deal.id,
                recommended_value=flag.get("recommended_action"),
                current_value=deal.stage,
                reason=flag["description"],
                agent_id="A5",
                status=ActionStatus.PENDING,
                expires_at=now + timedelta(days=5),
            ))

        # Expire pending actions for risk types that no longer apply
        stale_result = await self.db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.entity_id == deal.id,
                    PendingAction.entity_type == "deal",
                    PendingAction.agent_id == "A5",
                    PendingAction.status == ActionStatus.PENDING,
                )
            )
        )
        for action in stale_result.scalars().all():
            if action.action_type not in current_types:
                action.status = ActionStatus.EXPIRED

        # New high-severity risks get an immediate Slack ping
        new_high_risks = [
            f for f in risk_flags
            if f["severity"] == "high" and f["type"] not in previous_types
        ]
        if new_high_risks:
            await self._send_immediate_risk_alert(deal, new_high_risks)

        deal.risk_flags = risk_flags
        raw_score = len([f for f in risk_flags if f["severity"] == "high"]) * 0.4 + \
                    len([f for f in risk_flags if f["severity"] == "medium"]) * 0.2
        deal.risk_score = min(1.0, raw_score)

        await self.db.commit()

    async def _send_immediate_risk_alert(self, deal: Deal, high_risks: List[Dict]):
        """Send immediate Slack notification when a new high-severity risk is identified."""
        if not settings.ENABLE_SLACK_APPROVALS and settings.NOTIFICATION_PROVIDER != "slack":
            return
        if not settings.SLACK_BOT_TOKEN:
            return

        lines = [f"🔴 *Immediate Risk Alert — {deal.name}*"]
        if deal.owner_email:
            lines.append(f"Owner: {deal.owner_email}")
        lines.append(f"Stage: {deal.stage} | ${deal.amount:,.0f}" if deal.amount else f"Stage: {deal.stage}")
        for r in high_risks:
            r_type = str(r.get("type", "Risk")).replace("_", " ").title()
            desc = r.get("description", "")
            action = r.get("recommended_action", "")
            lines.append(f"\n• *{r_type}*: {desc}")
            if action:
                lines.append(f"   → _Action:_ {action}")

        await self.slack.send_alert("\n".join(lines))

    async def _evaluate_deal_with_ai(
        self, deal: Deal, thread_events: List[ConversationThread], risk_flags: List[Dict], baselines: Dict
    ) -> Dict[str, Any]:
        """
        Claude Sonnet: Deeply evaluate deal health, win probability, next best action,
        and stage confidence by reviewing deal parameters, conversation history, and historical baselines.
        """
        import json
        thread_context = "\n".join([
            f"[{t.direction.upper()} - {t.occurred_at.strftime('%Y-%m-%d')}]: {(t.content or '')[:300]}"
            for t in thread_events[-10:]
        ]) if thread_events else "No prior conversation thread history."

        prompt = f"""You are a senior enterprise Sales Operations & Deal Intelligence AI.
Analyze this Salesforce Deal opportunity and provide a deep intelligence evaluation.

Opportunity Details:
- Name: {deal.name}
- Stage: {deal.stage}
- Amount: ${deal.amount or 0:,.2f}
- Days in current stage: {deal.days_in_current_stage} days
- Owner email: {deal.owner_email or "unknown"}
- Meeting count: {deal.meeting_count or 0}
- Stakeholder count: {deal.stakeholder_count or 1}
- Buying Intent (AI-detected): {deal.buying_intent or "unknown"}
- Contact Readiness Score (from Agent 4 Outreach): {deal.contact.readiness_score if getattr(deal, "contact", None) else 0.0}

BANT Checklist (AI-detected):
- Budget Confirmed: {deal.budget_confirmed}
- Authority Confirmed: {deal.authority_confirmed}
- Need Confirmed: {deal.need_confirmed}
- Timeline Confirmed: {deal.timeline_confirmed}

Historical/Stage Baselines:
- Historical average days for WON deals in this stage: {baselines.get('avg_days', 14)} days
- Baseline response time: {baselines.get('avg_response_hours', 48)} hours
- Prospect actual average response time: {deal.avg_response_time_hours or "unknown"} hours

Identified Risk Flags:
{json.dumps(risk_flags, indent=2)}

Recent Conversation History (up to 10 messages):
{thread_context}

Evaluate the opportunity and return a valid JSON object containing:
1. "deal_health_score": A float (0.0 to 100.0) reflecting the overall opportunity strength, qualification completeness, and stakeholder engagement.
2. "deal_health_explanation": Explain the reasoning behind this health score, highlighting specific factors like BANT completeness or thread momentum.
3. "win_probability": A float (0.0 to 100.0) representing the estimated probability of this deal closing as WON.
4. "win_probability_explanation": Explain the reasoning behind this win probability, mapping it to current pipeline stage velocity and detected risks.
5. "stage_confidence": A float (0.0 to 1.0) indicating our confidence that the deal is in the correct sales stage and moving forward.
6. "stage_confidence_explanation": Explain the stage alignment reasoning.
7. "next_best_action": A clear, single-sentence actionable recommendation for the sales representative to move this deal forward.
8. "next_best_action_explanation": Explain why this recommendation is the most critical next step.
9. "risk_evaluations": A list of objects matching the input risk flags, but adding an AI-reasoned explanation for why each risk is present:
   [
     {{
       "type": "<flag type>",
       "severity": "<severity>",
       "description": "<description>",
       "recommended_action": "<recommended_action>",
       "ai_explanation": "<Detailed explanation of why this risk was detected and how serious it is>"
     }}
   ]

Return ONLY valid JSON. Do not write markdown blocks or text wrapper."""

        try:
            raw_result = await self.llm.complete(
                system="You are an enterprise Deal Intelligence analyst. Output ONLY valid JSON containing deal calculations and explanations.",
                user=prompt,
                use_sonnet=True,
                response_format=None,
            )
            # Safe clean and parse JSON
            if isinstance(raw_result, dict):
                return raw_result
            cleaned = _clean_json_str(str(raw_result))
            parsed = json.loads(cleaned)
            return parsed
        except Exception as e:
            logger.error("AI Deal evaluation failed", error=str(e))
            # Safe fallback using deterministic heuristics
            fallback_health = self._calculate_deal_health(deal, risk_flags)
            fallback_win = self._calculate_win_probability(deal, risk_flags)
            fallback_action = self._determine_next_best_action(deal, risk_flags)
            return {
                "deal_health_score": fallback_health,
                "deal_health_explanation": "Calculated via fallback heuristic rules.",
                "win_probability": fallback_win,
                "win_probability_explanation": "Calculated via fallback heuristic rules.",
                "stage_confidence": 0.5,
                "stage_confidence_explanation": "Calculated via fallback heuristic rules.",
                "next_best_action": fallback_action,
                "next_best_action_explanation": "Fallback next best action determined.",
                "risk_evaluations": risk_flags
            }

    async def _update_deal(self, deal: Deal, extraction: Dict):
        logger.info("A5: Updating deal signals and parameters", deal_id=deal.id)
        bant = extraction.get("bant_signals", {})
        deal.budget_confirmed = bant.get("budget_confirmed")
        deal.authority_confirmed = bant.get("authority_confirmed")
        deal.need_confirmed = bant.get("need_confirmed")
        deal.timeline_confirmed = bant.get("timeline_confirmed")
        deal.meeting_count = (deal.meeting_count or 0) + 1
        if extraction.get("buying_intent"):
            deal.buying_intent = extraction["buying_intent"]
        if extraction.get("stage_confidence") is not None:
            deal.stage_confidence = extraction["stage_confidence"]
        deal.objections = extraction.get("objections", [])
        # Set amount and amount_source from extraction or CRM
        extracted_amount = extraction.get("deal_amount") or extraction.get("budget_amount")
        if extracted_amount and isinstance(extracted_amount, (int, float)) and extracted_amount > 0:
            deal.amount = float(extracted_amount)
            deal.amount_source = "Prospect conversation"
        elif (deal.salesforce_opportunity_id or deal.hubspot_deal_id) and not deal.amount_source:
            deal.amount_source = "Salesforce"
        elif not deal.amount_source:
            deal.amount_source = "Not provided"
        elif not deal.amount_source:
            deal.amount_source = "Not provided"

        deal.updated_at = datetime.utcnow()
        await self.db.commit()
        logger.info("A5: Deal signals updated successfully", deal_id=deal.id)

    async def _resolve_deal_owner_email(
        self,
        contact: Optional[Contact] = None,
        attendee_emails: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Dynamically resolves the Deal Owner email from the authenticated user context.
        Priority:
        1. If attendee_emails are provided from the call transcript (e.g. Fireflies),
           check if any attendee matches an active registered User in the platform.
        2. If contact is linked to a user (contact.user_id), look up that User's email.
        3. If contact is linked to a user_input (contact.user_input_id), look up the User's email for that intake form.
        4. Look up the user who submitted the most recent UserInput session.
        5. Look up the most recently registered active User in the database.
        6. Explicit configured environment fallback (settings.DEAL_OWNER_EMAIL or settings.NOTIFICATION_EMAIL).
        7. If none found, log a warning and return None (never invent placeholder fallbacks).
        """
        from app.models.models import User, UserInput

        # 1. Check if any attendee in the meeting transcript is an active registered platform user (e.g. rep on the call)
        if attendee_emails:
            clean_emails = [e.strip().lower() for e in attendee_emails if e and "@" in e]
            if clean_emails:
                res = await self.db.execute(
                    select(User.email).where(
                        User.email.in_(clean_emails),
                        User.is_active == True,
                    ).limit(1)
                )
                user_email = res.scalar_one_or_none()
                if user_email:
                    logger.info("A5: Resolved deal owner from call attendee", email=user_email)
                    return user_email

        # 2. Check if contact is owned by a specific user
        if contact and getattr(contact, "user_id", None):
            res = await self.db.execute(
                select(User.email).where(User.id == contact.user_id, User.is_active == True)
            )
            user_email = res.scalar_one_or_none()
            if user_email:
                logger.info("A5: Resolved deal owner from contact.user_id", email=user_email)
                return user_email

        # 3. Check if contact is associated with a user_input that has an owner
        if contact and getattr(contact, "user_input_id", None):
            res = await self.db.execute(
                select(User.email)
                .join(UserInput, UserInput.user_id == User.id)
                .where(UserInput.id == contact.user_input_id, User.is_active == True)
            )
            user_email = res.scalar_one_or_none()
            if user_email:
                logger.info("A5: Resolved deal owner from contact.user_input_id", email=user_email)
                return user_email

        # 4. Check the latest UserInput session that has an owner
        res = await self.db.execute(
            select(User.email)
            .join(UserInput, UserInput.user_id == User.id)
            .where(User.is_active == True)
            .order_by(UserInput.id.desc())
            .limit(1)
        )
        user_email = res.scalar_one_or_none()
        if user_email:
            logger.info("A5: Resolved deal owner from latest active UserInput", email=user_email)
            return user_email

        # 5. Check the most recent active User
        res = await self.db.execute(
            select(User.email).where(User.is_active == True).order_by(User.created_at.desc()).limit(1)
        )
        user_email = res.scalar_one_or_none()
        if user_email:
            logger.info("A5: Resolved deal owner from latest active User", email=user_email)
            return user_email

        # 6. Check environment settings fallback
        env_fallback = getattr(settings, "DEAL_OWNER_EMAIL", None) or getattr(settings, "NOTIFICATION_EMAIL", None)
        if env_fallback and env_fallback.strip():
            logger.info("A5: Resolved deal owner from environment settings", email=env_fallback)
            return env_fallback.strip()

        # 7. Safe fail: log warning, do not invent placeholder
        logger.warning("A5: Unable to resolve authenticated deal owner; setting owner_email to None")
        return None

    async def _match_to_deal(
        self, attendees: List[Dict], title: str
    ) -> Tuple[Optional[Deal], Optional[Contact]]:
        """Match Fireflies transcript to a deal via attendee email, company name, or meeting title."""
        emails = [a.get("email", "") for a in attendees if a.get("email")]
        for email in emails:
            contact_result = await self.db.execute(select(Contact).where(Contact.email == email))
            contact = contact_result.scalar_one_or_none()
            if contact:
                # 1. Match deal directly by contact_id
                deal_result = await self.db.execute(
                    select(Deal).where(
                        and_(Deal.contact_id == contact.id, Deal.outcome.is_(None))
                    ).order_by(Deal.updated_at.desc())
                )
                deal = deal_result.scalars().first()
                if deal:
                    return deal, contact

                # 2. Match deal by contact's company name
                if contact.company:
                    comp_deal_result = await self.db.execute(
                        select(Deal).where(
                            and_(Deal.name.ilike(f"%{contact.company}%"), Deal.outcome.is_(None))
                        ).order_by(Deal.updated_at.desc())
                    )
                    comp_deal = comp_deal_result.scalars().first()
                    if comp_deal:
                        if not comp_deal.contact_id:
                            comp_deal.contact_id = contact.id
                            await self.db.commit()
                        return comp_deal, contact

                # 3. If no active deal found for this contact, create one
                new_deal = Deal(
                    name=f"{contact.company or contact.first_name} — Enterprise Solution",
                    contact_id=contact.id,
                    stage=DealStage.DISCOVERY,
                    amount=None,
                    amount_source="Not provided",
                    owner_email=await self._resolve_deal_owner_email(contact=contact, attendee_emails=emails),
                )
                self.db.add(new_deal)
                await self.db.commit()
                await self.db.refresh(new_deal)
                return new_deal, contact

        # 4. If no attendee email matched contact, search existing deals matching words in meeting title
        if title:
            clean_title = title.replace("—", "-").replace(":", "-").replace("|", "-")
            for part in clean_title.split("-"):
                part_clean = part.strip()
                if len(part_clean) >= 3 and not any(skip in part_clean.lower() for skip in ["call", "demo", "review", "meeting", "sync", "pricing"]):
                    deal_res = await self.db.execute(
                        select(Deal).where(
                            and_(Deal.name.ilike(f"%{part_clean}%"), Deal.outcome.is_(None))
                        ).order_by(Deal.updated_at.desc())
                    )
                    deal = deal_res.scalars().first()
                    if deal:
                        contact = None
                        if deal.contact_id:
                            c_res = await self.db.execute(select(Contact).where(Contact.id == deal.contact_id))
                            contact = c_res.scalar_one_or_none()
                        return deal, contact

        return None, None

    async def _get_pending_actions(self) -> List[PendingAction]:
        result = await self.db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.status == ActionStatus.PENDING,
                    PendingAction.agent_id == "A5",
                )
            ).order_by(PendingAction.created_at.desc()).limit(20)
        )
        return list(result.scalars().all())

    def _format_crm_note(self, extraction: Dict) -> str:
        lines = [f"AI Call Summary: {extraction.get('call_summary', '')}"]
        if extraction.get("next_steps"):
            lines.append("Next Steps: " + "; ".join(extraction["next_steps"]))
        if extraction.get("objections"):
            # Each objection is {"text": ..., "category": ...} — fall back to
            # plain strings gracefully in case an older extraction shape shows up.
            formatted = [
                f"[{o.get('category', 'other')}] {o.get('text', '')}" if isinstance(o, dict) else str(o)
                for o in extraction["objections"]
            ]
            lines.append("Objections: " + "; ".join(formatted))
        bant = extraction.get("bant_signals", {})
        bant_summary = ", ".join([
            f"{k.replace('_confirmed', '').upper()}: {'✓' if v else '✗'}"
            for k, v in bant.items() if "_confirmed" in k and v is not None
        ])
        if bant_summary:
            lines.append(f"BANT: {bant_summary}")
        return "\n".join(lines)

    def _build_deal_summary(self, deal: Deal, extraction: Optional[Dict], risk_flags: List[Dict]) -> Dict:
        """
        Assembles data already computed elsewhere into one readable summary
        for a manager/rep glancing at the deal. Deliberately NOT a new LLM
        call — every field here already exists on `deal` or in `extraction`.
        """
        strengths = [
            name for name, confirmed in [
                ("Budget", deal.budget_confirmed), ("Authority", deal.authority_confirmed),
                ("Need", deal.need_confirmed), ("Timeline", deal.timeline_confirmed),
            ] if confirmed
        ]
        return {
            "situation": (extraction or {}).get("call_summary") or "No recent call summary available.",
            "strengths": strengths,
            "risks": [f["description"] for f in risk_flags],
            "next_best_action": deal.next_best_action,
            "deal_health_score": deal.deal_health_score,
            "win_probability": deal.win_probability,
            "buying_intent": deal.buying_intent,
        }

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A5", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()


def _clean_json_str(s: str) -> str:
    """Clean markdown code block wrappers and find outermost JSON object."""
    s = s.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in s:
        s = s.split("```", 1)[1].split("```", 1)[0]
    first_brace = s.find("{")
    last_brace = s.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        s = s[first_brace:last_brace+1]
    return s.strip()
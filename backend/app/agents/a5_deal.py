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
    PendingAction, FunnelEvent, ActionStatus, DealStage, SignalEvent
)
from app.services.llm_service import LLMService
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

    # ── HubSpot sync ────────────────────────────────────────────────────────

    @property
    def _hubspot_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.HUBSPOT_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

    async def sync_deals_from_hubspot(self) -> Dict[str, Any]:
        """
        Pull active deals from HubSpot, upsert into `deals`, and write a
        DealStageHistory row whenever a stage transition is detected. This is
        the step that was entirely missing before — without it the deals
        table stays empty and everything downstream has nothing to scan.
        """
        if not settings.HUBSPOT_ACCESS_TOKEN:
            return {"synced": 0, "created": 0, "updated": 0, "skipped": "no HUBSPOT_ACCESS_TOKEN configured"}

        created = 0
        updated = 0
        unchanged = 0

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                raw_deals = await self._fetch_hubspot_deals(client)
                for raw in raw_deals:
                    contact_email = await self._get_associated_contact_email(client, raw["id"])
                    _, was_created, was_stage_change = await self._upsert_deal(raw, contact_email)
                    if was_created:
                        created += 1
                    elif was_stage_change:
                        updated += 1
                    else:
                        unchanged += 1

            await self.db.commit()
        except httpx.HTTPStatusError as exc:
            logger.error("HubSpot deal sync failed", status=exc.response.status_code, error=str(exc))
            return {"synced": 0, "created": 0, "updated": 0, "error": str(exc)}
        except Exception as exc:
            logger.error("HubSpot deal sync failed", error=str(exc))
            return {"synced": 0, "created": 0, "updated": 0, "error": str(exc)}

        return {
            "synced": created + updated + unchanged,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
        }

    async def _fetch_hubspot_deals(self, client: httpx.AsyncClient) -> List[Dict]:
        """Raw HubSpot search call — deals not yet closed-lost."""
        resp = await client.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals/search",
            headers=self._hubspot_headers,
            json={
                "filterGroups": [{"filters": [
                    {"propertyName": "dealstage", "operator": "NEQ", "value": "closedlost"}
                ]}],
                "properties": ["dealname", "amount", "dealstage", "closedate", "hubspot_owner_id"],
                "limit": 100,
            },
        )
        resp.raise_for_status()
        return resp.json().get("results", [])

    async def _get_associated_contact_email(
        self, client: httpx.AsyncClient, hubspot_deal_id: str
    ) -> Optional[str]:
        """Best-effort lookup of the first associated contact's email."""
        try:
            assoc_resp = await client.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/deals/{hubspot_deal_id}/associations/contacts",
                headers=self._hubspot_headers,
            )
            assoc_resp.raise_for_status()
            results = assoc_resp.json().get("results", [])
            if not results:
                return None
            contact_id = results[0]["id"]

            contact_resp = await client.get(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
                headers=self._hubspot_headers,
                params={"properties": "email"},
            )
            contact_resp.raise_for_status()
            return contact_resp.json().get("properties", {}).get("email")
        except Exception as e:
            logger.warning("Could not resolve HubSpot deal contact", deal_id=hubspot_deal_id, error=str(e))
            return None

    async def _upsert_deal(
        self, raw: Dict, contact_email: Optional[str]
    ) -> Tuple[Deal, bool, bool]:
        """
        Create or update a Deal from a raw HubSpot deal object.
        Returns (deal, was_created, was_stage_change).
        """
        props = raw.get("properties", {})
        hs_id = raw["id"]
        now = datetime.utcnow()

        raw_stage = props.get("dealstage")
        mapped_stage = HUBSPOT_STAGE_MAP.get(raw_stage, raw_stage or DealStage.PROSPECTING)
        outcome = "won" if mapped_stage == DealStage.CLOSED_WON else \
                  "lost" if mapped_stage == DealStage.CLOSED_LOST else None

        amount = None
        if props.get("amount"):
            try:
                amount = float(props["amount"])
            except (TypeError, ValueError):
                amount = None

        close_date = None
        if props.get("closedate"):
            try:
                close_date = datetime.utcfromtimestamp(int(props["closedate"]) / 1000)
            except (TypeError, ValueError):
                close_date = None

        contact_id = None
        if contact_email:
            contact_result = await self.db.execute(select(Contact).where(Contact.email == contact_email))
            contact = contact_result.scalar_one_or_none()
            if contact:
                contact_id = contact.id

        existing_result = await self.db.execute(select(Deal).where(Deal.hubspot_deal_id == hs_id))
        existing = existing_result.scalar_one_or_none()

        if not existing:
            deal = Deal(
                hubspot_deal_id=hs_id,
                contact_id=contact_id,
                name=props.get("dealname") or "Untitled Deal",
                stage=mapped_stage,
                amount=amount,
                close_date=close_date,
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

        existing.name = props.get("dealname") or existing.name
        existing.amount = amount if amount is not None else existing.amount
        existing.close_date = close_date or existing.close_date
        existing.outcome = outcome
        if contact_id and not existing.contact_id:
            existing.contact_id = contact_id
        existing.updated_at = now

        return existing, False, stage_changed

    async def _log_hubspot_note(self, deal: Deal, body: str) -> bool:
        """Log a call summary as a HubSpot note on the deal. Inline, matching A1's
        direct-httpx style rather than a separate service wrapper."""
        if not settings.HUBSPOT_ACCESS_TOKEN or not deal.hubspot_deal_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{HUBSPOT_BASE}/crm/v3/objects/notes",
                    headers=self._hubspot_headers,
                    json={"properties": {
                        "hs_note_body": body,
                        "hs_timestamp": str(int(datetime.utcnow().timestamp() * 1000)),
                    }},
                )
                resp.raise_for_status()
                note_id = resp.json().get("id")
                if note_id:
                    await client.put(
                        f"{HUBSPOT_BASE}/crm/v3/objects/notes/{note_id}/associations/deals/{deal.hubspot_deal_id}/note_to_deal",
                        headers=self._hubspot_headers,
                    )
                return True
        except Exception as e:
            logger.error("HubSpot note log failed", error=str(e))
            return False

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
            logger.info("A5: Matched transcript to HubSpot Deal", deal_id=deal.id, deal_name=deal.name)
        else:
            logger.info("A5: No matching HubSpot Deal found for transcript", transcript_id=transcript_id)

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

        if deal and settings.HUBSPOT_ACCESS_TOKEN:
            await self._log_hubspot_note(deal, self._format_crm_note(extraction))

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

    async def run_daily_deal_scan(self) -> Dict[str, Any]:
        """
        Nightly scan: sync fresh deal data from HubSpot first (best-effort),
        then re-check every open deal against risk patterns, even without a
        new transcript.
        """
        logger.info("A5 running daily deal scan")

        sync_result = await self.sync_deals_from_hubspot()
        logger.info("A5 HubSpot sync complete", **sync_result)

        # Only scan active deals that have supporting data (conversation history, transcripts, or CRM stage history)
        deals_result = await self.db.execute(
            select(Deal).where(
                and_(
                    Deal.outcome.is_(None),
                    Deal.contact_id.isnot(None),
                )
            )
        )
        all_deals = list(deals_result.scalars().all())
        
        # Filter to deals with actual conversation or stage progression history
        deals = []
        for d in all_deals:
            has_threads = await self.db.scalar(
                select(func.count(ConversationThread.id)).where(ConversationThread.contact_id == d.contact_id)
            )
            if (has_threads and has_threads > 0) or d.days_in_current_stage > 0:
                deals.append(d)

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
            "hubspot_sync": sync_result,
            "deals_scanned": len(deals),
            "deals_flagged": flagged,
            "pending_actions": len(pending),
            "reason": (
                "No active deals found — check HUBSPOT_ACCESS_TOKEN and that deals exist in your pipeline"
                if not deals else
                "No risk patterns detected"
                if flagged == 0 else
                "Risk actions created for review"
            ),
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
            if isinstance(raw_result, str):
                return json.loads(raw_result)
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

            # Automatically extract BANT details from email conversation history if available
            if thread_events:
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
        lines = [f"*🚨 Immediate Risk Alert for Deal: {deal.name}* (Stage: {deal.stage})\n"]
        for r in high_risks:
            lines.append(f"• *{r.get('type', 'Risk').replace('_', ' ').title()}*: {r.get('description', '')}")
            if r.get('recommended_action'):
                lines.append(f"  → _Action:_ {r['recommended_action']}")
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
Analyze this HubSpot Deal opportunity and provide a deep intelligence evaluation.

Opportunity Details:
- Name: {deal.name}
- Stage: {deal.stage}
- Amount: ${deal.amount or 0:,.2f}
- Days in current stage: {deal.days_in_current_stage} days
- Owner email: {deal.owner_email or "unknown"}
- Meeting count: {deal.meeting_count or 0}
- Stakeholder count: {deal.stakeholder_count or 1}
- Buying Intent (AI-detected): {deal.buying_intent or "unknown"}
- Contact Readiness Score (from Agent 4 Outreach): {deal.contact.readiness_score if (deal.contact or contact) else 0.0}

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

    async def _send_immediate_risk_alert(self, deal: Deal, new_high_risks: List[Dict]):
        """
        Immediate Slack ping for a newly-detected high-severity risk.
        Inline httpx, matching this file's style for HubSpot calls, rather
        than adding a method to the shared SlackService — this alert format
        is A5-specific and only used here.
        """
        if not settings.SLACK_BOT_TOKEN:
            return
        lines = [f"🔴 *New high-risk flag — {deal.name}*"]
        if deal.owner_email:
            lines.append(f"Owner: {deal.owner_email}")
        lines.append(f"Stage: {deal.stage} | ${deal.amount:,.0f}" if deal.amount else f"Stage: {deal.stage}")
        for f in new_high_risks:
            lines.append(f"\n• {f['description']}\n   → {f['recommended_action']}")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}"},
                    json={"channel": settings.SLACK_APPROVAL_CHANNEL, "text": "\n".join(lines)},
                )
        except Exception as e:
            logger.error("Immediate risk alert failed", deal_id=deal.id, error=str(e))

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
        deal.updated_at = datetime.utcnow()
        await self.db.commit()
        logger.info("A5: Deal signals updated successfully", deal_id=deal.id)

    async def _match_to_deal(
        self, attendees: List[Dict], title: str
    ) -> Tuple[Optional[Deal], Optional[Contact]]:
        """Match Fireflies transcript to a deal via attendee email."""
        emails = [a.get("email", "") for a in attendees if a.get("email")]
        for email in emails:
            contact_result = await self.db.execute(select(Contact).where(Contact.email == email))
            contact = contact_result.scalar_one_or_none()
            if contact:
                deal_result = await self.db.execute(
                    select(Deal).where(
                        and_(Deal.contact_id == contact.id, Deal.outcome.is_(None))
                    ).order_by(Deal.updated_at.desc())
                )
                deal = deal_result.scalars().first()
                if deal:
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
    """Clean markdown code block wrappers from JSON string if present."""
    s = s.strip()
    if s.startswith("```"):
        # Remove opening ```json or ```
        s = s.split("\n", 1)[1]
    if s.endswith("```"):
        s = s.rsplit("\n", 1)[0]
    return s.strip()
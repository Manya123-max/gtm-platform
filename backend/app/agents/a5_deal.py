"""
A5 — Deal Intelligence Agent
Compares live deals against closed-won/lost historical patterns.
Relationship health tracking. Stage changes are recommendations only — never autonomous.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, text

from app.core.config import settings
from app.models.models import (
    Deal, DealStageHistory, Contact, ConversationThread,
    PendingAction, FunnelEvent, ActionStatus
)
from app.services.llm_service import LLMService
from app.services.slack_service import SlackService
from app.services.hubspot_service import HubSpotService

logger = structlog.get_logger()

# Risk thresholds — deviation from historical baseline triggers a flag
RISK_THRESHOLDS = {
    "days_in_stage_multiplier": 1.5,   # 50% longer than average = flag
    "response_time_multiplier": 2.0,   # 2x slower response = flag
    "no_meeting_days": 21,             # 3 weeks without a meeting in proposal stage
    "no_reply_days": 10,               # 10 days without any contact = flag
}


class DealAgent:
    """
    A5: Post-call extraction + deal pattern comparison + relationship health.

    Key behaviours:
    - Extracts BANT signals from Fireflies transcripts using Claude Sonnet
    - Compares deal metrics to historical closed-won/lost baselines
    - Tracks relationship health via email frequency and stakeholder engagement
    - Writes risk flags to pending_actions — never changes CRM stages directly
    - Daily Slack digest surfaces pending actions to reps
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = LLMService()
        self.slack = SlackService()
        self.hubspot = HubSpotService()

    async def process_transcript(self, webhook_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called when Fireflies webhook fires (transcript ready).
        """
        transcript_id = webhook_payload.get("transcriptId", "")
        transcript_text = webhook_payload.get("transcript", "")
        attendees = webhook_payload.get("attendees", [])
        meeting_title = webhook_payload.get("title", "")

        logger.info("A5 processing transcript", transcript_id=transcript_id)

        # Find matching deal by attendee email
        deal, contact = await self._match_to_deal(attendees, meeting_title)

        # Extract structured data using Claude Sonnet (accuracy matters here)
        extraction = await self._extract_from_transcript(
            transcript_text, meeting_title, contact
        )

        # Update deal with extracted data
        risk_flags: List[Dict] = []
        if deal:
            await self._update_deal(deal, extraction)
            risk_flags = await self._detect_risk_patterns(deal)
            if risk_flags:
                await self._create_pending_actions(deal, risk_flags)

        # Sync to HubSpot
        if deal and settings.HUBSPOT_ACCESS_TOKEN:
            await self.hubspot.log_activity(
                deal_id=deal.hubspot_deal_id,
                activity_type="call",
                body=self._format_crm_note(extraction),
            )

        # Log funnel event
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
        }

    async def run_daily_deal_scan(self) -> Dict[str, Any]:
        """
        Nightly scan of all active deals.
        Detects deals drifting from healthy patterns without a new transcript.
        """
        logger.info("A5 running daily deal scan")

        deals_result = await self.db.execute(
            select(Deal).where(
                Deal.outcome.is_(None)  # active deals only
            )
        )
        deals = list(deals_result.scalars().all())

        flagged = 0
        for deal in deals:
            # Update days_in_current_stage
            deal.days_in_current_stage = (datetime.utcnow() - deal.stage_entered_at).days
            risk_flags = await self._detect_risk_patterns(deal)
            if risk_flags:
                await self._create_pending_actions(deal, risk_flags)
                flagged += 1

        await self.db.commit()

        # Send daily digest if there are pending actions
        pending = await self._get_pending_actions()
        if pending and settings.ENABLE_SLACK_APPROVALS:
            await self.slack.send_daily_digest(pending)

        return {
            "agent": "A5",
            "deals_scanned": len(deals),
            "deals_flagged": flagged,
            "pending_actions": len(pending),
            "reason": (
                "No active deals found"
                if not deals else
                "No risk patterns detected"
                if flagged == 0 else
                "Risk actions created for review"
            ),
        }

    async def _extract_from_transcript(
        self, transcript: str, title: str, contact: Optional[Contact]
    ) -> Dict[str, Any]:
        """
        Claude Sonnet: extract structured BANT data from transcript.
        Sonnet used here for accuracy — this data feeds the win-pattern model.
        """
        contact_ctx = f"{contact.first_name} {contact.last_name} at {contact.company}" if contact else "unknown contact"

        prompt = f"""Extract structured sales intelligence from this call transcript.

Meeting: {title}
Contact: {contact_ctx}

Transcript:
{transcript[:6000]}

Return JSON with exactly these fields:
{{
  "next_steps": ["list of concrete next steps with dates if mentioned"],
  "objections": ["list of objections raised"],
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
  "sentiment": "positive/neutral/negative"
}}

If a field is unclear, use null. Do not invent information not in the transcript."""

        try:
            return await self.llm.complete(
                system="You are a sales intelligence extraction engine. Extract only factual information present in the transcript. Return valid JSON only.",
                user=prompt,
                use_sonnet=True,
                response_format=None,
            )
        except Exception as e:
            logger.error("Transcript extraction failed", error=str(e))
            return {
                "next_steps": [], "objections": [],
                "bant_signals": {}, "stakeholders_mentioned": [],
                "recommended_stage_change": None, "call_summary": "Extraction failed",
                "sentiment": "neutral",
            }

    async def _detect_risk_patterns(self, deal: Deal) -> List[Dict]:
        """
        Compare deal metrics against historical baselines.
        Returns list of risk flags — each becomes a pending action for human review.
        """
        risk_flags = []
        baselines = await self._get_stage_baselines(deal.stage)

        # Risk 1: Deal stuck in stage too long
        if baselines.get("avg_days") and deal.days_in_current_stage:
            threshold = baselines["avg_days"] * RISK_THRESHOLDS["days_in_stage_multiplier"]
            if deal.days_in_current_stage > threshold:
                risk_flags.append({
                    "type": "stage_stall",
                    "severity": "high" if deal.days_in_current_stage > threshold * 1.5 else "medium",
                    "description": f"Deal has been in {deal.stage} for {deal.days_in_current_stage} days. Historical average is {baselines['avg_days']:.0f} days.",
                    "recommended_action": f"Review deal status and consider moving stage or closing.",
                })

        # Risk 2: Slow response time trend
        if deal.avg_response_time_hours and baselines.get("avg_response_hours"):
            threshold = baselines["avg_response_hours"] * RISK_THRESHOLDS["response_time_multiplier"]
            if deal.avg_response_time_hours > threshold:
                risk_flags.append({
                    "type": "response_slowdown",
                    "severity": "medium",
                    "description": f"Prospect response time has increased to {deal.avg_response_time_hours:.0f}h. Baseline is {baselines['avg_response_hours']:.0f}h.",
                    "recommended_action": "Check if champion is still engaged. Consider reaching out to another stakeholder.",
                })

        # Risk 3: No meeting in proposal stage
        if deal.stage == "proposal" and deal.days_in_current_stage > RISK_THRESHOLDS["no_meeting_days"]:
            risk_flags.append({
                "type": "no_meeting_proposal",
                "severity": "high",
                "description": f"No meeting booked in {deal.days_in_current_stage} days while in proposal stage.",
                "recommended_action": "Send a direct meeting request or check if procurement is blocking.",
            })

        # Risk 4: BANT incomplete at proposal stage
        if deal.stage in ("proposal", "negotiation"):
            missing_bant = []
            if not deal.budget_confirmed:
                missing_bant.append("budget")
            if not deal.authority_confirmed:
                missing_bant.append("authority")
            if missing_bant:
                risk_flags.append({
                    "type": "incomplete_bant",
                    "severity": "medium",
                    "description": f"Missing BANT confirmation: {', '.join(missing_bant)}",
                    "recommended_action": f"Confirm {' and '.join(missing_bant)} before advancing deal.",
                })

        return risk_flags

    async def _get_stage_baselines(self, stage: str) -> Dict:
        """
        Query historical closed-won deals to get baseline metrics for this stage.
        This is the comparison baseline for risk detection.
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

    async def _create_pending_actions(self, deal: Deal, risk_flags: List[Dict]):
        """Write risk flags to pending_actions. Never touch CRM stages directly."""
        for flag in risk_flags:
            # Avoid duplicate pending actions for same deal + type
            existing = await self.db.execute(
                select(PendingAction).where(
                    and_(
                        PendingAction.entity_id == deal.id,
                        PendingAction.action_type == flag["type"],
                        PendingAction.status == ActionStatus.PENDING,
                    )
                )
            )
            if existing.scalar_one_or_none():
                continue

            action = PendingAction(
                action_type=flag["type"],
                entity_type="deal",
                entity_id=deal.id,
                recommended_value=flag.get("recommended_action"),
                current_value=deal.stage,
                reason=flag["description"],
                agent_id="A5",
                status=ActionStatus.PENDING,
                expires_at=datetime.utcnow() + timedelta(days=3),
            )
            self.db.add(action)

        # Update deal risk fields
        deal.risk_flags = risk_flags
        deal.risk_score = len([f for f in risk_flags if f["severity"] == "high"]) * 0.4 + \
                          len([f for f in risk_flags if f["severity"] == "medium"]) * 0.2
        await self.db.commit()

    async def _update_deal(self, deal: Deal, extraction: Dict):
        bant = extraction.get("bant_signals", {})
        deal.budget_confirmed = bant.get("budget_confirmed")
        deal.authority_confirmed = bant.get("authority_confirmed")
        deal.need_confirmed = bant.get("need_confirmed")
        deal.timeline_confirmed = bant.get("timeline_confirmed")
        deal.meeting_count = (deal.meeting_count or 0) + 1
        deal.updated_at = datetime.utcnow()
        await self.db.commit()

    async def _match_to_deal(
        self, attendees: List[Dict], title: str
    ) -> tuple[Optional[Deal], Optional[Contact]]:
        """Match Fireflies transcript to a deal via attendee email."""
        emails = [a.get("email", "") for a in attendees if a.get("email")]
        for email in emails:
            contact_result = await self.db.execute(
                select(Contact).where(Contact.email == email)
            )
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
            lines.append("Objections: " + "; ".join(extraction["objections"]))
        bant = extraction.get("bant_signals", {})
        bant_summary = ", ".join([
            f"{k.replace('_confirmed', '').upper()}: {'✓' if v else '✗'}"
            for k, v in bant.items() if "_confirmed" in k and v is not None
        ])
        if bant_summary:
            lines.append(f"BANT: {bant_summary}")
        return "\n".join(lines)

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A5", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()

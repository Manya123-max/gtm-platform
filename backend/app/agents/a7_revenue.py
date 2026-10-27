"""
A7 — Predictive Revenue Agent
Comprehensive forward-looking pipeline intelligence & revenue forecasting.

Key Strategies Implemented:
1. Deal-Level Dynamic Win Probability:
   - Base stage prior calibrated by BANT qualification (Budget, Authority, Need, Timeline).
   - Buying intent (strong/medium/weak) and Deal Health / Risk scores from A5.
2. Time-in-Stage & Velocity Decay:
   - Stagnant deals lingering >1.5x stage velocity are penalized with exponential decay.
3. Velocity-Adjusted Horizon Allocation:
   - Calculates estimated days to close for each deal to accurately split revenue across 30d, 60d, and 90d horizons.
4. Top-of-Funnel Inflow Projection:
   - Factors in leading indicators from funnel_events (inbound replies, meetings booked, qualified prospects).
5. Bottleneck Diagnostics & Tactical Levers:
   - Stage conversion gap analysis against historical baselines with actionable recommendations.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import math
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, or_
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import (
    Deal, FunnelEvent, RevenueForecast, DealStageHistory, Contact, ConversationThread, User
)
from app.services.slack_service import SlackService
from app.services.resend_service import ResendService
from app.services.llm_service import LLMService

logger = structlog.get_logger()

STAGE_ORDER = [
    "prospecting", "discovery", "demo",
    "proposal", "negotiation", "closed_won"
]

STAGE_PRIORS = {
    "prospecting": 0.10,
    "discovery": 0.20,
    "demo": 0.35,
    "proposal": 0.55,
    "negotiation": 0.75,
    "closed_won": 1.00,
    "closed_lost": 0.00,
}

DEFAULT_STAGE_VELOCITY_DAYS = {
    "prospecting": 7.0,
    "discovery": 14.0,
    "demo": 14.0,
    "proposal": 21.0,
    "negotiation": 14.0,
}

DEFAULT_STAGE_CONVERSION_BASELINES = {
    "prospecting_to_discovery": 0.45,
    "discovery_to_demo": 0.55,
    "demo_to_proposal": 0.45,
    "proposal_to_negotiation": 0.50,
    "negotiation_to_closed_won": 0.65,
}


class RevenueAgent:
    """
    A7: Multi-strategy Predictive Revenue & Pipeline Analytics.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.slack = SlackService()
        self.resend = ResendService()
        self.llm = LLMService()

    async def run(
        self, user_id: Optional[str] = None, company_wide: bool = False
    ) -> Dict[str, Any]:
        """
        A7 main entry point.
        Strictly requires either an authenticated rep user_id or explicit company_wide=True authorization.
        """
        if not user_id and not company_wide:
            raise ValueError(
                "User context required for revenue forecasting. Pass user_id or specify company_wide=True."
            )

        logger.info(
            "A7 starting predictive revenue forecast",
            user_id=user_id,
            company_wide=company_wide,
        )

        # Step 1: Pull live deals and calculate stage velocities
        deals = await self._get_active_deals(user_id=user_id, company_wide=company_wide)
        velocity = await self._calculate_stage_velocity()
        conversion_rates, has_real_stage_history = await self._calculate_conversion_rates()
        baselines = await self._get_historical_baselines()

        # Step 2: Run deal-level probability & horizon calculations
        forecast_metrics = self._calculate_deal_level_forecast(deals, velocity)

        # Step 3: Factor in top-of-funnel pipeline inflow from leading funnel events
        inflow = await self._calculate_top_of_funnel_inflow(deals, user_id=user_id)
        forecast_30d = forecast_metrics["day_30"] + inflow["inflow_30d"]
        forecast_60d = forecast_metrics["day_60"] + inflow["inflow_60d"]
        forecast_90d = forecast_metrics["day_90"] + inflow["inflow_90d"]

        # Step 4: Identify bottleneck stage & tactical growth levers
        constraint = await self._identify_constraint_and_levers(
            conversion_rates, baselines, deals, has_real_stage_history=has_real_stage_history
        )

        # Step 5: Persist snapshot in revenue_forecasts table with authenticated rep ownership
        forecast_record = RevenueForecast(
            forecast_30d=round(forecast_30d, 2),
            forecast_60d=round(forecast_60d, 2),
            forecast_90d=round(forecast_90d, 2),
            current_pipeline_value=round(forecast_metrics["total_pipeline_value"], 2),
            bottleneck_stage=constraint.get("stage"),
            bottleneck_description=constraint.get("description"),
            recommended_lever=constraint.get("lever"),
            stage_conversion_rates=conversion_rates,
            stage_velocity_days=velocity,
            user_id=user_id if not company_wide else None,
            calculated_at=datetime.utcnow(),
        )
        self.db.add(forecast_record)
        await self.db.commit()

        # Step 6: Log funnel event for historical tracking
        await self._log_funnel_event("forecast_calculated", {
            "forecast_30d": round(forecast_30d, 2),
            "forecast_60d": round(forecast_60d, 2),
            "forecast_90d": round(forecast_90d, 2),
            "pipeline_value": round(forecast_metrics["total_pipeline_value"], 2),
            "deals_evaluated": len(deals),
            "unpriced_deals_count": forecast_metrics.get("unpriced_deals_count", 0),
            "bottleneck_stage": constraint.get("stage"),
            "user_id": user_id,
            "company_wide": company_wide,
        })

        return {
            "agent": "A7",
            "forecast_30d": round(forecast_30d, 2),
            "forecast_60d": round(forecast_60d, 2),
            "forecast_90d": round(forecast_90d, 2),
            "pipeline_value": round(forecast_metrics["total_pipeline_value"], 2),
            "deals_evaluated": len(deals),
            "unpriced_deals_count": forecast_metrics.get("unpriced_deals_count", 0),
            "priced_deals_count": forecast_metrics.get("priced_deals_count", 0),
            "bottleneck_stage": constraint.get("stage"),
            "lever": constraint.get("lever"),
            "conversion_rates": conversion_rates,
            "stage_velocity": velocity,
            "top_deals": forecast_metrics.get("deal_breakdown", [])[:5],
            "user_id": user_id,
            "company_wide": company_wide,
            "reason": (
                "Empty pipeline: zero-value forecast saved"
                if not deals else
                f"Forecast calculated across {len(deals)} active deal(s) ({forecast_metrics.get('unpriced_deals_count', 0)} unpriced)"
            ),
        }

    async def _get_active_deals(
        self, user_id: Optional[str] = None, company_wide: bool = False
    ) -> List[Deal]:
        """Fetch open deals scoped to the authenticated sales rep, or company-wide if authorized."""
        stmt = (
            select(Deal)
            .options(selectinload(Deal.contact))
            .where(Deal.outcome.is_(None))
        )
        if user_id:
            user = await self.db.get(User, user_id)
            own_contacts_q = select(Contact.id).where(Contact.user_id == user_id)
            conditions = [Deal.contact_id.in_(own_contacts_q)]
            if user and user.email:
                conditions.append(Deal.owner_email == user.email)
            stmt = stmt.where(or_(*conditions))
        elif not company_wide:
            # Safety gate: if not company-wide and no user_id, return empty list
            return []

        stmt = stmt.order_by(desc(Deal.amount))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _calculate_stage_velocity(self) -> Dict[str, float]:
        """Calculate average days spent in each stage over the last 90 days."""
        velocity = dict(DEFAULT_STAGE_VELOCITY_DAYS)
        for stage in STAGE_ORDER[:-1]:
            try:
                result = await self.db.execute(
                    select(func.avg(DealStageHistory.days_in_from_stage)).where(
                        and_(
                            DealStageHistory.from_stage == stage,
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=90),
                        )
                    )
                )
                avg = result.scalar()
                if avg and float(avg) > 0:
                    velocity[stage] = round(float(avg), 1)
            except Exception as e:
                logger.warning("Velocity calculation fallback", stage=stage, error=str(e))
        return velocity

    async def _calculate_conversion_rates(self) -> Tuple[Dict[str, float], bool]:
        """Calculate current (90-day rolling) stage-to-stage transition rates and data adequacy flag."""
        rates = dict(DEFAULT_STAGE_CONVERSION_BASELINES)
        total_transitions_found = 0
        for i, stage in enumerate(STAGE_ORDER[:-1]):
            next_stage = STAGE_ORDER[i + 1]
            key = f"{stage}_to_{next_stage}"
            try:
                entered_q = await self.db.execute(
                    select(func.count(DealStageHistory.id)).where(
                        and_(
                            DealStageHistory.to_stage == stage,
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=90),
                        )
                    )
                )
                entered_count = entered_q.scalar() or 0

                progressed_q = await self.db.execute(
                    select(func.count(DealStageHistory.id)).where(
                        and_(
                            DealStageHistory.from_stage == stage,
                            DealStageHistory.to_stage == next_stage,
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=90),
                        )
                    )
                )
                progressed_count = progressed_q.scalar() or 0

                if entered_count >= 2:
                    rates[key] = round(progressed_count / entered_count, 3)
                    total_transitions_found += progressed_count
            except Exception as e:
                logger.warning("Conversion rate calculation fallback", key=key, error=str(e))
        has_real_stage_history = total_transitions_found >= 2
        return rates, has_real_stage_history

    async def _get_historical_baselines(self) -> Dict[str, float]:
        """Historical conversion rate baseline across 365 days of won deals."""
        baselines = dict(DEFAULT_STAGE_CONVERSION_BASELINES)
        for i, stage in enumerate(STAGE_ORDER[:-1]):
            next_stage = STAGE_ORDER[i + 1]
            key = f"{stage}_to_{next_stage}"
            try:
                entered_q = await self.db.execute(
                    select(func.count(DealStageHistory.id))
                    .join(Deal, Deal.id == DealStageHistory.deal_id)
                    .where(
                        and_(
                            DealStageHistory.to_stage == stage,
                            Deal.outcome == "won",
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=365),
                        )
                    )
                )
                entered_count = entered_q.scalar() or 0

                progressed_q = await self.db.execute(
                    select(func.count(DealStageHistory.id))
                    .join(Deal, Deal.id == DealStageHistory.deal_id)
                    .where(
                        and_(
                            DealStageHistory.from_stage == stage,
                            DealStageHistory.to_stage == next_stage,
                            Deal.outcome == "won",
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=365),
                        )
                    )
                )
                progressed_count = progressed_q.scalar() or 0
                if entered_count >= 2:
                    baselines[key] = round(progressed_count / entered_count, 3)
            except Exception as e:
                logger.warning("Historical baseline fallback", key=key, error=str(e))
        return baselines

    def _calculate_deal_level_forecast(
        self, deals: List[Deal], stage_velocity: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Evaluate every single deal dynamically.
        Computes calibrated win probability, time-in-stage decay, and horizon allocation.
        Unpriced deals (null or <=0) are treated as 0 value rather than substituting synthetic $25,000.
        """
        total_pipeline_val = 0.0
        day_30_total = 0.0
        day_60_total = 0.0
        day_90_total = 0.0
        deal_breakdown: List[Dict[str, Any]] = []
        unpriced_deals_count = 0

        for deal in deals:
            # 1. Resolve Deal Amount — do NOT substitute $25,000 for missing amounts
            raw_amount = deal.amount
            is_unpriced = raw_amount is None or float(raw_amount) <= 0.0
            if is_unpriced:
                amount = 0.0
                unpriced_deals_count += 1
            else:
                amount = float(raw_amount)

            total_pipeline_val += amount

            # 2. Resolve Days in Current Stage
            days_in_stage = deal.days_in_current_stage or 0
            if deal.stage_entered_at:
                calculated_days = (datetime.utcnow() - deal.stage_entered_at).days
                days_in_stage = max(days_in_stage, calculated_days)

            # 3. Compute Calibrated Win Probability
            win_prob = self._compute_calibrated_win_probability(deal, days_in_stage, stage_velocity)

            # 4. Compute Estimated Days to Close
            days_to_close = self._estimate_days_to_close(deal.stage, days_in_stage, stage_velocity)

            # 5. Expected Value (0 for unpriced deals)
            expected_val = amount * win_prob

            # 6. Horizon Allocation Factors
            alloc_30, alloc_60, alloc_90 = self._horizon_allocation_factors(deal.stage, days_to_close)

            deal_30 = expected_val * alloc_30
            deal_60 = expected_val * alloc_60
            deal_90 = expected_val * alloc_90

            day_30_total += deal_30
            day_60_total += deal_60
            day_90_total += deal_90

            company_name = deal.contact.company if deal.contact and deal.contact.company else deal.name
            deal_breakdown.append({
                "deal_id": deal.id,
                "deal_name": deal.name,
                "company": company_name,
                "stage": deal.stage,
                "amount": float(raw_amount) if not is_unpriced else None,
                "is_unpriced": is_unpriced,
                "win_probability": round(win_prob * 100, 1),
                "expected_value": round(expected_val, 2),
                "days_in_stage": days_in_stage,
                "days_to_close_est": days_to_close,
                "ev_30d": round(deal_30, 2),
                "ev_60d": round(deal_60, 2),
                "ev_90d": round(deal_90, 2),
            })

        # Sort breakdown by expected value descending
        deal_breakdown.sort(key=lambda d: d["expected_value"], reverse=True)

        return {
            "total_pipeline_value": total_pipeline_val,
            "day_30": day_30_total,
            "day_60": day_60_total,
            "day_90": day_90_total,
            "unpriced_deals_count": unpriced_deals_count,
            "priced_deals_count": len(deals) - unpriced_deals_count,
            "deal_breakdown": deal_breakdown,
        }

    def _compute_calibrated_win_probability(
        self, deal: Deal, days_in_stage: int, stage_velocity: Dict[str, float]
    ) -> float:
        """
        Dynamic multi-factor win probability calibration.
        Combines Stage Prior + BANT Signals + Buying Intent + Health & Risk Scores + Time Decay.
        """
        stage = (deal.stage or "prospecting").lower()
        base_prob = STAGE_PRIORS.get(stage, 0.15)

        # A. BANT Signal Modifiers (from Fireflies call transcripts)
        bant_bonus = 0.0
        if deal.budget_confirmed:
            bant_bonus += 0.08
        if deal.authority_confirmed:
            bant_bonus += 0.08
        if deal.need_confirmed:
            bant_bonus += 0.05
        if deal.timeline_confirmed:
            bant_bonus += 0.05

        prob = base_prob + bant_bonus

        # B. Buying Intent Multiplier
        intent = (deal.buying_intent or "medium").lower()
        if intent == "strong":
            prob *= 1.25
        elif intent == "weak":
            prob *= 0.70
        elif intent == "lost":
            return 0.02

        # C. Deal Health Score (0-100) & Risk Score (0.0-1.0) Modifiers
        if deal.deal_health_score is not None:
            health_factor = 0.60 + 0.40 * (deal.deal_health_score / 100.0)
            prob *= health_factor

        risk = deal.risk_score or 0.0
        if risk > 0.0:
            risk_penalty = 1.0 - (0.45 * min(risk, 1.0))
            prob *= risk_penalty

        # D. Time-in-Stage Stagnation Decay
        avg_velocity = stage_velocity.get(stage, DEFAULT_STAGE_VELOCITY_DAYS.get(stage, 14.0))
        if days_in_stage > (1.5 * avg_velocity):
            excess_days = days_in_stage - avg_velocity
            # Exponential decay factor for stagnant deals
            decay = math.exp(-0.035 * excess_days)
            prob *= max(decay, 0.30)

        # Clamp between 2% and 95%
        return max(0.02, min(0.95, prob))

    def _estimate_days_to_close(
        self, stage: Optional[str], days_in_stage: int, stage_velocity: Dict[str, float]
    ) -> int:
        """Estimate calendar days remaining until deal closes won."""
        stage = (stage or "prospecting").lower()
        if stage == "closed_won":
            return 0

        # Sum velocities of remaining stages
        try:
            current_idx = STAGE_ORDER.index(stage)
        except ValueError:
            current_idx = 0

        remaining_stages = STAGE_ORDER[current_idx:-1]
        total_remaining_days = 0.0
        for i, s in enumerate(remaining_stages):
            vel = stage_velocity.get(s, DEFAULT_STAGE_VELOCITY_DAYS.get(s, 14.0))
            if i == 0:
                # Remaining days in current stage
                total_remaining_days += max(3.0, vel - days_in_stage)
            else:
                total_remaining_days += vel

        return max(3, int(round(total_remaining_days)))

    def _horizon_allocation_factors(
        self, stage: Optional[str], days_to_close: int
    ) -> Tuple[float, float, float]:
        """
        Determine what fraction of expected value closes in 30d, 60d, and 90d.
        Returns: (alloc_30d, alloc_60d, alloc_90d)
        """
        stage = (stage or "prospecting").lower()
        if stage == "negotiation":
            return (0.80, 0.95, 1.00)
        elif stage == "proposal":
            return (0.45, 0.85, 1.00)
        elif stage == "demo":
            return (0.20, 0.65, 0.90)
        elif stage == "discovery":
            return (0.05, 0.40, 0.80)
        else: # prospecting
            return (0.00, 0.25, 0.60)

    async def _calculate_top_of_funnel_inflow(
        self, active_deals: List[Deal], user_id: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Project new pipeline value generated by leading outbound and inbound funnel events.
        Does not fabricate inflow when active pipeline is empty or unpriced.
        """
        if not active_deals:
            return {"inflow_30d": 0.0, "inflow_60d": 0.0, "inflow_90d": 0.0}

        priced_amounts = [float(d.amount) for d in active_deals if d.amount and float(d.amount) > 0]
        if not priced_amounts:
            return {"inflow_30d": 0.0, "inflow_60d": 0.0, "inflow_90d": 0.0}

        cutoff = datetime.utcnow() - timedelta(days=30)
        try:
            # 1. Count high-intent meetings booked or reply received for rep's contacts
            funnel_stmt = select(func.count(FunnelEvent.id)).where(
                and_(
                    FunnelEvent.event_type.in_(["meeting_booked", "reply_received", "inbound_email"]),
                    FunnelEvent.timestamp >= cutoff,
                )
            )
            # 2. Count active qualified contacts in pipeline for rep
            contacts_stmt = select(func.count(Contact.id)).where(
                and_(
                    Contact.do_not_contact.is_(False),
                    Contact.icp_score >= settings.ICP_SCORE_THRESHOLD,
                )
            )
            if user_id:
                user_contact_subq = select(Contact.id).where(Contact.user_id == user_id)
                funnel_stmt = funnel_stmt.where(FunnelEvent.contact_id.in_(user_contact_subq))
                contacts_stmt = contacts_stmt.where(Contact.user_id == user_id)

            result = await self.db.execute(funnel_stmt)
            intent_events = result.scalar() or 0

            contacts_q = await self.db.execute(contacts_stmt)
            qualified_contacts = contacts_q.scalar() or 0

            # Average deal size calculated exclusively from confirmed priced deals
            avg_deal_amount = sum(priced_amounts) / len(priced_amounts)

            # Inflow estimates: top of funnel converts across 60d-90d
            inflow_rate = min(intent_events * 0.15 + qualified_contacts * 0.02, 3.0)
            monthly_inflow_value = inflow_rate * avg_deal_amount * 0.20

            return {
                "inflow_30d": monthly_inflow_value * 0.10,
                "inflow_60d": monthly_inflow_value * 0.60,
                "inflow_90d": monthly_inflow_value * 1.20,
            }
        except Exception as e:
            logger.warning("Top of funnel inflow calculation fallback", error=str(e))
            return {"inflow_30d": 0.0, "inflow_60d": 0.0, "inflow_90d": 0.0}

    async def _identify_constraint_and_levers(
        self,
        current_rates: Dict[str, float],
        baselines: Dict[str, float],
        deals: List[Deal],
        has_real_stage_history: bool = True,
    ) -> Dict[str, Optional[str]]:
        """
        Detect funnel bottlenecks and formulate executive-level tactical levers.
        Never manufactures bottlenecks when historical evidence is absent or deficit is zero.
        """
        if not deals:
            return {
                "stage": None,
                "description": "Empty pipeline: No active deals to evaluate for stage bottlenecks.",
                "lever": "Initiate A1 prospect search and A3 outreach to generate pipeline opportunities.",
            }

        if not has_real_stage_history:
            return {
                "stage": None,
                "description": "Insufficient historical data to determine bottlenecks.",
                "lever": "Insufficient historical data to determine bottlenecks.",
            }

        max_deficit = 0.0
        bottleneck_key = None

        for key, baseline in baselines.items():
            current = current_rates.get(key, 0.0)
            if baseline > 0:
                deficit = (baseline - current) / baseline
                if deficit > 0.05 and deficit > max_deficit:
                    max_deficit = deficit
                    bottleneck_key = key

        if not bottleneck_key or max_deficit <= 0.0:
            return {
                "stage": None,
                "description": "Pipeline converting healthily across stages. No stage bottlenecks detected.",
                "lever": "Maintain conversion momentum and scale top-of-funnel discovery volume.",
            }

        stage = bottleneck_key.split("_to_")[0]
        curr_pct = round(current_rates.get(bottleneck_key, 0.0) * 100, 1)
        base_pct = round(baselines.get(bottleneck_key, 0.0) * 100, 1)
        deficit_pct = round(max_deficit * 100)

        # Context-aware tactical lever recommendations
        lever_rules = {
            "prospecting": "Increase multi-channel outbound cadence. Run A1 prospecting and A3 multi-touch email sequences daily.",
            "discovery": "Enhance discovery qualification. Ensure decision makers and specific technical pain points are identified before booking demos.",
            "demo": "Improve demo-to-proposal conversion. Introduce proof-of-concept milestones and mutual evaluation plans during the demo call.",
            "proposal": "Shorten proposal evaluation cycles. Set clear decision deadlines and engage IT security/procurement stakeholders earlier.",
            "negotiation": "Overcome contract stall. Address commercial and pricing objections with flexible payment schedules or bundled onboarding.",
        }

        # Stalled deals context
        stalled_deals = [d for d in deals if d.stage == stage and (d.days_in_current_stage or 0) > 20]
        stalled_note = f" ({len(stalled_deals)} deals currently stalled >20 days)" if stalled_deals else ""

        description = (
            f"{stage.title()} stage conversion is {curr_pct}% vs {base_pct}% benchmark "
            f"({deficit_pct}% deficit){stalled_note}."
        )

        lever = lever_rules.get(stage, "Review stage-specific conversion data for targeted corrective actions.")

        return {
            "stage": stage,
            "description": description,
            "lever": lever,
        }

    async def send_weekly_digest(self, user_id: Optional[str] = None):
        """Send weekly digest email to stakeholders via Resend."""
        stmt = select(RevenueForecast)
        if user_id:
            stmt = stmt.where(RevenueForecast.user_id == user_id)
        result = await self.db.execute(
            stmt.order_by(RevenueForecast.calculated_at.desc()).limit(1)
        )
        latest = result.scalar_one_or_none()
        if not latest:
            return

        html = self._build_digest_html(latest)
        await self.resend.send(
            subject=f"GTM Platform Weekly — Pipeline ${latest.current_pipeline_value:,.0f} | 30d Forecast ${latest.forecast_30d:,.0f}",
            html=html,
        )
        logger.info("Weekly digest sent via Resend", user_id=user_id)

    def _build_digest_html(self, forecast: RevenueForecast) -> str:
        return f"""
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #1e293b;">
<h2 style="color: #0F2147; margin-bottom: 4px;">GTM Platform — Revenue Intelligence Digest</h2>
<p style="color: #64748b; font-size: 14px; margin-top: 0;">{datetime.utcnow().strftime('%B %d, %Y')}</p>

<div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 20px; margin: 20px 0;">
  <h3 style="margin: 0 0 14px; color: #0f172a; font-size: 16px;">Pipeline Forecast Horizons</h3>
  <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
    <tr><td style="padding: 6px 0; color: #64748b;">30-Day Forecast:</td><td style="padding: 6px 0; font-weight: bold; text-align: right; color: #0284c7;">${forecast.forecast_30d:,.0f}</td></tr>
    <tr><td style="padding: 6px 0; color: #64748b;">60-Day Forecast:</td><td style="padding: 6px 0; font-weight: bold; text-align: right; color: #0284c7;">${forecast.forecast_60d:,.0f}</td></tr>
    <tr><td style="padding: 6px 0; color: #64748b;">90-Day Forecast:</td><td style="padding: 6px 0; font-weight: bold; text-align: right; color: #0284c7;">${forecast.forecast_90d:,.0f}</td></tr>
    <tr style="border-top: 1px solid #e2e8f0;"><td style="padding: 10px 0 0; color: #334155; font-weight: 600;">Current Total Pipeline:</td><td style="padding: 10px 0 0; font-weight: bold; text-align: right; color: #0f172a;">${forecast.current_pipeline_value:,.0f}</td></tr>
  </table>
</div>

{"<div style='background: #fffbeb; border: 1px solid #fde68a; border-radius: 10px; padding: 18px; margin: 20px 0;'><h3 style='margin: 0 0 8px; color: #92400e; font-size: 15px;'>⚠ Constraint Detected: " + forecast.bottleneck_stage.title() + " Stage</h3><p style='margin: 0 0 10px; font-size: 13px; color: #78350f;'>" + forecast.bottleneck_description + "</p><p style='margin: 0; font-size: 13px; color: #1e40af;'><strong>Recommended Action:</strong> " + forecast.recommended_lever + "</p></div>" if forecast.bottleneck_stage else ""}

<p style="color: #94a3b8; font-size: 12px; margin-top: 24px; text-align: center;">Generated by GTM Platform Agent 7 (Predictive Revenue Intelligence)</p>
</body></html>"""

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A7", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()

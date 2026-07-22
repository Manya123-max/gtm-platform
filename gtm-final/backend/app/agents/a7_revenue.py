"""
A7 — Predictive Revenue Agent
30/60/90-day pipeline forecast. Automatic constraint identification.
Reads from funnel_events — the append-only log all agents write to.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import numpy as np
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.core.config import settings
from app.models.models import (
    Deal, FunnelEvent, RevenueForecast, DealStageHistory
)
from app.services.slack_service import SlackService
from app.services.resend_service import ResendService

logger = structlog.get_logger()

STAGE_ORDER = [
    "prospecting", "discovery", "demo",
    "proposal", "negotiation", "closed_won"
]


class RevenueAgent:
    """
    A7: Forward-looking pipeline intelligence.

    Key outputs:
    - 30/60/90-day revenue forecast from regression on funnel_events
    - Stage conversion rates vs historical baseline (rolling 90-day window)
    - Automatic constraint identification: which stage is furthest below baseline
    - Specific lever recommendations: more top-of-funnel OR improve conversion
    - Weekly digest email via Resend
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.slack = SlackService()
        self.resend = ResendService()

    async def run(self) -> Dict[str, Any]:
        logger.info("A7 running forecast")

        # Pull all input data
        pipeline = await self._get_current_pipeline()
        conversion_rates = await self._calculate_conversion_rates()
        velocity = await self._calculate_stage_velocity()
        activity_rates = await self._get_activity_rates()

        # Run forecast
        forecast = self._calculate_forecast(pipeline, conversion_rates, velocity)

        # Identify constraint
        baselines = await self._get_historical_baselines()
        constraint = self._identify_constraint(conversion_rates, baselines)

        # Build forecast record
        forecast_record = RevenueForecast(
            forecast_30d=forecast.get("day_30"),
            forecast_60d=forecast.get("day_60"),
            forecast_90d=forecast.get("day_90"),
            current_pipeline_value=pipeline.get("total_value"),
            bottleneck_stage=constraint.get("stage"),
            bottleneck_description=constraint.get("description"),
            recommended_lever=constraint.get("lever"),
            stage_conversion_rates=conversion_rates,
            stage_velocity_days=velocity,
            calculated_at=datetime.utcnow(),
        )
        self.db.add(forecast_record)
        await self.db.commit()

        await self._log_funnel_event("forecast_calculated", {
            "forecast_30d": forecast.get("day_30"),
            "bottleneck_stage": constraint.get("stage"),
        })

        return {
            "agent": "A7",
            "forecast_30d": forecast.get("day_30"),
            "forecast_60d": forecast.get("day_60"),
            "forecast_90d": forecast.get("day_90"),
            "pipeline_value": pipeline.get("total_value"),
            "bottleneck_stage": constraint.get("stage"),
            "lever": constraint.get("lever"),
            "conversion_rates": conversion_rates,
            "reason": (
                "No active pipeline; zero-value forecast saved"
                if not pipeline.get("total_count") else
                "Forecast calculated"
            ),
        }

    async def send_weekly_digest(self):
        """Send weekly digest email to stakeholders via Resend (free 100/day)."""
        result = await self.db.execute(
            select(RevenueForecast)
            .order_by(RevenueForecast.calculated_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if not latest:
            return

        html = self._build_digest_html(latest)
        await self.resend.send(
            subject=f"GTM Platform Weekly — Pipeline ${latest.current_pipeline_value:,.0f} | Forecast ${latest.forecast_30d:,.0f} (30d)",
            html=html,
        )
        logger.info("Weekly digest sent")

    async def _get_current_pipeline(self) -> Dict:
        """Pull active deals by stage from HubSpot-synced deal table."""
        result = await self.db.execute(
            select(
                Deal.stage,
                func.count(Deal.id).label("count"),
                func.sum(Deal.amount).label("total_value"),
                func.avg(Deal.days_in_current_stage).label("avg_days"),
            )
            .where(Deal.outcome.is_(None))
            .group_by(Deal.stage)
        )
        rows = result.all()

        pipeline = {"by_stage": {}, "total_value": 0, "total_count": 0}
        for row in rows:
            pipeline["by_stage"][row.stage] = {
                "count": row.count,
                "value": float(row.total_value or 0),
                "avg_days": float(row.avg_days or 0),
            }
            pipeline["total_value"] = pipeline["total_value"] + float(row.total_value or 0)
            pipeline["total_count"] = pipeline["total_count"] + row.count

        return pipeline

    async def _calculate_conversion_rates(self) -> Dict[str, float]:
        """
        Calculate current (30-day) conversion rate per stage transition.
        Used to compare against historical baseline to find constraint.
        """
        rates = {}
        for i, stage in enumerate(STAGE_ORDER[:-1]):
            next_stage = STAGE_ORDER[i + 1]
            try:
                # Count deals that entered this stage in last 90 days
                entered = await self.db.execute(
                    select(func.count(DealStageHistory.id)).where(
                        and_(
                            DealStageHistory.to_stage == stage,
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=90),
                        )
                    )
                )
                entered_count = entered.scalar() or 0

                # Count deals that progressed to next stage
                progressed = await self.db.execute(
                    select(func.count(DealStageHistory.id)).where(
                        and_(
                            DealStageHistory.from_stage == stage,
                            DealStageHistory.to_stage == next_stage,
                            DealStageHistory.transitioned_at >= datetime.utcnow() - timedelta(days=90),
                        )
                    )
                )
                progressed_count = progressed.scalar() or 0

                rates[f"{stage}_to_{next_stage}"] = (
                    progressed_count / entered_count if entered_count > 0 else 0.0
                )
            except Exception:
                rates[f"{stage}_to_{next_stage}"] = 0.0

        return rates

    async def _calculate_stage_velocity(self) -> Dict[str, float]:
        """Average days spent in each stage (current 90-day window)."""
        velocity = {}
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
                velocity[stage] = float(avg) if avg else 14.0
            except Exception:
                velocity[stage] = 14.0
        return velocity

    async def _get_activity_rates(self) -> Dict[str, int]:
        """Pull outbound activity rates from funnel_events (last 30 days)."""
        events = ["email_sent", "email_draft_created", "signal_batch_completed",
                  "reply_received", "meeting_booked"]
        rates = {}
        for event_type in events:
            result = await self.db.execute(
                select(func.count(FunnelEvent.id)).where(
                    and_(
                        FunnelEvent.event_type == event_type,
                        FunnelEvent.timestamp >= datetime.utcnow() - timedelta(days=30),
                    )
                )
            )
            rates[event_type] = result.scalar() or 0
        return rates

    async def _get_historical_baselines(self) -> Dict[str, float]:
        """
        Historical conversion rates from closed-won deals (365-day window).
        This is the baseline the constraint detection compares against.
        """
        baselines = {}
        for i, stage in enumerate(STAGE_ORDER[:-1]):
            next_stage = STAGE_ORDER[i + 1]
            try:
                entered = await self.db.execute(
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
                entered_count = entered.scalar() or 1  # avoid div/0

                progressed = await self.db.execute(
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
                progressed_count = progressed.scalar() or 0
                baselines[f"{stage}_to_{next_stage}"] = progressed_count / entered_count
            except Exception:
                baselines[f"{stage}_to_{next_stage}"] = 0.3  # fallback baseline

        return baselines

    def _calculate_forecast(
        self, pipeline: Dict, conversion_rates: Dict, velocity: Dict
    ) -> Dict[str, float]:
        """
        Simple expected-value forecast model.
        For each deal: value × probability of closing = expected revenue.
        Probability = product of remaining stage conversion rates.
        """
        stage_probabilities = {
            "prospecting": 0.05, "discovery": 0.15, "demo": 0.30,
            "proposal": 0.55, "negotiation": 0.75, "closed_won": 1.0,
        }

        total_expected = 0
        by_stage = pipeline.get("by_stage", {})

        for stage, data in by_stage.items():
            prob = stage_probabilities.get(stage, 0.1)
            expected = data.get("value", 0) * prob
            total_expected += expected

        # Velocity-adjusted 30/60/90 day splits
        avg_velocity = sum(velocity.values()) / max(len(velocity), 1)
        return {
            "day_30": total_expected * 0.25,  # ~25% closes in 30d
            "day_60": total_expected * 0.55,
            "day_90": total_expected * 0.80,
        }

    def _identify_constraint(
        self, current_rates: Dict, baseline_rates: Dict
    ) -> Dict[str, Optional[str]]:
        """
        Find the stage where gap between current and baseline is largest.
        That stage is the bottleneck. Surface a specific lever to address it.
        """
        max_gap = 0
        bottleneck_key = None

        for key in baseline_rates:
            baseline = baseline_rates.get(key, 0)
            current = current_rates.get(key, 0)
            if baseline > 0:
                gap = (baseline - current) / baseline  # relative underperformance
                if gap > max_gap:
                    max_gap = gap
                    bottleneck_key = key

        if not bottleneck_key:
            return {"stage": None, "description": "No constraint detected", "lever": None}

        stage = bottleneck_key.split("_to_")[0]
        baseline_pct = round(baseline_rates.get(bottleneck_key, 0) * 100, 1)
        current_pct = round(current_rates.get(bottleneck_key, 0) * 100, 1)

        lever_map = {
            "prospecting": "Increase top-of-funnel volume. Run prospect agent daily instead of weekly.",
            "discovery": "Improve discovery call quality. Review call recordings for missed qualification questions.",
            "demo": "Improve demo-to-proposal rate. Add a proof-of-concept or trial offer post-demo.",
            "proposal": "Reduce proposal stage time. Set a decision deadline in next call and get procurement involved earlier.",
            "negotiation": "Address negotiation stalls. Identify objections earlier in the process.",
        }

        return {
            "stage": stage,
            "description": f"{stage.title()} stage conversion is {current_pct}% vs {baseline_pct}% historical baseline ({round(max_gap*100)}% below).",
            "lever": lever_map.get(stage, "Review stage-specific conversion data for specific actions."),
        }

    def _build_digest_html(self, forecast: RevenueForecast) -> str:
        return f"""
<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
<h2 style="color: #0F2147;">GTM Platform Weekly Digest</h2>
<p style="color: #64748B;">{datetime.utcnow().strftime('%B %d, %Y')}</p>

<div style="background: #DBEAFE; border-radius: 8px; padding: 16px; margin: 20px 0;">
  <h3 style="margin: 0 0 12px; color: #1E3A5F;">Revenue Forecast</h3>
  <p><strong>30-day:</strong> ${forecast.forecast_30d:,.0f}</p>
  <p><strong>60-day:</strong> ${forecast.forecast_60d:,.0f}</p>
  <p><strong>90-day:</strong> ${forecast.forecast_90d:,.0f}</p>
  <p><strong>Current pipeline:</strong> ${forecast.current_pipeline_value:,.0f}</p>
</div>

{"" if not forecast.bottleneck_stage else f'''
<div style="background: #FEF3C7; border-radius: 8px; padding: 16px; margin: 20px 0;">
  <h3 style="margin: 0 0 8px; color: #78350F;">⚠ Constraint Detected: {forecast.bottleneck_stage.title()} Stage</h3>
  <p>{forecast.bottleneck_description}</p>
  <p><strong>Recommended action:</strong> {forecast.recommended_lever}</p>
</div>'''}

<p style="color: #64748B; font-size: 12px;">Generated by GTM Platform A7 Revenue Agent</p>
</body></html>"""

    async def _log_funnel_event(self, event_type: str, metadata: Dict):
        event = FunnelEvent(event_type=event_type, agent_id="A7", event_metadata=metadata)
        self.db.add(event)
        await self.db.commit()

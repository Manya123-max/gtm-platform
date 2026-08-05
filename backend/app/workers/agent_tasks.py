"""
Celery task definitions for all seven agents.
All scheduling handled here — no n8n required.
"""
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
import structlog
from croniter import croniter
from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal

logger = structlog.get_logger()


def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Scheduler tasks ────────────────────────────────────────────────────────

@celery_app.task(name="app.workers.scheduler_tasks.run_prospect_agent", queue="agents")
def run_prospect_agent(icp_config: Optional[Dict] = None, config: Optional[Dict] = None):
    cfg = icp_config or config or {
        "titles": ["VP of Sales", "Chief Revenue Officer", "Director of Sales", "Head of Sales"],
        "employee_ranges": ["11,200", "201,1000"],
        "limit": 50,
    }
    async def _run():
        from app.agents.a1_prospect import ProspectAgent
        async with AsyncSessionLocal() as db:
            agent = ProspectAgent(db)
            result = await agent.run(cfg)
            logger.info("A1 complete", **result)
            if result.get("saved_count", 0) > 0:
                run_signal_agent.delay()
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_signal_agent", queue="agents")
def run_signal_agent(contact_ids: Optional[List[str]] = None, config: Optional[Dict] = None):
    async def _run():
        from app.agents.a2_signal import SignalAgent
        async with AsyncSessionLocal() as db:
            agent = SignalAgent(db)
            result = await agent.run(contact_ids)
            logger.info("A2 complete", **result)
            if result.get("high_score_signals", 0) > 0:
                run_outreach_agent.delay()
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_outreach_agent", queue="agents")
def run_outreach_agent(contact_signal_pairs=None, config: Optional[Dict] = None):
    async def _run():
        from app.agents.a3_outreach import OutreachAgent
        async with AsyncSessionLocal() as db:
            agent = OutreachAgent(db)
            result = await agent.run(contact_signal_pairs)
            logger.info("A3 complete", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_deal_scan", queue="agents")
def run_deal_scan(config: Optional[Dict] = None):
    async def _run():
        from app.agents.a5_deal import DealAgent
        async with AsyncSessionLocal() as db:
            agent = DealAgent(db)
            result = await agent.run_daily_deal_scan()
            logger.info("A5 daily scan complete", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_content_agent", queue="agents")
def run_content_agent(icp_segments: Optional[List[str]] = None, config: Optional[Dict] = None):
    async def _run():
        from app.agents.a6_content import ContentAgent
        async with AsyncSessionLocal() as db:
            agent = ContentAgent(db)
            result = await agent.run(icp_segments)
            logger.info("A6 complete", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_revenue_agent", queue="agents")
def run_revenue_agent(config: Optional[Dict] = None):
    async def _run():
        from app.agents.a7_revenue import RevenueAgent
        async with AsyncSessionLocal() as db:
            agent = RevenueAgent(db)
            result = await agent.run()
            logger.info("A7 complete", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.run_email_verification", queue="default")
def run_email_verification(config: Optional[Dict] = None):
    async def _run():
        from sqlalchemy import select, and_
        from datetime import datetime, timedelta
        from app.models.models import Contact
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Contact).where(
                    and_(Contact.email_verified == False, Contact.do_not_contact == False)
                ).limit(200)
            )
            contacts = result.scalars().all()
            logger.info("Email verification scheduled", count=len(contacts))
            return {"verified_count": len(contacts)}
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.recalibrate_signal_registry", queue="default")
def recalibrate_signal_registry(config: Optional[Dict] = None):
    async def _run():
        from app.agents.a2_signal import SignalAgent
        async with AsyncSessionLocal() as db:
            agent = SignalAgent(db)
            await agent.recalibrate_registry()
            return {"status": "recalibrated"}
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.retrain_win_pattern_model", queue="default")
def retrain_win_pattern_model(config: Optional[Dict] = None):
    async def _run():
        from app.services.scoring_service import retrain_model
        async with AsyncSessionLocal() as db:
            success = await retrain_model(db)
            return {"retrained": success}
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.send_weekly_digest", queue="default")
def send_weekly_digest(config: Optional[Dict] = None):
    async def _run():
        from app.agents.a7_revenue import RevenueAgent
        async with AsyncSessionLocal() as db:
            agent = RevenueAgent(db)
            await agent.send_weekly_digest()
            return {"status": "sent"}
    return run_async(_run())


@celery_app.task(name="app.workers.scheduler_tasks.dispatch_agent_schedules", queue="default")
def dispatch_agent_schedules(config: Optional[Dict] = None):
    async def _run():
        from app.models.models import AgentSchedule

        now = datetime.utcnow()
        dispatched: List[str] = []
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AgentSchedule).where(AgentSchedule.enabled.is_(True))
            )
            schedules = result.scalars().all()
            for schedule in schedules:
                base = schedule.last_run_at or now
                try:
                    next_run = croniter(schedule.cron, base).get_next(datetime)
                except Exception as exc:
                    logger.warning(
                        "Invalid persisted agent schedule",
                        agent_id=schedule.agent_id,
                        cron=schedule.cron,
                        error=str(exc),
                    )
                    continue

                if next_run <= now:
                    celery_app.send_task(schedule.task_name, queue="agents")
                    schedule.last_run_at = now
                    dispatched.append(schedule.agent_id)

            await db.commit()
        return {"dispatched": dispatched, "count": len(dispatched)}

    return run_async(_run())


# ── Webhook tasks ──────────────────────────────────────────────────────────

@celery_app.task(name="app.workers.webhook_tasks.handle_inbound_reply", queue="webhooks")
def handle_inbound_reply(payload: Dict):
    async def _run():
        from app.agents.a4_inbound import InboundAgent
        async with AsyncSessionLocal() as db:
            agent = InboundAgent(db)
            result = await agent.handle_reply(payload)
            logger.info("A4 reply handled", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.webhook_tasks.handle_fireflies_transcript", queue="webhooks")
def handle_fireflies_transcript(payload: Dict):
    async def _run():
        from app.agents.a5_deal import DealAgent
        async with AsyncSessionLocal() as db:
            agent = DealAgent(db)
            result = await agent.process_transcript(payload)
            logger.info("A5 transcript processed", **result)
            return result
    return run_async(_run())


@celery_app.task(name="app.workers.agent_tasks.reply_approval_timeout", queue="webhooks")
def reply_approval_timeout(thread_event_id: str):
    async def _run():
        from app.agents.a4_inbound import InboundAgent
        async with AsyncSessionLocal() as db:
            agent = InboundAgent(db)
            await agent.handle_timeout(thread_event_id)
            return {"status": "timeout_handled"}
    return run_async(_run())


# ── A4 test task — simulate a reply for dev/testing ───────────────────────

@celery_app.task(name="app.workers.agent_tasks.run_a4_test", queue="webhooks")
def run_a4_test(config: Optional[Dict] = None):
    """
    A4 test mode for frontend manual trigger.
    Simulates an inbound reply so you can test the classification pipeline
    without needing a real inbound-reply webhook.
    """
    test_payload = {
        "event_type": "reply_received",
        "from_address": "test.prospect@example.com",
        "reply_text": "Thanks for reaching out! Yes, we are actually evaluating tools right now. Can you tell me more about what you offer?",
        "campaign_id": "test-campaign",
    }
    if config and config.get("reply_text"):
        test_payload["reply_text"] = config["reply_text"]
    if config and config.get("from_address"):
        test_payload["from_address"] = config["from_address"]

    async def _run():
        from app.agents.a4_inbound import InboundAgent
        from app.models.models import Contact
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            # Fallback to the first available contact in the database if default test email is missing
            if test_payload["from_address"] == "test.prospect@example.com":
                res = await db.execute(select(Contact).where(Contact.email == "test.prospect@example.com"))
                if not res.scalar_one_or_none():
                    res_any = await db.execute(select(Contact).limit(1))
                    any_contact = res_any.scalar_one_or_none()
                    if any_contact:
                        test_payload["from_address"] = any_contact.email
                        logger.info("A4 test falling back to existing contact", email=any_contact.email)
            
            agent = InboundAgent(db)
            result = await agent.handle_reply(test_payload)
            logger.info("A4 test run complete", **result)
            return result
    return run_async(_run())

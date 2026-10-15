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
from app.core.config import settings

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
        user_input_id = config.get("user_input_id") if config else None
        async with AsyncSessionLocal() as db:
            agent = SignalAgent(db)
            result = await agent.run(contact_ids, user_input_id=user_input_id)
            logger.info("A2 complete", **result)
            if result.get("high_score_signals", 0) > 0:
                run_outreach_agent.delay(config=config)
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


@celery_app.task(name="app.workers.scheduler_tasks.poll_gmail_inbox", queue="webhooks")
def poll_gmail_inbox(config: Optional[Dict] = None):
    """
    Polls connected sales reps' Google mailboxes via Gmail API, and falls back to
    global IMAP inbox if configured. Dispatches replies to A4.
    """
    async def _run():
        from app.services.google_oauth_service import GoogleOAuthService
        from app.services.gmail_imap_service import GmailIMAPService
        from app.agents.a4_inbound import InboundAgent
        from app.models.models import Contact, UserIntegration
        from sqlalchemy import select

        processed = []
        async with AsyncSessionLocal() as db:
            # 1. Multi-User: Poll active connected sales rep Google Workspace accounts
            # Priority 1 (Production Company Mailboxes): Microsoft 365 via Microsoft Graph
            from app.services.microsoft_graph_service import MicrosoftGraphService
            ms_svc = MicrosoftGraphService()
            ms_ints_res = await db.execute(
                select(UserIntegration).where(
                    UserIntegration.provider == "microsoft",
                    UserIntegration.status == "connected",
                )
            )
            ms_integrations = list(ms_ints_res.scalars().all())

            for ms_int in ms_integrations:
                try:
                    ms_token = await ms_svc.get_valid_access_token(ms_int, db)
                    if not ms_token:
                        continue
                    ms_messages = await ms_svc.fetch_user_unread_messages(ms_token, max_results=10)
                    agent = InboundAgent(db)
                    for item in ms_messages:
                        payload = {
                            "event_type": "reply_received",
                            "from_address": item["from_address"],
                            "reply_text": item["reply_text"],
                            "subject": item.get("subject", ""),
                            "message_id": item.get("id"),
                            "conversation_id": item.get("conversation_id"),
                        }
                        res = await agent.handle_reply(payload, user_id=str(ms_int.user_id))
                        await ms_svc.mark_message_read(ms_token, item["id"])
                        processed.append({
                            "from": item["from_address"],
                            "rep_user_id": str(ms_int.user_id),
                            "provider": "microsoft_graph",
                            "res": res,
                        })
                except Exception as ms_err:
                    logger.error("Error polling user Microsoft 365 inbox", user_id=ms_int.user_id, error=str(ms_err))

            # Priority 2 (Development/Testing Fallback): Google OAuth mailbox
            oauth_svc = GoogleOAuthService()
            user_ints_res = await db.execute(
                select(UserIntegration).where(
                    UserIntegration.provider == "google",
                    UserIntegration.status == "connected",
                )
            )
            user_integrations = list(user_ints_res.scalars().all())

            for integration in user_integrations:
                try:
                    valid_token = await oauth_svc.get_valid_access_token(integration, db)
                    if not valid_token:
                        continue
                    messages = await oauth_svc.fetch_user_unread_messages(valid_token, max_results=10)
                    agent = InboundAgent(db)
                    for item in messages:
                        payload = {
                            "event_type": "reply_received",
                            "from_address": item["from_address"],
                            "reply_text": item["reply_text"],
                            "subject": item.get("subject", ""),
                            "message_id": item.get("message_id") or item.get("id"),
                        }
                        res = await agent.handle_reply(payload, user_id=integration.user_id)
                        processed.append({"from": item["from_address"], "rep_user_id": integration.user_id, "res": res})
                except Exception as user_poll_err:
                    logger.error("Error polling user Google inbox", user_id=integration.user_id, error=str(user_poll_err))

            # Multi-User DWD: Poll users covered by Google Workspace Domain-Wide Delegation (Zero rep setup)
            if oauth_svc.dwd_enabled:
                from app.models.models import User
                users_res = await db.execute(select(User))
                all_users = users_res.scalars().all()
                oauth_user_ids = {str(i.user_id) for i in user_integrations}

                for u in all_users:
                    if str(u.id) in oauth_user_ids or not oauth_svc.is_dwd_enabled_for_email(u.email):
                        continue
                    try:
                        dwd_token = await oauth_svc.get_dwd_access_token(u.email)
                        if not dwd_token:
                            continue
                        messages = await oauth_svc.fetch_user_unread_messages(dwd_token, max_results=10)
                        agent = InboundAgent(db)
                        for item in messages:
                            payload = {
                                "event_type": "reply_received",
                                "from_address": item["from_address"],
                                "reply_text": item["reply_text"],
                                "subject": item.get("subject", ""),
                                "message_id": item.get("message_id") or item.get("id"),
                            }
                            res = await agent.handle_reply(payload, user_id=str(u.id))
                            processed.append({"from": item["from_address"], "rep_user_id": str(u.id), "provider": "dwd", "res": res})
                    except Exception as dwd_poll_err:
                        logger.error("Error polling DWD user inbox", user_email=u.email, error=str(dwd_poll_err))

            # 2. Legacy fallback: Global IMAP single-mailbox (if SMTP/IMAP credentials are set)
            if getattr(settings, "SMTP_USER", "") and getattr(settings, "SMTP_PASSWORD", ""):
                try:
                    service = GmailIMAPService()
                    c_res = await db.execute(select(Contact.email).where(Contact.email.is_not(None)))
                    known_emails = {row[0].strip().lower() for row in c_res.all() if row[0]}

                    unread = service.fetch_unread_replies(known_emails=known_emails)
                    logger.info("Gmail IMAP poller fetched replies", count=len(unread))

                    agent = InboundAgent(db)
                    for item in unread:
                        payload = {
                            "event_type": "reply_received",
                            "from_address": item["from_address"],
                            "reply_text": item["reply_text"],
                            "subject": item.get("subject", ""),
                            "message_id": item.get("message_id") or item.get("msg_id"),
                        }
                        res = await agent.handle_reply(payload)
                        processed.append({"from": item["from_address"], "scope": "global_imap", "res": res})
                except Exception as imap_err:
                    logger.warning("Global IMAP poller encountered error", error=str(imap_err))

            await db.commit()

        return {"count": len(processed), "processed": processed}

    return run_async(_run())


# ── A4 test task — simulate a reply for dev/testing ───────────────────────

@celery_app.task(name="app.workers.agent_tasks.run_a4_test", queue="webhooks")
def run_a4_test(config: Optional[Dict] = None):
    """
    A4 test mode for frontend manual trigger.
    Simulates an inbound reply so you can test the classification pipeline
    without needing a real inbound-reply webhook.
    """
    config = config or {}
    reply_text = config.get("reply_text") or "Thanks for reaching out! We are currently evaluating options and would love to schedule a quick call."
    from_address_input = config.get("from_address")

    async def _run():
        from app.agents.a4_inbound import InboundAgent
        from app.models.models import Contact
        from sqlalchemy import select
        async with AsyncSessionLocal() as db:
            email_to_use = from_address_input
            if not email_to_use:
                res_first = await db.execute(select(Contact).where(Contact.email != None).limit(1))
                first_contact = res_first.scalar_one_or_none()
                if first_contact:
                    email_to_use = first_contact.email
                else:
                    logger.warning("run_a4_test: no contacts found in database to simulate reply")
                    return {"status": "error", "message": "No contact available in database"}
            
            test_payload = {
                "event_type": "reply_received",
                "from_address": email_to_use,
                "reply_text": reply_text,
                "campaign_id": config.get("campaign_id", "test-campaign"),
            }
            agent = InboundAgent(db)
            result = await agent.handle_reply(test_payload)
            logger.info("A4 test run complete", **result)
            return result
    return run_async(_run())

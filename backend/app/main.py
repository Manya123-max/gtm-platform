"""
FastAPI main application.
All webhook ingestion, REST API for frontend, Slack action handlers.
"""
import json
import hmac
import hashlib
from contextlib import asynccontextmanager
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import structlog
 
from app.core.config import settings
from app.core.database import init_db, close_db, get_db
from app.api.v1 import router as api_router
 
logger = structlog.get_logger()
 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    await init_db()
    logger.info("GTM Platform started", env=settings.APP_ENV)
    yield
    await close_db()
    logger.info("GTM Platform stopped")
 
 
app = FastAPI(
    title="GTM Agent Platform",
    description="7-agent GTM automation platform with shared Prospect Intelligence Graph",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)
 
@app.get("/")
async def root():
    return {"message": "GTM Platform API Running"}
 
# ── CORS ──────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# ── API Routes ────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")
 
 
# ── Input Schema (new) ───────────────────────────────────────────────────
 
class InputData(BaseModel):
    our_company_name:    str
    our_services:        str
    target_location:     str
    target_industries:   str = ""
    target_company_size: str
    target_keywords:     str = ""
    target_job_titles:   str


@app.post("/submit-input")
async def submit_input(data: InputData):
    """
    Accepts structured company/lead input from the frontend and persists it.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import UserInput
 
    async with AsyncSessionLocal() as db:
        record = UserInput(
            our_company_name=    data.our_company_name,
            our_services=        data.our_services,
            target_location=     data.target_location,
            target_industries=   data.target_industries or None,
            target_company_size= data.target_company_size,
            target_keywords=     data.target_keywords or None,
            target_job_titles=   data.target_job_titles,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
 
    return {"message": "Input received", "id": record.id}
# ── Webhook Routes ────────────────────────────────────────────────────────
 
@app.post("/webhook/inbound-reply")
async def inbound_reply_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Provider-agnostic inbound email-reply webhook. Fires on every reply,
    open, unsubscribe. Validates HMAC signature. Pushes to Celery worker
    immediately. Returns 200 in < 10ms.
    """
    body = await request.body()
 
    # Validate signature if secret is configured
    if settings.INBOUND_WEBHOOK_SECRET:
        sig = request.headers.get("X-Inbound-Signature", "")
        expected = hmac.new(
            settings.INBOUND_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")
 
    payload = json.loads(body)
    event_type = payload.get("event_type", "")
 
    if event_type == "reply_received":
        from app.workers.agent_tasks import handle_inbound_reply
        background_tasks.add_task(
            lambda: handle_inbound_reply.apply_async(args=[payload], queue="webhooks")
        )
 
    elif event_type == "unsubscribed":
        background_tasks.add_task(_handle_unsubscribe, payload.get("email", ""))
 
    return {"status": "received", "event_type": event_type}
 
 
@app.post("/webhook/fireflies")
async def fireflies_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Fireflies transcript webhook. Fires when meeting transcript is ready.
    """
    body = await request.body()
 
    if settings.FIREFLIES_WEBHOOK_SECRET:
        sig = request.headers.get("X-Fireflies-Signature", "")
        expected = hmac.new(
            settings.FIREFLIES_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")
 
    payload = json.loads(body)
 
    from app.workers.agent_tasks import handle_fireflies_transcript
    background_tasks.add_task(
        lambda: handle_fireflies_transcript.apply_async(args=[payload], queue="webhooks")
    )
 
    return {"status": "received"}
 
 
@app.post("/webhook/slack/actions")
async def slack_actions(request: Request, background_tasks: BackgroundTasks):
    """
    Slack interactive actions (button clicks).
    Handles approve/reject for reply drafts and CRM actions.
    """
    body = await request.body()
 
    # Slack signature verification
    if settings.SLACK_SIGNING_SECRET:
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        slack_sig = request.headers.get("X-Slack-Signature", "")
        sig_base = f"v0:{timestamp}:{body.decode()}"
        expected = "v0=" + hmac.new(
            settings.SLACK_SIGNING_SECRET.encode(),
            sig_base.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(slack_sig, expected):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")
 
    # Parse URL-encoded payload
    from urllib.parse import parse_qs
    parsed = parse_qs(body.decode())
    payload = json.loads(parsed.get("payload", ["{}"])[0])
 
    actions = payload.get("actions", [])
    user = payload.get("user", {}).get("email", "unknown")
 
    for action in actions:
        action_id = action.get("action_id")
        value = action.get("value")
 
        if action_id == "approve_reply":
            background_tasks.add_task(_approve_reply, value, user)
        elif action_id == "reject_reply":
            logger.info("Reply rejected", thread_event_id=value, by=user)
        elif action_id == "approve_crm_action":
            background_tasks.add_task(_approve_crm_action, value, user)
 
    return JSONResponse({"text": "✓ Action received"})
 
 
@app.get("/health")
async def health():
    return {"status": "healthy", "env": settings.APP_ENV}
 
 
# ── Background task helpers ───────────────────────────────────────────────
 
async def _handle_unsubscribe(email: str):
    """Mark contact as do_not_contact in PIG."""
    if not email:
        return
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.models import Contact
 
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Contact).where(Contact.email == email))
        contact = result.scalar_one_or_none()
        if contact:
            contact.do_not_contact = True
            await db.commit()
            logger.info("Contact marked DNC", email=email)
 
 
async def _approve_reply(thread_event_id: str, approved_by: str):
    from app.core.database import AsyncSessionLocal
    from app.agents.a4_inbound import InboundAgent
 
    async with AsyncSessionLocal() as db:
        agent = InboundAgent(db)
        await agent.approve_reply(thread_event_id, approved_by)
 
 
async def _approve_crm_action(action_id: str, approved_by: str):
    from app.core.database import AsyncSessionLocal
    from sqlalchemy import select
    from app.models.models import PendingAction, ActionStatus
    from datetime import datetime
 
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
        action = result.scalar_one_or_none()
        if action and action.status == ActionStatus.PENDING:
            action.status = ActionStatus.APPROVED
            action.approved_by = approved_by
            action.approved_at = datetime.utcnow()
            await db.commit()
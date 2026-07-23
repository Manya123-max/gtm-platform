"""
REST API v1 — all endpoints consumed by the React frontend.
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.core.config import settings
from app.models.models import (
    Contact, SignalEvent, OutreachLog, ConversationThread,
    Deal, FunnelEvent, GeneratedContent, RevenueForecast,
    PendingAction, ActionStatus, SignalConversionRegistry,
    PromptVariant, WorkflowRun, AgentSchedule
)

router = APIRouter()


# ── Pydantic response models ───────────────────────────────────────────────

class ContactOut(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    icp_score: Optional[float] = None
    signal_score: Optional[float] = None
    readiness_score: float = 0.0
    do_not_contact: bool = False
    email_valid: Optional[bool] = None
    signal_type: Optional[str] = None
    latest_signal_at: Optional[datetime] = None
    created_at: datetime
    class Config:
        from_attributes = True


class DealOut(BaseModel):
    id: str
    name: str
    stage: str
    amount: Optional[float] = None
    risk_score: float = 0.0
    days_in_current_stage: int = 0
    risk_flags: Optional[list] = None
    budget_confirmed: Optional[bool] = None
    authority_confirmed: Optional[bool] = None
    need_confirmed: Optional[bool] = None
    timeline_confirmed: Optional[bool] = None
    owner_email: Optional[str] = None
    updated_at: datetime
    class Config:
        from_attributes = True


class ForecastOut(BaseModel):
    forecast_30d: Optional[float] = None
    forecast_60d: Optional[float] = None
    forecast_90d: Optional[float] = None
    current_pipeline_value: Optional[float] = None
    bottleneck_stage: Optional[str] = None
    bottleneck_description: Optional[str] = None
    recommended_lever: Optional[str] = None
    stage_conversion_rates: Optional[dict] = None
    stage_velocity_days: Optional[dict] = None
    calculated_at: datetime
    class Config:
        from_attributes = True


class AgentRunRequest(BaseModel):
    agent: str
    config: Optional[Dict[str, Any]] = None


class ApproveActionRequest(BaseModel):
    approved_by: str


class OrchestratorAgentRunRequest(BaseModel):
    agent_id: str
    payload: Optional[Dict[str, Any]] = None


class OrchestratorWorkflowRunRequest(BaseModel):
    workflow_name: str = "manual_full_gtm"
    agent_ids: Optional[List[str]] = None
    payload: Optional[Dict[str, Any]] = None


# ── Dashboard ──────────────────────────────────────────────────────────────

@router.get("/active-session")
async def get_active_session(db: AsyncSession = Depends(get_db)):
    """Returns the most recent user_input id — the current active session."""
    from app.models.models import UserInput
    result = await db.execute(select(UserInput.id).order_by(UserInput.id.desc()).limit(1))
    row = result.scalar_one_or_none()
    return {"user_input_id": row}


@router.get("/sessions/{session_id}")
async def get_session_details(session_id: int, db: AsyncSession = Depends(get_db)):
    """Returns details for a specific user input session."""
    from app.models.models import UserInput
    result = await db.execute(select(UserInput).where(UserInput.id == session_id))
    row = result.scalar_one_or_none()
    if not row:
        return {"error": "Session not found"}, 404
    return {
        "id": row.id,
        "our_company_name": row.our_company_name,
        "our_services": row.our_services,
    }


@router.get("/dashboard/overview")
async def get_dashboard_overview(
    user_input_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Base contact filter
    contact_filter = [Contact.do_not_contact == False]
    if user_input_id is not None:
        contact_filter.append(Contact.user_input_id == user_input_id)

    total_contacts = await db.scalar(
        select(func.count(Contact.id)).where(and_(*contact_filter))
    ) or 0
    qualified = await db.scalar(
        select(func.count(Contact.id)).where(
            and_(*contact_filter, Contact.icp_score >= settings.ICP_SCORE_THRESHOLD)
        )
    ) or 0

    # Signal / outreach scoped to session contacts
    contact_ids_q = select(Contact.id).where(and_(*contact_filter))
    active_signals = await db.scalar(
        select(func.count(SignalEvent.id)).where(
            and_(SignalEvent.processed == False,
                 SignalEvent.detected_at >= thirty_days_ago,
                 SignalEvent.contact_id.in_(contact_ids_q))
        )
    ) or 0
    emails_sent = await db.scalar(
        select(func.count(OutreachLog.id)).where(
            and_(OutreachLog.sent_at >= thirty_days_ago,
                 OutreachLog.contact_id.in_(contact_ids_q))
        )
    ) or 0
    replies = await db.scalar(
        select(func.count(OutreachLog.id)).where(
            and_(OutreachLog.replied == True,
                 OutreachLog.sent_at >= thirty_days_ago,
                 OutreachLog.contact_id.in_(contact_ids_q))
        )
    ) or 0
    meetings = await db.scalar(
        select(func.count(OutreachLog.id)).where(
            and_(OutreachLog.meeting_booked == True,
                 OutreachLog.sent_at >= thirty_days_ago,
                 OutreachLog.contact_id.in_(contact_ids_q))
        )
    ) or 0

    # Deals scoped to session contacts
    deal_filter = [Deal.outcome.is_(None)]
    if user_input_id is not None:
        deal_filter.append(Deal.contact_id.in_(contact_ids_q))
    pipeline_value = await db.scalar(
        select(func.sum(Deal.amount)).where(and_(*deal_filter))
    ) or 0

    pending_actions = await db.scalar(
        select(func.count(PendingAction.id)).where(
            PendingAction.status == ActionStatus.PENDING)
    ) or 0

    forecast_result = await db.execute(
        select(RevenueForecast).order_by(desc(RevenueForecast.calculated_at)).limit(1))
    forecast = forecast_result.scalar_one_or_none()

    return {
        "prospects": {"total": total_contacts, "qualified": qualified, "active_signals": active_signals},
        "outreach_30d": {
            "sent": emails_sent, "replies": replies, "meetings": meetings,
            "reply_rate": round(replies / max(emails_sent, 1) * 100, 1),
            "meeting_rate": round(meetings / max(emails_sent, 1) * 100, 1),
        },
        "pipeline": {
            "value": float(pipeline_value),
            "forecast_30d": float(forecast.forecast_30d or 0) if forecast else 0,
            "bottleneck": forecast.bottleneck_stage if forecast else None,
        },
        "pending_actions": pending_actions,
    }


# ── Contacts ───────────────────────────────────────────────────────────────

@router.get("/contacts", response_model=List[ContactOut])
async def list_contacts(
    skip: int = 0, limit: int = 100,
    min_score: Optional[float] = None,
    has_signal: Optional[bool] = None,
    do_not_contact: Optional[bool] = False,
    sort_by: str = "newest",
    user_input_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Contact).where(Contact.do_not_contact == do_not_contact)
    if user_input_id is not None:
        q = q.where(Contact.user_input_id == user_input_id)
    if min_score is not None:
        q = q.where(Contact.icp_score >= min_score)
    if has_signal:
        q = q.where(Contact.signal_score.isnot(None))
    if sort_by == "score":
        q = q.order_by(desc(Contact.icp_score), desc(Contact.created_at))
    else:
        q = q.order_by(desc(Contact.created_at), desc(Contact.icp_score))
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.get("/contacts/{contact_id}/thread")
async def get_contact_thread(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import asc
    result = await db.execute(
        select(ConversationThread)
        .where(ConversationThread.contact_id == contact_id)
        .order_by(asc(ConversationThread.occurred_at))
    )
    return result.scalars().all()


@router.get("/contacts/{contact_id}/signals")
async def get_contact_signals(contact_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SignalEvent)
        .where(SignalEvent.contact_id == contact_id)
        .order_by(desc(SignalEvent.detected_at))
    )
    return result.scalars().all()


# ── Deals ──────────────────────────────────────────────────────────────────

@router.get("/deals", response_model=List[DealOut])
async def list_deals(
    stage: Optional[str] = None, min_risk: Optional[float] = None,
    user_input_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Deal).where(Deal.outcome.is_(None))
    if user_input_id is not None:
        contact_ids_q = select(Contact.id).where(Contact.user_input_id == user_input_id)
        q = q.where(Deal.contact_id.in_(contact_ids_q))
    if stage:
        q = q.where(Deal.stage == stage)
    if min_risk is not None:
        q = q.where(Deal.risk_score >= min_risk)
    q = q.order_by(desc(Deal.risk_score))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/deals/pipeline-summary")
async def get_pipeline_summary(
    user_input_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    base = select(Deal).where(Deal.outcome.is_(None))
    if user_input_id is not None:
        contact_ids_q = select(Contact.id).where(Contact.user_input_id == user_input_id)
        base = base.where(Deal.contact_id.in_(contact_ids_q))
    result = await db.execute(
        select(Deal.stage, func.count(Deal.id).label("count"),
               func.sum(Deal.amount).label("value"),
               func.avg(Deal.days_in_current_stage).label("avg_days"),
               func.avg(Deal.risk_score).label("avg_risk"))
        .where(Deal.outcome.is_(None))
        .where(*([] if user_input_id is None else [Deal.contact_id.in_(select(Contact.id).where(Contact.user_input_id == user_input_id))]))
        .group_by(Deal.stage)
    )
    return [{"stage": r.stage, "count": r.count, "value": float(r.value or 0),
             "avg_days": float(r.avg_days or 0), "avg_risk": float(r.avg_risk or 0)}
            for r in result.all()]


# ── Pending Actions ────────────────────────────────────────────────────────

@router.get("/pending-actions")
async def list_pending_actions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PendingAction).where(PendingAction.status == ActionStatus.PENDING)
        .order_by(desc(PendingAction.created_at)).limit(50)
    )
    return result.scalars().all()


@router.post("/pending-actions/{action_id}/approve")
async def approve_action(
    action_id: str, body: ApproveActionRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404)
    action.status = ActionStatus.APPROVED
    action.approved_by = body.approved_by
    action.approved_at = datetime.utcnow()
    await db.commit()
    return {"status": "approved"}


@router.post("/pending-actions/{action_id}/dismiss")
async def dismiss_action(action_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404)
    action.status = ActionStatus.DISMISSED
    await db.commit()
    return {"status": "dismissed"}


# ── Revenue ────────────────────────────────────────────────────────────────

@router.get("/revenue/forecast", response_model=ForecastOut)
async def get_latest_forecast(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RevenueForecast).order_by(desc(RevenueForecast.calculated_at)).limit(1))
    forecast = result.scalar_one_or_none()
    if not forecast:
        raise HTTPException(status_code=404, detail="No forecast yet — run A7")
    return forecast


@router.get("/revenue/funnel-metrics")
async def get_funnel_metrics(
    days: int = Query(30, ge=7, le=365), db: AsyncSession = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(FunnelEvent.event_type, func.count(FunnelEvent.id).label("count"))
        .where(FunnelEvent.timestamp >= since)
        .group_by(FunnelEvent.event_type)
    )
    return {row.event_type: row.count for row in result.all()}


# ── Content ────────────────────────────────────────────────────────────────

@router.get("/content")
async def list_content(
    format: Optional[str] = None, icp_segment: Optional[str] = None,
    user_input_id: Optional[int] = None,
    limit: int = 20, db: AsyncSession = Depends(get_db)):
    from app.models.models import UserInput
    q = select(GeneratedContent)
    if format:
        q = q.where(GeneratedContent.content_format == format)
    if icp_segment:
        q = q.where(GeneratedContent.icp_segment == icp_segment)
    elif user_input_id is not None:
        # Filter by icp_segment matching company_name of that input
        ui_result = await db.execute(select(UserInput).where(UserInput.id == user_input_id))
        ui = ui_result.scalar_one_or_none()
        if ui:
            q = q.where(GeneratedContent.icp_segment.ilike(f"%{ui.company_name}%"))
    q = q.order_by(desc(GeneratedContent.created_at)).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


# ── Agents — manual trigger ────────────────────────────────────────────────

@router.post("/agents/run")
async def run_agent_manually(body: AgentRunRequest, background_tasks: BackgroundTasks):
    """
    Trigger any agent manually from the frontend.
    A4 (Inbound) is webhook-only — use /webhook/inbound-reply instead.
    """
    from app.workers.agent_tasks import (
        run_prospect_agent, run_signal_agent, run_outreach_agent,
        run_content_agent, run_revenue_agent, run_deal_scan,
        run_a4_test,
    )
    agent_map = {
        "A1": run_prospect_agent,
        "A2": run_signal_agent,
        "A3": run_outreach_agent,
        "A4": run_a4_test,      # test mode — simulates a reply for dev testing
        "A5": run_deal_scan,
        "A6": run_content_agent,
        "A7": run_revenue_agent,
    }
    task_fn = agent_map.get(body.agent)
    if not task_fn:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {body.agent}")
    task = task_fn.apply_async(kwargs={"config": body.config} if body.config else {})
    return {"status": "queued", "task_id": task.id, "agent": body.agent}


@router.get("/agents/status/{task_id}")
async def get_agent_task_status(task_id: str):
    from celery.result import AsyncResult
    result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


# ── Agent Orchestrator ─────────────────────────────────────────────────────

@router.get("/orchestrator/graph")
async def get_orchestrator_graph():
    from app.orchestrator.agent_graph import AGENT_GRAPH

    return {
        "nodes": [
            {
                "agent_id": agent_id,
                "name": config.get("name"),
                "depends_on": config.get("depends_on", []),
                "next": config.get("next", []),
                "enabled": config.get("enabled", True),
                "mode": config.get("mode", "manual"),
            }
            for agent_id, config in AGENT_GRAPH.items()
        ],
        "edges": [
            {"from": agent_id, "to": next_agent}
            for agent_id, config in AGENT_GRAPH.items()
            for next_agent in config.get("next", [])
        ],
    }


@router.post("/orchestrator/run-agent")
async def run_orchestrator_agent(
    body: OrchestratorAgentRunRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.orchestrator.agent_graph import AGENT_GRAPH
    from app.orchestrator.orchestrator_service import OrchestratorService
    #from app.workers.orchestrator_tasks import run_agent_node
    from app.workers.orchestrator_tasks import build_pipeline_chain

    agent_id = body.agent_id.upper()
    config = AGENT_GRAPH.get(agent_id)

    if config is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent: {agent_id}")
    if agent_id == "A4":
        raise HTTPException(
            status_code=400,
            detail="A4 is webhook-driven. Use the legacy A4 test endpoint for development.",
        )

    orchestrator = OrchestratorService(db)
    workflow = await orchestrator.create_workflow_run(
        workflow_name=f"manual_{agent_id.lower()}",
        input_payload=body.payload or {},
    )
    execution = await orchestrator.create_agent_execution(
        workflow_run_id=workflow.id,
        agent_id=agent_id,
        input_payload=body.payload or {},
    )

    '''task = cast(Any, run_agent_node).apply_async(
        kwargs={
            "workflow_run_id": workflow.id,
            "agent_id": agent_id,
            "payload": body.payload or {},
        },
        queue="agents",
    )'''
    
    pipeline = build_pipeline_chain(
    workflow_run_id=workflow.id,
    agent_ids=[agent_id],
    payload=body.payload or {},
    )

    task = cast(Any, pipeline.apply_async(queue="agents"))
    execution.task_id = task.id
    await db.commit()

    return {
        "status": "queued",
        "workflow_run_id": workflow.id,
        "agent_id": agent_id,
        "task_id": task.id,
    }


@router.post("/orchestrator/run")
async def run_orchestrator_workflow(
    body: OrchestratorWorkflowRunRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.orchestrator.agent_graph import AGENT_GRAPH, get_enabled_pipeline
    from app.orchestrator.orchestrator_service import OrchestratorService
    from app.workers.orchestrator_tasks import build_pipeline_chain

    agent_ids = [
        agent_id.upper()
        for agent_id in (body.agent_ids or get_enabled_pipeline())
    ]

    if not agent_ids:
        raise HTTPException(status_code=400, detail="No agents selected")

    invalid = [agent_id for agent_id in agent_ids if agent_id not in AGENT_GRAPH]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agents: {invalid}",
        )
    if "A4" in agent_ids:
        raise HTTPException(
            status_code=400,
            detail="A4 is webhook-driven and cannot be included in the sequential pipeline.",
        )

    orchestrator = OrchestratorService(db)
    workflow = await orchestrator.create_workflow_run(
        workflow_name=body.workflow_name,
        input_payload={
            "agent_ids": agent_ids,
            "payload": body.payload or {},
        },
    )

    for agent_id in agent_ids:
        await orchestrator.create_agent_execution(
            workflow_run_id=workflow.id,
            agent_id=agent_id,
            input_payload=body.payload or {},
        )

    pipeline = build_pipeline_chain(
        workflow_run_id=workflow.id,
        agent_ids=agent_ids,
        payload=body.payload or {},
    )
    async_result = cast(Any, pipeline.apply_async())

    return {
        "status": "queued",
        "workflow_run_id": workflow.id,
        "celery_root_task_id": async_result.id,
        "agent_ids": agent_ids,
    }


@router.get("/orchestrator/runs/{workflow_run_id}")
async def get_orchestrator_run(
    workflow_run_id: str,
    db: AsyncSession = Depends(get_db),
):
    from app.orchestrator.orchestrator_service import OrchestratorService

    status = await OrchestratorService(db).get_workflow_status(workflow_run_id)
    if status["workflow"] is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return status


@router.get("/orchestrator/runs")
async def list_orchestrator_runs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkflowRun)
        .order_by(desc(WorkflowRun.created_at))
        .limit(limit)
    )
    runs = result.scalars().all()

    return [
        {
            "id": run.id,
            "workflow_name": run.workflow_name,
            "status": run.status,
            "current_agent": run.current_agent,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "created_at": run.created_at,
            "error_message": run.error_message,
        }
        for run in runs
    ]


# ── Signal Registry ────────────────────────────────────────────────────────

@router.get("/signals/registry")
async def get_signal_registry(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SignalConversionRegistry))
    return result.scalars().all()


# ── Outreach Drafts ────────────────────────────────────────────────────────

@router.get("/outreach/drafts")
async def get_outreach_drafts(
    user_input_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    q = select(OutreachLog).where(
        and_(OutreachLog.outreach_provider_message_id.is_(None),
             OutreachLog.sent_at >= datetime.utcnow() - timedelta(days=7))
    )
    if user_input_id is not None:
        q = q.join(Contact).where(Contact.user_input_id == user_input_id)
    result = await db.execute(q.order_by(desc(OutreachLog.sent_at)).limit(50))
    return result.scalars().all()

# ── Agent Schedule Endpoints ─────────────────────────────────────────────
class AgentScheduleRequest(BaseModel):
    agent: str
    enabled: bool
    cron: Optional[str] = None

SCHEDULABLE_AGENT_TASKS = {
    "A1": ("app.workers.scheduler_tasks.run_prospect_agent", settings.PROSPECT_AGENT_SCHEDULE),
    "A2": ("app.workers.scheduler_tasks.run_signal_agent", settings.SIGNAL_AGENT_SCHEDULE),
    "A6": ("app.workers.scheduler_tasks.run_content_agent", settings.CONTENT_AGENT_SCHEDULE),
}


async def _ensure_agent_schedule_rows(db: AsyncSession) -> None:
    changed = False
    for agent_id, (task_name, default_cron) in SCHEDULABLE_AGENT_TASKS.items():
        row = await db.get(AgentSchedule, agent_id)
        if not row:
            db.add(AgentSchedule(
                agent_id=agent_id,
                enabled=True,
                cron=default_cron,
                task_name=task_name,
                last_run_at=datetime.utcnow(),
            ))
            changed = True
    if changed:
        await db.commit()


@router.get("/agents/schedule")
async def get_agent_schedules(db: AsyncSession = Depends(get_db)):
    await _ensure_agent_schedule_rows(db)
    result = await db.execute(select(AgentSchedule))
    rows = result.scalars().all()
    return {
        row.agent_id: {
            "scheduled": row.enabled,
            "cron": row.cron,
            "last_run_at": row.last_run_at,
        }
        for row in rows
    }


@router.post("/agents/schedule")
async def update_agent_schedule(body: AgentScheduleRequest, db: AsyncSession = Depends(get_db)):
    agent_id = body.agent.upper()
    entry = SCHEDULABLE_AGENT_TASKS.get(agent_id)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Agent {body.agent} is not schedulable")

    task_name, default_cron = entry
    row = await db.get(AgentSchedule, agent_id)
    if not row:
        row = AgentSchedule(
            agent_id=agent_id,
            enabled=False,
            cron=default_cron,
            task_name=task_name,
        )
        db.add(row)

    row.enabled = body.enabled
    row.cron = body.cron or row.cron or default_cron
    row.task_name = task_name
    row.updated_at = datetime.utcnow()
    if body.enabled and row.last_run_at is None:
        row.last_run_at = datetime.utcnow()
    await db.commit()

    return {
        "agent": agent_id,
        "scheduled": row.enabled,
        "cron": row.cron,
        "persisted": True,
    }


# Apollo's standard employee-count buckets used for range expansion
_APOLLO_BUCKETS = [
    (1, 10), (11, 50), (51, 200), (201, 500), (501, 1000),
    (1001, 5000), (5001, 10000), (10001, 20000), (20001, 50000), (50001, 100000),
]


def _expand_size_range(size_str: str) -> list:
    """
    Convert a user-entered size range like '50-5000' into all overlapping
    Apollo employee-count bucket strings.

    Examples:
        '50-5000'  → ['51,200', '201,500', '501,1000', '1001,5000']
        '10-10000' → ['1,10', '11,50', '51,200', '201,500', '501,1000',
                       '1001,5000', '5001,10000']
    """
    try:
        parts = size_str.replace(" ", "").split("-")
        lo, hi = int(parts[0]), int(parts[-1])
        return [f"{a},{b}" for a, b in _APOLLO_BUCKETS if a <= hi and b >= lo]
    except Exception:
        return ["11,200"]   # safe default


class InputData(BaseModel):
    our_company_name:    str          # vendor's company name
    our_services:        str          # what we sell — personalization context only
    target_location:     str          # where prospect companies are based
    target_industries:   str = ""    # optional: "SaaS, Fintech"
    target_company_size: str          # range: "50-5000"
    target_keywords:     str = ""    # optional: "cloud, kubernetes"
    target_job_titles:   str          # "CTO, VP Engineering"


@router.get("/input-history")
async def get_input_history(db: AsyncSession = Depends(get_db)):
    """Return all past intake form submissions (newest first)."""
    from app.models.models import UserInput
    from sqlalchemy import select
    stmt = select(UserInput).order_by(UserInput.id.desc()).limit(50)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id":                  r.id,
            "our_company_name":    r.our_company_name,
            "our_services":        r.our_services,
            "target_location":     r.target_location,
            "target_industries":   r.target_industries or "",
            "target_company_size": r.target_company_size,
            "target_keywords":     r.target_keywords or "",
            "target_job_titles":   r.target_job_titles,
        }
        for r in rows
    ]


@router.post("/submit-input")
async def submit_input(data: InputData, db: AsyncSession = Depends(get_db)):
    """
    Accepts structured company/lead input from the frontend and persists it,
    then automatically starts the GTM agent pipeline using this intake information.
    """
    from app.models.models import UserInput
    from app.orchestrator.agent_graph import get_enabled_pipeline
    from app.orchestrator.orchestrator_service import OrchestratorService
    from app.workers.orchestrator_tasks import build_pipeline_chain

    from app.agents.industry_tag_map import resolve_industries

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

    agent_ids = get_enabled_pipeline()
    if "A4" in agent_ids:
        agent_ids.remove("A4")

    if agent_ids:
        # Job titles
        titles = [t.strip() for t in data.target_job_titles.split(",") if t.strip()]

        # Organisation locations (company HQ, not person location)
        geographies = [g.strip() for g in data.target_location.split(",") if g.strip()]

        # Expand size range into all overlapping Apollo buckets
        employee_ranges = _expand_size_range(data.target_company_size)

        # Industry resolution: matched → tag IDs, unmatched → keyword fallback
        industry_tag_ids, industry_kw_fallback = resolve_industries(data.target_industries)

        # Build org keyword tags: user keywords + unmatched industry terms
        kw_list = [k.strip() for k in data.target_keywords.split(",") if k.strip()]
        kw_list += industry_kw_fallback
        org_keyword_tags = kw_list if kw_list else None

        payload = {
            "icp_config": {
                "titles":               titles,
                "organization_locations": geographies,
                "employee_ranges":      employee_ranges,
                "industry_tag_ids":     industry_tag_ids if industry_tag_ids else None,
                "org_keyword_tags":     org_keyword_tags,
                "vendor_services":      data.our_services,  # personalization only
                "threshold":            0,
                "enrich_limit":         25,
                "user_input_id":        record.id,
            }
        }
        # NOTE: company_name is intentionally absent from icp_config

        orchestrator = OrchestratorService(db)
        workflow = await orchestrator.create_workflow_run(
            workflow_name="manual_full_gtm",
            input_payload={
                "agent_ids": agent_ids,
                "payload": payload,
            },
        )

        for agent_id in agent_ids:
            await orchestrator.create_agent_execution(
                workflow_run_id=workflow.id,
                agent_id=agent_id,
                input_payload=payload,
            )

        pipeline = build_pipeline_chain(
            workflow_run_id=workflow.id,
            agent_ids=agent_ids,
            payload=payload,
        )
        pipeline.apply_async()

    workflow_id_str = str(workflow.id) if workflow else None
    return {
        "status": "success",
        "message": "Input saved and GTM pipeline triggered successfully",
        "workflow_run_id": workflow_id_str,
        "user_input_id": record.id,
    }

"""
REST API v1 — all endpoints consumed by the React frontend.
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc, asc, or_, String as SAString
from sqlalchemy.orm import selectinload
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import (
    Contact, SignalEvent, OutreachLog, ConversationThread,
    Deal, DealStageHistory, FunnelEvent, GeneratedContent, RevenueForecast,
    PendingAction, ActionStatus, SignalConversionRegistry,
    PromptVariant, WorkflowRun, AgentSchedule, OutreachDraft,
    User, UserInput,
)

# Every endpoint on this router requires a valid Bearer token (server-side
# enforced). The public auth routes live in app.api.v1.auth (mounted in main.py).
router = APIRouter(dependencies=[Depends(get_current_user)])


# ── Ownership helpers ──────────────────────────────────────────────────────

async def _owned_input_ids(db: AsyncSession, user):
    """IDs of the user's intake sessions. None ⇒ auth disabled (legacy mode)."""
    if user is None:
        return None
    result = await db.execute(select(UserInput.id).where(UserInput.user_id == user.id))
    return [r[0] for r in result.all()]


async def _ensure_owned_input(db: AsyncSession, user, user_input_id: int) -> None:
    """404 if the requested session is not owned by the current user."""
    if user is None or user_input_id is None:
        return
    row = await db.get(UserInput, user_input_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")


def _own_contact_ids_q(user):
    """Subquery: contact ids owned by the user."""
    return select(Contact.id).where(Contact.user_id == user.id)


def _own_deal_ids_q(user):
    """Subquery: deal ids whose contact is owned by the user."""
    return select(Deal.id).where(Deal.contact_id.in_(_own_contact_ids_q(user)))


# ── Pydantic response models ───────────────────────────────────────────────

class ContactOut(BaseModel):
    id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    linkedin_url: Optional[str] = None
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


class DealContactOut(BaseModel):
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    industry: Optional[str] = None
    linkedin_url: Optional[str] = None
    icp_score: Optional[float] = None
    signal_score: Optional[float] = None
    class Config:
        from_attributes = True


class DealStageHistoryOut(BaseModel):
    id: str
    from_stage: Optional[str] = None
    to_stage: str
    days_in_from_stage: Optional[int] = None
    transitioned_at: datetime
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
    objections: Optional[List[dict]] = None
    deal_health_score: Optional[float] = None
    win_probability: Optional[float] = None
    buying_intent: Optional[str] = None
    next_best_action: Optional[str] = None
    stage_confidence: Optional[float] = None
    contact_id: Optional[str] = None
    budget_confirmed: Optional[bool] = None
    authority_confirmed: Optional[bool] = None
    need_confirmed: Optional[bool] = None
    timeline_confirmed: Optional[bool] = None
    owner_email: Optional[str] = None
    hubspot_deal_id: Optional[str] = None
    close_date: Optional[datetime] = None
    stakeholder_count: int = 1
    meeting_count: int = 0
    avg_response_time_hours: Optional[float] = None
    stage_entered_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: datetime
    contact: Optional[DealContactOut] = None
    stage_history: Optional[List[DealStageHistoryOut]] = None
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
async def get_active_session(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Returns the most recent user_input id — the current active session."""
    from app.models.models import UserInput
    stmt = select(UserInput.id).order_by(UserInput.id.desc())
    if current_user is not None:
        stmt = stmt.where(UserInput.user_id == current_user.id)
    result = await db.execute(stmt.limit(1))
    row = result.scalar_one_or_none()
    return {"user_input_id": row}


@router.get("/sessions/{session_id}")
async def get_session_details(session_id: int, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Returns details for a specific user input session."""
    from app.models.models import UserInput
    result = await db.execute(select(UserInput).where(UserInput.id == session_id))
    row = result.scalar_one_or_none()
    if not row or (current_user is not None and row.user_id != current_user.id):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "Session not found"})
    return {
        "id": row.id,
        "our_company_name": row.our_company_name,
        "our_services": row.our_services,
    }


@router.get("/dashboard/overview")
async def get_dashboard_overview(
    user_input_id: Optional[int] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Base contact filter — always scoped to the current user's own contacts
    contact_filter = [Contact.do_not_contact == False]
    if current_user is not None:
        contact_filter.append(Contact.user_id == current_user.id)
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
    if current_user is not None:
        deal_filter.append(Deal.contact_id.in_(_own_contact_ids_q(current_user)))
    elif user_input_id is not None:
        deal_filter.append(Deal.contact_id.in_(contact_ids_q))
    pipeline_value = await db.scalar(
        select(func.sum(Deal.amount)).where(and_(*deal_filter))
    ) or 0

    pending_actions = await db.scalar(
        select(func.count(PendingAction.id)).where(
            and_(
                PendingAction.status == ActionStatus.PENDING,
                # scope pending actions to entities owned by the current user
                or_(
                    and_(PendingAction.entity_type == "contact",
                         PendingAction.entity_id.in_(_own_contact_ids_q(current_user))),
                    and_(PendingAction.entity_type == "deal",
                         PendingAction.entity_id.in_(_own_deal_ids_q(current_user))),
                ),
            )
        ) if current_user is not None else PendingAction.status == ActionStatus.PENDING
    ) or 0

    forecast_result = await db.execute(
        select(RevenueForecast)
        .where(RevenueForecast.user_id == current_user.id if current_user is not None else True)
        .order_by(desc(RevenueForecast.calculated_at)).limit(1))
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
    sort_order: str = "desc",
    user_input_id: Optional[int] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Contact).where(Contact.do_not_contact == do_not_contact)
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)
        q = q.where(Contact.user_id == current_user.id)
    if user_input_id is not None:
        q = q.where(Contact.user_input_id == user_input_id)
    if min_score is not None:
        q = q.where(Contact.icp_score >= min_score)
    if has_signal:
        q = q.where(Contact.signal_score.isnot(None))
    order_func = desc if sort_order == "desc" else asc
    if sort_by == "score":
        q = q.order_by(order_func(Contact.icp_score), desc(Contact.created_at))
    elif sort_by == "signal_score":
        q = q.order_by(order_func(Contact.signal_score), desc(Contact.created_at))
    else:
        q = q.order_by(order_func(Contact.created_at), desc(Contact.icp_score))
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: UUID, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Contact).where(Contact.id == contact_id)
    if current_user is not None:
        stmt = stmt.where(Contact.user_id == current_user.id)
    result = await db.execute(stmt)
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.get("/contacts/{contact_id}/thread")
async def get_contact_thread(contact_id: UUID, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import asc
    stmt = (
        select(ConversationThread)
        .join(Contact, Contact.id == ConversationThread.contact_id)
        .where(ConversationThread.contact_id == contact_id)
    )
    if current_user is not None:
        stmt = stmt.where(Contact.user_id == current_user.id)
    stmt = stmt.order_by(asc(ConversationThread.occurred_at))
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/contacts/{contact_id}/signals")
async def get_contact_signals(contact_id: UUID, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(SignalEvent)
        .join(Contact, Contact.id == SignalEvent.contact_id)
        .where(SignalEvent.contact_id == contact_id)
    )
    if current_user is not None:
        stmt = stmt.where(Contact.user_id == current_user.id)
    stmt = stmt.order_by(desc(SignalEvent.detected_at))
    result = await db.execute(stmt)
    return result.scalars().all()


# ── Deals ──────────────────────────────────────────────────────────────────

@router.get("/deals", response_model=List[DealOut])
async def list_deals(
    stage: Optional[str] = None, min_risk: Optional[float] = None,
    user_input_id: Optional[int] = None,
    contact_id: Optional[UUID] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)
    q = select(Deal).options(
        selectinload(Deal.contact),
        selectinload(Deal.stage_history)
    ).where(Deal.outcome.is_(None))
    if contact_id is not None:
        q = q.where(Deal.contact_id == contact_id)
    if current_user is not None:
        own_contacts = _own_contact_ids_q(current_user)
        if user_input_id is not None:
            own_contacts = own_contacts.where(Contact.user_input_id == user_input_id)
        q = q.where(Deal.contact_id.in_(own_contacts))
    elif user_input_id is not None:
        contact_ids_q = select(Contact.id).where(
            (Contact.user_input_id == user_input_id) | (Contact.user_input_id.is_(None))
        )
        q = q.where((Deal.contact_id.in_(contact_ids_q)) | (Deal.contact_id.is_(None)))
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
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)
    where_clauses = [Deal.outcome.is_(None)]
    if current_user is not None:
        own_contacts = _own_contact_ids_q(current_user)
        if user_input_id is not None:
            own_contacts = own_contacts.where(Contact.user_input_id == user_input_id)
        where_clauses.append(Deal.contact_id.in_(own_contacts))
    elif user_input_id is not None:
        contact_ids_q = select(Contact.id).where(
            (Contact.user_input_id == user_input_id) | (Contact.user_input_id.is_(None))
        )
        where_clauses.append((Deal.contact_id.in_(contact_ids_q)) | (Deal.contact_id.is_(None)))
    result = await db.execute(
        select(Deal.stage, func.count(Deal.id).label("count"),
               func.sum(Deal.amount).label("value"),
               func.avg(Deal.days_in_current_stage).label("avg_days"),
               func.avg(Deal.risk_score).label("avg_risk"))
        .where(and_(*where_clauses))
        .group_by(Deal.stage)
    )
    return [{"stage": r.stage, "count": r.count, "value": float(r.value or 0),
             "avg_days": float(r.avg_days or 0), "avg_risk": float(r.avg_risk or 0)}
            for r in result.all()]


@router.get("/deals/{deal_id}", response_model=DealOut)
async def get_deal(deal_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Deal)
        .options(
            selectinload(Deal.contact),
            selectinload(Deal.stage_history)
        )
        .where(Deal.id == deal_id)
    )
    if current_user is not None:
        stmt = stmt.where(Deal.contact_id.in_(_own_contact_ids_q(current_user)))
    result = await db.execute(stmt)
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


# ── Pending Actions ────────────────────────────────────────────────────────

async def _ensure_action_owned(db: AsyncSession, user, action) -> None:
    """404 if the action's entity (contact/deal) is not owned by the user."""
    if user is None:
        return
    if action.entity_type == "contact":
        contact = await db.get(Contact, action.entity_id)
        if not contact or contact.user_id != user.id:
            raise HTTPException(status_code=404)
    elif action.entity_type == "deal":
        deal = await db.get(Deal, action.entity_id)
        if not deal or not deal.contact_id:
            raise HTTPException(status_code=404)
        contact = await db.get(Contact, deal.contact_id)
        if not contact or contact.user_id != user.id:
            raise HTTPException(status_code=404)


@router.get("/pending-actions")
async def list_pending_actions(
    status: Optional[str] = "pending",
    agent_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 50,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    q = select(PendingAction)
    if status == "pending":
        q = q.where(PendingAction.status == ActionStatus.PENDING)
    elif status == "history":
        q = q.where(PendingAction.status.in_([ActionStatus.APPROVED, ActionStatus.DISMISSED, ActionStatus.EXPIRED]))
    elif status and status != "all":
        q = q.where(PendingAction.status == status)

    if agent_id:
        q = q.where(PendingAction.agent_id == agent_id)
    if entity_type:
        q = q.where(PendingAction.entity_type == entity_type)

    if current_user is not None:
        # Only surface actions whose entity belongs to the current user
        q = q.where(
            or_(
                and_(PendingAction.entity_type == "contact",
                     PendingAction.entity_id.in_(_own_contact_ids_q(current_user))),
                and_(PendingAction.entity_type == "deal",
                     PendingAction.entity_id.in_(_own_deal_ids_q(current_user))),
            )
        )

    q = q.order_by(desc(PendingAction.created_at)).limit(limit)
    result = await db.execute(q)
    actions = result.scalars().all()

    enriched = []
    for a in actions:
        item = {
            "id": a.id,
            "action_type": a.action_type,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "recommended_value": a.recommended_value,
            "current_value": a.current_value,
            "reason": a.reason,
            "agent_id": a.agent_id,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            "approved_by": a.approved_by,
            "deal_name": None,
            "company": None,
            "contact_name": None,
            "contact_id": None,
            "deal_id": None,
        }

        if a.entity_type == "deal":
            deal_res = await db.execute(select(Deal).where(Deal.id == a.entity_id))
            deal = deal_res.scalar_one_or_none()
            if deal:
                item["deal_id"] = deal.id
                item["deal_name"] = deal.name
                if deal.contact_id:
                    contact_res = await db.execute(select(Contact).where(Contact.id == deal.contact_id))
                    contact = contact_res.scalar_one_or_none()
                    if contact:
                        item["contact_id"] = contact.id
                        item["company"] = contact.company
                        item["contact_name"] = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
        elif a.entity_type == "contact":
            contact_res = await db.execute(select(Contact).where(Contact.id == a.entity_id))
            contact = contact_res.scalar_one_or_none()
            if contact:
                item["contact_id"] = contact.id
                item["company"] = contact.company
                item["contact_name"] = f"{contact.first_name or ''} {contact.last_name or ''}".strip()

        enriched.append(item)

    return enriched


@router.post("/pending-actions/{action_id}/approve")
async def approve_action(
    action_id: str, body: ApproveActionRequest, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404)
    await _ensure_action_owned(db, current_user, action)
    action.status = ActionStatus.APPROVED
    action.approved_by = body.approved_by
    action.approved_at = datetime.utcnow()
    
    if action.action_type == "approve_outreach":
        from app.agents.a3_outreach import DraftManager
        draft_manager = DraftManager(db)
        await draft_manager.approve_pending_draft(action.entity_id)

    await db.commit()
    return {"status": "approved"}


@router.post("/pending-actions/{action_id}/dismiss")
async def dismiss_action(action_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404)
    await _ensure_action_owned(db, current_user, action)
    action.status = ActionStatus.DISMISSED
    action.approved_at = datetime.utcnow()  # timestamp of resolution/dismissal
    await db.commit()
    return {"status": "dismissed"}


# ── Revenue ────────────────────────────────────────────────────────────────

@router.get("/revenue/forecast", response_model=ForecastOut)
async def get_latest_forecast(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(RevenueForecast)
    if current_user is not None:
        stmt = stmt.where(RevenueForecast.user_id == current_user.id)
    result = await db.execute(
        stmt.order_by(desc(RevenueForecast.calculated_at)).limit(1))
    forecast = result.scalar_one_or_none()
    if not forecast:
        raise HTTPException(status_code=404, detail="No forecast yet — run A7")
    return forecast


@router.get("/revenue/funnel-metrics")
async def get_funnel_metrics(
    days: int = Query(30, ge=7, le=365),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(FunnelEvent.event_type, func.count(FunnelEvent.id).label("count"))
        .where(FunnelEvent.timestamp >= since)
    )
    if current_user is not None:
        # Events owned via their contact or via the deal's contact
        stmt = stmt.where(
            or_(
                FunnelEvent.contact_id.in_(_own_contact_ids_q(current_user)),
                FunnelEvent.deal_id.in_(_own_deal_ids_q(current_user)),
            )
        )
    stmt = stmt.group_by(FunnelEvent.event_type)
    result = await db.execute(stmt)
    return {row.event_type: row.count for row in result.all()}


# ── Content ────────────────────────────────────────────────────────────────

@router.get("/content")
async def list_content(
    format: Optional[str] = None, icp_segment: Optional[str] = None,
    user_input_id: Optional[int] = None,
    limit: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)):
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)
    q = select(GeneratedContent)
    if format:
        q = q.where(GeneratedContent.content_format == format)
    if icp_segment:
        q = q.where(GeneratedContent.icp_segment == icp_segment)
    elif user_input_id is not None:
        from app.models.models import Contact, UserInput
        from sqlalchemy import or_
        
        # 1. Fetch UserInput to get target industries
        ui_result = await db.execute(select(UserInput).where(UserInput.id == user_input_id))
        ui = ui_result.scalar_one_or_none()
        industries = set()
        if ui and ui.target_industries:
            # target_industries is a comma-separated string, e.g. "SaaS, Healthcare"
            for ind in ui.target_industries.split(","):
                val = ind.strip()
                if val:
                    industries.add(val.lower())
                    
        # 2. Fetch distinct industries from active contacts associated with this user_input_id
        contact_res = await db.execute(
            select(Contact.industry)
            .where(
                and_(
                    Contact.user_input_id == user_input_id,
                    Contact.industry.isnot(None),
                    Contact.industry != ""
                )
            )
            .distinct()
        )
        for row in contact_res.all():
            val = row[0].strip()
            if val:
                industries.add(val.lower())
                
        # 3. Apply matching filter if any industries are found, otherwise fallback to SaaS/B2B technology
        if not industries:
            industries = {"saas", "b2b technology", "b2b saas"}
            
        conditions = []
        for ind in industries:
            conditions.append(GeneratedContent.icp_segment.ilike(f"%{ind}%"))
            # Also handle reverse / sub-word matching for compound industry names (e.g. "financial services" matches "finance")
            if len(ind) > 3:
                for sub in ind.replace("/", " ").replace("&", " ").split():
                    if len(sub) > 4:
                        conditions.append(GeneratedContent.icp_segment.ilike(f"%{sub}%"))
                        
        q = q.where(or_(*conditions))
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
    current_user=Depends(get_current_user),
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
    if current_user is not None:
        workflow.user_id = current_user.id
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
    current_user=Depends(get_current_user),
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
    if current_user is not None:
        workflow.user_id = current_user.id

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
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.orchestrator.orchestrator_service import OrchestratorService

    status = await OrchestratorService(db).get_workflow_status(workflow_run_id)
    if status["workflow"] is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if current_user is not None:
        workflow = await db.get(WorkflowRun, workflow_run_id)
        if workflow is None or workflow.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Workflow run not found")
    return status


@router.get("/orchestrator/runs")
async def list_orchestrator_runs(
    limit: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(WorkflowRun)
    if current_user is not None:
        stmt = stmt.where(WorkflowRun.user_id == current_user.id)
    result = await db.execute(
        stmt.order_by(desc(WorkflowRun.created_at)).limit(limit)
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
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    q = select(OutreachLog).where(
        and_(OutreachLog.outreach_provider_message_id.is_(None),
             OutreachLog.sent_at >= datetime.utcnow() - timedelta(days=7))
    )
    if current_user is not None:
        q = q.join(Contact, Contact.id == OutreachLog.contact_id).where(Contact.user_id == current_user.id)
        if user_input_id is not None:
            q = q.where(Contact.user_input_id == user_input_id)
    elif user_input_id is not None:
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
async def get_input_history(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return all past intake form submissions (newest first)."""
    from app.models.models import UserInput
    from sqlalchemy import select
    stmt = select(UserInput)
    if current_user is not None:
        stmt = stmt.where(UserInput.user_id == current_user.id)
    stmt = stmt.order_by(UserInput.id.desc()).limit(50)
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
async def submit_input(data: InputData, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Accepts structured company/lead input from the frontend and persists it,
    then automatically starts the GTM agent pipeline using this intake information.
    """
    from app.models.models import UserInput
    from app.orchestrator.agent_graph import get_enabled_pipeline
    from app.orchestrator.orchestrator_service import OrchestratorService
    from app.workers.orchestrator_tasks import build_pipeline_chain
    from app.services.icp_normalizer import normalize_icp_input

    record = UserInput(
        our_company_name=    data.our_company_name,
        our_services=        data.our_services,
        target_location=     data.target_location,
        target_industries=   data.target_industries or None,
        target_company_size= data.target_company_size,
        target_keywords=     data.target_keywords or None,
        target_job_titles=   data.target_job_titles,
        user_id=             current_user.id if current_user is not None else None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    agent_ids = get_enabled_pipeline()
    if "A4" in agent_ids:
        agent_ids.remove("A4")

    if agent_ids:
        raw_icp_dict = {
            "our_company_name":    data.our_company_name,
            "our_services":        data.our_services,
            "target_location":     data.target_location,
            "target_industries":   data.target_industries,
            "target_company_size": data.target_company_size,
            "target_keywords":     data.target_keywords,
            "target_job_titles":   data.target_job_titles,
            "user_id":             current_user.id if current_user is not None else None,
            "user_input_id":       record.id,
            "threshold":           settings.ICP_SCORE_THRESHOLD,
            "enrich_limit":        getattr(settings, "APOLLO_ENRICH_LIMIT", 10),
            "candidate_pool_size": getattr(settings, "APOLLO_CANDIDATE_POOL_SIZE", 150),
            "include_similar_titles": getattr(settings, "APOLLO_INCLUDE_SIMILAR_TITLES", False),
        }
        normalized = normalize_icp_input(raw_icp_dict)
        payload = {"icp_config": normalized.to_dict()}

        orchestrator = OrchestratorService(db)
        workflow = await orchestrator.create_workflow_run(
            workflow_name="manual_full_gtm",
            input_payload={
                "agent_ids": agent_ids,
                "payload": payload,
            },
        )
        if current_user is not None:
            workflow.user_id = current_user.id

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


# ── Draft Manager Endpoints ───────────────────────────────────────────────

class EditDraftRequest(BaseModel):
    subject: str
    body: str


async def _get_owned_draft(db: AsyncSession, user, draft_id: str) -> OutreachDraft:
    """Fetch a draft and enforce that its contact belongs to the user (404 otherwise)."""
    result = await db.execute(select(OutreachDraft).where(OutreachDraft.id == draft_id))
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if user is not None:
        contact = await db.get(Contact, draft.contact_id)
        if not contact or contact.user_id != user.id:
            raise HTTPException(status_code=404, detail="Draft not found")
    return draft

@router.get("/drafts")
async def get_drafts(
    user_input_id: Optional[int] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    q = select(OutreachDraft)
    if current_user is not None:
        await _ensure_owned_input(db, current_user, user_input_id)
        own = _own_contact_ids_q(current_user)
        if user_input_id is not None:
            own = own.where(Contact.user_input_id == user_input_id)
        q = q.where(OutreachDraft.contact_id.in_(own))
    elif user_input_id is not None:
        q = q.join(Contact).where(Contact.user_input_id == user_input_id)
    result = await db.execute(
        q.order_by(OutreachDraft.created_at.desc())
    )
    drafts = result.scalars().all()
    
    serialized = []
    for d in drafts:
        contact_res = await db.execute(select(Contact).where(Contact.id == d.contact_id))
        contact = contact_res.scalar_one_or_none()
        signal_res = await db.execute(select(SignalEvent).where(SignalEvent.id == d.signal_id))
        signal = signal_res.scalar_one_or_none()
        
        serialized.append({
            "id": d.id,
            "contact_id": d.contact_id,
            "signal_id": d.signal_id,
            "subject": d.subject,
            "body": d.body,
            "business_case": d.business_case,
            "matched_services": d.matched_services,
            "channel": d.channel,
            "status": d.status,
            "approval_state": d.approval_state,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "contact": {
                "first_name": contact.first_name if contact else "",
                "last_name": contact.last_name if contact else "",
                "email": contact.email if contact else "",
                "company": contact.company if contact else "",
                "title": contact.title if contact else "",
                "user_input_id": contact.user_input_id if contact else None
            } if contact else None,
            "signal": {
                "signal_type": signal.signal_type if signal else "",
                "confidence": signal.confidence if signal else 0.0,
                "raw_data": signal.raw_data if signal else {}
            } if signal else None
        })
    return serialized

@router.get("/drafts/{draft_id}/preview")
async def preview_draft(draft_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await _get_owned_draft(db, current_user, draft_id)
        
    contact_res = await db.execute(select(Contact).where(Contact.id == d.contact_id))
    contact = contact_res.scalar_one_or_none()
    signal_res = await db.execute(select(SignalEvent).where(SignalEvent.id == d.signal_id))
    signal = signal_res.scalar_one_or_none()
    
    return {
        "id": d.id,
        "contact_id": d.contact_id,
        "signal_id": d.signal_id,
        "subject": d.subject,
        "body": d.body,
        "business_case": d.business_case,
        "matched_services": d.matched_services,
        "channel": d.channel,
        "status": d.status,
        "approval_state": d.approval_state,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "contact": {
            "first_name": contact.first_name if contact else "",
            "last_name": contact.last_name if contact else "",
            "email": contact.email if contact else "",
            "company": contact.company if contact else "",
            "title": contact.title if contact else "",
            "user_input_id": contact.user_input_id if contact else None
        } if contact else None,
        "signal": {
            "signal_type": signal.signal_type if signal else "",
            "confidence": signal.confidence if signal else 0.0,
            "raw_data": signal.raw_data if signal else {}
        } if signal else None
    }

@router.post("/drafts/{draft_id}/approve")
async def approve_draft_route(draft_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.agents.a3_outreach import DraftManager
    draft_manager = DraftManager(db)
    # Fetch draft details (ownership enforced)
    draft = await _get_owned_draft(db, current_user, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
        
    contact_id = draft.contact_id
    
    # Perform approval and dispatch
    res = await draft_manager.approve_draft(draft_id)
    success = res.get("success", False) if isinstance(res, dict) else bool(res)
    error_msg = res.get("error") if isinstance(res, dict) else None

    if not success:
        raise HTTPException(status_code=400, detail=error_msg or "Approval failed or draft not pending")
    
    # Find and resolve associated pending actions
    action_res = await db.execute(
        select(PendingAction)
        .where(and_(
            PendingAction.entity_id == contact_id,
            PendingAction.action_type == "approve_outreach",
            PendingAction.status == ActionStatus.PENDING
        ))
    )
    actions = action_res.scalars().all()
    for action in actions:
        action.status = ActionStatus.APPROVED
        action.approved_at = datetime.utcnow()
            
    await db.commit()
    return {
        "status": "approved",
        "sent": True
    }

@router.post("/drafts/{draft_id}/reject")
async def reject_draft_route(draft_id: str, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await _get_owned_draft(db, current_user, draft_id)
    if d.approval_state != "pending":
        raise HTTPException(status_code=400, detail="Draft not in pending state")
        
    d.approval_state = "rejected"
    d.status = "failed"
    
    action_res = await db.execute(
        select(PendingAction)
        .where(and_(
            PendingAction.entity_id == d.contact_id,
            PendingAction.action_type == "approve_outreach",
            PendingAction.status == ActionStatus.PENDING
        ))
    )
    action = action_res.scalar_one_or_none()
    if action:
        action.status = ActionStatus.DISMISSED

    await db.commit()
    return {"status": "rejected"}

@router.post("/drafts/{draft_id}/edit")
async def edit_draft_route(draft_id: str, body: EditDraftRequest, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = await _get_owned_draft(db, current_user, draft_id)
    if d.approval_state != "pending":
        raise HTTPException(status_code=400, detail="Cannot edit approved/rejected draft")
        
    d.subject = body.subject
    d.body = body.body
    await db.commit()
    return {"status": "updated", "subject": d.subject, "body": d.body}


@router.get("/dashboard/outreach-analytics")
async def get_outreach_analytics(current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Scope helpers — everything ties back to the user's own contacts
    draft_pending = await db.scalar(
        select(func.count(OutreachDraft.id))
        .join(Contact, Contact.id == OutreachDraft.contact_id)
        .where(and_(OutreachDraft.approval_state == "pending",
                    Contact.user_id == current_user.id) if current_user is not None
               else OutreachDraft.approval_state == "pending")) or 0
    draft_approved = await db.scalar(
        select(func.count(OutreachDraft.id))
        .join(Contact, Contact.id == OutreachDraft.contact_id)
        .where(and_(OutreachDraft.approval_state == "approved",
                    Contact.user_id == current_user.id) if current_user is not None
               else OutreachDraft.approval_state == "approved")) or 0
    draft_rejected = await db.scalar(
        select(func.count(OutreachDraft.id))
        .join(Contact, Contact.id == OutreachDraft.contact_id)
        .where(and_(OutreachDraft.approval_state == "rejected",
                    Contact.user_id == current_user.id) if current_user is not None
               else OutreachDraft.approval_state == "rejected")) or 0
    total_drafts = draft_pending + draft_approved + draft_rejected

    log_scope = (OutreachLog.contact_id.in_(_own_contact_ids_q(current_user))
                 if current_user is not None else True)
    total_sent = await db.scalar(select(func.count(OutreachLog.id)).where(log_scope)) or 0
    total_replies = await db.scalar(select(func.count(OutreachLog.id)).where(and_(log_scope, OutreachLog.replied == True))) or 0
    total_meetings = await db.scalar(select(func.count(OutreachLog.id)).where(and_(log_scope, OutreachLog.meeting_booked == True))) or 0

    # 3. Channel performance (scoped to the user's own outreach)
    channel_stmt = (
        select(
            OutreachLog.channel,
            func.count(OutreachLog.id),
            func.count(func.nullif(OutreachLog.replied, False)),
            func.count(func.nullif(OutreachLog.meeting_booked, False))
        )
        .where(log_scope)
        .group_by(OutreachLog.channel)
        if current_user is not None else
        select(
            OutreachLog.channel,
            func.count(OutreachLog.id),
            func.count(func.nullif(OutreachLog.replied, False)),
            func.count(func.nullif(OutreachLog.meeting_booked, False))
        ).group_by(OutreachLog.channel)
    )
    channel_perf_res = await db.execute(channel_stmt)
    channel_performance = []
    for chan, sent, replies, meetings in channel_perf_res.all():
        channel_performance.append({
            "channel": chan or "email",
            "sent": sent,
            "replies": replies,
            "meetings": meetings,
            "reply_rate": round(replies / max(sent, 1) * 100, 1),
            "meeting_rate": round(meetings / max(sent, 1) * 100, 1)
        })

    # 4. Business Case performance (Draft breakdown, scoped)
    draft_scope = (Contact.user_id == current_user.id) if current_user is not None else True
    bc_perf_res = await db.execute(
        select(
            OutreachDraft.business_case,
            func.count(OutreachDraft.id),
            func.count(func.nullif(OutreachDraft.approval_state == "approved", False)),
            func.count(func.nullif(OutreachDraft.approval_state == "rejected", False))
        )
        .join(Contact, Contact.id == OutreachDraft.contact_id)
        .where(draft_scope)
        .group_by(OutreachDraft.business_case)
        if current_user is not None else
        select(
            OutreachDraft.business_case,
            func.count(OutreachDraft.id),
            func.count(func.nullif(OutreachDraft.approval_state == "approved", False)),
            func.count(func.nullif(OutreachDraft.approval_state == "rejected", False))
        ).group_by(OutreachDraft.business_case)
    )
    business_case_performance = []
    for bc, total, approved, rejected in bc_perf_res.all():
        business_case_performance.append({
            "business_case": bc or "General Sales Outreach",
            "total_drafts": total,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": round(approved / max(total, 1) * 100, 1)
        })

    # 5. Template (Prompt Variant) performance
    variant_res = await db.execute(
        select(
            PromptVariant.id,
            PromptVariant.signal_type,
            PromptVariant.send_count,
            PromptVariant.reply_count,
            PromptVariant.meeting_count,
            PromptVariant.reply_rate
        ).where(PromptVariant.is_active == True)
    )
    template_performance = []
    for vid, sig, sent, replies, meetings, rate in variant_res.all():
        template_performance.append({
            "variant_id": vid,
            "signal_type": sig,
            "sent": sent,
            "replies": replies,
            "meetings": meetings,
            "reply_rate": round(rate * 100, 1) if rate else 0.0
        })

    return {
        "summary": {
            "total_drafts": total_drafts,
            "draft_pending": draft_pending,
            "draft_approved": draft_approved,
            "draft_rejected": draft_rejected,
            "total_sent": total_sent,
            "total_replies": total_replies,
            "total_meetings": total_meetings,
        },
        "channel_performance": channel_performance,
        "business_case_performance": business_case_performance,
        "template_performance": template_performance
    }


@router.post("/inbound/poll-gmail")
async def poll_gmail_inbox_endpoint():
    """Triggers Gmail IMAP poller to check unread emails in intotech7@gmail.com and process replies via A4."""
    from app.workers.agent_tasks import poll_gmail_inbox
    task = poll_gmail_inbox.apply_async(queue="webhooks")
    return {"status": "queued", "task_id": task.id}


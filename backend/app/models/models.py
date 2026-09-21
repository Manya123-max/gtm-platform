"""
All database models for the GTM Platform.
Central schema â€” every agent reads from and writes to these tables.
"""
import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, Integer,Column, Float, Boolean, DateTime, Text, JSON,
    ForeignKey, UniqueConstraint, Index, Enum as SAEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from app.core.database import Base
import enum


def generate_uuid():
    return str(uuid.uuid4())


class SignalType(str, enum.Enum):
    TECH_STACK_CHANGE = "tech_stack_change"
    NEW_HIRE = "new_hire"
    FUNDING_ROUND = "funding_round"
    JOB_POSTING = "job_posting"
    EARNINGS_CALL = "earnings_call"
    COMPETITOR_REVIEW = "competitor_review"
    NEWS_EXPANSION = "news_expansion"
    SOCIAL_ENGAGEMENT = "social_engagement"


class ReplyIntent(str, enum.Enum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    REFERRAL = "referral"
    UNSUBSCRIBE = "unsubscribe"
    UNKNOWN = "unknown"


class DealStage(str, enum.Enum):
    PROSPECTING = "prospecting"
    DISCOVERY = "discovery"
    DEMO = "demo"
    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class ContentFormat(str, enum.Enum):
    LINKEDIN_POST = "linkedin_post"
    EMAIL_SEQUENCE = "email_sequence"
    CASE_STUDY = "case_study"
    BLOG_ARTICLE = "blog_article"
    SALES_DECK_OUTLINE = "sales_deck_outline"



class Contact(Base):
    """
    Central contact table. All agents read from and write to this.
    """
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    title: Mapped[Optional[str]] = mapped_column(String(200))
    company: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    company_domain: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500))

    # Firmographic enrichment
    company_size: Mapped[Optional[str]] = mapped_column(String(50))
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    funding_stage: Mapped[Optional[str]] = mapped_column(String(50))
    tech_stack: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)
    geography: Mapped[Optional[str]] = mapped_column(String(100))
    annual_revenue: Mapped[Optional[str]] = mapped_column(String(50))
    employee_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Scoring  A1
    icp_score: Mapped[Optional[float]] = mapped_column(Float, index=True)
    icp_score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB)
    win_pattern_score: Mapped[Optional[float]] = mapped_column(Float)

    # Signal  A2
    signal_type: Mapped[Optional[str]] = mapped_column(String(255))
    signal_score: Mapped[Optional[float]] = mapped_column(Float)
    latest_signal_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Readiness  A4
    readiness_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Prospect Interest & Engagement Detection Engine
    interest_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    interest_status: Mapped[str] = mapped_column(String(50), default="INACTIVE", index=True)
    interest_score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_response_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_outreach_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    response_count: Mapped[int] = mapped_column(Integer, default=0)
    outreach_count: Mapped[int] = mapped_column(Integer, default=0)
    interest_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Status flags
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_valid: Mapped[Optional[bool]] = mapped_column(Boolean)

    # Timestamps
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Source tracking
    source: Mapped[Optional[str]] = mapped_column(String(50))
    hubspot_id: Mapped[Optional[str]] = mapped_column(String(100))
    apollo_id: Mapped[Optional[str]] = mapped_column(String(100))
    user_input_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("user_inputs.id"), nullable=True, index=True)

    # Relationships
    signals: Mapped[List["SignalEvent"]] = relationship("SignalEvent", back_populates="contact")
    outreach_logs: Mapped[List["OutreachLog"]] = relationship("OutreachLog", back_populates="contact")
    conversation_threads: Mapped[List["ConversationThread"]] = relationship("ConversationThread", back_populates="contact")
    funnel_events: Mapped[List["FunnelEvent"]] = relationship("FunnelEvent", back_populates="contact")
    deals: Mapped[List["Deal"]] = relationship("Deal", back_populates="contact")

    __table_args__ = (
        Index("ix_contacts_icp_score_dnc", "icp_score", "do_not_contact"),
        Index("ix_contacts_user_input_id", "user_input_id"),
    )


class SignalEvent(Base):
    """
    One record per detected buying signal.
    A2 writes here. Signal Conversion Registry is derived from this + funnel_events.
    """
    __tablename__ = "signal_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    contact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    signal_source: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    conversion_weight: Mapped[Optional[float]] = mapped_column(Float)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_outreach: Mapped[bool] = mapped_column(Boolean, default=False)
    sequence_step: Mapped[int] = mapped_column(Integer, default=0)
    next_step_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    contact: Mapped["Contact"] = relationship("Contact", back_populates="signals")

    __table_args__ = (
        Index("ix_signal_events_contact_type", "contact_id", "signal_type"),
    )


class SignalConversionRegistry(Base):
    """
    Empirical conversion rates per signal type. Updated monthly by A2.
    This is what makes signal detection self-improving.
    """
    __tablename__ = "signal_conversion_registry"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    signal_type: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, default=0.3)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    last_calibrated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OutreachLog(Base):
    """
    One record per email/message sent. Prevents duplicate sends.
    Unique constraint on (contact_id, campaign_type) enforces deduplication.
    """
    __tablename__ = "outreach_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    contact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), nullable=False, index=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(String(100))
    campaign_type: Mapped[str] = mapped_column(String(50))
    channel: Mapped[str] = mapped_column(String(20), default="email")
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body_preview: Mapped[Optional[str]] = mapped_column(Text)
    prompt_variant_id: Mapped[Optional[str]] = mapped_column(String(50))
    signal_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("signal_events.id"))
    sequence_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    call_script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linkedin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Opaque message/lead id returned by the email provider (Resend message id)
    outreach_provider_message_id: Mapped[Optional[str]] = mapped_column(String(100))
    sequence_step: Mapped[int] = mapped_column(Integer, default=0)
    call_script: Mapped[Optional[str]] = mapped_column(Text)
    linkedin_note: Mapped[Optional[str]] = mapped_column(Text)

    # Engagement tracking
    opened: Mapped[bool] = mapped_column(Boolean, default=False)
    open_count: Mapped[int] = mapped_column(Integer, default=0)
    replied: Mapped[bool] = mapped_column(Boolean, default=False)
    meeting_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    unsubscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    bounced: Mapped[bool] = mapped_column(Boolean, default=False)

    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    contact: Mapped["Contact"] = relationship("Contact", back_populates="outreach_logs")

    __table_args__ = (
        UniqueConstraint("contact_id", "campaign_type", name="uq_outreach_contact_campaign"),
        Index("ix_outreach_log_sent_at", "sent_at"),
    )


class PromptVariant(Base):
    """
    Email prompt variants per signal type. A3 selects variants based on reply_rate.
    Auto-promotes highest performing variant.
    """
    __tablename__ = "prompt_variants"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    reply_rate: Mapped[float] = mapped_column(Float, default=0.0)
    send_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    meeting_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationThread(Base):
    """
    Ordered thread of every interaction with a prospect.
    A4 loads this before generating any reply.
    """
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    contact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), nullable=False, index=True)
    outreach_log_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("outreach_log.id"))

    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(10))  # inbound / outbound
    channel: Mapped[str] = mapped_column(String(20), default="email")
    content: Mapped[Optional[str]] = mapped_column(Text)
    subject: Mapped[Optional[str]] = mapped_column(String(500))

    # Reply classification (A4)
    intent: Mapped[Optional[str]] = mapped_column(String(50))
    intent_confidence: Mapped[Optional[float]] = mapped_column(Float)
    readiness_score_delta: Mapped[Optional[float]] = mapped_column(Float)
    readiness_score_after: Mapped[Optional[float]] = mapped_column(Float)

    # Human loop
    draft_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_content: Mapped[Optional[str]] = mapped_column(Text)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(100))
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(100))
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    contact: Mapped["Contact"] = relationship("Contact", back_populates="conversation_threads")

    __table_args__ = (
        Index("ix_conversation_threads_contact_time", "contact_id", "occurred_at"),
    )


class Deal(Base):
    """
    CRM deal record. Synced from HubSpot. A5 reads and recommends updates.
    """
    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    hubspot_deal_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(50), default=DealStage.PROSPECTING, index=True)
    amount: Mapped[Optional[float]] = mapped_column(Float)
    close_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    owner_email: Mapped[Optional[str]] = mapped_column(String(200))

    # Pattern analysis fields (A5)
    days_in_current_stage: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_time_hours: Mapped[Optional[float]] = mapped_column(Float)
    stakeholder_count: Mapped[int] = mapped_column(Integer, default=1)
    meeting_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_flags: Mapped[Optional[list]] = mapped_column(JSONB, default=list)
    objections: Mapped[Optional[List[dict]]] = mapped_column(JSONB, nullable=True, default=None)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    deal_health_score: Mapped[Optional[float]] = mapped_column(Float)
    win_probability: Mapped[Optional[float]] = mapped_column(Float)
    buying_intent: Mapped[Optional[str]] = mapped_column(String(50))
    next_best_action: Mapped[Optional[str]] = mapped_column(Text)
    stage_confidence: Mapped[Optional[float]] = mapped_column(Float)

    # BANT signals from transcripts
    budget_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean)
    authority_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean)
    need_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean)
    timeline_confirmed: Mapped[Optional[bool]] = mapped_column(Boolean)

    # Outcome (for win-pattern model training)
    outcome: Mapped[Optional[str]] = mapped_column(String(20))  # won / lost
    lost_reason: Mapped[Optional[str]] = mapped_column(String(300))

    stage_entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stage_history: Mapped[List["DealStageHistory"]] = relationship("DealStageHistory", back_populates="deal")
    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="deals")


class DealStageHistory(Base):
    """Append-only log of every stage transition. Used for velocity baseline."""
    __tablename__ = "deal_stage_history"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    deal_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("deals.id"), nullable=False, index=True)
    from_stage: Mapped[Optional[str]] = mapped_column(String(50))
    to_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    days_in_from_stage: Mapped[Optional[int]] = mapped_column(Integer)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deal: Mapped["Deal"] = relationship("Deal", back_populates="stage_history")


class PendingAction(Base):
    """
    CRM actions waiting for human approval.
    A5 writes here. Daily Slack digest surfaces them to reps.
    Stage changes are never autonomous.
    """
    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(100))
    recommended_value: Mapped[Optional[str]] = mapped_column(String(500))
    current_value: Mapped[Optional[str]] = mapped_column(String(500))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    agent_id: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default=ActionStatus.PENDING, index=True)
    slack_message_ts: Mapped[Optional[str]] = mapped_column(String(100))
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_pending_actions_status_created", "status", "created_at"),
    )


class FunnelEvent(Base):
    """
    Append-only event log. Every state change in the GTM motion is written here.
    A7 reads from this to calculate conversion rates and forecast revenue.
    Never updated â€” only inserted.
    """
    __tablename__ = "funnel_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    contact_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), index=True)
    deal_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("deals.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(10))
    event_metadata: Mapped[Optional[dict]] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="funnel_events")

    __table_args__ = (
        Index("ix_funnel_events_type_time", "event_type", "timestamp"),
    )


class BrandAsset(Base):
    """
    Brand voice reference content with embeddings.
    A6 queries with cosine similarity to retrieve style examples.
    """
    __tablename__ = "brand_assets"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[Optional[str]] = mapped_column(String(50))
    icp_segment: Mapped[Optional[str]] = mapped_column(String(100))
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GeneratedContent(Base):
    """
    Content produced by A6. Tagged by ICP segment for use in A3 sequences.
    """
    __tablename__ = "generated_content"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(300))
    content_format: Mapped[str] = mapped_column(String(50))
    icp_segment: Mapped[Optional[str]] = mapped_column(String(100))
    topic: Mapped[Optional[str]] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    brief: Mapped[Optional[dict]] = mapped_column(JSONB)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    used_in_outreach: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RevenueForecast(Base):
    """Latest revenue forecast snapshot from A7."""
    __tablename__ = "revenue_forecasts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    forecast_30d: Mapped[Optional[float]] = mapped_column(Float)
    forecast_60d: Mapped[Optional[float]] = mapped_column(Float)
    forecast_90d: Mapped[Optional[float]] = mapped_column(Float)
    current_pipeline_value: Mapped[Optional[float]] = mapped_column(Float)
    bottleneck_stage: Mapped[Optional[str]] = mapped_column(String(50))
    bottleneck_description: Mapped[Optional[str]] = mapped_column(Text)
    recommended_lever: Mapped[Optional[str]] = mapped_column(Text)
    stage_conversion_rates: Mapped[Optional[dict]] = mapped_column(JSONB)
    stage_velocity_days: Mapped[Optional[dict]] = mapped_column(JSONB)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    input_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_payload: Mapped[Optional[dict]] = mapped_column(JSONB)

    error_message: Mapped[Optional[str]] = mapped_column(Text)
    current_agent: Mapped[Optional[str]] = mapped_column(String(10))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)

    workflow_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workflow_runs.id"),
        nullable=False,
        index=True
    )

    agent_id: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100))
    task_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)

    input_payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_payload: Mapped[Optional[dict]] = mapped_column(JSONB)

    error_message: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_agent_executions_workflow_agent", "workflow_run_id", "agent_id"),
    )


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"

    agent_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class OutreachDraft(Base):
    """
    Outreach drafts generated by Agent 3 waiting for approval.
    """
    __tablename__ = "outreach_drafts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    contact_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("contacts.id"), nullable=False, index=True)
    signal_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("signal_events.id"))
    
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    business_case: Mapped[str] = mapped_column(String(100), nullable=False)
    matched_services: Mapped[list] = mapped_column(JSONB, default=list)
    channel: Mapped[str] = mapped_column(String(50), default="email")
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, sent, failed
    approval_state: Mapped[str] = mapped_column(String(50), default="pending")  # pending, approved, rejected
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact: Mapped["Contact"] = relationship("Contact")
    signal: Mapped[Optional["SignalEvent"]] = relationship("SignalEvent")


class UserInput(Base):
    """
    Raw form submissions from the frontend intake form.
    Captured via POST /submit-input before any agent processing.

    Fields:
        our_services        — what the vendor sells (personalization context, NOT sent to Apollo)
        target_location     — where prospect companies are headquartered
        target_industries   — optional: comma-separated industry names for Apollo filtering
        target_company_size — employee range e.g. "50-5000" (expanded to Apollo buckets at runtime)
        target_keywords     — optional: comma-separated keyword signals for Apollo search
        target_job_titles   — comma-separated job titles to find at prospect companies
    """
    __tablename__ = "user_inputs"

    id: Mapped[int]                    = mapped_column(Integer, primary_key=True, autoincrement=True)
    our_company_name: Mapped[str]      = mapped_column(Text, nullable=False, server_default="")
    our_services: Mapped[str]          = mapped_column(Text, nullable=False)
    target_location: Mapped[str]       = mapped_column(String(200), nullable=False)
    target_industries: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_company_size: Mapped[str]   = mapped_column(String(50), nullable=False)
    target_keywords: Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
    target_job_titles: Mapped[str]     = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)

"""
Unit and integration tests for Agent 7 (Revenue Intelligence) isolation,
anti-fabrication guarantees, unpriced deal handling, and multi-user data scoping.

Tests:
1. Rep A's forecast includes Rep A's deals and excludes Rep B's deals.
2. Rep A's forecast is owned by Rep A even if Rep B submitted the latest intake.
3. Contact-based and owner-email-based deal ownership work correctly.
4. Missing user context cannot accidentally run an unrestricted rep forecast (raises ValueError).
5. Explicit company_wide mode executes safely.
6. Null and zero deal amounts do not become $25,000 (valued at $0.0, counted as unpriced).
7. Empty pipeline produces truthful zero-revenue state without fabrication.
8. Insufficient stage history displays 'Insufficient historical data to determine bottlenecks.'
9. Zero conversion deficit produces stage=None and does not create a false bottleneck alert.
10. Forecast pipeline value and deal list stay mathematically consistent.
"""
import uuid
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, delete

from app.core.database import AsyncSessionLocal, init_db, close_db
from app.core.config import get_settings
from app.models.models import (
    User, Contact, Deal, DealStageHistory, RevenueForecast, UserInput
)
from app.agents.a7_revenue import RevenueAgent, STAGE_ORDER


def _email(prefix="rep") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


@pytest_asyncio.fixture
async def db_session():
    settings = get_settings()
    settings.APP_ENV = "test"
    await init_db()
    async with AsyncSessionLocal() as db:
        yield db

    # Cleanup test data created
    async with AsyncSessionLocal() as db:
        users = (await db.execute(
            select(User).where(User.email.ilike("%@example.com"))
        )).scalars().all()
        if users:
            uids = [u.id for u in users]
            # Delete forecasts
            await db.execute(delete(RevenueForecast).where(RevenueForecast.user_id.in_(uids)))
            # Delete deals linked to users
            own_cids = (await db.execute(
                select(Contact.id).where(Contact.user_id.in_(uids))
            )).scalars().all()
            if own_cids:
                deal_ids = (await db.execute(
                    select(Deal.id).where(Deal.contact_id.in_(own_cids))
                )).scalars().all()
                if deal_ids:
                    await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id.in_(deal_ids)))
                await db.execute(delete(Deal).where(Deal.contact_id.in_(own_cids)))
                await db.execute(delete(Contact).where(Contact.id.in_(own_cids)))
            # Delete deals by owner email
            emails = [u.email for u in users if u.email]
            if emails:
                await db.execute(delete(Deal).where(Deal.owner_email.in_(emails)))
            # Delete user inputs
            await db.execute(delete(UserInput).where(UserInput.user_id.in_(uids)))
            # Delete users
            await db.execute(delete(User).where(User.id.in_(uids)))
            await db.commit()
    await close_db()


@pytest.mark.asyncio
async def test_a7_multi_user_deal_isolation(db_session):
    """Rep A's forecast includes Rep A's deals and excludes Rep B's deals."""
    db = db_session

    # Create Rep A and Rep B
    rep_a = User(name="Rep A", email=_email("rep-a"), password_hash="pw", is_active=True)
    rep_b = User(name="Rep B", email=_email("rep-b"), password_hash="pw", is_active=True)
    db.add_all([rep_a, rep_b])
    await db.commit()
    await db.refresh(rep_a)
    await db.refresh(rep_b)

    # Contacts
    contact_a = Contact(email=_email("contact-a"), company="Corp A", user_id=rep_a.id)
    contact_b = Contact(email=_email("contact-b"), company="Corp B", user_id=rep_b.id)
    db.add_all([contact_a, contact_b])
    await db.commit()
    await db.refresh(contact_a)
    await db.refresh(contact_b)

    # Deals
    deal_a = Deal(
        name="Deal A - Cloud Migration",
        amount=100000.0,
        amount_source="Salesforce",
        stage="proposal",
        contact_id=contact_a.id,
        owner_email=rep_a.email,
        outcome=None,
    )
    deal_b = Deal(
        name="Deal B - AI Transformation",
        amount=250000.0,
        amount_source="Salesforce",
        stage="discovery",
        contact_id=contact_b.id,
        owner_email=rep_b.email,
        outcome=None,
    )
    db.add_all([deal_a, deal_b])
    await db.commit()

    agent = RevenueAgent(db)

    # Run forecast for Rep A
    result_a = await agent.run(user_id=rep_a.id)
    assert result_a["deals_evaluated"] == 1
    assert result_a["pipeline_value"] == 100000.0
    assert result_a["user_id"] == rep_a.id
    # Assert Rep B deal is not in top deals
    top_deal_names_a = [d["deal_name"] for d in result_a.get("top_deals", [])]
    assert "Deal A - Cloud Migration" in top_deal_names_a
    assert "Deal B - AI Transformation" not in top_deal_names_a

    # Run forecast for Rep B
    result_b = await agent.run(user_id=rep_b.id)
    assert result_b["deals_evaluated"] == 1
    assert result_b["pipeline_value"] == 250000.0
    assert result_b["user_id"] == rep_b.id
    top_deal_names_b = [d["deal_name"] for d in result_b.get("top_deals", [])]
    assert "Deal B - AI Transformation" in top_deal_names_b
    assert "Deal A - Cloud Migration" not in top_deal_names_b


@pytest.mark.asyncio
async def test_a7_forecast_ownership_attribution(db_session):
    """Rep A's forecast is owned by Rep A even if Rep B submitted the latest intake."""
    db = db_session

    rep_a = User(name="Rep A", email=_email("rep-a-owner"), password_hash="pw", is_active=True)
    rep_b = User(name="Rep B", email=_email("rep-b-owner"), password_hash="pw", is_active=True)
    db.add_all([rep_a, rep_b])
    await db.commit()
    await db.refresh(rep_a)
    await db.refresh(rep_b)

    # Rep B submits latest global intake
    intake_b = UserInput(
        user_id=rep_b.id,
        our_company_name="B Company",
        our_services="Services",
        target_location="United States",
        target_industries="SaaS",
        target_company_size="51-200",
        target_keywords="CRM",
        target_job_titles="VP Sales",
        created_at=datetime.utcnow() + timedelta(seconds=10),
    )
    db.add(intake_b)

    # Rep A has a deal
    contact_a = Contact(email=_email("contact-a2"), company="Corp A2", user_id=rep_a.id)
    db.add(contact_a)
    await db.commit()
    await db.refresh(contact_a)

    deal_a = Deal(
        name="Deal A - Data Platform",
        amount=80000.0,
        amount_source="Salesforce",
        stage="negotiation",
        contact_id=contact_a.id,
        owner_email=rep_a.email,
        outcome=None,
    )
    db.add(deal_a)
    await db.commit()

    agent = RevenueAgent(db)
    result = await agent.run(user_id=rep_a.id)

    # Verify forecast record in database has user_id = rep_a.id, NOT rep_b.id
    res = await db.execute(
        select(RevenueForecast)
        .where(RevenueForecast.user_id == rep_a.id)
        .order_by(RevenueForecast.calculated_at.desc())
        .limit(1)
    )
    saved_forecast = res.scalar_one_or_none()
    assert saved_forecast is not None
    assert saved_forecast.user_id == rep_a.id
    assert saved_forecast.current_pipeline_value == 80000.0


@pytest.mark.asyncio
async def test_a7_contact_and_owner_email_resolution(db_session):
    """Deals are resolved both by Contact.user_id and Deal.owner_email."""
    db = db_session

    rep = User(name="Rep Dual", email=_email("rep-dual"), password_hash="pw", is_active=True)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    # Deal 1: contact.user_id == rep.id
    contact1 = Contact(email=_email("c1"), company="Co 1", user_id=rep.id)
    db.add(contact1)
    await db.commit()
    await db.refresh(contact1)

    deal1 = Deal(
        name="Deal 1 (Via Contact)",
        amount=40000.0,
        stage="proposal",
        contact_id=contact1.id,
        owner_email="other@corp.com",
        outcome=None,
    )

    # Deal 2: unowned contact, but deal.owner_email == rep.email
    contact2 = Contact(email=_email("c2"), company="Co 2", user_id=None)
    db.add(contact2)
    await db.commit()
    await db.refresh(contact2)

    deal2 = Deal(
        name="Deal 2 (Via Owner Email)",
        amount=60000.0,
        stage="discovery",
        contact_id=contact2.id,
        owner_email=rep.email,
        outcome=None,
    )

    # Deal 3: completely unrelated deal
    contact3 = Contact(email=_email("c3"), company="Co 3", user_id=None)
    db.add(contact3)
    await db.commit()
    await db.refresh(contact3)

    deal3 = Deal(
        name="Deal 3 (Unrelated)",
        amount=99000.0,
        stage="discovery",
        contact_id=contact3.id,
        owner_email="stranger@other.com",
        outcome=None,
    )
    db.add_all([deal1, deal2, deal3])
    await db.commit()

    agent = RevenueAgent(db)
    result = await agent.run(user_id=rep.id)

    # Rep should see Deal 1 and Deal 2 ($40k + $60k = $100k), and NOT Deal 3
    assert result["deals_evaluated"] == 2
    assert result["pipeline_value"] == 100000.0
    deal_names = [d["deal_name"] for d in result.get("top_deals", [])]
    assert "Deal 1 (Via Contact)" in deal_names
    assert "Deal 2 (Via Owner Email)" in deal_names
    assert "Deal 3 (Unrelated)" not in deal_names


@pytest.mark.asyncio
async def test_a7_missing_user_context_rejected(db_session):
    """Missing user context cannot accidentally run an unrestricted rep forecast."""
    db = db_session
    agent = RevenueAgent(db)

    # Must raise ValueError when user_id is None and company_wide is False
    with pytest.raises(ValueError, match="User context required"):
        await agent.run()

    with pytest.raises(ValueError, match="User context required"):
        await agent.run(user_id=None, company_wide=False)


@pytest.mark.asyncio
async def test_a7_explicit_company_wide_mode(db_session):
    """Explicit company_wide mode executes safely and computes global pipeline."""
    db = db_session

    rep_a = User(name="Rep CW A", email=_email("rep-cw-a"), password_hash="pw", is_active=True)
    rep_b = User(name="Rep CW B", email=_email("rep-cw-b"), password_hash="pw", is_active=True)
    db.add_all([rep_a, rep_b])
    await db.commit()
    await db.refresh(rep_a)
    await db.refresh(rep_b)

    c_a = Contact(email=_email("cw-ca"), company="Corp CW A", user_id=rep_a.id)
    c_b = Contact(email=_email("cw-cb"), company="Corp CW B", user_id=rep_b.id)
    db.add_all([c_a, c_b])
    await db.commit()
    await db.refresh(c_a)
    await db.refresh(c_b)

    d_a = Deal(name="CW Deal A", amount=50000.0, stage="discovery", contact_id=c_a.id, outcome=None)
    d_b = Deal(name="CW Deal B", amount=70000.0, stage="proposal", contact_id=c_b.id, outcome=None)
    db.add_all([d_a, d_b])
    await db.commit()

    agent = RevenueAgent(db)
    result = await agent.run(user_id=None, company_wide=True)

    assert result["company_wide"] is True
    assert result["user_id"] is None
    # Global pipeline includes both deals
    assert result["deals_evaluated"] >= 2
    assert result["pipeline_value"] >= 120000.0


@pytest.mark.asyncio
async def test_a7_null_and_zero_deal_amounts_no_25k(db_session):
    """Null and zero deal amounts do NOT become $25,000; unpriced count is accurately reported."""
    db = db_session

    rep = User(name="Rep Unpriced", email=_email("rep-unpriced"), password_hash="pw", is_active=True)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    contact = Contact(email=_email("c-unpriced"), company="Unpriced Co", user_id=rep.id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)

    # 1 unpriced deal (amount=None)
    deal_null = Deal(
        name="Unpriced Deal (None)",
        amount=None,
        amount_source="Not provided",
        stage="discovery",
        contact_id=contact.id,
        owner_email=rep.email,
        outcome=None,
    )
    # 1 zero deal (amount=0.0)
    deal_zero = Deal(
        name="Zero Amount Deal",
        amount=0.0,
        amount_source="Not provided",
        stage="discovery",
        contact_id=contact.id,
        owner_email=rep.email,
        outcome=None,
    )
    # 1 priced deal (amount=45,000.0)
    deal_priced = Deal(
        name="Confirmed Deal",
        amount=45000.0,
        amount_source="Salesforce",
        stage="proposal",
        contact_id=contact.id,
        owner_email=rep.email,
        outcome=None,
    )
    db.add_all([deal_null, deal_zero, deal_priced])
    await db.commit()

    agent = RevenueAgent(db)
    result = await agent.run(user_id=rep.id)

    # In previous buggy code, pipeline_value would be 25000 + 25000 + 45000 = $95,000!
    # In remediated code, pipeline_value must strictly equal confirmed $45,000.0!
    assert result["pipeline_value"] == 45000.0
    assert result["deals_evaluated"] == 3
    assert result["unpriced_deals_count"] == 2
    assert result["priced_deals_count"] == 1

    # Check top deals breakdown: unpriced deals have is_unpriced=True
    top_deals = {d["deal_name"]: d for d in result.get("top_deals", [])}
    assert top_deals["Unpriced Deal (None)"]["is_unpriced"] is True
    assert top_deals["Unpriced Deal (None)"]["amount"] is None
    assert top_deals["Zero Amount Deal"]["is_unpriced"] is True
    assert top_deals["Zero Amount Deal"]["amount"] is None
    assert top_deals["Confirmed Deal"]["is_unpriced"] is False
    assert top_deals["Confirmed Deal"]["amount"] == 45000.0


@pytest.mark.asyncio
async def test_a7_empty_pipeline_truthful_state(db_session):
    """An empty pipeline produces truthful zero revenue and no fabricated bottleneck."""
    db = db_session

    rep = User(name="Rep Empty", email=_email("rep-empty"), password_hash="pw", is_active=True)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    agent = RevenueAgent(db)
    result = await agent.run(user_id=rep.id)

    assert result["pipeline_value"] == 0.0
    assert result["forecast_30d"] == 0.0
    assert result["forecast_60d"] == 0.0
    assert result["forecast_90d"] == 0.0
    assert result["deals_evaluated"] == 0
    assert result["unpriced_deals_count"] == 0
    assert result["bottleneck_stage"] is None
    assert "Empty pipeline" in result["reason"]


@pytest.mark.asyncio
async def test_a7_insufficient_stage_history_no_false_bottleneck(db_session):
    """Missing stage transition history displays clear insufficient data message."""
    db = db_session

    rep = User(name="Rep NoHistory", email=_email("rep-nohistory"), password_hash="pw", is_active=True)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    contact = Contact(email=_email("c-nohistory"), company="NoHistory Co", user_id=rep.id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)

    deal = Deal(
        name="Deal Without Stage Transitions",
        amount=75000.0,
        stage="proposal",
        contact_id=contact.id,
        owner_email=rep.email,
        outcome=None,
    )
    db.add(deal)
    await db.commit()

    agent = RevenueAgent(db)
    result = await agent.run(user_id=rep.id)

    # When fewer than 2 real historical stage transitions exist, lever must be truthful
    assert result["lever"] == "Insufficient historical data to determine bottlenecks."
    assert result["bottleneck_stage"] is None


@pytest.mark.asyncio
async def test_a7_zero_deficit_no_false_bottleneck(db_session):
    """Directly test constraint identification: deficit <= 0 produces stage=None without false alerts."""
    db = db_session
    agent = RevenueAgent(db)

    # Mock conversion rates equal to baseline (deficit = 0.0 across all stages)
    baselines = {
        "discovery_to_demo": 0.40,
        "demo_to_proposal": 0.50,
        "proposal_to_negotiation": 0.60,
        "negotiation_to_closing": 0.70,
        "closing_to_won": 0.80,
    }
    conversion_rates = dict(baselines)
    deals = [Deal(name="Active Deal", amount=50000.0, stage="proposal")]

    constraint = await agent._identify_constraint_and_levers(
        current_rates=conversion_rates,
        baselines=baselines,
        deals=deals,
        has_real_stage_history=True,
    )

    # Must NOT produce a false bottleneck stage
    assert constraint["stage"] is None
    assert "Maintain conversion momentum" in constraint["lever"]


@pytest.mark.asyncio
async def test_a7_deal_table_and_forecast_consistency(db_session):
    """The revenue forecast pipeline value and deal breakdown stay mathematically identical."""
    db = db_session

    rep = User(name="Rep Consistent", email=_email("rep-consistent"), password_hash="pw", is_active=True)
    db.add(rep)
    await db.commit()
    await db.refresh(rep)

    contact = Contact(email=_email("c-consistent"), company="Consistent Co", user_id=rep.id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)

    deal1 = Deal(name="Deal 1", amount=35000.0, stage="discovery", contact_id=contact.id, owner_email=rep.email)
    deal2 = Deal(name="Deal 2", amount=65000.0, stage="proposal", contact_id=contact.id, owner_email=rep.email)
    deal3 = Deal(name="Deal 3", amount=None, stage="demo", contact_id=contact.id, owner_email=rep.email)
    db.add_all([deal1, deal2, deal3])
    await db.commit()

    agent = RevenueAgent(db)
    active_deals = await agent._get_active_deals(user_id=rep.id)
    assert len(active_deals) == 3

    # Sum of priced deals
    priced_sum = sum(d.amount for d in active_deals if d.amount and d.amount > 0)
    assert priced_sum == 100000.0

    result = await agent.run(user_id=rep.id)
    assert result["pipeline_value"] == priced_sum
    assert result["deals_evaluated"] == len(active_deals)

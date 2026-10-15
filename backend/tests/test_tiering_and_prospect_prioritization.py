"""
Unit & Integration Tests for ICP-Based Prospect Tiering and Prioritization
Covers all tiering rules and constraints:
1. Tier 1: Strong ICP (>= 70) + recent verified buying intent (funding_round, new_hire, earnings_call)
2. Tier 1 (Momentum): Good ICP (65–69) + exceptionally strong verified signal
3. Tier 2: Good ICP (>= 65) awaiting signals (no recent buying intent)
4. Tier 2: Moderate ICP (50–64) + meaningful recent signals
5. Tier 2 (Opportunistic): Fringe ICP (40–49) + verified active buying events (funding, hiring)
6. Tier 3: Fringe ICP (40–49) with only passive tech stack remains in Tier 3
7. Tier 3: Moderate ICP (50–64) with only weak supporting signals remains in Tier 3
8. Tier 3: Low ICP (< 40) remains in Tier 3
9. Passive technology-stack presence does not independently elevate accounts
10. Event coupling: Signal score, signal type, and recency belong to the SAME event
    (stale signal from Contact A cannot borrow recency from Contact B)
11. Duplicate signals do not artificially inflate priority
12. Missing ICP or signal data handled safely
13. Account-level consistency across multiple contacts of the same company
14. End-to-end API integration tests: /contacts/tier-summary and /contacts?tier=1|2|3|all
"""
import pytest
import uuid
from datetime import datetime, timedelta
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.models import User, Contact, ContactUserInputAssociation, UserInput
from app.services.tier_service import (
    AccountTierService,
    TIER_1_MIN_ICP,
    TIER_1_MIN_SIGNAL_SCORE,
    TIER_2_MIN_ICP,
    TIER_2_MIN_SIGNAL_SCORE,
    RECENCY_WINDOW_DAYS,
)
from sqlalchemy import select, delete
import httpx


# ── Helper Stub Contact ──────────────────────────────────────────────────────
class StubContact:
    def __init__(
        self,
        company="Acme Corp",
        icp_score=None,
        signal_score=None,
        signal_type=None,
        latest_signal_at=None,
        signal_source="",
        signals=None,
    ):
        self.id = str(uuid.uuid4())
        self.company = company
        self.icp_score = icp_score
        self.signal_score = signal_score
        self.signal_type = signal_type
        self.latest_signal_at = latest_signal_at
        self.signal_source = signal_source
        self.signals = signals or []


# ── 1. Tier 1: Strong ICP Fit (>= 70) + Recent Verified Buying Intent ────────
def test_tier_1_strong_icp_plus_recent_verified_buying_intent():
    now = datetime.utcnow()
    contacts = [
        StubContact(
            company="CloudTech",
            icp_score=80.0,
            signal_score=75.0,
            signal_type="funding_round",
            latest_signal_at=now - timedelta(days=2),
            signal_source="google_news_rss",
        )
    ]
    info = AccountTierService.classify_company("CloudTech", contacts, now=now)
    assert info.tier == 1
    assert info.tier_label == "Tier 1"
    assert "Strong ICP fit" in info.reason
    assert "funding round" in info.reason
    assert "funding_round" in info.signal_types


# ── 2. Tier 1 (Momentum): Good ICP (65–69) + Exceptionally Strong Signals ────
def test_tier_1_momentum_icp_65_to_69():
    now = datetime.utcnow()
    # ArriVent Biopharma style: ICP 67 with earnings call (score 64)
    contacts = [
        StubContact(
            company="Momentum Bio",
            icp_score=67.0,
            signal_score=64.0,
            signal_type="earnings_call",
            latest_signal_at=now - timedelta(days=5),
            signal_source="google_news_rss",
        )
    ]
    info = AccountTierService.classify_company("Momentum Bio", contacts, now=now)
    assert info.tier == 1
    assert info.tier_label == "Tier 1 (Momentum)"
    assert "High Momentum" in info.reason
    assert info.account_icp_score == 67.0


# ── 3. Tier 2: Good ICP (>= 65) Awaiting Signals ─────────────────────────────
def test_tier_2_good_icp_awaiting_signals():
    now = datetime.utcnow()
    # High ICP (78.0) but no signals
    contacts = [
        StubContact(
            company="Ashton Potter",
            icp_score=78.0,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
        )
    ]
    info = AccountTierService.classify_company("Ashton Potter", contacts, now=now)
    assert info.tier == 2
    assert info.tier_label == "Tier 2"
    assert "awaiting recent buying signals" in info.reason or "Strong ICP fit" in info.reason

    # ICP 68 awaiting signals
    contacts_68 = [
        StubContact(
            company="API Connects Ltd",
            icp_score=68.0,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
        )
    ]
    info_68 = AccountTierService.classify_company("API Connects Ltd", contacts_68, now=now)
    assert info_68.tier == 2
    assert info_68.tier_label == "Tier 2"


# ── 4. Passive Technology Stack Presence Does Not Elevate to Tier 1 ──────────
def test_passive_tech_stack_does_not_elevate_to_tier_1():
    now = datetime.utcnow()
    # High ICP (78.0) with passive website fingerprint detection
    contacts = [
        StubContact(
            company="Fingerprint Co",
            icp_score=78.0,
            signal_score=55.0,
            signal_type="tech_stack_change",
            signal_source="website_fingerprint",
            latest_signal_at=now - timedelta(days=2),
        )
    ]
    info = AccountTierService.classify_company("Fingerprint Co", contacts, now=now)
    # Must NOT become Tier 1 based only on passive tech stack presence!
    assert info.tier == 2
    assert "installed tech stack presence" in info.reason or "awaiting active buying intent" in info.reason


# ── 5. Tier 2: Moderate ICP (50–64) With Meaningful Recent Signals ───────────
def test_tier_2_moderate_fit_with_meaningful_signal():
    now = datetime.utcnow()
    contacts = [
        StubContact(
            company="MidScale Inc",
            icp_score=60.0,
            signal_score=55.0,
            signal_type="funding_round",
            latest_signal_at=now - timedelta(days=5),
            signal_source="google_news_rss",
        )
    ]
    info = AccountTierService.classify_company("MidScale Inc", contacts, now=now)
    assert info.tier == 2
    assert info.tier_label == "Tier 2"
    assert "Promising ICP fit" in info.reason


# ── 6. Tier 2 (Opportunistic): Fringe ICP (40–49) With Verified Active Events ─
def test_tier_2_opportunistic_fringe_icp_with_funding():
    now = datetime.utcnow()
    # Buildertrend style: ICP 49 with verified funding round
    contacts = [
        StubContact(
            company="Buildertrend",
            icp_score=49.0,
            signal_score=58.0,
            signal_type="funding_round",
            latest_signal_at=now - timedelta(days=15),
            signal_source="google_news_rss",
        )
    ]
    info = AccountTierService.classify_company("Buildertrend", contacts, now=now)
    assert info.tier == 2
    assert info.tier_label == "Tier 2 (Opportunistic)"
    assert "Opportunistic Discovery" in info.reason


# ── 7. Fringe ICP (40–49) With Passive Tech Stack Remains in Tier 3 ──────────
def test_fringe_icp_with_passive_tech_remains_tier_3():
    now = datetime.utcnow()
    # Xtalic style: ICP 42 with only website fingerprinting
    contacts = [
        StubContact(
            company="Xtalic Corporation",
            icp_score=42.0,
            signal_score=40.0,
            signal_type="tech_stack_change",
            signal_source="website_fingerprint",
            latest_signal_at=now - timedelta(days=2),
        )
    ]
    info = AccountTierService.classify_company("Xtalic Corporation", contacts, now=now)
    assert info.tier == 3
    assert info.tier_label == "Tier 3"
    assert "without verified funding or hiring" in info.reason or "Fringe ICP fit" in info.reason


# ── 8. Tier 3: Low ICP (< 40) or Moderate ICP Without Meaningful Signals ─────
def test_tier_3_low_icp_and_weak_signals():
    now = datetime.utcnow()
    # Low ICP (< 40)
    c_low = [
        StubContact(
            company="LowFit Corp",
            icp_score=35.0,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
        )
    ]
    info_low = AccountTierService.classify_company("LowFit Corp", c_low, now=now)
    assert info_low.tier == 3
    assert info_low.tier_label == "Tier 3"

    # Moderate ICP (63) with only weak geo expansion (score 22 < 40 threshold)
    c_weak = [
        StubContact(
            company="NextEdge",
            icp_score=63.0,
            signal_score=22.0,
            signal_type="news_expansion",
            signal_source="adzuna",
            latest_signal_at=now - timedelta(days=2),
        )
    ]
    info_weak = AccountTierService.classify_company("NextEdge", c_weak, now=now)
    assert info_weak.tier == 3
    assert info_weak.tier_label == "Tier 3"


# ── 9. Recency Window: Old vs Recent Signals Handled Differently ──────────────
def test_signal_recency_handling():
    now = datetime.utcnow()

    # Case A: Signal is recent (5 days old <= 30 days) -> Qualifies for Tier 1 with ICP 75
    recent_contacts = [
        StubContact(
            company="Recent Co",
            icp_score=75.0,
            signal_score=70.0,
            signal_type="funding_round",
            signal_source="google_news_rss",
            latest_signal_at=now - timedelta(days=5),
        )
    ]
    info_recent = AccountTierService.classify_company("Recent Co", recent_contacts, now=now)
    assert info_recent.tier == 1
    assert info_recent.is_recent is True

    # Case B: Signal is old (45 days old > 30 days) -> Stale, does NOT qualify for Tier 1; drops to Tier 2
    stale_contacts = [
        StubContact(
            company="Stale Co",
            icp_score=75.0,
            signal_score=70.0,
            signal_type="funding_round",
            signal_source="google_news_rss",
            latest_signal_at=now - timedelta(days=45),
        )
    ]
    info_stale = AccountTierService.classify_company("Stale Co", stale_contacts, now=now)
    assert info_stale.tier == 2  # Strong ICP but stale signals
    assert info_stale.is_recent is False
    assert "older than 30d" in info_stale.reason


# ── 10. Event Coupling: Stale Event Cannot Borrow Recency From Unrelated Event ─
def test_unrelated_events_do_not_cross_contaminate_recency():
    now = datetime.utcnow()
    # Contact 1 has a stale high-value funding signal (50 days old)
    c1 = StubContact(
        company="CrossContamination Inc",
        icp_score=80.0,
        signal_score=70.0,
        signal_type="funding_round",
        signal_source="google_news_rss",
        latest_signal_at=now - timedelta(days=50),
    )
    # Contact 2 has a recent but weak geographic expansion signal (score 22, 2 days old)
    c2 = StubContact(
        company="CrossContamination Inc",
        icp_score=75.0,
        signal_score=22.0,
        signal_type="news_expansion",
        signal_source="adzuna",
        latest_signal_at=now - timedelta(days=2),
    )
    contacts = [c1, c2]
    info = AccountTierService.classify_company("CrossContamination Inc", contacts, now=now)

    # Must NOT become Tier 1!
    # The funding round cannot borrow the 2-day recency of the weak news expansion!
    assert info.tier == 2
    assert "awaiting high-intent buying signals" in info.reason or "supporting market signals" in info.reason


# ── 11. Duplicate Signals Do Not Artificially Inflate Priority ────────────────
def test_duplicate_signals_deduplication():
    now = datetime.utcnow()
    # Contact with repeated duplicate signal types "job_posting,job_posting,job_posting"
    contacts = [
        StubContact(
            company="Duplicate Co",
            icp_score=40.0,  # Fringe ICP (< 50)
            signal_score=30.0,
            signal_type="job_posting,job_posting,job_posting",
            latest_signal_at=now - timedelta(days=2),
        )
    ]
    info = AccountTierService.classify_company("Duplicate Co", contacts, now=now)
    # Unique signal types should only have 1 item
    assert len(info.signal_types) == 1
    assert info.signal_count == 1
    # Weak score (30 < 40) cannot jump to Tier 2
    assert info.tier == 3


# ── 12. Missing ICP or Signal Data Handled Safely ─────────────────────────────
def test_missing_data_safe_handling():
    now = datetime.utcnow()
    contacts = [
        StubContact(
            company="Ghost Account",
            icp_score=None,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
        )
    ]
    # Must not raise exceptions or crash
    info = AccountTierService.classify_company("Ghost Account", contacts, now=now)
    assert info.tier == 3
    assert info.account_icp_score == 0.0
    assert info.account_signal_score == 0.0
    assert info.signal_count == 0
    assert info.is_recent is False


# ── 13. Account-Level Consistency Across Multiple Contacts of Same Company ────
def test_account_level_tiering_consistency():
    now = datetime.utcnow()
    # Two contacts at same company: Executive with high ICP, junior with lower ICP
    c1 = StubContact(
        company="Enterprise Alpha",
        icp_score=85.0,
        signal_score=72.0,
        signal_type="funding_round",
        signal_source="google_news_rss",
        latest_signal_at=now - timedelta(days=1),
    )
    c2 = StubContact(
        company="Enterprise Alpha",
        icp_score=45.0,
        signal_score=None,
        signal_type=None,
        latest_signal_at=None,
    )
    contacts = [c1, c2]
    annotated = AccountTierService.annotate_contacts(contacts, now=now)

    # BOTH contacts must receive Tier 1 because Enterprise Alpha is a Tier 1 account
    assert annotated[0].tier == 1
    assert annotated[1].tier == 1
    assert annotated[0].tier_label == "Tier 1"
    assert annotated[1].tier_label == "Tier 1"
    assert annotated[0].account_icp_score == 85.0
    assert annotated[1].account_icp_score == 85.0


# ── 14. Integration Test: API Tier Filtering and Tier Summary ─────────────────
@pytest.mark.asyncio
async def test_api_tier_summary_and_filtering():
    async with AsyncSessionLocal() as db:
        user_suffix = uuid.uuid4().hex[:6]
        user = User(
            id=str(uuid.uuid4()),
            email=f"rep_{user_suffix}@forcecloud.com",
            name="Tier Rep",
            password_hash="hashed_pw",
        )
        db.add(user)
        await db.commit()

        u_input = UserInput(
            user_id=user.id,
            our_company_name="ForceCloud Tier Test",
            our_services="Salesforce AI",
            target_location="US",
            target_company_size="50-200",
            target_job_titles="VP",
        )
        db.add(u_input)
        await db.commit()

        now = datetime.utcnow()

        # Contact 1: Tier 1 candidate (ICP 85 + verified funding round)
        c1 = Contact(
            email=f"t1_{user_suffix}@alpha.com",
            first_name="Alice",
            last_name="Alpha",
            company=f"Alpha Corp {user_suffix}",
            user_id=user.id,
            user_input_id=u_input.id,
            icp_score=85.0,
            signal_score=72.0,
            signal_type="funding_round",
            latest_signal_at=now - timedelta(days=2),
            source="apollo",
        )
        # Contact 2: Tier 2 candidate (ICP 75, no signal)
        c2 = Contact(
            email=f"t2_{user_suffix}@beta.com",
            first_name="Bob",
            last_name="Beta",
            company=f"Beta Corp {user_suffix}",
            user_id=user.id,
            user_input_id=u_input.id,
            icp_score=75.0,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
            source="apollo",
        )
        # Contact 3: Tier 3 candidate (ICP 30, no signal)
        c3 = Contact(
            email=f"t3_{user_suffix}@gamma.com",
            first_name="Charlie",
            last_name="Gamma",
            company=f"Gamma Corp {user_suffix}",
            user_id=user.id,
            user_input_id=u_input.id,
            icp_score=30.0,
            signal_score=None,
            signal_type=None,
            latest_signal_at=None,
            source="apollo",
        )

        db.add_all([c1, c2, c3])
        await db.flush()

        db.add(ContactUserInputAssociation(contact_id=c1.id, user_input_id=u_input.id))
        db.add(ContactUserInputAssociation(contact_id=c2.id, user_input_id=u_input.id))
        db.add(ContactUserInputAssociation(contact_id=c3.id, user_input_id=u_input.id))
        await db.commit()

        token = create_access_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
                # 1. Test GET /contacts/tier-summary
                res_sum = await client.get(f"/api/v1/contacts/tier-summary?user_input_id={u_input.id}", headers=headers)
                assert res_sum.status_code == 200
                data_sum = res_sum.json()
                assert data_sum["all"] == 3
                assert data_sum["tier_1"] == 1
                assert data_sum["tier_2"] == 1
                assert data_sum["tier_3"] == 1

                # 2. Test GET /contacts with tier=all
                res_all = await client.get(f"/api/v1/contacts?user_input_id={u_input.id}&tier=all", headers=headers)
                assert res_all.status_code == 200
                assert len(res_all.json()) == 3

                # 3. Test GET /contacts with tier=1
                res_t1 = await client.get(f"/api/v1/contacts?user_input_id={u_input.id}&tier=1", headers=headers)
                assert res_t1.status_code == 200
                data_t1 = res_t1.json()
                assert len(data_t1) == 1
                assert data_t1[0]["email"] == c1.email
                assert data_t1[0]["tier"] == 1
                assert data_t1[0]["tier_label"] == "Tier 1"

                # 4. Test GET /contacts with tier=2
                res_t2 = await client.get(f"/api/v1/contacts?user_input_id={u_input.id}&tier=2", headers=headers)
                assert res_t2.status_code == 200
                data_t2 = res_t2.json()
                assert len(data_t2) == 1
                assert data_t2[0]["email"] == c2.email
                assert data_t2[0]["tier"] == 2

                # 5. Test GET /contacts with tier=3
                res_t3 = await client.get(f"/api/v1/contacts?user_input_id={u_input.id}&tier=3", headers=headers)
                assert res_t3.status_code == 200
                data_t3 = res_t3.json()
                assert len(data_t3) == 1
                assert data_t3[0]["email"] == c3.email
                assert data_t3[0]["tier"] == 3

                # 6. Test GET /contacts/{id} detail view annotations
                res_det = await client.get(f"/api/v1/contacts/{c1.id}", headers=headers)
                assert res_det.status_code == 200
                det_json = res_det.json()
                assert det_json["tier"] == 1
                assert det_json["tier_label"] == "Tier 1"
                assert "Strong ICP fit" in det_json["tier_reason"]

        finally:
            # Teardown test rows
            await db.execute(delete(ContactUserInputAssociation).where(ContactUserInputAssociation.user_input_id == u_input.id))
            await db.delete(c1)
            await db.delete(c2)
            await db.delete(c3)
            await db.delete(u_input)
            await db.delete(user)
            await db.commit()

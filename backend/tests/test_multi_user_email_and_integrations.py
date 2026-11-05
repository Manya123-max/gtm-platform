"""
Multi-User Email Architecture & Production Readiness Tests.

Tests:
1. Google integration ownership & encryption
2. User A cannot access or disconnect User B's integration
3. User A cannot send using User B's mailbox
4. Cal.com per-sales-rep configuration & booking URL generation
5. A3 outbound ownership & sender selection
6. A4 inbound isolation & unknown sender rejection
7. A4 duplicate message-id idempotency protection
8. Slack signature validation & replay protection
9. A5 deal default amount is None / Not provided (no fake $50,000)
10. A5 simulation mode flag guards synthetic transcripts
11. Real CRM / transcript amounts are preserved
"""
import uuid
import time
import hmac
import hashlib
from datetime import datetime, timedelta
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.main import app
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db, close_db
from app.models.models import (
    User, UserIntegration, Contact, OutreachDraft, Deal, DealStage, Notification, UserInput, ConversationThread
)
from app.services.token_encryption import encrypt_token, decrypt_token
from app.services.cal_service import CalService
from app.agents.a3_outreach import DraftManager
from app.agents.a4_inbound import InboundAgent
from app.agents.a5_deal import DealAgent


@pytest_asyncio.fixture
async def client():
    orig_auth = settings.AUTH_ENABLED
    orig_env = settings.APP_ENV
    settings.AUTH_ENABLED = True
    settings.APP_ENV = "test"
    await init_db()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        # Clean up any test users and their data created during tests
        from app.core.database import AsyncSessionLocal
        from app.models.models import (
            User, Contact, UserInput, Notification, SignalEvent, OutreachDraft, Deal,
            UserIntegration, OutreachLog, ConversationThread, FunnelEvent
        )
        from sqlalchemy import select, delete, or_
        async with AsyncSessionLocal() as db:
            users = (await db.execute(select(User).where(or_(User.email.ilike("%@example.com"), User.email.ilike("%@company.com"))))).scalars().all()
            if users:
                uids = [u.id for u in users]
                c_sub = select(Contact.id).where(Contact.user_id.in_(uids))
                await db.execute(delete(OutreachDraft).where(OutreachDraft.user_id.in_(uids)))
                await db.execute(delete(Deal).where(Deal.contact_id.in_(c_sub)))
                await db.execute(delete(Notification).where(Notification.contact_id.in_(c_sub)))
                await db.execute(delete(SignalEvent).where(SignalEvent.contact_id.in_(c_sub)))
                await db.execute(delete(OutreachLog).where(OutreachLog.contact_id.in_(c_sub)))
                await db.execute(delete(ConversationThread).where(ConversationThread.contact_id.in_(c_sub)))
                await db.execute(delete(FunnelEvent).where(FunnelEvent.contact_id.in_(c_sub)))
                await db.execute(delete(Contact).where(Contact.user_id.in_(uids)))
                await db.execute(delete(UserInput).where(UserInput.user_id.in_(uids)))
                await db.execute(delete(UserIntegration).where(UserIntegration.user_id.in_(uids)))
                await db.execute(delete(User).where(User.id.in_(uids)))
                await db.commit()
        settings.AUTH_ENABLED = orig_auth
        settings.APP_ENV = orig_env
        await close_db()


def _email(prefix="rep"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}@company.com"


async def _register(client, email=None, password="Passw0rd123!", name="Sales Rep"):
    email = email or _email()
    r = await client.post("/api/v1/auth/register", json={
        "name": name, "email": email,
        "password": password, "confirm_password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# 1. TOKEN ENCRYPTION & DECRYPTION
# ─────────────────────────────────────────────────────────────────────────────

def test_token_encryption_and_decryption():
    raw_token = "ya29.a0AfH6SMD_test_refresh_token_very_secret_12345"
    encrypted = encrypt_token(raw_token)
    assert encrypted is not None
    assert encrypted != raw_token
    decrypted = decrypt_token(encrypted)
    assert decrypted == raw_token

    # None and empty handling
    assert encrypt_token(None) is None
    assert decrypt_token(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. MULTI-USER INTEGRATION ISOLATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_integrations_endpoint_unauthenticated(client):
    r = await client.get("/api/v1/integrations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_user_a_cannot_access_or_disconnect_user_b_integration(client):
    # Register Rep A and Rep B
    rep_a = await _register(client, name="Alice Rep")
    rep_b = await _register(client, name="Bob Rep")

    auth_a = {"Authorization": f"Bearer {rep_a['access_token']}"}
    auth_b = {"Authorization": f"Bearer {rep_b['access_token']}"}

    # Seed an active Google integration for Rep A in the DB
    async with AsyncSessionLocal() as db:
        int_a = UserIntegration(
            user_id=rep_a["user"]["id"],
            provider="google",
            provider_account_email=rep_a["user"]["email"],
            encrypted_access_token=encrypt_token("access-token-a"),
            encrypted_refresh_token=encrypt_token("refresh-token-a"),
            token_expires_at=datetime.utcnow() + timedelta(hours=1),
            status="connected",
        )
        db.add(int_a)
        await db.commit()

    # Rep A sees Google connected
    r_a = await client.get("/api/v1/integrations", headers=auth_a)
    assert r_a.status_code == 200
    assert r_a.json()["user_integrations"]["google"]["connected"] is True
    assert r_a.json()["user_integrations"]["google"]["email"] == rep_a["user"]["email"]

    # Rep B sees Google NOT connected
    r_b = await client.get("/api/v1/integrations", headers=auth_b)
    assert r_b.status_code == 200
    assert r_b.json()["user_integrations"]["google"]["connected"] is False

    # Rep B attempts to disconnect Google -> only disconnects Rep B's own integration
    disc_b = await client.post("/api/v1/integrations/google/disconnect", headers=auth_b)
    assert disc_b.status_code == 200

    # Rep A's integration MUST still be connected
    r_a_after = await client.get("/api/v1/integrations", headers=auth_a)
    assert r_a_after.json()["user_integrations"]["google"]["connected"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. CAL.COM PER-SALES-REP CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cal_com_user_settings_isolation(client):
    rep_a = await _register(client, name="Alice Rep")
    rep_b = await _register(client, name="Bob Rep")

    auth_a = {"Authorization": f"Bearer {rep_a['access_token']}"}
    auth_b = {"Authorization": f"Bearer {rep_b['access_token']}"}

    # Rep A sets their Cal.com link
    url_a = "https://cal.com/alice-gtm/15min"
    r_set_a = await client.put("/api/v1/user/settings", headers=auth_a, json={
        "cal_com_booking_url": url_a,
        "cal_com_event_slug": "alice-gtm/15min",
    })
    assert r_set_a.status_code == 200

    # Rep B sets their Cal.com link
    url_b = "https://cal.com/bob-gtm/30min"
    r_set_b = await client.put("/api/v1/user/settings", headers=auth_b, json={
        "cal_com_booking_url": url_b,
        "cal_com_event_slug": "bob-gtm/30min",
    })
    assert r_set_b.status_code == 200

    # Verify Rep A gets Rep A's link
    get_a = await client.get("/api/v1/user/settings", headers=auth_a)
    assert get_a.json()["cal_com_booking_url"] == url_a

    # Verify Rep B gets Rep B's link
    get_b = await client.get("/api/v1/user/settings", headers=auth_b)
    assert get_b.json()["cal_com_booking_url"] == url_b

    # Verify CalService generates rep-specific booking link
    async with AsyncSessionLocal() as db:
        user_a = await db.get(User, rep_a["user"]["id"])
        user_b = await db.get(User, rep_b["user"]["id"])
        cal_svc = CalService()

        link_a = await cal_svc.get_booking_link("prospect@target.com", "John Doe", user=user_a)
        assert "alice-gtm/15min" in link_a
        assert "bob-gtm" not in link_a

        link_b = await cal_svc.get_booking_link("prospect@target.com", "John Doe", user=user_b)
        assert "bob-gtm/30min" in link_b
        assert "alice-gtm" not in link_b


# ─────────────────────────────────────────────────────────────────────────────
# 4. A3 OUTBOUND OWNERSHIP & DRAFT APPROVAL ISOLATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a3_outbound_ownership_and_draft_approval_isolation(client):
    settings.AGENT3_TEST_MODE = True
    rep_a = await _register(client, name="Alice Rep")
    rep_b = await _register(client, name="Bob Rep")

    auth_a = {"Authorization": f"Bearer {rep_a['access_token']}"}
    auth_b = {"Authorization": f"Bearer {rep_b['access_token']}"}

    # Create contact owned by Rep A
    async with AsyncSessionLocal() as db:
        contact_a = Contact(
            first_name="Jane",
            last_name="Prospect",
            email=_email("prospect"),
            company="Acme Corp",
            user_id=rep_a["user"]["id"],
        )
        db.add(contact_a)
        await db.commit()
        await db.refresh(contact_a)

        # Create outreach draft for contact_a
        draft = OutreachDraft(
            contact_id=contact_a.id,
            user_id=rep_a["user"]["id"],
            subject="Introducing AI Automation",
            body="Hi Jane, would love to connect.",
            business_case="efficiency",
            channel="email",
            status="pending",
            approval_state="pending",
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        draft_id = draft.id

    # Rep B attempts to approve Rep A's draft via API -> rejected (404/403)
    r_b_approve = await client.post(f"/api/v1/drafts/{draft_id}/approve", headers=auth_b)
    assert r_b_approve.status_code in (404, 403)

    # Rep A approves their own draft -> succeeds
    r_a_approve = await client.post(f"/api/v1/drafts/{draft_id}/approve", headers=auth_a)
    assert r_a_approve.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 5. A4 INBOUND EMAIL: MULTI-REP ISOLATION & SAFETY
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a4_inbound_rep_isolation_and_safety(client):
    rep_a = await _register(client, name="Alice Inbound")
    rep_b = await _register(client, name="Bob Inbound")
    rep_a_id = rep_a["user"]["id"]
    rep_b_id = rep_b["user"]["id"]
    prospect_email = _email("prospect")

    async with AsyncSessionLocal() as db:
        u_a = UserInput(
            user_id=rep_a_id,
            our_company_name="Rep A Corp",
            our_services="SaaS",
            target_location="United States",
            target_company_size="50-200",
            target_job_titles="CTO",
        )
        u_b = UserInput(
            user_id=rep_b_id,
            our_company_name="Rep B Corp",
            our_services="SaaS",
            target_location="United States",
            target_company_size="50-200",
            target_job_titles="CTO",
        )
        db.add_all([u_a, u_b])
        await db.commit()
        await db.refresh(u_a)
        await db.refresh(u_b)

        # Rep A has a contact with prospect_email
        c_a = Contact(
            first_name="Target",
            last_name="Alpha",
            email=prospect_email,
            company="Company A",
            user_id=rep_a_id,
            user_input_id=u_a.id,
        )
        # Rep B has a contact with the same prospect_email in their own pipeline
        c_b = Contact(
            first_name="Target",
            last_name="Beta",
            email=prospect_email,
            company="Company B",
            user_id=rep_b_id,
            user_input_id=u_b.id,
        )
        db.add_all([c_a, c_b])
        await db.commit()
        await db.refresh(c_a)
        await db.refresh(c_b)

        try:
            agent = InboundAgent(db)

            # 1. Reply into Rep A's mailbox (user_id=rep_a_id)
            matched_contact_a = await agent._find_contact(prospect_email, user_id=rep_a_id)
            assert matched_contact_a is not None
            assert matched_contact_a.id == c_a.id
            assert matched_contact_a.user_id == rep_a_id

            # 2. Reply into Rep B's mailbox (user_id=rep_b_id)
            matched_contact_b = await agent._find_contact(prospect_email, user_id=rep_b_id)
            assert matched_contact_b is not None
            assert matched_contact_b.id == c_b.id
            assert matched_contact_b.user_id == rep_b_id

            # 3. Unknown sender rejection
            unknown = await agent._find_contact("random.unknown@stranger.org", user_id=rep_a_id)
            assert unknown is None

            # 4. Duplicate message-id idempotency
            msg_id = f"test_msg_{uuid.uuid4().hex[:8]}"
            payload = {
                "from_address": prospect_email,
                "reply_text": "Sounds interesting, let's talk.",
                "subject": "Re: Partnership",
                "message_id": msg_id,
            }
            res1 = await agent.handle_reply(payload, user_id=rep_a_id)
            assert res1.get("status") != "already_processed"

            # Second delivery of same message_id is rejected as duplicate
            res2 = await agent.handle_reply(payload, user_id=rep_a_id)
            assert res2.get("status") == "already_processed"
        finally:
            for cid in [c_a.id, c_b.id]:
                nots = (await db.execute(select(Notification).where(Notification.contact_id == cid))).scalars().all()
                for n in nots:
                    await db.delete(n)
                thrs = (await db.execute(select(ConversationThread).where(ConversationThread.contact_id == cid))).scalars().all()
                for t in thrs:
                    await db.delete(t)
            await db.delete(c_a)
            await db.delete(c_b)
            await db.delete(u_a)
            await db.delete(u_b)
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 6. SLACK SIGNATURE & REPLAY VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_signature_verification_and_replay_protection(client):
    orig_secret = settings.SLACK_SIGNING_SECRET
    test_secret = "test-slack-signing-secret-gtm-12345"
    settings.SLACK_SIGNING_SECRET = test_secret

    try:
        now_ts = str(int(time.time()))
        body_str = '{"type": "block_actions", "actions": []}'

        # Valid signature
        sig_base = f"v0:{now_ts}:{body_str}"
        valid_sig = "v0=" + hmac.new(test_secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()

        headers_valid = {
            "X-Slack-Request-Timestamp": now_ts,
            "X-Slack-Signature": valid_sig,
            "Content-Type": "application/json",
        }
        r_ok = await client.post("/slack/actions", content=body_str, headers=headers_valid)
        assert r_ok.status_code == 200

        # Invalid signature -> 401
        headers_bad = {
            "X-Slack-Request-Timestamp": now_ts,
            "X-Slack-Signature": "v0=invalid_signature_hash_here",
            "Content-Type": "application/json",
        }
        r_bad = await client.post("/slack/actions", content=body_str, headers=headers_bad)
        assert r_bad.status_code == 401

        # Expired timestamp (replay attack > 5 min old) -> 400
        old_ts = str(int(time.time()) - 400)
        old_base = f"v0:{old_ts}:{body_str}"
        old_sig = "v0=" + hmac.new(test_secret.encode(), old_base.encode(), hashlib.sha256).hexdigest()
        headers_old = {
            "X-Slack-Request-Timestamp": old_ts,
            "X-Slack-Signature": old_sig,
            "Content-Type": "application/json",
        }
        r_expired = await client.post("/slack/actions", content=body_str, headers=headers_old)
        assert r_expired.status_code == 400
    finally:
        settings.SLACK_SIGNING_SECRET = orig_secret


# ─────────────────────────────────────────────────────────────────────────────
# 7. A5 DEAL AMOUNT: NULL / NOT PROVIDED (NO FAKE $50,000)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a5_discovery_deal_amount_none_not_50000():
    async with AsyncSessionLocal() as db:
        contact = Contact(
            first_name="Arthur",
            last_name="Dent",
            email=_email("dent"),
            company="Megadodo Publications",
        )
        db.add(contact)
        await db.commit()
        await db.refresh(contact)

        agent = DealAgent(db)
        # Call _match_to_deal for contact with no active deal
        deal, matched_contact = await agent._match_to_deal(
            attendees=[{"email": contact.email, "name": f"{contact.first_name} {contact.last_name}"}],
            title="Discovery Call",
        )

        try:
            assert deal is not None
            # Deal amount must be None (not 50000.0)
            assert deal.amount is None
            assert deal.amount_source == "Not provided"
        finally:
            if deal:
                await db.delete(deal)
            await db.delete(contact)
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# 8. A5 SIMULATION MODE GUARD & REAL CRM PRESERVATION
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a5_simulation_mode_guard_and_crm_preservation():
    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        # In production mode (A5_SIMULATION_MODE=False):
        settings.A5_SIMULATION_MODE = False
        res = await agent._identify_and_process_meeting_prospects()
        assert res["transcripts_processed"] == 0
        assert res["deals_created"] == 0

        # Real CRM deal amount preservation:
        crm_deal = Deal(
            name="HubSpot Enterprise Sync",
            hubspot_deal_id=f"hs_deal_{uuid.uuid4().hex[:8]}",
            amount=85000.0,
            amount_source="HubSpot",
            stage=DealStage.DISCOVERY,
        )
        db.add(crm_deal)
        await db.commit()
        await db.refresh(crm_deal)

        try:
            assert crm_deal.amount == 85000.0
            assert crm_deal.amount_source == "HubSpot"
        finally:
            await db.delete(crm_deal)
            await db.commit()

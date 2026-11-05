"""
CRM and Multi-Sales-Rep Automation Test Suite
Validates:
1. User A & User B login and token isolation
2. Google Workspace Domain-Wide Delegation (DWD) auto-mailbox resolution
3. User A cannot impersonate or send from User B's mailbox
4. Cal.com automated booking link resolution from sales rep identity
5. Cal.com custom override preservation
6. Salesforce CRM service opportunity queries and activity task logging
7. A5 Deal intelligence syncs from Salesforce with amount_source="Salesforce"
8. HubSpot code is no longer executed & HUBSPOT_ACCESS_TOKEN is not required
9. Deal amount defaults to None / "Not provided" (no fake $50,000)
10. Production mode (A5_SIMULATION_MODE=False) creates zero synthetic data
"""
import uuid
import time
import pytest
import httpx
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from jose import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.models import User, UserIntegration, Deal, Contact, OutreachDraft, DealStage
from app.services.salesforce_service import SalesforceService, SALESFORCE_STAGE_MAP
from app.services.google_oauth_service import GoogleOAuthService
from app.services import CalService
from app.agents.a5_deal import DealAgent
from app.agents.a3_outreach import DraftManager


async def _create_test_user(email: str, name: str) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash="test_hashed_password_xyz",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


# ── Test 1: User A & User B Login and Token Isolation ─────────────────────────

@pytest.mark.asyncio
async def test_user_a_and_b_login_isolation():
    user_a = await _create_test_user(f"rep_a_{uuid.uuid4().hex[:6]}@company.com", "Rep Alpha")
    user_b = await _create_test_user(f"rep_b_{uuid.uuid4().hex[:6]}@company.com", "Rep Beta")

    token_a = create_access_token(str(user_a.id))
    token_b = create_access_token(str(user_b.id))

    assert token_a != token_b

    # Verify token decoding yields exact user identity
    from app.core.security import decode_token
    user_id_a = decode_token(token_a)
    user_id_b = decode_token(token_b)

    assert user_id_a == str(user_a.id)
    assert user_id_b == str(user_b.id)
    assert user_id_a != user_id_b


# ── Test 2: Google Workspace DWD Identity Resolution ─────────────────────────

@pytest.mark.asyncio
async def test_google_workspace_dwd_identity_resolution():
    oauth_svc = GoogleOAuthService()

    # Generate an RSA private key for testing DWD signing
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_key = rsa_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    orig_dwd = settings.GOOGLE_WORKSPACE_DWD_ENABLED
    orig_sa_email = settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL
    orig_sa_key = settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY
    orig_domain = settings.GOOGLE_WORKSPACE_DOMAIN

    try:
        # Configure DWD settings
        settings.GOOGLE_WORKSPACE_DWD_ENABLED = True
        settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL = "gtm-sa@company-gcp.iam.gserviceaccount.com"
        settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY = pem_key
        settings.GOOGLE_WORKSPACE_DOMAIN = "company.com"

        # Refresh service instance settings
        oauth_svc.dwd_enabled = True
        oauth_svc.sa_email = settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL
        oauth_svc.sa_key = settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY
        oauth_svc.workspace_domain = "company.com"

        # Verify company email matches DWD
        assert oauth_svc.is_dwd_enabled_for_email("john@company.com") is True
        assert oauth_svc.is_dwd_enabled_for_email("jane@company.com") is True

        # Verify outsider/non-company email is rejected by DWD
        assert oauth_svc.is_dwd_enabled_for_email("attacker@otherdomain.com") is False
        assert oauth_svc.is_dwd_enabled_for_email("random@gmail.com") is False

        # Test DWD token generation: mock the Google token endpoint
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"access_token": "mock_dwd_token_abc123", "expires_in": 3600},
            )
            token = await oauth_svc.get_dwd_access_token("john@company.com")
            assert token == "mock_dwd_token_abc123"

            # Verify JWT payload passed to Google contains the impersonated user in 'sub'
            call_args = mock_post.call_args
            assertion = call_args[1]["data"]["assertion"]
            unverified_claims = jwt.get_unverified_claims(assertion)
            assert unverified_claims["sub"] == "john@company.com"
            assert unverified_claims["iss"] == settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL
    finally:
        settings.GOOGLE_WORKSPACE_DWD_ENABLED = orig_dwd
        settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_EMAIL = orig_sa_email
        settings.GOOGLE_WORKSPACE_SERVICE_ACCOUNT_KEY = orig_sa_key
        settings.GOOGLE_WORKSPACE_DOMAIN = orig_domain


# ── Test 3: User A Cannot Impersonate or Use User B Mailbox ──────────────────

@pytest.mark.asyncio
async def test_user_a_cannot_impersonate_or_use_user_b_mailbox():
    user_a = await _create_test_user(f"alice_{uuid.uuid4().hex[:6]}@company.com", "Alice")
    user_b = await _create_test_user(f"bob_{uuid.uuid4().hex[:6]}@company.com", "Bob")

    oauth_svc = GoogleOAuthService()

    # Effective token for Alice must resolve to Alice's email, not Bob's
    with patch.object(oauth_svc, "is_dwd_enabled_for_email", return_value=True), \
         patch.object(oauth_svc, "get_dwd_access_token", new_callable=AsyncMock) as mock_dwd:
        mock_dwd.return_value = "token_for_alice"

        token, ptype = await oauth_svc.get_effective_access_token_for_user(user_a)
        assert token == "token_for_alice"
        mock_dwd.assert_called_once_with(user_a.email)

    # Calling for user_b calls with user_b.email
    with patch.object(oauth_svc, "is_dwd_enabled_for_email", return_value=True), \
         patch.object(oauth_svc, "get_dwd_access_token", new_callable=AsyncMock) as mock_dwd_b:
        mock_dwd_b.return_value = "token_for_bob"

        token_b, ptype_b = await oauth_svc.get_effective_access_token_for_user(user_b)
        assert token_b == "token_for_bob"
        mock_dwd_b.assert_called_once_with(user_b.email)


# ── Test 4: Cal.com Automated Link Resolution from User Identity ─────────────

@pytest.mark.asyncio
async def test_cal_com_automated_link_resolution():
    cal_svc = CalService()

    user = await _create_test_user(f"sarah_{uuid.uuid4().hex[:6]}@company.com", "Sarah Connor")
    user.cal_com_booking_url = None
    user.cal_com_event_slug = None
    username = user.email.split("@")[0]
    user.cal_com_username = username

    # Case A: Standard resolution without org slug
    settings.CAL_COM_ORG_SLUG = None
    settings.CAL_COM_DEFAULT_EVENT_SLUG = "15min"

    auto_url = cal_svc.resolve_user_booking_url(user)
    assert auto_url == f"https://cal.com/{username}/15min"

    # Case B: Organization-level resolution (CAL_COM_ORG_SLUG configured)
    settings.CAL_COM_ORG_SLUG = "acmecorp"
    settings.CAL_COM_DEFAULT_EVENT_SLUG = "discovery"

    org_url = cal_svc.resolve_user_booking_url(user)
    assert org_url == f"https://cal.com/acmecorp/{username}/discovery"

    # Verify get_booking_link injects contact params
    link = await cal_svc.get_booking_link("prospect@target.com", "John Doe", user=user)
    assert f"https://cal.com/acmecorp/{username}/discovery?" in link
    assert "name=John+Doe" in link
    assert "email=prospect%40target.com" in link


# ── Test 5: Cal.com Custom Override Preservation ─────────────────────────────

@pytest.mark.asyncio
async def test_cal_com_custom_override_preservation():
    cal_svc = CalService()

    user = await _create_test_user(f"custom_{uuid.uuid4().hex[:6]}@company.com", "Custom Rep")
    user.cal_com_booking_url = "https://cal.com/special-team/vip-demo"

    # Even if org slug is set, explicit custom URL takes absolute priority
    settings.CAL_COM_ORG_SLUG = "acmecorp"
    resolved = cal_svc.resolve_user_booking_url(user)
    assert resolved == "https://cal.com/special-team/vip-demo"

    link = await cal_svc.get_booking_link("vip@prospect.com", "VIP Prospect", user=user)
    assert link.startswith("https://cal.com/special-team/vip-demo?")


# ── Test 6: Salesforce Service Query and Activity Logging ────────────────────

@pytest.mark.asyncio
async def test_salesforce_service_query_and_activity_logging():
    sf_service = SalesforceService()
    settings.SALESFORCE_INSTANCE_URL = "https://example.my.salesforce.com"
    settings.SALESFORCE_ACCESS_TOKEN = "test_sf_bearer_token"
    sf_service.instance_url = "https://example.my.salesforce.com"
    sf_service.access_token = "test_sf_bearer_token"

    assert sf_service.is_configured is True
    assert sf_service.base_url == "https://example.my.salesforce.com/services/data/v60.0"

    # 1. Test Opportunity SOQL query
    mock_opps_response = {
        "totalSize": 2,
        "done": True,
        "records": [
            {
                "Id": "006XX000001",
                "Name": "Global Corp Expansion",
                "Amount": 120000.0,
                "StageName": "Needs Analysis",
                "CloseDate": "2026-12-15",
                "Owner": {"Email": "rep@company.com", "Name": "Sales Rep"},
            },
            {
                "Id": "006XX000002",
                "Name": "TechStart Pilot",
                "Amount": 45000.0,
                "StageName": "Proposal/Price Quote",
                "CloseDate": "2026-11-30",
                "Owner": {"Email": "rep@company.com", "Name": "Sales Rep"},
            },
        ],
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_opps_response,
            raise_for_status=lambda: None,
        )
        opps = await sf_service.sync_opportunities()
        assert len(opps) == 2
        assert opps[0]["Name"] == "Global Corp Expansion"
        assert opps[0]["Amount"] == 120000.0

    # 2. Test Task / Activity Logging
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=201,
            json=lambda: {"id": "00TXX000001", "success": True},
            raise_for_status=lambda: None,
        )
        logged = await sf_service.log_activity("006XX000001", "Call Intelligence Note", "Budget: $120k confirmed")
        assert logged is True

        post_payload = mock_post.call_args[1]["json"]
        assert post_payload["WhatId"] == "006XX000001"
        assert post_payload["Subject"] == "Call Intelligence Note"
        assert "Budget: $120k confirmed" in post_payload["Description"]


# ── Test 7: A5 Deal Sync from Salesforce with amount_source="Salesforce" ───────

@pytest.mark.asyncio
async def test_a5_sync_deals_from_salesforce():
    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        opp_id = f"006_{uuid.uuid4().hex[:8]}"
        mock_opps = [
            {
                "Id": opp_id,
                "Name": "Enterprise Cloud Deal",
                "Amount": 95000.0,
                "StageName": "Proposal/Price Quote",
                "CloseDate": "2026-11-20",
                "Owner": {"Email": "rep@company.com"},
            }
        ]

        try:
            with patch.object(SalesforceService, "is_configured", True), \
                 patch.object(SalesforceService, "sync_opportunities", new_callable=AsyncMock) as mock_sync:
                mock_sync.return_value = mock_opps

                res = await agent.sync_deals_from_salesforce()
                assert res["created"] >= 1

                # Verify Deal in database has correct Salesforce opportunity ID and source
                from sqlalchemy import select
                deal_res = await db.execute(
                    select(Deal).where(Deal.salesforce_opportunity_id == opp_id)
                )
                deal = deal_res.scalar_one_or_none()
                assert deal is not None
                assert deal.name == "Enterprise Cloud Deal"
                assert deal.amount == 95000.0
                assert deal.amount_source == "Salesforce"
                assert deal.stage == DealStage.PROPOSAL
        finally:
            from sqlalchemy import select, delete
            from app.models.models import DealStageHistory
            deal_res = await db.execute(select(Deal).where(Deal.salesforce_opportunity_id == opp_id))
            deal = deal_res.scalar_one_or_none()
            if deal:
                await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id == deal.id))
                await db.delete(deal)
                await db.commit()


# ── Test 8: HubSpot Code Deprecation and Safe Fallbacks ───────────────────────

@pytest.mark.asyncio
async def test_hubspot_unneeded_and_deprecated():
    from app.services import HubSpotService
    hs = HubSpotService()

    # Calling legacy methods does not throw errors and returns safe fallbacks
    res_activity = await hs.log_activity("any_deal_id", "note", "body")
    assert res_activity is False

    res_deals = await hs.sync_deals()
    assert res_deals == []

    # Calling legacy sync_deals_from_hubspot redirects to Salesforce
    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)
        with patch.object(agent, "sync_deals_from_salesforce", new_callable=AsyncMock) as mock_sf_sync:
            mock_sf_sync.return_value = {"synced": 5, "created": 2, "updated": 3}
            res = await agent.sync_deals_from_hubspot()
            assert res["synced"] == 5
            mock_sf_sync.assert_called_once()


# ── Test 9: A5 Deal Amount Defaults to None & No Fake $50,000 ─────────────────

@pytest.mark.asyncio
async def test_a5_deal_amount_defaults_to_none_not_50000():
    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        deal = Deal(
            name=f"Discovery Prospect {uuid.uuid4().hex[:6]}",
            stage=DealStage.DISCOVERY,
            amount=None,
            amount_source="Not provided",
        )
        db.add(deal)
        await db.commit()
        await db.refresh(deal)

        try:
            assert deal.amount is None
            assert deal.amount_source == "Not provided"

            # Verify risk pattern detection does NOT overwrite amount with $50,000
            flags = await agent._detect_risk_patterns(deal)
            assert deal.amount is None
            assert deal.amount != 50000.0
        finally:
            await db.delete(deal)
            await db.commit()


# ── Test 10: Production Mode (A5_SIMULATION_MODE=False) Zero Synthetic Data ───

@pytest.mark.asyncio
async def test_a5_production_mode_zero_synthetic_data():
    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)
        settings.A5_SIMULATION_MODE = False

        res = await agent._identify_and_process_meeting_prospects()
        assert res["transcripts_processed"] == 0
        assert res["deals_created"] == 0

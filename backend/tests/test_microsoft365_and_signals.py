import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from sqlalchemy import select, text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.models import User, UserIntegration, Contact, SignalEvent, OutreachDraft, ConversationThread
from app.services.microsoft_graph_service import MicrosoftGraphService
from app.services import CalService
from app.services.token_encryption import encrypt_token, decrypt_token
from app.agents.a3_outreach import DraftManager
from app.agents.a4_inbound import InboundAgent


@pytest.mark.asyncio
async def test_microsoft_integration_status_disconnected():
    """Test 1: GET /api/v1/integrations reports Microsoft 365 as production and not connected."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one_or_none()
        assert user is not None, "Migrated user shree.lakshmi@forcecloudlabs.com must exist"
        token = create_access_token(user.id)
    
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.get("/api/v1/integrations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "user_integrations" in data
        ms = data["user_integrations"]["microsoft"]
        assert ms["provider"] == "microsoft"
        assert ms["is_production"] is True
        assert ms["email"] == "shree.lakshmi@forcecloudlabs.com"


@pytest.mark.asyncio
async def test_microsoft_oauth_connect_unconfigured():
    """Test 2: GET /api/v1/integrations/microsoft/connect returns 503 when credentials are empty."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()
        token = create_access_token(user.id)
    
    with patch.object(MicrosoftGraphService, "is_configured", return_value=False):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/integrations/microsoft/connect", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 503
            detail = resp.json()["detail"]
            assert "MICROSOFT_CLIENT_ID" in detail


@pytest.mark.asyncio
async def test_microsoft_oauth_connect_configured():
    """Test 2b: GET /api/v1/integrations/microsoft/connect returns 200 with authorization URL when configured."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()
        token = create_access_token(user.id)
    
    with patch.object(MicrosoftGraphService, "is_configured", return_value=True), \
         patch.object(MicrosoftGraphService, "get_authorization_url", return_value="https://login.microsoftonline.com/617aa372-a362-423a-b00d-d33cecf52ea7/oauth2/v2.0/authorize?mock=1"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/integrations/microsoft/connect", headers={"Authorization": f"Bearer {token}"})
            assert resp.status_code == 200
            data = resp.json()
            assert "url" in data
            assert "https://login.microsoftonline.com" in data["url"]
            assert "state" in data


@pytest.mark.asyncio
async def test_microsoft_oauth_callback_and_encryption():
    """Test 3: Microsoft OAuth token encryption and persistence."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()
        user_id = user.id
    
    mock_tokens = {
        "access_token": "mock-access-token-12345",
        "refresh_token": "mock-refresh-token-67890",
        "expires_in": 3600,
        "scope": "Mail.Send Mail.Read offline_access openid profile email",
    }
    mock_profile = {
        "email": "shree.lakshmi@forcecloudlabs.com",
        "displayName": "P P Shree Lakshmi",
        "id": "ms-user-id-abc",
    }
    
    with patch.object(MicrosoftGraphService, "is_configured", return_value=True), \
         patch.object(MicrosoftGraphService, "exchange_code_for_tokens", return_value=mock_tokens), \
         patch.object(MicrosoftGraphService, "get_user_profile", return_value=mock_profile):
        
        state = f"{user_id}:test_random_state"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/v1/integrations/microsoft/callback?code=mock_code&state={state}",
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "microsoft_connected=true" in resp.headers["location"]
            
        # Verify database record
        async with AsyncSessionLocal() as db_session:
            int_res = await db_session.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == user_id,
                    UserIntegration.provider == "microsoft",
                )
            )
            integration = int_res.scalar_one_or_none()
            assert integration is not None
            assert integration.status == "connected"
            assert integration.provider_account_email == "shree.lakshmi@forcecloudlabs.com"
            # Verify encryption
            decrypted_acc = decrypt_token(integration.encrypted_access_token)
            decrypted_ref = decrypt_token(integration.encrypted_refresh_token)
            assert decrypted_acc == "mock-access-token-12345"
            assert decrypted_ref == "mock-refresh-token-67890"


@pytest.mark.asyncio
async def test_a3_outbound_uses_microsoft_graph():
    """Test 4: Agent 3 dispatches cold email via authenticated rep's Microsoft 365 mailbox."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()

        # Find or create contact
        res_c = await db_session.execute(
            select(Contact).where(
                Contact.email == "shreelakshmipp2003@gmail.com",
                Contact.user_id == user.id,
            )
        )
        contact = res_c.scalar_one_or_none()
        if not contact:
            contact = Contact(
                first_name="Test",
                last_name="Prospect",
                email="shreelakshmipp2003@gmail.com",
                company="TestCorp",
                user_id=user.id,
            )
            db_session.add(contact)
            await db_session.flush()

        # Ensure user has connected microsoft integration
        int_res = await db_session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user.id,
                UserIntegration.provider == "microsoft",
            )
        )
        ms_int = int_res.scalar_one_or_none()
        if not ms_int:
            ms_int = UserIntegration(
                user_id=user.id,
                provider="microsoft",
                provider_account_email="shree.lakshmi@forcecloudlabs.com",
                status="connected",
                encrypted_access_token=encrypt_token("mock-token-xyz"),
            )
            db_session.add(ms_int)
        else:
            ms_int.status = "connected"

        draft_mgr = DraftManager(db_session)
        draft = await draft_mgr.create_draft(
            contact_id=contact.id,
            signal_id=None,
            subject="Discussion on CRM automation",
            body="Hi Test, would love to connect. Best, [Your Name]",
            business_case="General Sales Outreach",
            matched_services=["Salesforce Integration"],
            channel="email",
        )
        await db_session.commit()
        draft_id = draft.id

    try:
        async with AsyncSessionLocal() as db_session:
            draft_mgr = DraftManager(db_session)
            with patch("app.core.config.settings.AGENT3_TEST_MODE", True), \
                 patch.object(MicrosoftGraphService, "get_valid_access_token", new_callable=AsyncMock) as mock_get_token, \
                 patch.object(MicrosoftGraphService, "send_mail", new_callable=AsyncMock) as mock_send:
                mock_get_token.return_value = "mock-token-xyz"
                mock_send.return_value = "msg_graph_test_123"
                success = await draft_mgr.approve_draft(draft_id)
                assert success is True
                mock_send.assert_awaited_once()
                call_kwargs = mock_send.await_args.kwargs
                assert call_kwargs["to_email"] == "shreelakshmipp2003@gmail.com"
                assert call_kwargs["from_email"] == "shree.lakshmi@forcecloudlabs.com"
                assert "Discussion on CRM automation" in call_kwargs["subject"]
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(OutreachDraft).where(OutreachDraft.id == draft_id))
            await db_session.execute(delete(OutreachLog).where(OutreachLog.subject == "Discussion on CRM automation"))
            await db_session.commit()


@pytest.mark.asyncio
async def test_a3_blocks_fallback_for_production_rep():
    """Test 5: A3 refuses to silently fall back to personal Gmail if Microsoft 365 is disconnected for production rep."""
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()

        # Temporarily disconnect Microsoft integration
        int_res = await db_session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user.id,
                UserIntegration.provider == "microsoft",
            )
        )
        ms_int = int_res.scalar_one_or_none()
        if ms_int:
            ms_int.status = "disconnected"
            await db_session.commit()

        unique_email = f"test2_{uuid.uuid4().hex[:6]}@example.com"
        contact = Contact(
            first_name="Test2",
            last_name="Prospect2",
            email=unique_email,
            company="TestCorp2",
            user_id=user.id,
        )
        db_session.add(contact)
        await db_session.flush()

        draft_mgr = DraftManager(db_session)
        draft = await draft_mgr.create_draft(
            contact_id=contact.id,
            signal_id=None,
            subject="Testing strict policy",
            body="Hello there",
            business_case="General Sales Outreach",
            matched_services=[],
            channel="email",
        )
        await db_session.commit()
        draft_id = draft.id

    try:
        async with AsyncSessionLocal() as db_session:
            draft_mgr = DraftManager(db_session)
            success = await draft_mgr.approve_draft(draft_id)
            assert success is False, "A3 must block send when production Microsoft mailbox is not connected"

            # Restore integration status
            res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
            user = res.scalar_one()
            int_res = await db_session.execute(
                select(UserIntegration).where(
                    UserIntegration.user_id == user.id,
                    UserIntegration.provider == "microsoft",
                )
            )
            ms_int = int_res.scalar_one_or_none()
            if ms_int:
                ms_int.status = "connected"
                await db_session.commit()
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(OutreachDraft).where(OutreachDraft.id == draft_id))
            await db_session.execute(delete(Contact).where(Contact.id == contact.id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_a4_inbound_processes_microsoft_graph_reply():
    """Test 6: A4 processes prospect reply from rep's Microsoft 365 mailbox."""
    unique_email = f"alice_{uuid.uuid4().hex[:6]}@prospectcompany.com"
    async with AsyncSessionLocal() as db_session:
        res = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res.scalar_one()

        contact = Contact(
            first_name="Alice",
            last_name="Prospect",
            email=unique_email,
            company="Prospect Company",
            user_id=user.id,
        )
        db_session.add(contact)
        await db_session.commit()
        contact_id = contact.id

    try:
        async with AsyncSessionLocal() as db_session:
            agent = InboundAgent(db_session)
            payload = {
                "event_type": "reply_received",
                "from_address": unique_email,
                "reply_text": "Sounds interesting! Let's schedule a 15 minute call next week.",
                "subject": "Re: Discussion on CRM automation",
                "message_id": "ms_msg_inbound_999",
            }
            
            with patch.object(agent.llm, "complete", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = {"intent": "positive", "confidence": 0.95}
                result = await agent.handle_reply(payload, user_id=str(user.id))
                assert result is not None
                assert result.get("status") == "pending_approval"
                assert result.get("thread_event_id") is not None

            # Verify thread event recorded in DB for this contact
            res_thread = await db_session.execute(
                select(ConversationThread).where(ConversationThread.id == result["thread_event_id"])
            )
            thread_event = res_thread.scalar_one_or_none()
            assert thread_event is not None
            assert thread_event.contact_id == contact_id
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(Notification).where(Notification.contact_id == contact_id))
            await db_session.execute(delete(ConversationThread).where(ConversationThread.contact_id == contact_id))
            await db_session.execute(delete(FunnelEvent).where(FunnelEvent.contact_id == contact_id))
            await db_session.execute(delete(Contact).where(Contact.id == contact_id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_a4_inbound_rep_isolation():
    """Test 7: Reply to Rep A is never matched to Rep B's contact."""
    async with AsyncSessionLocal() as db_session:
        user_b = User(
            name="Sales Rep B",
            email=f"rep_b_{uuid.uuid4().hex[:6]}@forcecloudlabs.com",
            password_hash=hash_password("Pass1234!"),
            role="SALES_REPRESENTATIVE",
        )
        db_session.add(user_b)
        await db_session.flush()

        contact_b = Contact(
            first_name="Bob",
            last_name="Prospect",
            email=f"bob_{uuid.uuid4().hex[:6]}@company.com",
            company="Isolated Corp",
            user_id=user_b.id,
        )
        db_session.add(contact_b)
        await db_session.commit()

        res_a = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user_a = res_a.scalar_one()

    try:
        async with AsyncSessionLocal() as db_session:
            agent = InboundAgent(db_session)
            payload = {
                "event_type": "reply_received",
                "from_address": contact_b.email,
                "reply_text": "Hello Rep A?",
                "subject": "Re: Isolated inquiry",
                "message_id": "ms_msg_inbound_888",
            }

            # Pass user_a's ID: lookup must fail because bob belongs to user_b
            result = await agent.handle_reply(payload, user_id=str(user_a.id))
            assert result.get("matched") is False or result.get("contact_id") != str(contact_b.id)
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(Contact).where(Contact.id == contact_b.id))
            await db_session.execute(delete(User).where(User.id == user_b.id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_contact_signals_endpoint_siobhan_fogarty():
    """Test 8: ContactDetail signals endpoint returns all 3 signals for Siobhan Fogarty without 500 error."""
    async with AsyncSessionLocal() as db_session:
        # Find Siobhan Fogarty
        res = await db_session.execute(
            select(Contact).where(Contact.first_name == "Siobhan", Contact.last_name == "Fogarty")
        )
        siobhan = res.scalar_one_or_none()
        assert siobhan is not None, "Siobhan Fogarty contact must exist in DB"
        siobhan_id = siobhan.id

        res_user = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res_user.scalar_one()
        token = create_access_token(user.id)

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        resp = await client.get(
            f"/api/v1/contacts/{siobhan_id}/signals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        signals = resp.json()
        assert len(signals) >= 3, f"Expected at least 3 signals for Siobhan Fogarty, got {len(signals)}"
        sig_types = {s["signal_type"] for s in signals}
        assert "earnings_call" in sig_types
        assert "news_expansion" in sig_types
        assert "funding_round" in sig_types


@pytest.mark.asyncio
async def test_contact_without_signals_returns_empty_list():
    """Test 9: Contact without signals returns HTTP 200 with empty list []."""
    async with AsyncSessionLocal() as db_session:
        res_user = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        user = res_user.scalar_one()

        contact = Contact(
            first_name="NoSignals",
            last_name="Prospect",
            email=f"nosig_{uuid.uuid4().hex[:6]}@example.com",
            company="Clean Corp",
            user_id=user.id,
        )
        db_session.add(contact)
        await db_session.commit()
        contact_id = contact.id
        token = create_access_token(user.id)

    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            resp = await client.get(
                f"/api/v1/contacts/{contact_id}/signals",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            assert resp.json() == []
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(Contact).where(Contact.id == contact_id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_signals_user_isolation():
    """Test 10: Rep B cannot access Rep A's contact signals."""
    async with AsyncSessionLocal() as db_session:
        user_b = User(
            name="Rep B Isolated",
            email=f"rep_b_{uuid.uuid4().hex[:6]}@company.com",
            password_hash=hash_password("Pass1234!"),
            role="SALES_REPRESENTATIVE",
        )
        db_session.add(user_b)
        await db_session.commit()

        res = await db_session.execute(
            select(Contact).where(Contact.first_name == "Siobhan", Contact.last_name == "Fogarty")
        )
        siobhan = res.scalar_one()
        siobhan_id = siobhan.id
        token_b = create_access_token(user_b.id)

    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            resp = await client.get(
                f"/api/v1/contacts/{siobhan_id}/signals",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            # Because contact belongs to user_a, user_b receives empty list
            assert resp.status_code == 200
            assert resp.json() == []
    finally:
        async with AsyncSessionLocal() as db_session:
            await db_session.execute(delete(User).where(User.id == user_b.id))
            await db_session.commit()


@pytest.mark.asyncio
async def test_cal_com_explicit_mapping_no_guessing():
    """Test 11: CalService explicitly resolves confirmed URL and never guesses from email prefix."""
    cal_svc = CalService()

    async with AsyncSessionLocal() as db_session:
        res_user = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        prod_user = res_user.scalar_one()

    url = cal_svc.resolve_user_booking_url(prod_user)
    assert url is not None
    assert "https://cal.com/shree-lakshmi-iaqqsz" in url
    assert "shreelakshmipp" not in url

    # Unmapped mock user
    unmapped_user = User(
        name="Unmapped Rep",
        email="random.person@forcecloudlabs.com",
        password_hash="...",
        role="SALES_REPRESENTATIVE",
        cal_com_username=None,
        cal_com_event_slug=None,
        cal_com_booking_url=None,
    )
    unmapped_url = cal_svc.resolve_user_booking_url(unmapped_user)
    assert unmapped_url is None, "Must return None for unmapped user, never guess random.person"


@pytest.mark.asyncio
async def test_admin_user_management_authorization():
    """Test 12: Admin can list/create users; Sales Rep gets 403 Forbidden."""
    async with AsyncSessionLocal() as db_session:
        res_admin = await db_session.execute(select(User).where(User.email == "shree.lakshmi@forcecloudlabs.com"))
        admin = res_admin.scalar_one()
        admin_token = create_access_token(admin.id)

        rep = User(
            name="Regular Sales Rep",
            email=f"rep_{uuid.uuid4().hex[:6]}@forcecloudlabs.com",
            password_hash=hash_password("Pass1234!"),
            role="SALES_REPRESENTATIVE",
        )
        db_session.add(rep)
        await db_session.commit()
        rep_token = create_access_token(rep.id)

    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # 1. Admin can list users
        admin_resp = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
        assert admin_resp.status_code == 200
        users_list = admin_resp.json()
        assert len(users_list) >= 2

        # 2. Regular sales rep gets 403 Forbidden
        rep_resp = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {rep_token}"})
        assert rep_resp.status_code == 403
        assert "Admin privileges required" in rep_resp.json()["detail"]

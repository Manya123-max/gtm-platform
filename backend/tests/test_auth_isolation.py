"""
Multi-user authentication & data-isolation tests.

Run against the real PostgreSQL database (localhost:5433 per backend/.env):

    cd backend
    .venv\\Scripts\\python.exe -m pytest tests/test_auth_isolation.py -v

These tests exercise the running FastAPI app in-process via httpx ASGI.
They create their own random users and clean up nothing (harmless test rows).
"""
import uuid

import httpx
import pytest
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def client():
    from app.core.database import init_db, close_db
    from app.core.config import get_settings
    settings = get_settings()
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
        from app.models.models import User, Contact, UserInput, Notification, SignalEvent
        from sqlalchemy import select, delete, or_
        async with AsyncSessionLocal() as db:
            users = (await db.execute(select(User).where(or_(User.email.ilike("%@example.com"), User.email.ilike("%@company.com"))))).scalars().all()
            if users:
                uids = [u.id for u in users]
                c_sub = select(Contact.id).where(Contact.user_id.in_(uids))
                await db.execute(delete(Notification).where(Notification.contact_id.in_(c_sub)))
                await db.execute(delete(SignalEvent).where(SignalEvent.contact_id.in_(c_sub)))
                await db.execute(delete(Contact).where(Contact.user_id.in_(uids)))
                await db.execute(delete(UserInput).where(UserInput.user_id.in_(uids)))
                await db.execute(delete(User).where(User.id.in_(uids)))
                await db.commit()
        settings.AUTH_ENABLED = orig_auth
        settings.APP_ENV = orig_env
        await close_db()


def _email() -> str:
    return f"test-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, email=None, password="Passw0rd123", name="Test User"):
    email = email or _email()
    r = await client.post("/api/v1/auth/register", json={
        "name": name, "email": email,
        "password": password, "confirm_password": password,
    })
    assert r.status_code == 201, r.text
    return {"email": email, "token": r.json()["access_token"],
            "user": r.json()["user"], "headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


async def _create_session_and_contact(email, name):
    """Insert a user_input + contact directly (bypasses Celery)."""
    from app.core.database import AsyncSessionLocal
    from app.models.models import UserInput, Contact, User as UserM
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        uid = (await db.execute(select(UserM.id).where(UserM.email == email))).scalar_one()
        ui = UserInput(our_company_name=name, our_services="s", target_location="US",
                       target_company_size="50-500", target_job_titles="CTO", user_id=uid)
        db.add(ui)
        await db.flush()
        contact = Contact(email=f"c-{uuid.uuid4().hex[:8]}@example.com", first_name=name,
                          user_id=uid, user_input_id=ui.id)
        db.add(contact)
        await db.commit()
        return ui.id, contact.id

# ── Authentication ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_and_me(client):
    user = await _register(client)
    r = await client.get("/api/v1/auth/me", headers=user["headers"])
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert r.json()["user"]["email"] == user["email"]
    assert "password" not in r.json()["user"] and "password_hash" not in r.json()["user"]


@pytest.mark.asyncio
async def test_duplicate_email_rejected(client):
    user = await _register(client)
    r = await client.post("/api/v1/auth/register", json={
        "name": "Dup", "email": user["email"],
        "password": "Passw0rd123", "confirm_password": "Passw0rd123",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_password_mismatch_rejected(client):
    r = await client.post("/api/v1/auth/register", json={
        "name": "X", "email": _email(),
        "password": "Passw0rd123", "confirm_password": "Different123",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_weak_password_rejected(client):
    r = await client.post("/api/v1/auth/register", json={
        "name": "X", "email": _email(),
        "password": "short", "confirm_password": "short",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_login_success_and_failure(client):
    user = await _register(client)
    r = await client.post("/api/v1/auth/login",
                          json={"email": user["email"], "password": "Passw0rd123"})
    assert r.status_code == 200
    assert r.json()["access_token"]

    r = await client.post("/api/v1/auth/login",
                          json={"email": user["email"], "password": "WrongPass1"})
    assert r.status_code == 401

    r = await client.post("/api/v1/auth/login",
                          json={"email": "nobody@nowhere.io", "password": "WrongPass1"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client):
    user = await _register(client)
    login = await client.post("/api/v1/auth/login",
                              json={"email": user["email"], "password": "Passw0rd123"})
    refresh = login.json()["refresh_token"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert r.json()["access_token"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": user["token"]})
    assert r.status_code == 401  # access token cannot be used as refresh


@pytest.mark.asyncio
async def test_logout(client):
    user = await _register(client)
    r = await client.post("/api/v1/auth/logout", headers=user["headers"])
    assert r.status_code == 200


# ── Authorization ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_access_denied(client):
    r = await client.get("/api/v1/contacts")
    assert r.status_code == 401
    r = await client.get("/api/v1/dashboard/overview")
    assert r.status_code == 401
    r = await client.get("/api/v1/input-history")
    assert r.status_code == 401
    r = await client.post("/api/v1/submit-input", json={})
    assert r.status_code == 401


# ── Data isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_data_isolation(client):
    user_a = await _register(client)
    user_b = await _register(client)

    session_a, contact_a = await _create_session_and_contact(user_a["email"], "CompanyA")
    session_b, contact_b = await _create_session_and_contact(user_b["email"], "CompanyB")

    # Lists contain only own data
    ra = await client.get("/api/v1/contacts", headers=user_a["headers"])
    ids_a = [c["id"] for c in ra.json()]
    assert contact_a in ids_a and contact_b not in ids_a

    rb = await client.get("/api/v1/contacts", headers=user_b["headers"])
    ids_b = [c["id"] for c in rb.json()]
    assert contact_b in ids_b and contact_a not in ids_b

    # History contains only own sessions
    ha = await client.get("/api/v1/input-history", headers=user_a["headers"])
    hist_a = [h["id"] for h in ha.json()]
    assert session_a in hist_a and session_b not in hist_a

    # Direct access to the other user's contact → 404
    r = await client.get(f"/api/v1/contacts/{contact_b}", headers=user_a["headers"])
    assert r.status_code == 404

    # Direct access to the other user's session detail → not found
    r = await client.get(f"/api/v1/sessions/{session_b}", headers=user_a["headers"])
    assert r.status_code == 404 or r.json() == {"error": "Session not found"}

    # Foreign session passed as a query param → 404
    r = await client.get("/api/v1/dashboard/overview",
                         params={"user_input_id": session_b}, headers=user_a["headers"])
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_active_session_scoped(client):
    user_a = await _register(client)
    await _create_session_and_contact(user_a["email"], "CompanyA")
    r = await client.get("/api/v1/active-session", headers=user_a["headers"])
    assert r.status_code == 200
    assert r.json()["user_input_id"] is not None


@pytest.mark.asyncio
async def test_invalid_token_rejected(client):
    r = await client.get("/api/v1/contacts", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_multi_user_history_isolation(client):
    """
    TEST 1 & 2:
    User A creates search A1, A2.
    User B creates search B1, B2.
    User A sees ONLY [A2, A1].
    User B sees ONLY [B2, B1].
    Attempting to pass ?user_id=... parameter has no effect and cannot leak data.
    """
    user_a = await _register(client, name="User A")
    user_b = await _register(client, name="User B")

    # User A creates searches A1 and A2
    s_a1, _ = await _create_session_and_contact(user_a["email"], "Company A1")
    s_a2, _ = await _create_session_and_contact(user_a["email"], "Company A2")

    # User B creates searches B1 and B2
    s_b1, _ = await _create_session_and_contact(user_b["email"], "Company B1")
    s_b2, _ = await _create_session_and_contact(user_b["email"], "Company B2")

    # User A history
    res_a = await client.get("/api/v1/input-history", headers=user_a["headers"])
    assert res_a.status_code == 200
    ids_a = [item["id"] for item in res_a.json()]
    assert s_a1 in ids_a and s_a2 in ids_a
    assert s_b1 not in ids_a and s_b2 not in ids_a

    # User B history
    res_b = await client.get("/api/v1/input-history", headers=user_b["headers"])
    assert res_b.status_code == 200
    ids_b = [item["id"] for item in res_b.json()]
    assert s_b1 in ids_b and s_b2 in ids_b
    assert s_a1 not in ids_b and s_a2 not in ids_b

    # ID tampering attempt: User A passes User B's user_id as query param
    res_tamper = await client.get(
        "/api/v1/input-history",
        params={"user_id": user_b["user"]["id"]},
        headers=user_a["headers"]
    )
    assert res_tamper.status_code == 200
    ids_tamper = [item["id"] for item in res_tamper.json()]
    assert s_a1 in ids_tamper and s_a2 in ids_tamper
    assert s_b1 not in ids_tamper and s_b2 not in ids_tamper


@pytest.mark.asyncio
async def test_direct_object_access_prevention(client):
    """
    TEST 4 & 5:
    User A cannot access or mutate User B's objects (contacts, deals, drafts, sessions, workflows).
    All return 404 Not Found.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import Contact, Deal, OutreachDraft, WorkflowRun, User as UserM
    from sqlalchemy import select, delete

    user_a = await _register(client, name="User A")
    user_b = await _register(client, name="User B")

    session_b, contact_b_id = await _create_session_and_contact(user_b["email"], "Company B")

    # Create a deal, draft, and workflow run for User B
    async with AsyncSessionLocal() as db:
        uid_b = (await db.execute(select(UserM.id).where(UserM.email == user_b["email"]))).scalar_one()

        deal_b = Deal(name="Deal B", contact_id=contact_b_id, amount=50000.0)
        db.add(deal_b)
        await db.flush()

        draft_b = OutreachDraft(
            contact_id=contact_b_id,
            subject="Hello from B",
            body="Draft content",
            business_case="Outreach",
        )
        db.add(draft_b)
        await db.flush()

        wf_b = WorkflowRun(workflow_name="test_wf_b", user_id=uid_b)
        db.add(wf_b)
        await db.commit()

        deal_b_id = deal_b.id
        draft_b_id = draft_b.id
        wf_b_id = wf_b.id

    # User A tries to view User B's deal -> 404
    r = await client.get(f"/api/v1/deals/{deal_b_id}", headers=user_a["headers"])
    assert r.status_code == 404

    # User A tries to preview User B's draft -> 404
    r = await client.get(f"/api/v1/drafts/{draft_b_id}/preview", headers=user_a["headers"])
    assert r.status_code == 404

    # User A tries to approve User B's draft -> 404
    r = await client.post(f"/api/v1/drafts/{draft_b_id}/approve", headers=user_a["headers"])
    assert r.status_code == 404

    # User A tries to reject User B's draft -> 404
    r = await client.post(f"/api/v1/drafts/{draft_b_id}/reject", headers=user_a["headers"])
    assert r.status_code == 404

    # User A tries to edit User B's draft -> 404
    r = await client.post(
        f"/api/v1/drafts/{draft_b_id}/edit",
        json={"subject": "Hacked", "body": "Hacked"},
        headers=user_a["headers"]
    )
    assert r.status_code == 404

    # User A tries to view User B's workflow run -> 404
    r = await client.get(f"/api/v1/orchestrator/runs/{wf_b_id}", headers=user_a["headers"])
    assert r.status_code == 404

    # Cleanup entities
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Deal).where(Deal.id == deal_b_id))
        await db.execute(delete(OutreachDraft).where(OutreachDraft.id == draft_b_id))
        await db.execute(delete(WorkflowRun).where(WorkflowRun.id == wf_b_id))
        await db.commit()


@pytest.mark.asyncio
async def test_query_parameter_tampering_rejected(client):
    """
    Passing a foreign session/user_input_id into query params must result in 404.
    """
    user_a = await _register(client, name="User A")
    user_b = await _register(client, name="User B")

    session_b, _ = await _create_session_and_contact(user_b["email"], "Company B")

    for endpoint in ["/api/v1/dashboard/overview", "/api/v1/contacts", "/api/v1/deals", "/api/v1/content", "/api/v1/drafts"]:
        r = await client.get(endpoint, params={"user_input_id": session_b}, headers=user_a["headers"])
        assert r.status_code == 404, f"Endpoint {endpoint} did not return 404 for foreign session_id"


@pytest.mark.asyncio
async def test_prospect_agent_same_email_isolation():
    """
    TEST 7:
    When User A and User B discover the same prospect email,
    two independent contact rows are saved, each properly owned by its user.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.models import User as UserM, Contact
    from app.agents.a1_prospect import ProspectAgent
    from sqlalchemy import select

    test_suffix = uuid.uuid4().hex[:8]
    shared_email = f"shared-lead-{test_suffix}@acme.com"

    async with AsyncSessionLocal() as db:
        user_a = UserM(id=str(uuid.uuid4()), name="User A", email=f"usera-{test_suffix}@example.com", password_hash="hash")
        user_b = UserM(id=str(uuid.uuid4()), name="User B", email=f"userb-{test_suffix}@example.com", password_hash="hash")
        db.add_all([user_a, user_b])
        await db.commit()

        agent_a = ProspectAgent(db)
        await agent_a._save_contacts(
            contacts=[{
                "email": shared_email,
                "first_name": "Shared",
                "last_name": "Lead",
                "company": "Acme Inc",
                "win_pattern_score": 85.0,
            }],
            user_input_id=None,
            user_id=user_a.id,
        )

        agent_b = ProspectAgent(db)
        await agent_b._save_contacts(
            contacts=[{
                "email": shared_email,
                "first_name": "Shared",
                "last_name": "Lead",
                "company": "Acme Inc",
                "win_pattern_score": 90.0,
            }],
            user_input_id=None,
            user_id=user_b.id,
        )

        # Check User A's contact
        res_a = await db.execute(select(Contact).where(Contact.email == shared_email, Contact.user_id == user_a.id))
        contact_a = res_a.scalar_one_or_none()
        assert contact_a is not None
        assert contact_a.user_id == user_a.id
        assert contact_a.icp_score == 85.0

        # Check User B's contact
        res_b = await db.execute(select(Contact).where(Contact.email == shared_email, Contact.user_id == user_b.id))
        contact_b = res_b.scalar_one_or_none()
        assert contact_b is not None
        assert contact_b.user_id == user_b.id
        assert contact_b.icp_score == 90.0

        assert contact_a.id != contact_b.id



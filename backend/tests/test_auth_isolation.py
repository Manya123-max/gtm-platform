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
    settings.AUTH_ENABLED = True
    await init_db()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        settings.AUTH_ENABLED = orig_auth
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


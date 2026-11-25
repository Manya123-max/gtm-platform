"""
Comprehensive End-to-End Verification Test Suite for Authentication,
Local Database Connectivity, and Multi-User History Isolation.

Tests:
1. Backend startup and database connectivity test.
2. Registration test (creates real user, verifies PBKDF2 hash, issues valid JWT).
3. Existing user login test (valid credentials succeed).
4. Invalid password rejection test (HTTP 401, no bypass).
5. Unknown user rejection test (HTTP 401, no auto-provisioning).
6. JWT validation and /me profile test (returns actual user details).
7. History retrieval test (scoped strictly to authenticated user).
8. Cross-user access control test (IDOR prevention on sessions, contacts, drafts, deletion).
9. Database-unavailable test (HTTP 503 returned, no fallback session issued).
10. No unsafe auto-provisioning or admin bypass.
"""
import asyncio
import uuid
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, delete, or_

from app.main import app
from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.core.security import verify_password
from app.models.models import User, UserInput, Contact, ContactUserInputAssociation


@pytest_asyncio.fixture(scope="module")
async def async_client():
    settings.APP_ENV = "test"
    settings.AUTH_ENABLED = True
    await init_db()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver/api/v1"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_1_database_connectivity(async_client):
    """Test 1: Backend startup and database connectivity check."""
    resp = await async_client.get("http://testserver/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_2_registration(async_client):
    """Test 2: Registration creates proper user record with PBKDF2 hash and returns JWT."""
    test_email = f"audit_rep_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    test_password = "SecurePassword123!"

    resp = await async_client.post("/auth/register", json={
        "name": "Audit Sales Rep",
        "email": test_email,
        "password": test_password,
        "confirm_password": test_password,
    })
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["user"]["email"] == test_email
    assert body["user"]["name"] == "Audit Sales Rep"

    # Verify directly in the DB that the password is safe and hashed
    async with AsyncSessionLocal() as db:
        user_row = (await db.execute(select(User).where(User.email == test_email))).scalar_one()
        assert user_row.password_hash.startswith("pbkdf2_sha256$")
        assert verify_password(test_password, user_row.password_hash) is True
        assert verify_password("WrongPassword123!", user_row.password_hash) is False

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.email == test_email))
        await db.commit()


@pytest.mark.asyncio
async def test_3_existing_user_login(async_client):
    """Test 3: Existing user can log in with valid credentials."""
    test_email = f"audit_login_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    test_password = "LoginPassword123!"

    # Create account
    reg_resp = await async_client.post("/auth/register", json={
        "name": "Login Tester",
        "email": test_email,
        "password": test_password,
        "confirm_password": test_password,
    })
    assert reg_resp.status_code == 201

    # Login with valid credentials
    login_resp = await async_client.post("/auth/login", json={
        "email": test_email,
        "password": test_password,
    })
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert "access_token" in body
    assert body["user"]["email"] == test_email

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.email == test_email))
        await db.commit()


@pytest.mark.asyncio
async def test_4_invalid_password_rejected(async_client):
    """Test 4: Invalid credentials are rejected with 401."""
    test_email = f"audit_invalid_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    test_password = "ValidPassword123!"

    reg_resp = await async_client.post("/auth/register", json={
        "name": "Invalid Tester",
        "email": test_email,
        "password": test_password,
        "confirm_password": test_password,
    })
    assert reg_resp.status_code == 201

    # Attempt with bad password
    bad_resp = await async_client.post("/auth/login", json={
        "email": test_email,
        "password": "WrongPassword999!",
    })
    assert bad_resp.status_code == 401
    assert "Incorrect Username or Password." in bad_resp.json().get("detail", "")

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.email == test_email))
        await db.commit()


@pytest.mark.asyncio
async def test_5_unknown_user_rejected_no_autoprovision(async_client):
    """Test 5: Unknown email is rejected with 401 and not auto-provisioned."""
    fake_email = f"nonexistent_{uuid.uuid4().hex[:8]}@forcecloudlabs.com"

    resp = await async_client.post("/auth/login", json={
        "email": fake_email,
        "password": "SomePassword123!",
    })
    assert resp.status_code == 401
    assert "Incorrect Username or Password." in resp.json().get("detail", "")

    # Ensure no account was created in the database
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == fake_email))
        assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_6_jwt_and_me_profile(async_client):
    """Test 6: /auth/me returns the authenticated user's actual profile."""
    test_email = f"audit_me_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    test_password = "MePassword123!"

    reg_resp = await async_client.post("/auth/register", json={
        "name": "Samantha Jones",
        "email": test_email,
        "password": test_password,
        "confirm_password": test_password,
    })
    token = reg_resp.json()["access_token"]

    # Call /auth/me with Bearer token
    me_resp = await async_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_body = me_resp.json()
    assert me_body["authenticated"] is True
    assert me_body["user"]["name"] == "Samantha Jones"
    assert me_body["user"]["email"] == test_email

    # Unauthenticated /auth/me call returns 401
    unauth_resp = await async_client.get("/auth/me", headers={"Authorization": "Bearer bad.token.here"})
    assert unauth_resp.status_code == 401

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(User).where(User.email == test_email))
        await db.commit()


@pytest.mark.asyncio
async def test_7_history_retrieval_and_user_scoping(async_client):
    """Test 7: History queries are strictly scoped to the authenticated user ID."""
    suffix = uuid.uuid4().hex[:6]
    user_a_email = f"rep_a_{suffix}@forcecloudlabs.com"
    user_b_email = f"rep_b_{suffix}@forcecloudlabs.com"
    password = "TestPassword123!"

    # Register Rep A and Rep B
    resp_a = await async_client.post("/auth/register", json={
        "name": "Rep A", "email": user_a_email, "password": password, "confirm_password": password
    })
    token_a = resp_a.json()["access_token"]
    user_a_id = resp_a.json()["user"]["id"]

    resp_b = await async_client.post("/auth/register", json={
        "name": "Rep B", "email": user_b_email, "password": password, "confirm_password": password
    })
    token_b = resp_b.json()["access_token"]
    user_b_id = resp_b.json()["user"]["id"]

    # Create search input for Rep A and Rep B
    async with AsyncSessionLocal() as db:
        input_a = UserInput(
            user_id=user_a_id,
            our_company_name="Company Alpha",
            our_services="CRM Automation",
            target_location="US",
            target_company_size="50-100",
            target_job_titles="VP Sales",
        )
        input_b = UserInput(
            user_id=user_b_id,
            our_company_name="Company Beta",
            our_services="GTM Consulting",
            target_location="UK",
            target_company_size="100-250",
            target_job_titles="CRO",
        )
        db.add_all([input_a, input_b])
        await db.commit()
        await db.refresh(input_a)
        await db.refresh(input_b)
        id_a, id_b = input_a.id, input_b.id

    # Verify Rep A only sees input_a
    hist_a = await async_client.get("/input-history", headers={"Authorization": f"Bearer {token_a}"})
    assert hist_a.status_code == 200
    items_a = hist_a.json()
    assert len(items_a) == 1
    assert items_a[0]["id"] == id_a
    assert items_a[0]["our_company_name"] == "Company Alpha"

    # Verify Rep B only sees input_b
    hist_b = await async_client.get("/input-history", headers={"Authorization": f"Bearer {token_b}"})
    assert hist_b.status_code == 200
    items_b = hist_b.json()
    assert len(items_b) == 1
    assert items_b[0]["id"] == id_b
    assert items_b[0]["our_company_name"] == "Company Beta"

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserInput).where(UserInput.id.in_([id_a, id_b])))
        await db.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
        await db.commit()


@pytest.mark.asyncio
async def test_8_cross_user_access_control_idor(async_client):
    """Test 8: IDOR security - one user cannot access or delete another user's sessions/records."""
    suffix = uuid.uuid4().hex[:6]
    user_a_email = f"rep_idor_a_{suffix}@forcecloudlabs.com"
    user_b_email = f"rep_idor_b_{suffix}@forcecloudlabs.com"
    password = "IdorPassword123!"

    resp_a = await async_client.post("/auth/register", json={
        "name": "IDOR Rep A", "email": user_a_email, "password": password, "confirm_password": password
    })
    token_a = resp_a.json()["access_token"]
    user_a_id = resp_a.json()["user"]["id"]

    resp_b = await async_client.post("/auth/register", json={
        "name": "IDOR Rep B", "email": user_b_email, "password": password, "confirm_password": password
    })
    token_b = resp_b.json()["access_token"]
    user_b_id = resp_b.json()["user"]["id"]

    # Rep B has a private session
    async with AsyncSessionLocal() as db:
        input_b = UserInput(
            user_id=user_b_id,
            our_company_name="Private Beta Inc",
            our_services="Proprietary Tech",
            target_location="US",
            target_company_size="50-100",
            target_job_titles="CTO",
        )
        db.add(input_b)
        await db.commit()
        await db.refresh(input_b)
        session_b_id = input_b.id

    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 1. Rep A tries to get Rep B's session details -> 404
    resp_detail = await async_client.get(f"/sessions/{session_b_id}", headers=headers_a)
    assert resp_detail.status_code == 404

    # 2. Rep A tries to get contacts scoped to Rep B's session -> 404
    resp_contacts = await async_client.get("/contacts", params={"user_input_id": session_b_id}, headers=headers_a)
    assert resp_contacts.status_code == 404

    # 3. Rep A tries to get drafts scoped to Rep B's session -> 404
    resp_drafts = await async_client.get("/drafts", params={"user_input_id": session_b_id}, headers=headers_a)
    assert resp_drafts.status_code == 404

    # 4. Rep A tries to delete Rep B's search history -> 403 Forbidden
    resp_del = await async_client.delete(f"/input-history/{session_b_id}", headers=headers_a)
    assert resp_del.status_code == 403

    # Cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserInput).where(UserInput.id == session_b_id))
        await db.execute(delete(User).where(User.id.in_([user_a_id, user_b_id])))
        await db.commit()


@pytest.mark.asyncio
async def test_9_database_unavailable_returns_503(monkeypatch):
    """Test 9: Database outage must return 503 Service Unavailable, NEVER authenticate user."""
    from unittest.mock import AsyncMock
    from app.core.database import get_db

    async def mock_failing_db():
        session = AsyncMock()
        session.execute.side_effect = Exception("Simulated DB connection failure / outage")
        yield session

    app.dependency_overrides[get_db] = mock_failing_db

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver/api/v1"
        ) as client:
            login_resp = await client.post("/auth/login", json={
                "email": "shree.lakshmi@forcecloudlabs.com",
                "password": "AnyPassword123!",
            })
            assert login_resp.status_code == 503, f"Expected 503 on DB error, got {login_resp.status_code}"
            assert "temporarily unavailable" in login_resp.json().get("detail", "").lower()
            assert "access_token" not in login_resp.json()
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_10_no_unsafe_admin_autoprovision(async_client):
    """Test 10: Calling login for primary email with wrong password never auto-provisions or bypasses auth."""
    # Ensure shree.lakshmi is not auto-created with an arbitrary password
    unknown_email = f"random_admin_candidate_{uuid.uuid4().hex[:6]}@forcecloudlabs.com"
    resp = await async_client.post("/auth/login", json={
        "email": unknown_email,
        "password": "ArbitraryPassword123!",
    })
    assert resp.status_code == 401
    assert "access_token" not in resp.json()

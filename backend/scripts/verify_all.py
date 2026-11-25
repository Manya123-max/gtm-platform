import asyncio
import sys
sys.path.insert(0, "/app")

import httpx
import json

BASE_URLS = ["http://localhost:8000"]

async def main():
    print("==================================================")
    print("STEP 1: VERIFY HEALTH ENDPOINTS & DB AVAILABILITY")
    print("==================================================")
    async with httpx.AsyncClient(timeout=10) as client:
        for base in BASE_URLS:
            for path in ["/health", "/api/v1/health"]:
                url = f"{base}{path}"
                r = await client.get(url)
                print(f"GET {url} -> Status: {r.status_code}, Body: {r.text}")
                assert r.status_code == 200, f"Expected 200, got {r.status_code}"
                data = r.json()
                assert data.get("status") == "healthy", f"Expected healthy status, got {data}"
                assert data.get("database") == "connected", f"Expected database connected, got {data}"
    print("PASS: Both /health and /api/v1/health report 200 OK with healthy, connected database.")

    print("\n==================================================")
    print("STEP 2: VERIFY REGISTRATION & AUTHENTICATION FLOW")
    print("==================================================")
    test_email = "test_user_flow@forcecloudlabs.com"
    initial_pw = "InitialPass123!"
    new_pw = "NewUpdatedPass123!"

    async with httpx.AsyncClient(timeout=15) as client:
        # Register test user
        reg_r = await client.post("http://localhost:8000/api/v1/auth/register", json={
            "name": "Test Verified User",
            "email": test_email,
            "password": initial_pw,
            "confirm_password": initial_pw
        })
        print(f"Registration -> Status: {reg_r.status_code}")
        # If user already registered, 400 is expected, which is fine
        if reg_r.status_code == 200:
            print("Registered new test user successfully.")
        else:
            print(f"Registration status: {reg_r.status_code} ({reg_r.json()})")

        # Login with correct credentials
        login_r = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": test_email,
            "password": initial_pw
        })
        print(f"Login with valid credentials -> Status: {login_r.status_code}")
        assert login_r.status_code == 200, f"Expected 200, got {login_r.status_code}"
        token_data = login_r.json()
        assert "access_token" in token_data
        assert "refresh_token" in token_data
        token = token_data["access_token"]

        # Call /auth/me
        me_r = await client.get("http://localhost:8000/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        print(f"GET /auth/me -> Status: {me_r.status_code}, User: {me_r.json().get('user', {}).get('email')}")
        assert me_r.status_code == 200
        assert me_r.json().get("authenticated") is True
        assert me_r.json().get("user", {}).get("email") == test_email

        # Login with incorrect password
        bad_pw_r = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": test_email,
            "password": "WrongPassword999!"
        })
        print(f"Login with incorrect password -> Status: {bad_pw_r.status_code}, Detail: {bad_pw_r.json().get('detail')}")
        assert bad_pw_r.status_code == 401
        assert bad_pw_r.json().get("detail") == "Incorrect Username or Password."

        # Login with non-existent user
        no_user_r = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": "definitely_nonexistent_user@forcecloudlabs.com",
            "password": "AnyPassword123!"
        })
        print(f"Login with non-existent user -> Status: {no_user_r.status_code}, Detail: {no_user_r.json().get('detail')}")
        assert no_user_r.status_code == 401
        assert no_user_r.json().get("detail") == "Incorrect Username or Password."
    print("PASS: Registration, authentication, invalid password rejection, and /auth/me fully verified.")

    print("\n==================================================")
    print("STEP 3: VERIFY FORGOT-PASSWORD SECURITY & PRIVACY")
    print("==================================================")
    async with httpx.AsyncClient(timeout=25) as client:
        # Non-existent email
        forgot_non = await client.post("http://localhost:8000/api/v1/auth/forgot-password", json={
            "email": "unknown_account_xyz@forcecloudlabs.com"
        })
        print(f"Forgot PW (non-existent email) -> Status: {forgot_non.status_code}, Message: {forgot_non.json().get('message')}")
        assert forgot_non.status_code == 200
        assert "reset_token" not in forgot_non.json(), "FAIL: reset_token exposed in API response!"

        # Registered email
        forgot_reg = await client.post("http://localhost:8000/api/v1/auth/forgot-password", json={
            "email": test_email
        })
        print(f"Forgot PW (registered email) -> Status: {forgot_reg.status_code}, Message: {forgot_reg.json().get('message')}")
        assert forgot_reg.status_code == 200
        assert "reset_token" not in forgot_reg.json(), "FAIL: reset_token exposed in API response!"
        assert forgot_reg.json().get("message") == forgot_non.json().get("message"), "FAIL: User enumeration! Messages differ."
    print("PASS: Generic response identical, zero user enumeration, zero token leakage in API responses.")

    print("\n==================================================")
    print("STEP 4: VERIFY SINGLE-USE RESET TOKEN ENFORCEMENT")
    print("==================================================")
    from app.core.security import create_reset_token
    from app.core.database import AsyncSessionLocal
    from app.models.models import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == test_email))
        user_row = res.scalar_one()
        reset_token = create_reset_token(str(user_row.id), user_row.password_hash)

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Reset password once (should succeed)
        reset1_r = await client.post("http://localhost:8000/api/v1/auth/reset-password", json={
            "token": reset_token,
            "password": new_pw,
            "confirm_password": new_pw
        })
        print(f"Reset attempt 1 -> Status: {reset1_r.status_code}, Body: {reset1_r.json()}")
        assert reset1_r.status_code == 200
        assert reset1_r.json().get("success") is True

        # 2. Replay the SAME token (MUST FAIL as already used)
        reset2_r = await client.post("http://localhost:8000/api/v1/auth/reset-password", json={
            "token": reset_token,
            "password": "ThirdPassword123!",
            "confirm_password": "ThirdPassword123!"
        })
        print(f"Reset attempt 2 (reuse token) -> Status: {reset2_r.status_code}, Body: {reset2_r.json()}")
        assert reset2_r.status_code == 400
        assert "already been used" in reset2_r.json().get("detail", "")
        print("PASS: Token reuse was successfully blocked with HTTP 400.")

        # 3. Verify login with old password fails
        old_login_r = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": test_email,
            "password": initial_pw
        })
        print(f"Login with old password -> Status: {old_login_r.status_code}")
        assert old_login_r.status_code == 401

        # 4. Verify login with newly updated password succeeds
        new_login_r = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": test_email,
            "password": new_pw
        })
        print(f"Login with new password -> Status: {new_login_r.status_code}")
        assert new_login_r.status_code == 200
        print("PASS: Successfully authenticated with updated password.")

    print("\n==================================================")
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())

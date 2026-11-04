"""
End-to-end Multi-User Account Isolation, Revenue Accuracy, and Profile Verification Script.
Tests:
1. Independent registration for Sales Rep A, B, C.
2. Initial clean state (0 inherited sessions, 0 contacts, 0 drafts).
3. Search submission and strict search history scoping per rep.
4. Direct object cross-access prevention (IDOR security - 404 on other user's session).
5. Revenue forecast accuracy (0 active deals -> $0 pipeline and $0 forecast).
6. Profile verification (dynamic user data, no hardcoded fallbacks).
7. Admin RBAC protection (Rep gets 403 on /admin/users, Admin gets 200).
8. Cleanup of test users.
"""
import asyncio
import uuid
import httpx
from sqlalchemy import select, delete, or_

from app.core.database import AsyncSessionLocal
from app.models.models import (
    User, UserInput, Contact, Notification, SignalEvent,
    Deal, DealStageHistory, RevenueForecast, OutreachDraft,
    OutreachLog, ContactUserInputAssociation
)

BASE_URL = "http://localhost:8000/api/v1"

async def run_scenario():
    print("=" * 70)
    print("STARTING 3-SALES-REPRESENTATIVE MULTI-USER ISOLATION VERIFICATION")
    print("=" * 70)

    suffix = uuid.uuid4().hex[:6]
    rep_a_email = f"salesrep_a_{suffix}@forcecloudlabs.com"
    rep_b_email = f"salesrep_b_{suffix}@forcecloudlabs.com"
    rep_c_email = f"salesrep_c_{suffix}@forcecloudlabs.com"
    password = "TestPassword123!"

    reps = [
        {"name": "Sales Rep Alpha", "email": rep_a_email, "company": "Alpha Corp"},
        {"name": "Sales Rep Beta", "email": rep_b_email, "company": "Beta Corp"},
        {"name": "Sales Rep Gamma", "email": rep_c_email, "company": "Gamma Corp"},
    ]

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # Step 1: Register all 3 sales reps
        print("\n[Step 1] Registering Sales Reps A, B, C independently...")
        tokens = {}
        for rep in reps:
            reg_resp = await client.post("/auth/register", json={
                "name": rep["name"],
                "email": rep["email"],
                "password": password,
                "confirm_password": password,
            })
            assert reg_resp.status_code == 201, f"Failed to register {rep['email']}: {reg_resp.text}"
            token = reg_resp.json()["access_token"]
            tokens[rep["email"]] = token
            print(f"  ✓ Registered {rep['name']} ({rep['email']}) successfully.")

        # Step 2: Verify Initial Clean State for Rep A (No inherited legacy or test data)
        print("\n[Step 2] Verifying initial clean slate for newly registered Rep A...")
        headers_a = {"Authorization": f"Bearer {tokens[rep_a_email]}"}
        
        # 2a: Active session should be None
        sess_resp = await client.get("/active-session", headers=headers_a)
        assert sess_resp.status_code == 200
        assert sess_resp.json().get("user_input_id") is None, f"Expected None active session, got {sess_resp.json()}"
        print("  ✓ Active session is correctly None (no inherited sessions).")

        # 2b: Search history should be empty
        hist_resp = await client.get("/input-history", headers=headers_a)
        assert hist_resp.status_code == 200
        assert len(hist_resp.json()) == 0, f"Expected 0 history items, got {len(hist_resp.json())}"
        print("  ✓ Search history is empty [] (no legacy search leaks).")

        # 2c: Contacts list should be empty
        contacts_resp = await client.get("/contacts", headers=headers_a)
        assert contacts_resp.status_code == 200
        assert len(contacts_resp.json()) == 0, f"Expected 0 contacts, got {len(contacts_resp.json())}"
        print("  ✓ Contacts list is empty [] (no unowned contact leaks).")

        # 2d: Drafts list should be empty
        drafts_resp = await client.get("/drafts", headers=headers_a)
        assert drafts_resp.status_code == 200
        assert len(drafts_resp.json()) == 0, f"Expected 0 drafts, got {len(drafts_resp.json())}"
        print("  ✓ Outreach drafts list is empty [] (no unowned draft leaks).")

        # Step 3: Verify Revenue Forecast returns 0 when no deals exist
        print("\n[Step 3] Verifying Revenue Forecast for Rep A (0 active deals)...")
        rev_resp = await client.get("/revenue/forecast", headers=headers_a)
        assert rev_resp.status_code == 200
        rev_data = rev_resp.json()
        assert rev_data["current_pipeline_value"] == 0.0, f"Expected pipeline 0.0, got {rev_data['current_pipeline_value']}"
        assert rev_data["forecast_30d"] == 0.0, f"Expected forecast_30d 0.0, got {rev_data['forecast_30d']}"
        assert rev_data["forecast_60d"] == 0.0, f"Expected forecast_60d 0.0, got {rev_data['forecast_60d']}"
        assert rev_data["forecast_90d"] == 0.0, f"Expected forecast_90d 0.0, got {rev_data['forecast_90d']}"
        assert rev_data["bottleneck_stage"] is None, f"Expected bottleneck None, got {rev_data['bottleneck_stage']}"
        print("  ✓ Revenue forecast correctly returns $0 pipeline, $0 forecast, and None bottleneck!")

        # Step 4: Submit search sessions for Rep A, Rep B, Rep C
        print("\n[Step 4] Creating search sessions for Rep A, Rep B, Rep C...")
        session_ids = {}
        for rep in reps:
            h = {"Authorization": f"Bearer {tokens[rep['email']]}"}
            # Directly create search session in DB to test isolation cleanly
            async with AsyncSessionLocal() as db:
                user_res = await db.execute(select(User).where(User.email == rep["email"]))
                u = user_res.scalar_one()
                ui = UserInput(
                    user_id=u.id,
                    our_company_name=rep["company"],
                    our_services="Cloud AI Platform",
                    target_location="United States",
                    target_company_size="50-200",
                    target_job_titles="VP Sales",
                )
                db.add(ui)
                await db.commit()
                await db.refresh(ui)
                session_ids[rep["email"]] = ui.id
            print(f"  ✓ Created session #{session_ids[rep['email']]} for {rep['name']}.")

        # Step 5: Verify strict search history isolation
        print("\n[Step 5] Verifying search history isolation across all reps...")
        for rep in reps:
            h = {"Authorization": f"Bearer {tokens[rep['email']]}"}
            h_resp = await client.get("/input-history", headers=h)
            assert h_resp.status_code == 200
            items = h_resp.json()
            assert len(items) == 1, f"Expected exactly 1 session for {rep['name']}, got {len(items)}"
            assert items[0]["id"] == session_ids[rep["email"]], f"Session ID mismatch: {items[0]['id']} != {session_ids[rep['email']]}"
            assert items[0]["our_company_name"] == rep["company"], f"Company mismatch: {items[0]['our_company_name']} != {rep['company']}"
            print(f"  ✓ {rep['name']} sees ONLY Session #{session_ids[rep['email']]} ({rep['company']}).")

        # Step 6: Verify Direct Object Access Prevention (IDOR Security)
        print("\n[Step 6] Testing cross-user access attempts (IDOR Prevention)...")
        # Rep A attempts to access Rep B's session detail
        idor_resp1 = await client.get(f"/sessions/{session_ids[rep_b_email]}", headers=headers_a)
        assert idor_resp1.status_code == 404, f"Rep A accessed Rep B's session! Status: {idor_resp1.status_code}"
        print("  ✓ Rep A cannot access Rep B's session detail (HTTP 404).")

        # Rep A attempts to filter contacts with Rep B's session ID
        idor_resp2 = await client.get("/contacts", params={"user_input_id": session_ids[rep_b_email]}, headers=headers_a)
        assert idor_resp2.status_code == 404, f"Rep A accessed Rep B's contacts! Status: {idor_resp2.status_code}"
        print("  ✓ Rep A cannot query contacts using Rep B's session ID (HTTP 404).")

        # Rep A attempts to filter drafts with Rep B's session ID
        idor_resp3 = await client.get("/drafts", params={"user_input_id": session_ids[rep_b_email]}, headers=headers_a)
        assert idor_resp3.status_code == 404, f"Rep A accessed Rep B's drafts! Status: {idor_resp3.status_code}"
        print("  ✓ Rep A cannot query drafts using Rep B's session ID (HTTP 404).")

        # Step 7: Verify Profile Page & RBAC Permissions
        print("\n[Step 7] Verifying View Profile and RBAC permissions...")
        # 7a: Rep A profile reflects Rep A data
        profile_resp = await client.get("/user/settings", headers=headers_a)
        assert profile_resp.status_code == 200
        p_data = profile_resp.json()
        assert p_data["email"] == rep_a_email, f"Profile email mismatch: {p_data['email']}"
        assert p_data["name"] == "Sales Rep Alpha", f"Profile name mismatch: {p_data['name']}"
        assert p_data["role"] == "SALES_REPRESENTATIVE", f"Profile role mismatch: {p_data['role']}"
        print(f"  ✓ Rep A profile correctly returns '{p_data['name']}' ({p_data['email']}).")

        # 7b: Rep A (non-admin) is blocked from /admin/users
        admin_block_resp = await client.get("/admin/users", headers=headers_a)
        assert admin_block_resp.status_code == 403, f"Expected 403 on /admin/users for regular rep, got {admin_block_resp.status_code}"
        print("  ✓ Regular sales rep is forbidden from /admin/users (HTTP 403).")

        # 7c: Shree (Admin) can access /admin/users
        from app.core.security import create_access_token
        admin_token = create_access_token("f7d9b0fe-27c4-4c17-b2ea-b8225944f60f")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        admin_resp = await client.get("/admin/users", headers=admin_headers)
        assert admin_resp.status_code == 200, f"Expected 200 on /admin/users for Admin, got {admin_resp.status_code}: {admin_resp.text}"
        user_list = admin_resp.json()
        assert isinstance(user_list, list) and len(user_list) > 0
        print(f"  ✓ Admin successfully retrieved {len(user_list)} users from /admin/users (HTTP 200).")

        # Step 8: Teardown test users
        print("\n[Step 8] Cleaning up verification test users...")
        async with AsyncSessionLocal() as db:
            del_users = (await db.execute(select(User).where(or_(
                User.email == rep_a_email,
                User.email == rep_b_email,
                User.email == rep_c_email
            )))).scalars().all()
            if del_users:
                uids = [u.id for u in del_users]
                await db.execute(delete(UserInput).where(UserInput.user_id.in_(uids)))
                await db.execute(delete(User).where(User.id.in_(uids)))
                await db.commit()
            print("  ✓ Cleaned up test reps successfully.")

    print("\n" + "=" * 70)
    print("ALL MULTI-USER ISOLATION & ACCURACY CHECKS PASSED PERFECTLY!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_scenario())

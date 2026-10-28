import asyncio
import httpx
import asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://gtm:gtmpass@localhost:5433/gtm")
    row = await conn.fetchrow("SELECT id, email, user_id FROM contacts WHERE user_id IS NOT NULL LIMIT 1")
    if not row:
        row = await conn.fetchrow("SELECT id, email, user_id FROM contacts LIMIT 1")
    await conn.close()
    
    cid = str(row["id"])
    email = row["email"]
    uid = row["user_id"]
    
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        # Register user
        reg_user = f"user_{cid[:8]}@example.com"
        reg = await client.post("/api/v1/auth/register", json={
            "name": "Test User", "email": reg_user,
            "password": "Password123!", "confirm_password": "Password123!"
        })
        if reg.status_code == 201:
            token = reg.json()["access_token"]
            new_uid = reg.json()["user"]["id"]
            # Assign contact to user in DB
            conn = await asyncpg.connect("postgresql://gtm:gtmpass@localhost:5433/gtm")
            await conn.execute("UPDATE contacts SET user_id = $1 WHERE id = $2", new_uid, row["id"])
            await conn.close()
        else:
            login = await client.post("/api/v1/auth/login", json={"email": reg_user, "password": "Password123!"})
            token = login.json()["access_token"]
            
        headers = {"Authorization": f"Bearer {token}"}
        print(f"Testing POST /api/v1/contacts/{cid}/sync-salesforce with valid token...")
        res = await client.post(f"/api/v1/contacts/{cid}/sync-salesforce", headers=headers)
        print("Status Code:", res.status_code)
        print("Response Body:", res.text)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import httpx
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Contact

async def clean_hubspot_companies():
    token = settings.HUBSPOT_ACCESS_TOKEN
    if not token:
        print("No HUBSPOT_ACCESS_TOKEN configured.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # 1. Get the list of real company names from our 25 DB contacts
    async with AsyncSessionLocal() as db:
        real_contacts = (await db.execute(select(Contact))).scalars().all()
        real_companies = set(c.company.lower().strip() for c in real_contacts if c.company)
        print(f"Active Real Companies ({len(real_companies)}):")
        for comp in sorted(real_companies):
            print(f"  ✓ {comp}")

    # 2. Fetch all companies from HubSpot
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.get("https://api.hubapi.com/crm/v3/objects/companies?limit=100&properties=name,domain", headers=headers)
        if res.status_code != 200:
            print(f"Failed to fetch HubSpot companies: {res.status_code} {res.text}")
            return

        hs_companies = res.json().get("results", [])
        print(f"\nTotal Companies in HubSpot: {len(hs_companies)}")

        deleted_count = 0
        retained_count = 0

        for c in hs_companies:
            c_id = c.get("id")
            c_name = c.get("properties", {}).get("name", "").strip()
            c_name_lower = c_name.lower().strip()
            c_domain = c.get("properties", {}).get("domain", "").lower().strip()

            # Check if this company matches any of our 25 real companies or their domain
            matches_real = any(
                rc in c_name_lower or c_name_lower in rc
                for rc in real_companies
            )

            # Special case for HubSpot sample company
            if c_name_lower == "hubspot" or not c_name_lower or not matches_real:
                print(f" -> Deleting mock/stale company from HubSpot: '{c_name}' (domain: {c_domain}) [ID: {c_id}]")
                del_res = await client.delete(f"https://api.hubapi.com/crm/v3/objects/companies/{c_id}", headers=headers)
                if del_res.status_code in [200, 204]:
                    deleted_count += 1
                    print(f"    ✓ Deleted {c_id} successfully")
                else:
                    print(f"    ✕ Delete failed: {del_res.status_code} {del_res.text}")
            else:
                retained_count += 1
                print(f" ✓ Retaining real company in HubSpot: '{c_name}' [ID: {c_id}]")

        print(f"\nHubSpot Companies cleanup finished! Deleted: {deleted_count}, Retained: {retained_count}")

if __name__ == "__main__":
    asyncio.run(clean_hubspot_companies())

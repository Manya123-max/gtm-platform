import asyncio
import httpx
from datetime import datetime, timedelta
from sqlalchemy import select, delete, or_
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, Contact, PendingAction, ActionStatus, SignalEvent, SignalType, DealStageHistory

async def sync_contacts_and_deals_to_hubspot():
    token = settings.HUBSPOT_ACCESS_TOKEN
    if not token:
        print("No HUBSPOT_ACCESS_TOKEN configured.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with AsyncSessionLocal() as db:
        # 1. Fetch contacts from DB
        contacts_res = await db.execute(select(Contact))
        contacts = contacts_res.scalars().all()
        print(f"\nSyncing {len(contacts)} contacts to HubSpot...")

        contact_hubspot_map = {} # contact_id -> hs_contact_id

        async with httpx.AsyncClient(timeout=20.0) as client:
            for c in contacts:
                # Prepare contact properties
                body = {
                    "properties": {
                        "email": c.email,
                        "firstname": c.first_name or "",
                        "lastname": c.last_name or "",
                        "jobtitle": c.title or "",
                        "company": c.company or "",
                    }
                }
                
                try:
                    # Create or update contact in HubSpot
                    res = await client.post("https://api.hubapi.com/crm/v3/objects/contacts", headers=headers, json=body)
                    if res.status_code in [200, 201]:
                        hs_data = res.json()
                        hs_id = hs_data.get("id")
                        c.hubspot_id = hs_id
                        contact_hubspot_map[c.id] = hs_id
                        print(f" -> Created contact {c.first_name} {c.last_name} ({c.email}) in HubSpot (ID: {hs_id})")
                    elif res.status_code == 409:
                        # Contact already exists in HubSpot, search by email to get ID
                        search_res = await client.post(
                            "https://api.hubapi.com/crm/v3/objects/contacts/search",
                            headers=headers,
                            json={"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": c.email}]}]}
                        )
                        if search_res.status_code == 200 and search_res.json().get("results"):
                            hs_id = search_res.json()["results"][0]["id"]
                            c.hubspot_id = hs_id
                            contact_hubspot_map[c.id] = hs_id
                            print(f" -> Contact {c.email} already exists in HubSpot (ID: {hs_id})")
                    else:
                        print(f"Failed to create contact {c.email}: {res.status_code} {res.text}")
                except Exception as e:
                    print(f"Error syncing contact {c.email}: {e}")

            # 2. Sync Deals to HubSpot
            deals_res = await db.execute(select(Deal))
            deals = deals_res.scalars().all()
            print(f"\nSyncing {len(deals)} active deals to HubSpot...")

            for d in deals:
                deal_body = {
                    "properties": {
                        "dealname": d.name,
                        "amount": str(d.amount or 60000),
                        "dealstage": "presentationscheduled" if d.stage == "demo" else "appointmentscheduled",
                        "pipeline": "default"
                    }
                }
                try:
                    deal_res = await client.post("https://api.hubapi.com/crm/v3/objects/deals", headers=headers, json=deal_body)
                    if deal_res.status_code in [200, 201]:
                        hs_deal_data = deal_res.json()
                        hs_deal_id = hs_deal_data.get("id")
                        d.hubspot_deal_id = hs_deal_id
                        print(f" -> Created deal '{d.name}' in HubSpot (ID: {hs_deal_id})")

                        # Associate Deal with Contact if available
                        if d.contact_id and d.contact_id in contact_hubspot_map:
                            hs_c_id = contact_hubspot_map[d.contact_id]
                            assoc_url = f"https://api.hubapi.com/crm/v3/objects/deals/{hs_deal_id}/associations/contacts/{hs_c_id}/deal_to_contact"
                            assoc_res = await client.put(assoc_url, headers=headers)
                            if assoc_res.status_code in [200, 201]:
                                print(f"    -> Associated deal {hs_deal_id} with contact {hs_c_id}")
                    else:
                        print(f"Failed to create deal '{d.name}': {deal_res.status_code} {deal_res.text}")
                except Exception as e:
                    print(f"Error syncing deal '{d.name}': {e}")

            await db.commit()
            print("\nHubSpot Two-Way Sync Complete!")

if __name__ == "__main__":
    asyncio.run(sync_contacts_and_deals_to_hubspot())

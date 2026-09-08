import asyncio
import httpx
from sqlalchemy import select, delete
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, Contact, PendingAction, ActionStatus, SignalEvent

async def test_hubspot():
    token = settings.HUBSPOT_ACCESS_TOKEN
    print(f"Testing HubSpot token: {token[:10]}... (len={len(token)})")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Test Contacts API
        try:
            r = await client.get("https://api.hubapi.com/crm/v3/objects/contacts", headers=headers)
            print(f"HubSpot Contacts API Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"Found {len(data.get('results', []))} contacts in HubSpot:")
                for c in data.get('results', []):
                    props = c.get('properties', {})
                    print(f" - {props.get('firstname')} {props.get('lastname')} ({props.get('email')}) - ID: {c.get('id')}")
            else:
                print(f"Contacts API Error: {r.text}")
        except Exception as e:
            print(f"Contacts API Exception: {e}")
            
        # Test Deals API
        try:
            r = await client.get("https://api.hubapi.com/crm/v3/objects/deals", headers=headers)
            print(f"HubSpot Deals API Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"Found {len(data.get('results', []))} deals in HubSpot:")
                for d in data.get('results', []):
                    props = d.get('properties', {})
                    print(f" - {props.get('dealname')} (Stage: {props.get('dealstage')}, Amount: {props.get('amount')}) - ID: {d.get('id')}")
            else:
                print(f"Deals API Error: {r.text}")
        except Exception as e:
            print(f"Deals API Exception: {e}")

async def inspect_and_clean_db():
    async with AsyncSessionLocal() as db:
        print("\n--- Inspecting Deals in DB ---")
        deals_res = await db.execute(select(Deal))
        deals = deals_res.scalars().all()
        print(f"Total deals in DB: {len(deals)}")
        for d in deals:
            print(f" - Deal ID: {d.id} | Name: '{d.name}' | Contact ID: {d.contact_id} | Stage: {d.stage} | Amount: {d.amount}")

        print("\n--- Inspecting Contacts in DB ---")
        contacts_res = await db.execute(select(Contact))
        contacts = contacts_res.scalars().all()
        print(f"Total contacts in DB: {len(contacts)}")
        for c in contacts:
            print(f" - Contact ID: {c.id} | Name: {c.first_name} {c.last_name} | Company: '{c.company}' | Email: {c.email} | user_input_id: {c.user_input_id}")

        print("\n--- Inspecting Pending Actions in DB ---")
        actions_res = await db.execute(select(PendingAction).where(PendingAction.status == ActionStatus.PENDING))
        actions = actions_res.scalars().all()
        print(f"Total Pending Actions: {len(actions)}")
        for a in actions:
            print(f" - Action ID: {a.id} | entity_type: {a.entity_type} | entity_id: {a.entity_id} | action_type: {a.action_type} | reason: {a.reason[:60]}...")

if __name__ == "__main__":
    asyncio.run(test_hubspot())
    asyncio.run(inspect_and_clean_db())

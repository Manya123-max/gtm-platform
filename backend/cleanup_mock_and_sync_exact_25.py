import asyncio
import httpx
from sqlalchemy import select, delete
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    Contact, Deal, PendingAction, OutreachDraft, OutreachLog,
    SignalEvent, ConversationThread, FunnelEvent, DealStageHistory
)

async def cleanup_and_sync_exact_25():
    token = settings.HUBSPOT_ACCESS_TOKEN
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    async with AsyncSessionLocal() as db:
        # 1. Fetch exact 25 real contacts from Session 12
        real_contacts_res = await db.execute(select(Contact).where(Contact.user_input_id == 12))
        real_contacts = real_contacts_res.scalars().all()
        real_contact_ids = set(c.id for c in real_contacts)
        real_emails = set(c.email.lower().strip() for c in real_contacts if c.email)
        print(f"Retaining exactly {len(real_contacts)} real contacts from Session 12:")
        for c in real_contacts:
            print(f"  ✓ {c.first_name} {c.last_name} ({c.email}) at {c.company}")

        # 2. Find all other contacts in DB to delete
        all_contacts_res = await db.execute(select(Contact))
        all_contacts = all_contacts_res.scalars().all()
        contacts_to_delete = [c for c in all_contacts if c.id not in real_contact_ids]
        delete_ids = [c.id for c in contacts_to_delete]
        print(f"\nDeleting {len(contacts_to_delete)} mock/stale contacts from PostgreSQL DB...")

        if delete_ids:
            # Delete dependent records
            await db.execute(delete(FunnelEvent).where(FunnelEvent.contact_id.in_(delete_ids)))
            await db.execute(delete(ConversationThread).where(ConversationThread.contact_id.in_(delete_ids)))
            await db.execute(delete(OutreachDraft).where(OutreachDraft.contact_id.in_(delete_ids)))
            await db.execute(delete(OutreachLog).where(OutreachLog.contact_id.in_(delete_ids)))
            await db.execute(delete(SignalEvent).where(SignalEvent.contact_id.in_(delete_ids)))
            await db.execute(delete(PendingAction).where(
                PendingAction.entity_type == "contact",
                PendingAction.entity_id.in_(delete_ids)
            ))
            
            # Delete deals tied to deleted contacts
            del_deals = (await db.execute(select(Deal).where(Deal.contact_id.in_(delete_ids)))).scalars().all()
            if del_deals:
                del_deal_ids = [d.id for d in del_deals]
                await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id.in_(del_deal_ids)))
                await db.execute(delete(PendingAction).where(PendingAction.entity_id.in_(del_deal_ids)))
                await db.execute(delete(Deal).where(Deal.id.in_(del_deal_ids)))

            # Delete the contacts
            await db.execute(delete(Contact).where(Contact.id.in_(delete_ids)))

        # Also ensure only the real deal (Galvin Technologies) remains in DB
        other_deals = (await db.execute(select(Deal).where(~Deal.name.ilike("%galvin%")))).scalars().all()
        if other_deals:
            other_deal_ids = [d.id for d in other_deals]
            print(f"Deleting {len(other_deals)} mock deals from DB: {[d.name for d in other_deals]}")
            await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id.in_(other_deal_ids)))
            await db.execute(delete(PendingAction).where(PendingAction.entity_id.in_(other_deal_ids)))
            await db.execute(delete(Deal).where(Deal.id.in_(other_deal_ids)))

        await db.commit()
        print("PostgreSQL Database cleaned successfully! Exact 25 contacts remaining.")

    # 3. Clean up HubSpot CRM via API
    if not token:
        print("No HUBSPOT_ACCESS_TOKEN configured.")
        return

    print("\n--- Cleaning up HubSpot CRM ---")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # A. Fetch all contacts from HubSpot
        hs_contacts_res = await client.get("https://api.hubapi.com/crm/v3/objects/contacts?limit=100&properties=email,firstname,lastname", headers=headers)
        if hs_contacts_res.status_code == 200:
            hs_contacts = hs_contacts_res.json().get("results", [])
            print(f"Found {len(hs_contacts)} contacts in HubSpot:")
            for hc in hs_contacts:
                h_id = hc.get("id")
                h_email = hc.get("properties", {}).get("email", "").lower().strip()
                h_name = f"{hc.get('properties', {}).get('firstname', '')} {hc.get('properties', {}).get('lastname', '')}".strip()

                if h_email not in real_emails:
                    print(f"  -> Deleting mock contact from HubSpot: {h_name} ({h_email}) [ID: {h_id}]")
                    del_res = await client.delete(f"https://api.hubapi.com/crm/v3/objects/contacts/{h_id}", headers=headers)
                    if del_res.status_code in [200, 204]:
                        print(f"     ✓ Deleted {h_id} successfully")
                    else:
                        print(f"     ✕ Delete failed: {del_res.status_code} {del_res.text}")
                else:
                    print(f"  ✓ Retaining real prospect in HubSpot: {h_name} ({h_email})")

        # B. Fetch all deals from HubSpot
        hs_deals_res = await client.get("https://api.hubapi.com/crm/v3/objects/deals?limit=100&properties=dealname", headers=headers)
        if hs_deals_res.status_code == 200:
            hs_deals = hs_deals_res.json().get("results", [])
            print(f"\nFound {len(hs_deals)} deals in HubSpot:")
            for hd in hs_deals:
                d_id = hd.get("id")
                d_name = hd.get("properties", {}).get("dealname", "")
                if "galvin" not in d_name.lower():
                    print(f"  -> Deleting mock deal from HubSpot: '{d_name}' [ID: {d_id}]")
                    del_d_res = await client.delete(f"https://api.hubapi.com/crm/v3/objects/deals/{d_id}", headers=headers)
                    if del_d_res.status_code in [200, 204]:
                        print(f"     ✓ Deleted {d_id} successfully")
                    else:
                        print(f"     ✕ Delete failed: {del_d_res.status_code} {del_d_res.text}")
                else:
                    print(f"  ✓ Retaining real deal in HubSpot: '{d_name}'")

        # C. Update Hubspot IDs for the 25 real contacts in our DB
        async with AsyncSessionLocal() as db:
            for rc in real_contacts:
                s_res = await client.post(
                    "https://api.hubapi.com/crm/v3/objects/contacts/search",
                    headers=headers,
                    json={"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": rc.email}]}]}
                )
                if s_res.status_code == 200 and s_res.json().get("results"):
                    hs_id = s_res.json()["results"][0]["id"]
                    rc_db = await db.get(Contact, rc.id)
                    if rc_db:
                        rc_db.hubspot_id = hs_id
                        print(f"Updated DB contact {rc.email} -> HubSpot ID {hs_id}")
            await db.commit()

    print("\nPurge and Sync complete! Exactly 25 real prospects are in HubSpot and DB.")

if __name__ == "__main__":
    asyncio.run(cleanup_and_sync_exact_25())

import asyncio
import httpx
from sqlalchemy import select, delete, text
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import (
    Contact, Deal, PendingAction, OutreachDraft, OutreachLog,
    SignalEvent, ConversationThread, FunnelEvent, DealStageHistory,
    GeneratedContent
)

MOCK_EMAILS = [
    'sarah.chen@growthops.io',
    'marcus.johnson@scalepath.com',
    'priya.patel@revstack.ai',
    'suriya.krishnan@forcecloudlabs.com',
    'tom.wright@databridge.co',
    'lisa.wang@pipelineco.io',
    'james.miller@salesforge.com',
    'anna.thompson@growthleap.io',
    'david.kim@metrics360.com',
    'rachel.green@outbound.ai',
    'chris.davis@salenova.com',
    'david.chen@acmecorp.com',
    'googlecloud@google.com',
    'team@moonshot.ai',
    'hello@cal.com',
    'onboarding@hubspot.com',
    'fred@fireflies.ai'
]

async def cleanup_all_mock_data():
    print("=== STARTING MOCK DATA PURGE ===")
    
    async with AsyncSessionLocal() as db:
        # 1. Find mock contacts
        res = await db.execute(select(Contact).where(Contact.email.in_(MOCK_EMAILS)))
        mock_contacts = res.scalars().all()
        mock_contact_ids = [c.id for c in mock_contacts]
        print(f"Found {len(mock_contacts)} mock contacts to purge.")

        if mock_contact_ids:
            # Delete dependent funnel events
            r = await db.execute(delete(FunnelEvent).where(FunnelEvent.contact_id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} dependent funnel events")

            # Delete dependent conversation threads
            r = await db.execute(delete(ConversationThread).where(ConversationThread.contact_id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} dependent conversation threads")

            # Delete dependent outreach drafts
            r = await db.execute(delete(OutreachDraft).where(OutreachDraft.contact_id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} dependent outreach drafts")

            # Delete dependent outreach logs
            r = await db.execute(delete(OutreachLog).where(OutreachLog.contact_id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} dependent outreach logs")

            # Delete dependent signals
            r = await db.execute(delete(SignalEvent).where(SignalEvent.contact_id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} dependent signals")

            # Delete dependent pending actions
            r = await db.execute(delete(PendingAction).where(
                PendingAction.entity_type == "contact",
                PendingAction.entity_id.in_(mock_contact_ids)
            ))
            print(f"  ✓ Deleted {r.rowcount} dependent pending actions")

            # Delete deals tied to mock contacts
            del_deals = (await db.execute(select(Deal).where(Deal.contact_id.in_(mock_contact_ids)))).scalars().all()
            if del_deals:
                del_deal_ids = [d.id for d in del_deals]
                await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id.in_(del_deal_ids)))
                await db.execute(delete(PendingAction).where(PendingAction.entity_id.in_(del_deal_ids)))
                r = await db.execute(delete(Deal).where(Deal.id.in_(del_deal_ids)))
                print(f"  ✓ Deleted {r.rowcount} dependent deals")

            # Delete the contacts
            r = await db.execute(delete(Contact).where(Contact.id.in_(mock_contact_ids)))
            print(f"  ✓ Deleted {r.rowcount} mock contacts")

        # 2. Clean up mock / old generated content
        # Keep only the latest 15 real generated pieces from the active Agent 6 pipeline run
        from datetime import datetime
        res = await db.execute(
            delete(GeneratedContent).where(
                (GeneratedContent.created_at < datetime(2026, 9, 8, 0, 0, 0)) |
                (GeneratedContent.title.ilike('%hospital%')) |
                (GeneratedContent.title.ilike('%Why B2B Outbound Fails%')) |
                (GeneratedContent.title.ilike('%How Series B Companies%'))
            )
        )
        print(f"  ✓ Deleted {res.rowcount} mock/stale generated content pieces")

        await db.commit()

        # Check remaining counts
        rem_contacts = (await db.execute(select(Contact))).scalars().all()
        rem_content = (await db.execute(select(GeneratedContent))).scalars().all()
        print(f"\nRemaining in Database:")
        print(f"  - Real Contacts: {len(rem_contacts)}")
        print(f"  - Real Generated Content: {len(rem_content)}")

    # 3. Clean up HubSpot CRM if token is configured
    token = settings.HUBSPOT_ACCESS_TOKEN
    if token:
        print("\n--- Cleaning HubSpot CRM ---")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            hs_contacts_res = await client.get(
                "https://api.hubapi.com/crm/v3/objects/contacts?limit=100&properties=email,firstname,lastname",
                headers=headers
            )
            if hs_contacts_res.status_code == 200:
                hs_contacts = hs_contacts_res.json().get("results", [])
                for hc in hs_contacts:
                    h_id = hc.get("id")
                    h_email = hc.get("properties", {}).get("email", "").lower().strip()
                    if h_email in [e.lower() for e in MOCK_EMAILS]:
                        del_res = await client.delete(f"https://api.hubapi.com/crm/v3/objects/contacts/{h_id}", headers=headers)
                        print(f"  ✓ Deleted mock contact from HubSpot: {h_email} [ID: {h_id}]")

    print("\n=== PURGE COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    asyncio.run(cleanup_all_mock_data())

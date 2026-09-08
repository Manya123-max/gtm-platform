import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check_dependencies():
    async with AsyncSessionLocal() as db:
        mock_emails = [
            'sarah.chen@growthops.io', 'marcus.johnson@scalepath.com', 'priya.patel@revstack.ai',
            'suriya.krishnan@forcecloudlabs.com', 'lisa.wang@pipelineco.io', 'james.miller@salesforge.com',
            'anna.thompson@growthleap.io', 'david.kim@metrics360.com', 'rachel.green@outbound.ai',
            'chris.davis@salenova.com', 'david.chen@acmecorp.com', 'googlecloud@google.com',
            'team@moonshot.ai', 'hello@cal.com', 'onboarding@hubspot.com', 'fred@fireflies.ai'
        ]
        
        res = await db.execute(text('SELECT id, email, first_name, last_name, company FROM contacts WHERE email = ANY(:emails);'), {'emails': mock_emails})
        found_contacts = res.fetchall()
        print(f'Found {len(found_contacts)} mock contacts to delete:')
        for c in found_contacts:
            print(f' - {c[1]} ({c[2]} {c[3]}) at {c[4]} [ID: {c[0]}]')
            
        c_ids = [str(c[0]) for c in found_contacts]
        
        # Check deals
        res = await db.execute(text('SELECT count(*) FROM deals WHERE contact_id::text = ANY(:c_ids);'), {'c_ids': c_ids})
        print('Dependent deals:', res.scalar())

        # Check signals
        res = await db.execute(text('SELECT count(*) FROM signal_events WHERE contact_id::text = ANY(:c_ids);'), {'c_ids': c_ids})
        print('Dependent signals:', res.scalar())

        # Check conversation threads
        res = await db.execute(text('SELECT count(*) FROM conversation_threads WHERE contact_id::text = ANY(:c_ids);'), {'c_ids': c_ids})
        print('Dependent threads:', res.scalar())

        # Check outreach drafts
        res = await db.execute(text('SELECT count(*) FROM outreach_drafts WHERE contact_id::text = ANY(:c_ids);'), {'c_ids': c_ids})
        print('Dependent outreach drafts:', res.scalar())

        # Check pending actions
        res = await db.execute(text('SELECT count(*) FROM pending_actions WHERE entity_id::text = ANY(:c_ids);'), {'c_ids': c_ids})
        print('Dependent pending actions:', res.scalar())

        # Check mock generated content
        res = await db.execute(text("SELECT id, title, created_at FROM generated_content WHERE created_at < '2026-09-08 00:00:00' OR title ILIKE '%hospital%'"))
        mock_content = res.fetchall()
        print(f'\nFound {len(mock_content)} older/mock content pieces:')
        for mc in mock_content:
            print(f' - {mc[1]} ({mc[2]})')

if __name__ == "__main__":
    asyncio.run(check_dependencies())

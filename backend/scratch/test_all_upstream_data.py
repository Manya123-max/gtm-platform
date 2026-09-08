import asyncio
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models.models import (
    Contact, SignalEvent, OutreachDraft, OutreachLog,
    ConversationThread, Deal, UserInput
)

async def test_all_upstream_data():
    async with AsyncSessionLocal() as db:
        print("=== 1. A1: CONTACTS & ICP SEGMENTS ===")
        contacts_res = await db.execute(
            select(Contact.industry, Contact.title, Contact.company)
            .where(Contact.industry.isnot(None))
            .limit(10)
        )
        contacts = contacts_res.all()
        print(f"Sample Contacts ({len(contacts)}):", [(c[0], c[1], c[2]) for c in contacts[:5]])
        
        print("\n=== 2. A2: BUYING SIGNALS ===")
        signals_res = await db.execute(
            select(SignalEvent, Contact.company)
            .outerjoin(Contact, SignalEvent.contact_id == Contact.id)
            .order_by(desc(SignalEvent.detected_at))
            .limit(10)
        )
        signals = signals_res.all()
        print(f"Total signals found: {len(signals)}")
        for sig, comp in signals[:5]:
            sig_type = sig.signal_type.value if hasattr(sig.signal_type, 'value') else sig.signal_type
            print(f" - [{comp or 'Unknown'}] Type: {sig_type} | Source: {sig.signal_source} | Raw: {sig.raw_data}")
            
        print("\n=== 3. A3: OUTREACH DRAFTS & LOGS ===")
        drafts_res = await db.execute(
            select(OutreachDraft, Contact.company)
            .outerjoin(Contact, OutreachDraft.contact_id == Contact.id)
            .order_by(desc(OutreachDraft.created_at))
            .limit(10)
        )
        drafts = drafts_res.all()
        print(f"Total drafts found: {len(drafts)}")
        for d, comp in drafts[:5]:
            print(f" - [{comp or 'Unknown'}] Case: {d.business_case} | Services: {d.matched_services} | Subj: {d.subject}")
            
        print("\n=== 4. A4: INBOUND CONVERSATION THREADS ===")
        threads_res = await db.execute(
            select(ConversationThread, Contact.company)
            .outerjoin(Contact, ConversationThread.contact_id == Contact.id)
            .where(ConversationThread.direction == "inbound")
            .limit(5)
        )
        threads = threads_res.all()
        print(f"Inbound threads found: {len(threads)}")
        for t, comp in threads[:3]:
            print(f" - [{comp or 'Unknown'}] Intent: {t.intent} | Text: {(t.content or '')[:60]}...")
            
        print("\n=== 5. A5: DEALS & TRANSCRIPT OBJECTIONS ===")
        deals_res = await db.execute(select(Deal).options(selectinload(Deal.contact)))
        deals = deals_res.scalars().all()
        print(f"Deals found: {len(deals)}")
        for dl in deals:
            print(f" - Deal: {dl.name} | Objections: {dl.objections} | Risks: {dl.risk_flags}")
            
        print("\n=== 6. USER INPUT / ONBOARDING CONTEXT ===")
        ui_res = await db.execute(select(UserInput).order_by(desc(UserInput.id)).limit(1))
        ui = ui_res.scalar_one_or_none()
        if ui:
            print(f" - Company: {ui.our_company_name} | Services: {ui.our_services} | Industries: {ui.target_industries}")
        else:
            print(" - No UserInput record found.")

if __name__ == "__main__":
    asyncio.run(test_all_upstream_data())

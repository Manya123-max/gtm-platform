import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, Contact, SignalEvent
from sqlalchemy import select

async def check_signals():
    async with AsyncSessionLocal() as db:
        # Get Galvin Deal
        deal_res = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
        deal = deal_res.scalars().first()
        if not deal:
            print("No Galvin deal found.")
            return
            
        print(f"Deal: {deal.name}")
        print(f"  ID: {deal.id}")
        print(f"  contact_id: {deal.contact_id}")
        
        if deal.contact_id:
            # Get Contact
            contact_res = await db.execute(select(Contact).where(Contact.id == deal.contact_id))
            contact = contact_res.scalars().first()
            if contact:
                print(f"Contact:")
                print(f"  ID: {contact.id}")
                print(f"  Name: {contact.first_name} {contact.last_name}")
                print(f"  Email: {contact.email}")
                print(f"  Company: {contact.company}")
                
            # Get Signals for this contact
            signals_res = await db.execute(
                select(SignalEvent).where(SignalEvent.contact_id == deal.contact_id)
            )
            signals = signals_res.scalars().all()
            print(f"\nSignals filtered by contact_id ({deal.contact_id}) (Count: {len(signals)}):")
            for idx, s in enumerate(signals):
                print(f"  [{idx}] Signal ID: {s.id}")
                print(f"      Type: {s.signal_type}")
                print(f"      Source: {s.signal_source}")
                print(f"      Raw Data: {s.raw_data}")

if __name__ == "__main__":
    asyncio.run(check_signals())

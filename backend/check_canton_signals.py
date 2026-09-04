import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import SignalEvent, Contact
from sqlalchemy import select

async def check_canton():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(SignalEvent))
        signals = res.scalars().all()
        
        canton_signals = []
        for s in signals:
            headline = s.raw_data.get("headline", "") if s.raw_data else ""
            if "canton" in headline.lower() or "canton" in str(s.raw_data).lower():
                canton_signals.append(s)
                
        print(f"Found {len(canton_signals)} signals matching 'Canton' in DB:")
        for idx, s in enumerate(canton_signals):
            contact_res = await db.execute(select(Contact).where(Contact.id == s.contact_id))
            contact = contact_res.scalars().first()
            c_info = f"{contact.first_name} {contact.last_name} at {contact.company} (ID: {contact.id})" if contact else "None"
            print(f"\n[{idx}] Signal ID: {s.id}")
            print(f"    Detected At: {s.detected_at}")
            print(f"    Source: {s.signal_source}")
            print(f"    Type: {s.signal_type}")
            print(f"    Contact: {c_info}")
            print(f"    Raw Data: {s.raw_data}")

if __name__ == "__main__":
    asyncio.run(check_canton())

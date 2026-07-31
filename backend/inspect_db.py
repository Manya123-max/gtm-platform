import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import AsyncSessionLocal
from app.models.models import Contact, SignalEvent

async def main():
    db = AsyncSessionLocal()
    try:
        from sqlalchemy import select
        res = await db.execute(select(Contact))
        contacts = res.scalars().all()
        print("CONTACTS SIGNAL TYPES:")
        for c in contacts:
            if c.signal_type:
                print(f"Contact: {c.first_name} {c.last_name} | Company: {c.company} | SignalType: {repr(c.signal_type)}")
                
        res = await db.execute(select(SignalEvent))
        signals = res.scalars().all()
        print("\nALL SIGNAL EVENTS IN DB:")
        for s in signals:
            print(f"Contact ID: {s.contact_id} | Signal: {s.signal_type} | Source: {s.signal_source}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())

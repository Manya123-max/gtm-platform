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
        res = await db.execute(select(SignalEvent).where(SignalEvent.signal_type == "social_engagement"))
        signals = res.scalars().all()
        print("\nSOCIAL ENGAGEMENT SIGNALS IN DB:")
        for s in signals:
            print(f"Contact ID: {s.contact_id} | Signal: {s.signal_type} | Source: {s.signal_source} | Data: {s.raw_data}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())

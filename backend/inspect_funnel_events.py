import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import FunnelEvent, Deal
from sqlalchemy import select

async def inspect_events():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(FunnelEvent)
            .where(FunnelEvent.event_type == "transcript_processed")
            .order_by(FunnelEvent.timestamp.desc())
        )
        events = res.scalars().all()
        print(f"Found {len(events)} transcript_processed events:")
        for idx, event in enumerate(events):
            print(f"\n--- Event {idx} | Timestamp: {event.timestamp} ---")
            print(f"Metadata: {event.event_metadata}")

        res_deal = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
        deal = res_deal.scalars().first()
        if deal:
            print(f"\nGalvin Deal Updated At: {deal.updated_at}")

if __name__ == "__main__":
    asyncio.run(inspect_events())

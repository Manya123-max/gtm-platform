import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import ConversationThread, OutreachLog, Contact
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ConversationThread).where(ConversationThread.contact_id == 'f9715c19-ff33-45d7-bd6d-74f8e8d14651'))
        threads = res.scalars().all()
        print(f"ConversationThread entries for Tom Wright: {len(threads)}")
        for t in threads:
            print(f"  [ID: {t.id}] Dir: {t.direction} | Event: {t.event_type} | Content: {(t.content or '')[:60]}...")
            
        res2 = await db.execute(select(OutreachLog).where(OutreachLog.contact_id == 'f9715c19-ff33-45d7-bd6d-74f8e8d14651'))
        logs = res2.scalars().all()
        print(f"OutreachLog entries for Tom Wright: {len(logs)}")
        for l in logs:
            print(f"  [ID: {l.id}] Subject: {l.subject} | SentAt: {l.sent_at} | Body: {(l.body or '')[:60]}...")

if __name__ == "__main__":
    asyncio.run(main())

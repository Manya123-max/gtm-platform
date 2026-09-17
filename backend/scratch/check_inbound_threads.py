import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_
from app.core.database import AsyncSessionLocal
from app.models.models import ConversationThread, Contact, Deal

async def check_threads_and_deals():
    async with AsyncSessionLocal() as db:
        print("=== INBOUND CONVERSATION THREADS ===")
        inbound_res = await db.execute(
            select(ConversationThread, Contact.company)
            .outerjoin(Contact, ConversationThread.contact_id == Contact.id)
            .where(
                or_(
                    ConversationThread.direction == "inbound",
                    ConversationThread.event_type.in_(["reply_received", "inbound_email"]),
                    ConversationThread.intent.isnot(None)
                )
            )
        )
        inbound_threads = inbound_res.all()
        print(f"Total inbound/reply conversation threads: {len(inbound_threads)}")
        for ct, comp in inbound_threads[:10]:
            print(f" - [Company: {comp or 'Unknown'}] [Dir: {ct.direction}] [Intent: {ct.intent}] [Date: {ct.occurred_at}]")
            print(f"   Content: {(ct.content or '')[:120]}...\n")
            
        print("\n=== CURRENT A6 QUERY MATCH ===")
        cutoff = datetime.utcnow() - timedelta(days=90)  # check 90 days vs 30 days
        a6_res = await db.execute(
            select(ConversationThread.content, ConversationThread.contact_id, Contact.company)
            .join(Contact, ConversationThread.contact_id == Contact.id)
            .where(
                and_(
                    ConversationThread.content.isnot(None),
                    ConversationThread.content != ""
                )
            )
        )
        all_with_content = a6_res.all()
        print(f"Total threads with content joined with contact: {len(all_with_content)}")
        
        print("\n=== DEALS WITH OBJECTIONS / TRANSCRIPTS ===")
        deals_res = await db.execute(select(Deal))
        deals = deals_res.scalars().all()
        for d in deals:
            print(f" - Deal '{d.name}' (Stage: {d.stage}):")
            print(f"   Objections ({len(d.objections) if d.objections else 0}): {d.objections}")
            print(f"   Risk Flags ({len(d.risk_flags) if d.risk_flags else 0}): {d.risk_flags}")

if __name__ == "__main__":
    asyncio.run(check_threads_and_deals())

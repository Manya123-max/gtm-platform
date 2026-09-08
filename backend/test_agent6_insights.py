import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent
from app.models.models import ConversationThread, Contact
from sqlalchemy import select, delete
from datetime import datetime

async def test_insights():
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        
        # 1. Count original threads
        cutoff = datetime.utcnow() - datetime.fromtimestamp(0).utcnow() # all time
        orig_threads_res = await db.execute(
            select(ConversationThread).where(ConversationThread.intent.in_(["interested", "not_interested"]))
        )
        orig_threads = orig_threads_res.scalars().all()
        print(f"Original DB threads with interested/not_interested intent: {len(orig_threads)}")

        # 2. Check if we can temporarily isolate a zero-thread state in a transaction
        # Start a nested transaction / savepoint, delete all matching threads, verify return is [], rollback
        async with db.begin_nested():
            await db.execute(delete(ConversationThread).where(ConversationThread.intent.in_(["interested", "not_interested"])))
            print("Temporarily deleted all matching threads inside nested transaction.")
            res_empty = await agent._get_conversation_insights()
            print("Result with 0 threads:", res_empty)
            assert res_empty == [], "Expected empty list when there are no threads"
            print("✓ Zero-thread check passed inside rollback transaction.")

        # 3. Seed some test conversation threads
        print("\nSeeding test conversation threads...")
        contacts_res = await db.execute(select(Contact).limit(2))
        contacts = contacts_res.scalars().all()
        if len(contacts) < 2:
            print("ERROR: Need at least 2 contacts in DB to test.")
            return

        c1, c2 = contacts[0], contacts[1]
        
        t1 = ConversationThread(
            contact_id=c1.id,
            direction="inbound",
            event_type="reply_pricing",
            intent="interested",
            content="We are interested in trying this GTM platform, but we want to confirm the pricing. Is there a startup discount or free tier for small teams?",
            subject="TEST_INSIGHTS_SUBJECT",
            occurred_at=datetime.utcnow()
        )
        t2 = ConversationThread(
            contact_id=c2.id,
            direction="inbound",
            event_type="reply_not_interested",
            intent="not_interested",
            content="Thanks for reaching out. We are not interested right now because our current CRM migration project is blocked by security compliance issues in Europe.",
            subject="TEST_INSIGHTS_SUBJECT",
            occurred_at=datetime.utcnow()
        )
        db.add(t1)
        db.add(t2)
        await db.commit()
        print(f"Seeded threads for {c1.first_name} at {c1.company} and {c2.first_name} at {c2.company}.")

        # 4. Run insights extraction
        print("\nRunning _get_conversation_insights with seeded threads...")
        insights = await agent._get_conversation_insights()
        print(f"Extracted {len(insights)} insights:")
        for ins in insights:
            print(f"  - Company: {ins.get('company')} | Contact ID: {ins.get('contact_id')} | Source: {ins.get('source')}")
            print(f"    Text: {ins.get('text')}")
            
        # Clean up
        await db.execute(
            delete(ConversationThread).where(ConversationThread.subject == "TEST_INSIGHTS_SUBJECT")
        )
        await db.commit()
        print("\nCleaned up seeded test threads successfully.")

if __name__ == "__main__":
    asyncio.run(test_insights())

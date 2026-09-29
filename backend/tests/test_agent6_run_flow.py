import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent
from app.models.models import ConversationThread, Contact
from sqlalchemy import select, delete
from datetime import datetime

async def test_full_run_flow():
    print("Testing ContentAgent.run() integration...")
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        
        # Seed test conversation threads to verify A4 insights input
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
            content="We want to try the GTM platform but are worried about the pricing. Is there a startup discount or free tier for small teams?",
            subject="TEST_INSIGHTS_SUBJECT",
            occurred_at=datetime.utcnow()
        )
        t2 = ConversationThread(
            contact_id=c2.id,
            direction="inbound",
            event_type="reply_not_interested",
            intent="not_interested",
            content="We cannot proceed right now because our current CRM migration project is blocked by security compliance issues in Europe.",
            subject="TEST_INSIGHTS_SUBJECT",
            occurred_at=datetime.utcnow()
        )
        db.add(t1)
        db.add(t2)
        await db.commit()
        print(f"Seeded test threads for {c1.company} and {c2.company}.")

        # Execute ContentAgent.run()
        print("\nRunning ContentAgent.run()...")
        # Limit generated formats to save tokens/time by mocking save_content or limiting briefs
        result = await agent.run(icp_segments=["SaaS", "B2B Tech"])
        print("\nExecution Result:")
        print(f"  Briefs created: {result.get('briefs_created')}")
        print(f"  Content pieces generated: {result.get('content_pieces_generated')}")
        print(f"  Errors: {result.get('generation_errors')}")

        # Check topics in generated content
        print("\nQuerying recently generated content briefs from DB...")
        from app.models.models import GeneratedContent
        recent_res = await db.execute(
            select(GeneratedContent).order_by(GeneratedContent.created_at.desc()).limit(5)
        )
        recent_pieces = recent_res.scalars().all()
        print("Generated Content Titles & Topics:")
        for p in recent_pieces:
            print(f"  - [{p.content_format}] {p.title}")
            print(f"    Topic: {p.topic}")
            print(f"    Brief Details: Angle='{p.brief.get('angle')}'")

        # Clean up
        await db.execute(
            delete(ConversationThread).where(ConversationThread.subject == "TEST_INSIGHTS_SUBJECT")
        )
        await db.commit()
        print("\nCleaned up seeded test threads successfully.")

if __name__ == "__main__":
    asyncio.run(test_full_run_flow())

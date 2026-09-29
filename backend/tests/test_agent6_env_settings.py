import asyncio
import os
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent
from app.models.models import Contact, ConversationThread
from sqlalchemy import select, delete
from datetime import datetime
from app.core.config import settings

async def test_env_settings_flow():
    print("Testing dynamic settings configuration in ContentAgent...")
    
    # 1. Override settings dynamically in memory
    settings.A6_CONTENT_FORMATS = "linkedin_post,invalid_format_name"
    settings.A6_MAX_BRIEFS = 1
    
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        
        # Seed a test thread to have a direct insight
        contacts_res = await db.execute(select(Contact).limit(1))
        contact = contacts_res.scalars().first()
        if not contact:
            print("ERROR: No contact found in database.")
            return

        t1 = ConversationThread(
            contact_id=contact.id,
            direction="inbound",
            event_type="reply_pricing",
            intent="interested",
            content="Is there a startups discount?",
            subject="ENV_SETTINGS_TEST_SUBJECT",
            occurred_at=datetime.utcnow()
        )
        db.add(t1)
        await db.commit()
        
        print("\nExecuting ContentAgent.run() with limited formats and 1 brief max...")
        result = await agent.run(icp_segments=["SaaS"])
        
        print("\nExecution Result:")
        print(f"  Briefs created: {result.get('briefs_created')}")
        print(f"  Content pieces generated: {result.get('content_pieces_generated')}")
        print(f"  Content pieces skipped: {result.get('content_pieces_skipped_existing')}")
        
        total_attempted = result.get('content_pieces_generated') + result.get('content_pieces_skipped_existing')
        print(f"  Total generated/skipped: {total_attempted}")
        
        # Verifications
        assert result.get('briefs_created') >= 1, "Should generate at least 1 brief"
        assert total_attempted == 1, "Should attempt to generate exactly 1 content piece due to configuration limits!"
        
        # Clean up
        await db.execute(
            delete(ConversationThread).where(ConversationThread.subject == "ENV_SETTINGS_TEST_SUBJECT")
        )
        await db.commit()
        print("\n✓ SUCCESS: Dynamic configuration tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_env_settings_flow())

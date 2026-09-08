import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, and_, or_
from app.core.database import AsyncSessionLocal
from app.models.models import ConversationThread, Contact
from app.services.llm_service import LLMService
import json

async def test_conv_insights_relaxed():
    async with AsyncSessionLocal() as db:
        cutoff = datetime.utcnow() - timedelta(days=90)
        query = (
            select(
                ConversationThread.content,
                ConversationThread.contact_id,
                Contact.company
            )
            .join(Contact, ConversationThread.contact_id == Contact.id)
            .where(
                and_(
                    or_(
                        ConversationThread.intent.in_(["interested", "not_interested"]),
                        ConversationThread.direction == "inbound",
                        ConversationThread.event_type == "reply_received"
                    ),
                    ConversationThread.occurred_at >= cutoff,
                    ConversationThread.content.isnot(None),
                    ConversationThread.content != ""
                )
            )
            .order_by(ConversationThread.occurred_at.desc())
            .limit(20)
        )
        res = await db.execute(query)
        rows = res.all()
        print(f"Found {len(rows)} inbound/reply threads in last 90 days:")
        for r in rows[:5]:
            print(f" - Company: {r.company} | Text: {r.content[:70]}...")

if __name__ == "__main__":
    asyncio.run(test_conv_insights_relaxed())

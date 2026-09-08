import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent

async def test_a6_insights():
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        conv_insights = await agent._get_conversation_insights()
        deal_insights = await agent._get_deal_insights()
        print(f"Conversation Insights (A4): {len(conv_insights)}")
        for ci in conv_insights:
            print(" -", ci)
        print(f"\nDeal Insights from Transcripts/Deals (A5): {len(deal_insights)}")
        for di in deal_insights:
            print(" -", di)

if __name__ == "__main__":
    asyncio.run(test_a6_insights())

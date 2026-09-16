import asyncio
from app.agents.a6_content import ContentAgent
from app.core.database import AsyncSessionLocal

async def test_brief_gen():
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        
        conv_insights = await agent._get_conversation_insights()
        deal_insights = await agent._get_deal_insights()
        buying_signals = await agent._get_buying_signals()
        outreach_insights = await agent._get_outreach_insights()
        user_context = await agent._get_user_input_context()
        icp_segments = await agent._get_active_icp_segments()
        
        print("Inputs fetched:")
        print(f" - conv_insights: {len(conv_insights)}")
        print(f" - deal_insights: {len(deal_insights)}")
        print(f" - buying_signals: {len(buying_signals)}")
        print(f" - outreach_insights: {len(outreach_insights)}")
        print(f" - icp_segments: {len(icp_segments)}")
        
        briefs = await agent._generate_content_briefs(
            signals=[],
            icp_segments=icp_segments,
            conv_insights=conv_insights,
            deal_insights=deal_insights,
            buying_signals=buying_signals,
            outreach_insights=outreach_insights,
            user_context=user_context,
            existing_topics=[]
        )
        print(f"\nBriefs generated ({len(briefs)}):")
        for b in briefs:
            print(" * Topic:", b.get("topic"))
            print("   ICP:", b.get("icp_segment"))
            print("   Angle:", b.get("angle"))

if __name__ == "__main__":
    asyncio.run(test_brief_gen())

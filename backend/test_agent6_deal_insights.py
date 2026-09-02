import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent
from app.models.models import Deal
from sqlalchemy import select

async def test_deal_insights():
    print("Testing _get_deal_insights from ContentAgent...")
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        
        # 1. Fetch deal directly to compare
        deal_res = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
        deal = deal_res.scalars().first()
        
        if not deal:
            print("ERROR: No Galvin Technologies deal found in database.")
            return
            
        print(f"Matched Deal: {deal.name} [ID: {deal.id}]")
        print(f"  Objections count: {len(deal.objections or [])}")
        print(f"  Risk Flags count: {len(deal.risk_flags or [])}")

        # 2. Run _get_deal_insights
        insights = await agent._get_deal_insights()
        print(f"\nExtracted {len(insights)} total deal-related insights:")
        for ins in insights:
            print(f"  - Category: {ins.get('category')} | Company: {ins.get('company')} | Deal ID: {ins.get('deal_id')} | Source: {ins.get('source')}")
            print(f"    Text: {ins.get('text')}")

        # Verifications
        if insights:
            assert all(ins["source"] == "A5" for ins in insights), "All deal insights must have source='A5'"
            assert all("text" in ins for ins in insights), "All deal insights must have 'text'"
            assert all("deal_id" in ins for ins in insights), "All deal insights must have 'deal_id'"
            print("\n✓ SUCCESS: All deal insights checks passed successfully!")
        else:
            print("\n✕ NOTE: No insights found (if deal objections/risk flags are empty, this is expected).")

if __name__ == "__main__":
    asyncio.run(test_deal_insights())

import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a5_deal import DealAgent
from sqlalchemy import select
from app.models.models import Deal

async def test_transcript():
    print("Simulating a Fireflies call transcript webhook for Galvin Technologies...")
    payload = {
        "transcriptId": "trans-test-12345",
        "title": "Galvin Technologies — Demo and Pricing Review Call",
        "attendees": [
            {"email": "shreelakshmipp2003@gmail.com", "name": "Lauren Bell"}
        ],
        "transcript": """
Lauren Bell: We are excited about the CRM and Enterprise RAG migration. However, we have a few concerns.
Sales Rep: What concerns do you have, Lauren?
Lauren Bell: First, we are worried about the pricing. $60k is slightly above our budget for Q3. We need to see if we can get a discount or split the payment.
Sales Rep: I understand. We can discuss flexible payment plans. What else?
Lauren Bell: Secondly, our security team is concerned about self-hosting or data residency rules in Europe. We must ensure the vector database compliance.
Sales Rep: We support isolated European tenant deployment. That will be compliant.
Lauren Bell: Great. And can you deliver this CRM migration in 4 weeks? The timeline is very tight.
        """
    }

    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)
        
        # 1. Check current deal state
        deal_before = (await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))).scalars().first()
        if not deal_before:
            print("ERROR: No Galvin Technologies deal found in database to match transcript to.")
            return

        print(f"Matched Deal Before: {deal_before.name} [ID: {deal_before.id}]")
        print(f"Objections before: {deal_before.objections}")

        # 2. Process transcript
        print("\nProcessing transcript with Agent 5...")
        result = await agent.process_transcript(payload)
        print("Transcript processed successfully!")
        
        # 3. Reload deal and verify objections
        await db.refresh(deal_before)
        print("\nMatched Deal After:")
        print(f"  Health Score: {deal_before.deal_health_score}")
        print(f"  Win Probability: {deal_before.win_probability}")
        print(f"  Objections: {deal_before.objections}")
        
        if deal_before.objections:
            print("\n✓ SUCCESS: Objections were successfully persisted to the Deal row!")
            for obj in deal_before.objections:
                print(f"   - Category: {obj.get('category')} | Text: {obj.get('text')}")
        else:
            print("\n✕ FAILURE: Objections list is empty or None on the Deal row.")

if __name__ == "__main__":
    asyncio.run(test_transcript())

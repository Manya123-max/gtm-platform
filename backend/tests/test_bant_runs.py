import asyncio
import app.services.llm_service
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, Contact
from app.agents.a5_deal import DealAgent
from sqlalchemy import select

# Spy on LLM Service
original_complete = app.services.llm_service.LLMService.complete

async def spy_complete(self, system, user, *args, **kwargs):
    print("\n[LLM CALL]")
    print(f"System Prompt (truncated):\n{system[:300]}...")
    print(f"User Prompt (truncated):\n{user[:300]}...")
    res = await original_complete(self, system, user, *args, **kwargs)
    print(f"Extracted JSON:\n{res}")
    return res

app.services.llm_service.LLMService.complete = spy_complete

payload = {
    "transcriptId": "trans-test-56789",
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

async def run_test():
    for run in range(1, 4):
        print(f"\n=================== RUN {run} ===================")
        async with AsyncSessionLocal() as db:
            # 1. Reset BANT fields on Galvin deal before run
            deal_res = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
            deal = deal_res.scalars().first()
            if not deal:
                print("ERROR: Galvin deal not found!")
                return
                
            deal.budget_confirmed = False
            deal.authority_confirmed = False
            deal.need_confirmed = False
            deal.timeline_confirmed = False
            await db.commit()
            await db.refresh(deal)
            
            print(f"Deal status reset: budget={deal.budget_confirmed}, timeline={deal.timeline_confirmed}")
            
            # 2. Run process_transcript
            agent = DealAgent(db)
            await agent.process_transcript(payload)
            
            # 3. Reload and show final values
            await db.refresh(deal)
            print(f"\n=================== RUN {run} FINAL RESULT ===================")
            print(f"Final budget_confirmed: {deal.budget_confirmed}")
            print(f"Final timeline_confirmed: {deal.timeline_confirmed}")
            print("================================================\n")

if __name__ == "__main__":
    asyncio.run(run_test())

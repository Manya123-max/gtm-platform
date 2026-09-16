import asyncio
import json
from app.core.database import AsyncSessionLocal
from app.agents.a5_deal import DealAgent
from app.models.models import Deal
from sqlalchemy import select

async def main():
    print("=" * 65)
    print("Testing Agent 5: Ingesting Fireflies Transcript for Acme Corp")
    print("=" * 65)

    payload = {
        "transcriptId": "ff-acme-998811",
        "title": "Acme Corp — Enterprise AI Deployment Demo & Security Review",
        "attendees": [
            {"email": "david.chen@acmecorp.com", "name": "David Chen"}
        ],
        "transcript": """
Sales Rep: Thanks for joining today's demo, David. How did the multi-agent orchestration architecture look to your team?
David Chen: The architecture is very impressive. Our engineering and revenue leadership agree this fits our exact requirements.
Sales Rep: Excellent. To confirm budget alignment, our enterprise package is $75,000 annually. Is that aligned with your approved budget?
David Chen: Yes, our executive committee approved $80,000 for this initiative, so $75k is well within budget.
Sales Rep: And who will be the final executive signing off on the agreement?
David Chen: Sarah Jenkins, our Chief Technology Officer (CTO), has the final purchasing authority. She asked me to lead this technical evaluation.
Sales Rep: Great. What is your target deployment timeline?
David Chen: We need this live before the end of Q3 — roughly 5 weeks from now.
Sales Rep: We can commit to a 3-week deployment timeline. Do you have any technical or compliance concerns?
David Chen: Our only question is around HIPAA and SOC2 compliance, but your security documentation looks solid. Please prepare the master services agreement (MSA) for Sarah's review.
"""
    }

    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        # 1. Check deal before
        deal_before = (await db.execute(select(Deal).where(Deal.name.ilike("%acme%")))).scalars().first()
        print(f"\n[1] Matched Deal in DB: '{deal_before.name}' (Stage: {deal_before.stage}, Amount: ${deal_before.amount:,.0f})")

        # 2. Process transcript with Agent 5
        print("\n[2] Processing transcript with Claude Sonnet / Agent 5...")
        result = await agent.process_transcript(payload)

        # 3. Reload deal and display updated state
        await db.refresh(deal_before)
        print("\n[3] Deal State After Agent 5 Transcript Extraction:")
        print(f"  • Buying Intent: {deal_before.buying_intent}")
        print(f"  • Health Score: {deal_before.deal_health_score}")
        print(f"  • Win Probability: {deal_before.win_probability}%")
        print(f"  • Budget Confirmed: {deal_before.budget_confirmed}")
        print(f"  • Authority Confirmed: {deal_before.authority_confirmed}")
        print(f"  • Need Confirmed: {deal_before.need_confirmed}")
        print(f"  • Timeline Confirmed: {deal_before.timeline_confirmed}")
        print(f"  • Stage Confidence: {deal_before.stage_confidence}")
        print(f"  • Next Best Action: {deal_before.next_best_action}")
        print(f"  • Objections: {deal_before.objections}")

        print("\n" + "=" * 65)
        print("✓ Acme Corp Deal intelligence updated and synced!")
        print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())

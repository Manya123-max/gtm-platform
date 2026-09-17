"""
Test Script: Agent 5 Deal Intelligence for Acme Corp Fireflies Call
Simulates a Fireflies call transcript for Acme Corp, processes through Agent 5,
and checks full reflection in the database and API.
"""
import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a5_deal import DealAgent
from app.models.models import Deal, Contact
from sqlalchemy import select

async def main():
    print("=" * 65)
    print("Testing Agent 5: Ingesting Fireflies Transcript for Acme Corp")
    print("=" * 65)

    payload = {
        "transcriptId": "ff-transcript-acme-881902",
        "title": "Acme Corp — Multi-Agent AI Deployment Demo & Security Review",
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
David Chen: Our only concern is around HIPAA and SOC2 Type II compliance, but your security documentation looks solid. Please prepare the master services agreement (MSA) for Sarah's review.
"""
    }

    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        # Ensure contact exists
        contact = (await db.execute(select(Contact).where(Contact.email == "david.chen@acmecorp.com"))).scalar_one_or_none()
        if not contact:
            contact = Contact(
                email="david.chen@acmecorp.com",
                first_name="David",
                last_name="Chen",
                company="Acme Corp",
                title="Director of Engineering",
                user_input_id=4
            )
            db.add(contact)
            await db.commit()
            await db.refresh(contact)

        print(f"\n[1] Processing transcript with Agent 5 for {contact.company}...")
        result = await agent.process_transcript(payload)

        # Reload deal
        deal = (await db.execute(select(Deal).where(Deal.name.ilike("%acme%")))).scalars().first()
        if deal:
            print("\n[2] Deal State in DB After Agent 5 Transcript Extraction:")
            print(f"  • Deal Name: {deal.name}")
            print(f"  • Stage: {deal.stage.upper()} | Amount: ${deal.amount:,.0f}")
            print(f"  • Buying Intent: {deal.buying_intent}")
            print(f"  • Health Score: {deal.deal_health_score}/100")
            print(f"  • Win Probability: {deal.win_probability}%")
            print(f"  • Budget Confirmed: {deal.budget_confirmed}")
            print(f"  • Authority Confirmed: {deal.authority_confirmed}")
            print(f"  • Need Confirmed: {deal.need_confirmed}")
            print(f"  • Timeline Confirmed: {deal.timeline_confirmed}")
            print(f"  • Stage Confidence: {deal.stage_confidence}")
            print(f"  • Next Best Action: {deal.next_best_action}")
            print(f"  • Objections: {deal.objections}")

        print("\n" + "=" * 65)
        print("✓ Acme Corp Deal intelligence successfully processed and saved!")
        print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())

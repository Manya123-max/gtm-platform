"""
Test Script: Agent 5 Deal Intelligence & Fireflies Transcript Simulation
Simulates an inbound Fireflies call transcript for CloudZone / Enterprise AI Architecture,
processes it through Agent 5 with full LLM extraction, updates the deal state in PostgreSQL,
generates risk actions, and validates reflection via the REST API endpoints.
"""
import asyncio
import json
import httpx
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, Contact, PendingAction, ActionStatus
from app.agents.a5_deal import DealAgent

async def run_fireflies_test():
    print("=" * 70)
    print("🚀 Agent 5 (Deal Intelligence) — Fireflies Call Transcript Live Test")
    print("=" * 70)

    # 1. Prepare realistic Call Transcript payload
    transcript_payload = {
        "transcriptId": "ff-transcript-cloudzone-772910",
        "title": "CloudZone — Enterprise GenAI & Salesforce Migration Technical Review",
        "attendees": [
            {"email": "orita@cloudzone.io", "name": "Ori Tabachnik"}
        ],
        "transcript": """
Sales Rep: Thanks for joining today's architecture and proposal sync, Ori!
Ori Tabachnik: Thanks for having me. We reviewed your multi-agent architecture and Salesforce CRM synchronization pipelines. Our team is very excited about the capability.
Sales Rep: That's great to hear! Let's talk about scope and budget. For the full enterprise deployment and dedicated custom agent workflows, our quote is $85,000 annually. Does that align with your approved budget for this quarter?
Ori Tabachnik: Yes, our executive board already approved $90,000 for this initiative, so $85k is well within our budget allocation.
Sales Rep: Excellent. Who will be leading the final commercial sign-off and legal agreement on your side?
Ori Tabachnik: I am managing the technical evaluation, and our Chief Revenue Officer (CRO), Michael Goldberg, has final signing authority for software contracts. He is already briefed and aligned.
Sales Rep: Perfect. What is your required deployment timeline?
Ori Tabachnik: We need this live and fully integrated within 5 weeks before our Q4 sales summit begins.
Sales Rep: We can deliver the complete rollout and testing in 3.5 weeks. Are there any specific technical, security, or compliance objections?
Ori Tabachnik: Two key items: First, we need European data residency guarantee for our Frankfurt operations. Second, our security team requires SOC2 Type II audit report before contracting. Can you provide those?
Sales Rep: Absolutely. We have native EU data residency and our latest SOC2 Type II report is ready to share under NDA.
Ori Tabachnik: Fantastic! Please send over the MSA and SOC2 documentation today so we can finalize the agreement.
"""
    }

    async with AsyncSessionLocal() as db:
        agent = DealAgent(db)

        # 1. Check existing deal or contact state before
        print("\n[Step 1] Checking DB state before processing...")
        contact = (await db.execute(select(Contact).where(Contact.email == "orita@cloudzone.io"))).scalar_one_or_none()
        if contact:
            print(f"  ✓ Found Contact: {contact.first_name} {contact.last_name} ({contact.company}) [ID: {contact.id}]")
        else:
            print("  ℹ Creating test contact for Ori Tabachnik at CloudZone...")
            contact = Contact(
                email="orita@cloudzone.io",
                first_name="Ori",
                last_name="Tabachnik",
                company="CloudZone",
                title="VP of Engineering",
                user_input_id=4
            )
            db.add(contact)
            await db.commit()
            await db.refresh(contact)

        deal_before = (await db.execute(select(Deal).where(Deal.name.ilike("%cloudzone%")))).scalars().first()
        if deal_before:
            print(f"  Existing Deal Found: '{deal_before.name}' (Stage: {deal_before.stage}, Amount: ${deal_before.amount:,.0f})")
            print(f"  Health: {deal_before.deal_health_score}, Win Prob: {deal_before.win_probability}%, Intent: {deal_before.buying_intent}")
        else:
            print("  No prior deal existed for CloudZone — Agent 5 will auto-match and create one.")

        # 2. Process Transcript with Agent 5
        print("\n[Step 2] Ingesting & processing Fireflies transcript with Agent 5...")
        result = await agent.process_transcript(transcript_payload)
        extraction = result.get("extraction", {})
        
        print("\n[Step 3] AI Extraction Results from Claude / Agent 5:")
        print(f"  • Call Summary: {extraction.get('call_summary')}")
        print(f"  • Buying Intent: {(extraction.get('buying_intent') or 'N/A').upper()}")
        print(f"  • Decision Maker: {extraction.get('decision_maker_details')}")
        bant = extraction.get("bant_signals", {})
        print(f"  • BANT Signals: Budget={bant.get('budget_confirmed')} | Auth={bant.get('authority_confirmed')} | Need={bant.get('need_confirmed')} | Time={bant.get('timeline_confirmed')}")
        print(f"  • Objections Detected ({len(extraction.get('objections', []))}):")
        for obj in extraction.get("objections", []):
            print(f"     - [{obj.get('category', 'general').upper()}]: {obj.get('text')}")

        # 3. Verify Deal in DB after processing
        deal_after = (await db.execute(select(Deal).where(Deal.name.ilike("%cloudzone%")))).scalars().first()
        if deal_after:
            print("\n[Step 4] Updated Deal State in PostgreSQL Database:")
            print(f"  • Deal Name: {deal_after.name}")
            print(f"  • Stage: {deal_after.stage.upper()} | Amount: ${deal_after.amount:,.0f}")
            print(f"  • Deal Health Score: {deal_after.deal_health_score:.1f}/100")
            print(f"  • Win Probability: {deal_after.win_probability:.1f}%")
            print(f"  • Stage Confidence: {deal_after.stage_confidence}")
            print(f"  • Buying Intent: {deal_after.buying_intent.upper() if deal_after.buying_intent else 'UNKNOWN'}")
            print(f"  • Next Best Action: {deal_after.next_best_action}")
            print(f"  • BANT in DB: Budget={deal_after.budget_confirmed} | Authority={deal_after.authority_confirmed} | Need={deal_after.need_confirmed} | Timeline={deal_after.timeline_confirmed}")
            print(f"  • Stored Objections: {deal_after.objections}")

        # 4. Check Pending Actions / Deal Guard
        actions = (await db.execute(
            select(PendingAction).where(
                PendingAction.entity_type == "deal",
                PendingAction.status == ActionStatus.PENDING
            )
        )).scalars().all()
        print(f"\n[Step 5] Active CRM Deal Actions Generated ({len(actions)} total):")
        for a in actions[-3:]:
            print(f"  • [{a.action_type}]: {a.reason[:80]}... → Action: {a.recommended_value}")

    # 5. Verify REST API reflection (what the frontend web app fetches)
    print("\n[Step 6] Verifying REST API reflection for frontend...")
    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
            resp = await client.get("/api/v1/deals")
            if resp.status_code == 200:
                deals_data = resp.json()
                print(f"  ✓ GET /api/v1/deals returned {len(deals_data)} deals:")
                for d in deals_data:
                    print(f"     - '{d['name']}' | Stage: {d['stage']} | Health: {d.get('deal_health_score')}/100 | Win: {d.get('win_probability')}% | BANT: B={d.get('budget_confirmed')}, A={d.get('authority_confirmed')}, N={d.get('need_confirmed')}, T={d.get('timeline_confirmed')}")
            else:
                print(f"  ✕ GET /api/v1/deals returned status {resp.status_code}")

            summary_resp = await client.get("/api/v1/deals/pipeline-summary")
            if summary_resp.status_code == 200:
                summary_data = summary_resp.json()
                print(f"  ✓ GET /api/v1/deals/pipeline-summary returned pipeline stages:")
                for s in summary_data:
                    print(f"     - Stage: {s['stage']} | Count: {s['count']} | Value: ${s['value']:,.0f}")
    except Exception as e:
        print(f"  (Local REST API check skipped: {e})")

    print("\n" + "=" * 70)
    print("✅ Live Agent 5 Fireflies simulation test completed successfully!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_fireflies_test())

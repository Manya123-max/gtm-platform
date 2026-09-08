import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import SignalEvent, Contact, Deal, PendingAction, ActionStatus, OutreachDraft, OutreachLog
from app.agents.a2_signal import SignalAgent
from app.agents.a5_deal import DealAgent
from sqlalchemy import select, delete, and_, update

async def run_verification():
    async with AsyncSessionLocal() as db:
        print("=== STEP 1: Deleting duplicate Canton Strategic Holdings SignalEvent rows ===")
        # Find Lauren Bell's contact
        contact_res = await db.execute(select(Contact).where(Contact.email == "shreelakshmipp2003@gmail.com"))
        contact = contact_res.scalars().first()
        if not contact:
            print("ERROR: Lauren Bell contact not found!")
            return
            
        print(f"Found Contact: {contact.first_name} {contact.last_name} (ID: {contact.id})")
        
        # Query Canton signals before deletion
        canton_res = await db.execute(
            select(SignalEvent).where(
                and_(
                    SignalEvent.contact_id == contact.id,
                    SignalEvent.signal_source == "currents"
                )
            )
        )
        canton_signals = canton_res.scalars().all()
        canton_ids = [s.id for s in canton_signals]
        print(f"Canton signals before deletion: {len(canton_signals)}")
        for s in canton_signals:
            print(f"  - ID: {s.id} | Headline: {s.raw_data.get('headline')}")
            
        if canton_ids:
            # 1. Update referencing OutreachDrafts
            print("Nullifying signal_id references in outreach_drafts...")
            await db.execute(
                update(OutreachDraft)
                .where(OutreachDraft.signal_id.in_(canton_ids))
                .values(signal_id=None)
            )
            
            # 2. Update referencing OutreachLogs
            print("Nullifying signal_id references in outreach_log...")
            await db.execute(
                update(OutreachLog)
                .where(OutreachLog.signal_id.in_(canton_ids))
                .values(signal_id=None)
            )
            
            # 3. Delete them
            print("Deleting SignalEvent rows...")
            await db.execute(
                delete(SignalEvent).where(SignalEvent.id.in_(canton_ids))
            )
            await db.commit()
            print("Canton signals deleted successfully.")
        
        # Verify deletion
        verify_canton_res = await db.execute(
            select(SignalEvent).where(
                and_(
                    SignalEvent.contact_id == contact.id,
                    SignalEvent.signal_source == "currents"
                )
            )
        )
        print(f"Canton signals after deletion: {len(verify_canton_res.scalars().all())}")

        print("\n=== STEP 2: Running live check_currents with relevance filter ===")
        agent_a2 = SignalAgent(db)
        weights = await agent_a2._load_registry()
        # Call _check_currents directly
        currents_signals = await agent_a2._check_currents(contact, weights)
        print(f"Signals returned by _check_currents for Galvin Technologies: {len(currents_signals)}")
        for s in currents_signals:
            print(f"  - Type: {s.get('signal_type')} | Headline: {s.get('raw_data', {}).get('headline')}")

        print("\n=== STEP 3: Verifying Agent 5 transcript processing & timeline_confirmed ===")
        agent_a5 = DealAgent(db)
        
        # Get Galvin Deal before
        deal_res = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
        deal = deal_res.scalars().first()
        if not deal:
            print("ERROR: Galvin Technologies deal not found!")
            return
            
        print(f"Galvin Deal Before: {deal.name}")
        print(f"  timeline_confirmed: {deal.timeline_confirmed}")
        print(f"  risk_flags: {deal.risk_flags}")
        
        # Get pending actions for Galvin before
        pa_res = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.entity_id == deal.id,
                    PendingAction.action_type == "missing_timeline"
                )
            )
        )
        pas_before = pa_res.scalars().all()
        print("Pending actions (missing_timeline) before:")
        for pa in pas_before:
            print(f"  - ID: {pa.id} | Status: {pa.status} | Reason: {pa.reason[:100]}...")

        # Simulating the Fireflies call transcript webhook for Galvin Technologies
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
        
        print("\nProcessing transcript using process_transcript()...")
        await agent_a5.process_transcript(payload)
        
        # Reload Deal
        await db.refresh(deal)
        print(f"Galvin Deal After processing transcript:")
        print(f"  timeline_confirmed: {deal.timeline_confirmed} (Should be False because 'timeline is very tight' is not a confirmation)")
        print(f"  risk_flags: {deal.risk_flags}")
        
        # Query PendingAction again
        pa_res_after = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.entity_id == deal.id,
                    PendingAction.action_type == "missing_timeline"
                )
            )
        )
        pas_after = pa_res_after.scalars().all()
        print("Pending actions (missing_timeline) after:")
        for pa in pas_after:
            print(f"  - ID: {pa.id} | Status: {pa.status} | Reason: {pa.reason[:100]}...")

        print("\n=== STEP 4: Verifying PendingAction expiration when risk is resolved ===")
        # Manually force timeline_confirmed = True
        print("Manually setting timeline_confirmed = True...")
        deal.timeline_confirmed = True
        await db.commit()
        
        # Trigger daily scan/reconciliation
        print("Re-running Agent 5 risk patterns and reconciliation...")
        risk_flags = await agent_a5._detect_risk_patterns(deal)
        await agent_a5._reconcile_risk_state(deal, risk_flags)
        
        # Reload Deal and query PendingAction
        await db.refresh(deal)
        pa_res_final = await db.execute(
            select(PendingAction).where(
                and_(
                    PendingAction.entity_id == deal.id,
                    PendingAction.action_type == "missing_timeline"
                )
            )
        )
        pas_final = pa_res_final.scalars().all()
        print("Pending actions (missing_timeline) after manually confirming timeline:")
        for pa in pas_final:
            print(f"  - ID: {pa.id} | Status: {pa.status} (Should be EXPIRED)")

if __name__ == "__main__":
    asyncio.run(run_verification())

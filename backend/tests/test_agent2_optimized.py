import asyncio
import time
from app.core.database import AsyncSessionLocal
from app.models.models import Contact
from app.agents.a2_signal import SignalAgent
from sqlalchemy import select

async def run_optimization_test():
    async with AsyncSessionLocal() as db:
        agent = SignalAgent(db)
        
        # Load up to 5 contacts to verify loop behavior
        contacts_res = await db.execute(
            select(Contact).where(Contact.do_not_contact.is_(False)).limit(5)
        )
        contacts = list(contacts_res.scalars().all())
        print(f"Loaded {len(contacts)} contacts for verification.")
        
        weights = await agent._load_registry()
        
        for idx, contact in enumerate(contacts, 1):
            print(f"\n--- Scanning Contact {idx}: {contact.first_name} {contact.last_name} ({contact.company}) ---")
            print(f"PredictLeads disabled state before scan: {agent._predictleads_disabled}")
            
            start = time.time()
            signals = await agent._detect_signals(contact, weights)
            duration = time.time() - start
            
            print(f"Scan finished in {duration:.2f}s (returned {len(signals)} signals)")
            print(f"PredictLeads disabled state after scan: {agent._predictleads_disabled}")

if __name__ == "__main__":
    asyncio.run(run_optimization_test())

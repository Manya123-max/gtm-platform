import asyncio
import time
from app.core.database import AsyncSessionLocal
from app.models.models import Contact
from app.agents.a2_signal import SignalAgent
from sqlalchemy import select

async def time_calls():
    async with AsyncSessionLocal() as db:
        agent = SignalAgent(db)
        
        # Get Lauren Bell contact
        contact_res = await db.execute(select(Contact).where(Contact.email == "shreelakshmipp2003@gmail.com"))
        contact = contact_res.scalars().first()
        if not contact:
            print("Contact not found!")
            return
            
        print(f"Testing speed on contact: {contact.first_name} {contact.last_name} at {contact.company}")
        weights = await agent._load_registry()
        
        # We will time each checker method individually
        checkers = {
            "adzuna": agent._check_job_postings,
            "predictleads": agent._check_predictleads,
            "currents": agent._check_currents,
            "newsapi": agent._check_news,
            "apify": agent._check_apify
        }
        
        for name, fn in checkers.items():
            start = time.time()
            print(f"\n--- Testing {name} ---")
            try:
                # set a 20s timeout on each task individually to avoid hanging the script
                res = await asyncio.wait_for(fn(contact, weights), timeout=20.0)
                duration = time.time() - start
                print(f"{name} finished in {duration:.2f}s (returned {len(res)} signals)")
            except asyncio.TimeoutError:
                print(f"ERROR: {name} TIMED OUT after 20 seconds!")
            except Exception as e:
                print(f"ERROR: {name} raised exception: {str(e)}")

if __name__ == "__main__":
    asyncio.run(time_calls())

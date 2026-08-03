import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def run_agent():
    from app.core.database import AsyncSessionLocal
    from app.agents.a3_outreach import OutreachAgent
    
    db = AsyncSessionLocal()
    try:
        agent = OutreachAgent(db)
        res = await agent.run()
        print("AGENT RUN RESULTS:")
        print(res)
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(run_agent())

import asyncio
import json
from app.core.database import AsyncSessionLocal
from app.agents.a1_prospect import ProspectAgent

async def main():
    async with AsyncSessionLocal() as db:
        a1 = ProspectAgent(db)
        res = await a1.run_pipeline({
            "target_industries": ["Software"],
            "company_size": "11-50"
        })
        print("Pipeline Status:", res.get("status"))
        print("Agent:", res.get("agent"))
        print("Total Fetched:", res.get("total_fetched"))
        print("Summary:", res.get("summary"))

if __name__ == "__main__":
    asyncio.run(main())

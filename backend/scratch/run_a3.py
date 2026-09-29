import asyncio
import structlog
from app.core.database import AsyncSessionLocal
from app.agents.a3_outreach import OutreachAgent

logger = structlog.get_logger()

async def main():
    async with AsyncSessionLocal() as db:
        agent = OutreachAgent(db)
        res = await agent.run()
        print("A3 Execution Result:", res)

if __name__ == "__main__":
    asyncio.run(main())

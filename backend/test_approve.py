import asyncio
import structlog
from app.core.database import AsyncSessionLocal
from app.agents.a3_outreach import DraftManager

logger = structlog.get_logger()

async def main():
    async with AsyncSessionLocal() as db:
        manager = DraftManager(db)
        res = await manager.approve_draft("5ab4744d-8df1-499f-a242-c0dea660374f")
        await db.commit()
        print("Draft approve result:", res)

if __name__ == "__main__":
    asyncio.run(main())

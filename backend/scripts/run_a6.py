import asyncio
from app.core.database import AsyncSessionLocal
from app.agents.a6_content import ContentAgent

async def main():
    async with AsyncSessionLocal() as db:
        agent = ContentAgent(db)
        result = await agent.run()
        print(result)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from sqlalchemy import select, desc
from app.core.database import AsyncSessionLocal
from app.models.models import GeneratedContent

async def inspect_latest_content():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(GeneratedContent)
            .order_by(desc(GeneratedContent.created_at))
            .limit(15)
        )
        pieces = res.scalars().all()
        print(f"=== LATEST 15 GENERATED PIECES (Total: {len(pieces)}) ===")
        for p in pieces:
            print(f"\n[Format: {p.content_format}] [ICP: {p.icp_segment}]")
            print(f"Title: {p.title}")
            print(f"Topic: {p.topic}")
            print(f"Content Preview (first 180 chars):\n{p.content[:180]}...\n{'-'*60}")

if __name__ == "__main__":
    asyncio.run(inspect_latest_content())

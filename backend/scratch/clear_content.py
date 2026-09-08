import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal
from app.models.models import GeneratedContent
from sqlalchemy import delete

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(GeneratedContent))
        await db.commit()
    print("DELETED ALL GENERATED CONTENT")

if __name__ == "__main__":
    asyncio.run(main())

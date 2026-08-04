import asyncio
from app.core.database import engine
from sqlalchemy import text

async def main():
    async with engine.connect() as conn:
        res = await conn.execute(text("select * from user_inputs limit 0"))
        print("Columns in DB:", res.keys())

if __name__ == "__main__":
    asyncio.run(main())

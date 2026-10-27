import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def seed_profile():
    async with AsyncSessionLocal() as db:
        # Check if resettest user exists and update
        await db.execute(text("""
            UPDATE users SET
                name = 'P P Shree Lakshmi',
                email = 'shree.lakshmi@forcecloudlabs.com',
                role = 'ADMIN',
                cal_com_username = 'shree-lakshmi-iaqqsz',
                cal_com_event_slug = '15min',
                cal_com_booking_url = 'https://cal.com/shree-lakshmi-iaqqsz/30min',
                is_active = true
            WHERE id = 'eb27217a-0358-4431-afb8-aa2d06651603' OR email = 'resettest@gtmexample.com'
        """))
        await db.commit()
        print("Updated user to P P Shree Lakshmi (shree.lakshmi@forcecloudlabs.com) with ADMIN role and Cal.com mapping!")

if __name__ == "__main__":
    asyncio.run(seed_profile())

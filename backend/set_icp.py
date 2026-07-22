import asyncio
import json
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

config = {
    "titles": [
        "CTO", "VP Engineering", "Head of Engineering",
        "Director of Engineering", "VP Product",
        "Chief Technology Officer", "Head of Technology"
    ],
    "employee_ranges": ["51,200", "201,500", "501,1000"],
    "geographies": ["India", "United States", "Singapore"],
    "seniorities": ["vp", "director", "c_suite"],
    "limit": 25
}

async def update():
    async with AsyncSessionLocal() as db:
        check = await db.execute(
            text("SELECT agent_id FROM agent_schedules WHERE agent_id = 'A1'")
        )
        exists = check.fetchone()

        if exists:
            await db.execute(
                text("UPDATE agent_schedules SET config = :cfg WHERE agent_id = 'A1'"),
                {"cfg": json.dumps(config)}
            )
            print("Updated existing A1 schedule config")
        else:
            await db.execute(
                text("""
                    INSERT INTO agent_schedules
                        (agent_id, schedule_cron, config, is_active)
                    VALUES
                        ('A1', '0 8 * * 1', :cfg, true)
                """),
                {"cfg": json.dumps(config)}
            )
            print("Inserted new A1 schedule config")

        await db.commit()

        result = await db.execute(
            text("SELECT agent_id, config FROM agent_schedules WHERE agent_id = 'A1'")
        )
        row = result.fetchone()
        print("Saved config:", row[1])

asyncio.run(update())

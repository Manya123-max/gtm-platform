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
                text("UPDATE agent_schedules SET cron = '0 8 * * 1', enabled = true WHERE agent_id = 'A1'")
            )
            print("Updated existing A1 schedule")
        else:
            await db.execute(
                text("""
                    INSERT INTO agent_schedules
                        (agent_id, cron, enabled, task_name)
                    VALUES
                        ('A1', '0 8 * * 1', true, 'app.workers.scheduler_tasks.run_prospect_agent')
                """)
            )
            print("Inserted new A1 schedule")

        await db.commit()

        result = await db.execute(
            text("SELECT agent_id, cron, enabled FROM agent_schedules WHERE agent_id = 'A1'")
        )
        row = result.fetchone()
        print("Saved schedule:", row[0], "cron:", row[1], "enabled:", row[2])

asyncio.run(update())

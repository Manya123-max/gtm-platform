"""
Run this once to:
1. Create user_inputs table if missing
2. Show what's currently saved in it
3. Show what A1 will receive as ICP config on next run
"""
import asyncio
import json
from sqlalchemy import text
from app.core.database import AsyncSessionLocal, engine
from app.models.models import Base

async def main():
    # Step 1 — ensure all tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ All tables created / verified")

    async with AsyncSessionLocal() as db:

        # Step 2 — show user_inputs rows
        try:
            r = await db.execute(text(
                "SELECT id, company_name, company_size, location, job_title, keywords "
                "FROM user_inputs ORDER BY id DESC LIMIT 5"
            ))
            rows = r.fetchall()
            print(f"\n=== user_inputs table ({len(rows)} rows) ===")
            for row in rows:
                print(f"  id={row[0]} | company={row[1]} | size={row[2]} | "
                      f"location={row[3]} | title={row[4]} | keywords={row[5][:40]}")
        except Exception as e:
            print(f"  ERROR reading user_inputs: {e}")
            return

        if not rows:
            print("  ⚠ Table exists but is EMPTY — fill the intake form first")
            return

        # Step 3 — simulate what A1 will use
        latest = rows[0]
        titles = [t.strip() for t in latest[4].split(",") if t.strip()]
        geographies = [g.strip() for g in latest[3].split(",") if g.strip()]
        size = latest[2].replace("-", ",").strip()
        employee_ranges = [size] if size else ["11,200"]

        cfg = {
            "titles": titles,
            "geographies": geographies,
            "employee_ranges": employee_ranges,
            "limit": 10,
        }
        print(f"\n=== A1 will use this ICP config ===")
        print(json.dumps(cfg, indent=2))

        # Step 4 — score a sample contact to see what threshold gives
        from app.services.scoring_service import WinPatternScorer
        scorer = WinPatternScorer()
        sample = {
            "title": titles[0] if titles else "CTO",
            "company_size": size,
            "employee_count": 150,
            "industry": "saas",
            "funding_stage": "series b",
            "tech_stack": ["aws", "kubernetes"],
        }
        score, breakdown = scorer.score(sample)
        print(f"\n=== Sample score for '{sample['title']}' at {size}-employee company ===")
        print(f"  Score: {score}/100")
        print(f"  Breakdown: {breakdown}")
        print(f"\n  Current ICP_SCORE_THRESHOLD is set in .env")
        print(f"  If score < threshold → contacts are rejected")

asyncio.run(main())
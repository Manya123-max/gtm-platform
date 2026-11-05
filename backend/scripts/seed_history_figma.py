import asyncio
from datetime import datetime, timedelta
from sqlalchemy import text, select
from app.core.database import AsyncSessionLocal

async def seed_history():
    async with AsyncSessionLocal() as db:
        # Check columns
        res = await db.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'user_inputs' 
            ORDER BY ordinal_position
        """))
        cols = [r[0] for r in res.fetchall()]
        print("user_inputs columns:", cols)

        # 5 Exact Search History items matching Figma screenshot
        # IDs 1 to 5
        history_items = [
            {
                "id": 5,
                "our_company_name": "4CE Cloud",
                "our_services": "Salesforce Implementation, Life Sciences Cloud, Sales Cloud, Service Cloud, Managed Services",
                "target_location": "United States",
                "target_job_titles": "CIO, CTO, VP Commercial IT, VP CRM, VP Digital Transformation, Director CRM",
                "target_industries": "Pharmaceuticals, Biotechnology, Life Sciences",
                "target_keywords": "commercial operations, patient services, clinical operations, life sciences, HCP engagement, CRM transformation",
                "target_company_size": "200-5000",
            },
            {
                "id": 4,
                "our_company_name": "4CE Cloud",
                "our_services": "Salesforce Implementation, Life Sciences Cloud, Sales Cloud, Service Cloud, Managed Services",
                "target_location": "United States",
                "target_job_titles": "CIO, CTO, VP Commercial IT, VP CRM, VP Digital Transformation, Director CRM",
                "target_industries": "Pharmaceuticals, Biotechnology, Life Sciences",
                "target_keywords": "commercial operations, patient services, clinical operations, life sciences, HCP engagement, CRM transformation",
                "target_company_size": "200-5000",
            },
            {
                "id": 3,
                "our_company_name": "4CE Cloud",
                "our_services": "Salesforce Implementation, Life Sciences Cloud, Sales Cloud, Service Cloud, Managed Services",
                "target_location": "United States",
                "target_job_titles": "CIO, CTO, VP Commercial IT, VP CRM, VP Digital Transformation, Director CRM",
                "target_industries": "Pharmaceuticals, Biotechnology, Life Sciences",
                "target_keywords": "commercial operations, patient services, clinical operations, life sciences, HCP engagement, CRM transformation",
                "target_company_size": "200-5000",
            },
            {
                "id": 2,
                "our_company_name": "4CE Cloud",
                "our_services": "Salesforce Implementation, Life Sciences Cloud, Sales Cloud, Service Cloud, Managed Services",
                "target_location": "United States",
                "target_job_titles": "CIO, CTO, VP Commercial IT, VP CRM, VP Digital Transformation, Director CRM",
                "target_industries": "Pharmaceuticals, Biotechnology, Life Sciences",
                "target_keywords": "commercial operations, patient services, clinical operations, life sciences, HCP engagement, CRM transformation",
                "target_company_size": "200-5000",
            },
            {
                "id": 1,
                "our_company_name": "4CE Cloud",
                "our_services": "Salesforce Implementation, Life Sciences Cloud, Sales Cloud, Service Cloud, Managed Services",
                "target_location": "United States",
                "target_job_titles": "CIO, CTO, VP Commercial IT, VP CRM, VP Digital Transformation, Director CRM",
                "target_industries": "Pharmaceuticals, Biotechnology, Life Sciences",
                "target_keywords": "commercial operations, patient services, clinical operations, life sciences, HCP engagement, CRM transformation",
                "target_company_size": "200-5000",
            },
        ]

        # Insert or update each record
        for item in history_items:
            # Check if row exists
            check = await db.execute(text("SELECT id FROM user_inputs WHERE id = :id"), {"id": item["id"]})
            existing = check.fetchone()
            if existing:
                await db.execute(text("""
                    UPDATE user_inputs SET
                        our_company_name = :our_company_name,
                        our_services = :our_services,
                        target_location = :target_location,
                        target_job_titles = :target_job_titles,
                        target_industries = :target_industries,
                        target_keywords = :target_keywords,
                        target_company_size = :target_company_size,
                        user_id = NULL
                    WHERE id = :id
                """), item)
            else:
                await db.execute(text("""
                    INSERT INTO user_inputs (
                        id, our_company_name, our_services, target_location,
                        target_job_titles, target_industries, target_keywords,
                        target_company_size, user_id
                    ) VALUES (
                        :id, :our_company_name, :our_services, :target_location,
                        :target_job_titles, :target_industries, :target_keywords,
                        :target_company_size, NULL
                    )
                """), item)

        # Update sequence so next inserts don't collide
        await db.execute(text("SELECT setval('user_inputs_id_seq', (SELECT MAX(id) FROM user_inputs))"))
        await db.commit()
        print("Successfully seeded 5 exact history searches!")

if __name__ == "__main__":
    asyncio.run(seed_history())

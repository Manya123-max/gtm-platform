import asyncio
import os
import sys
import csv
import json
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://gtm:gtmpass@db:5432/gtm"
)

def parse_date(val: str) -> Optional[datetime]:
    if not val or val.strip() == "":
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(val)
    except ValueError:
        return None

def parse_bool(val: str) -> bool:
    if not val:
        return False
    return val.strip().lower() in ("t", "true", "1", "yes")

def parse_json(val: str):
    if not val:
        return None
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        # If it's a bracketed list of strings e.g. "[]", return that
        if val.strip() == "[]":
            return []
        return val

async def main():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import select
    from app.models.models import Contact, UserInput

    print(f"Connecting to database at {DATABASE_URL}...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    csv_path = "/app/prospects_export.csv"
    if not os.path.exists(csv_path):
        print(f"CSV file not found at {csv_path}")
        return

    print(f"Reading prospects from {csv_path}...")
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Found {len(rows)} rows to process.")

    async with Session() as db:
        # First, scan for unique user_input_ids
        user_input_ids = set()
        for row in rows:
            ui_id_str = row.get("user_input_id")
            if ui_id_str and ui_id_str.strip():
                try:
                    user_input_ids.add(int(ui_id_str))
                except ValueError:
                    pass

        # Create dummy UserInputs if they don't exist
        for ui_id in user_input_ids:
            res = await db.execute(select(UserInput).where(UserInput.id == ui_id))
            if not res.scalar_one_or_none():
                print(f"Creating dummy UserInput with ID {ui_id}...")
                ui = UserInput(
                    id=ui_id,
                    our_company_name="Imported Vendor",
                    our_services="Imported Services",
                    target_location="Anywhere",
                    target_industries="SaaS",
                    target_company_size="11-50",
                    target_keywords="None",
                    target_job_titles="Sales Ops",
                )
                db.add(ui)
        await db.commit()

        # Now, import contacts
        success_count = 0
        for row in rows:
            email = row.get("email")
            if not email:
                continue

            # Check if contact already exists
            res = await db.execute(select(Contact).where(Contact.email == email))
            existing = res.scalar_one_or_none()

            contact_id = row.get("id") or None
            user_input_id = None
            ui_id_str = row.get("user_input_id")
            if ui_id_str and ui_id_str.strip():
                try:
                    user_input_id = int(ui_id_str)
                except ValueError:
                    pass

            tech_stack_val = parse_json(row.get("tech_stack"))
            if tech_stack_val is None:
                tech_stack_val = []

            icp_score_breakdown_val = parse_json(row.get("icp_score_breakdown"))

            contact_data = {
                "email": email,
                "first_name": row.get("first_name") or None,
                "last_name": row.get("last_name") or None,
                "title": row.get("title") or None,
                "company": row.get("company") or None,
                "company_domain": row.get("company_domain") or None,
                "linkedin_url": row.get("linkedin_url") or None,
                "company_size": row.get("company_size") or None,
                "industry": row.get("industry") or None,
                "funding_stage": row.get("funding_stage") or None,
                "tech_stack": tech_stack_val,
                "geography": row.get("geography") or None,
                "annual_revenue": row.get("annual_revenue") or None,
                "employee_count": int(row.get("employee_count")) if row.get("employee_count") else None,
                "icp_score": float(row.get("icp_score")) if row.get("icp_score") else None,
                "icp_score_breakdown": icp_score_breakdown_val,
                "win_pattern_score": float(row.get("win_pattern_score")) if row.get("win_pattern_score") else None,
                "signal_type": row.get("signal_type") or None,
                "signal_score": float(row.get("signal_score")) if row.get("signal_score") else None,
                "latest_signal_at": parse_date(row.get("latest_signal_at")),
                "readiness_score": float(row.get("readiness_score")) if row.get("readiness_score") else 0.0,
                "do_not_contact": parse_bool(row.get("do_not_contact")),
                "email_verified": parse_bool(row.get("email_verified")),
                "email_valid": parse_bool(row.get("email_valid")) if row.get("email_valid") else None,
                "verified_at": parse_date(row.get("verified_at")),
                "enriched_at": parse_date(row.get("enriched_at")),
                "created_at": parse_date(row.get("created_at")) or datetime.utcnow(),
                "updated_at": parse_date(row.get("updated_at")) or datetime.utcnow(),
                "source": row.get("source") or None,
                "hubspot_id": row.get("hubspot_id") or None,
                "apollo_id": row.get("apollo_id") or None,
                "user_input_id": user_input_id,
            }

            if existing:
                print(f"Updating existing contact: {email}")
                for k, v in contact_data.items():
                    setattr(existing, k, v)
            else:
                print(f"Inserting new contact: {email}")
                new_contact = Contact(
                    id=contact_id,
                    **contact_data
                )
                db.add(new_contact)
            
            success_count += 1
            if success_count % 50 == 0:
                await db.commit()
                print(f"Committed {success_count} contacts.")
        
        await db.commit()
        print(f"Finished. Successfully imported/updated {success_count} contacts.")

if __name__ == "__main__":
    asyncio.run(main())

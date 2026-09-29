import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import GeneratedContent, UserInput, Contact
from sqlalchemy import select

async def inspect():
    async with AsyncSessionLocal() as db:
        print("=== User Inputs (Sessions) ===")
        ui_res = await db.execute(select(UserInput))
        uis = ui_res.scalars().all()
        for ui in uis:
            print(f"ID: {ui.id} | Company Name: {ui.our_company_name} | Target Industries: {ui.target_industries}")
            
        print("\n=== Contacts ===")
        contact_res = await db.execute(select(Contact).limit(10))
        contacts = contact_res.scalars().all()
        for c in contacts:
            print(f"Contact: {c.first_name} {c.last_name} | Company: {c.company} | Industry: {c.industry} | UserInputID: {c.user_input_id}")

        print("\n=== Generated Content (Most Recent 3) ===")
        content_res = await db.execute(select(GeneratedContent).order_by(GeneratedContent.created_at.desc()).limit(3))
        pieces = content_res.scalars().all()
        for p in pieces:
            print(f"\nTitle: {p.title}")
            print(f"Format: {p.content_format}")
            print(f"Content:\n{p.content}")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(inspect())

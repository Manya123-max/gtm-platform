import asyncio
import traceback
from sqlalchemy import select
from app.core.database import init_db, close_db, AsyncSessionLocal
from app.models.models import Contact
from app.services import SalesforceSyncService

async def debug_sf_sync():
    await init_db()
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Contact).limit(1))
            contact = res.scalar_one_or_none()
            if not contact:
                print("No contact found in DB.")
                return
            
            print(f"Testing Salesforce sync for Contact: {contact.first_name} {contact.last_name} ({contact.email})...")
            sf_service = SalesforceSyncService()
            result = sf_service.sync_contact_model(contact)
            print("Result:", result)
    except Exception as e:
        print("\n==================================================")
        print("EXACT TRACEBACK ENCOUNTERED:")
        print("==================================================")
        traceback.print_exc()
    finally:
        await close_db()

if __name__ == "__main__":
    asyncio.run(debug_sf_sync())

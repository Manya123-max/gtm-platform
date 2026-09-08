import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import Deal, PendingAction
from sqlalchemy import select

async def check_galvin():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Deal).where(Deal.name.ilike("%galvin%")))
        deal = res.scalars().first()
        if not deal:
            print("No Galvin deal found.")
            return
        
        print("Galvin Deal Info:")
        print(f"  ID: {deal.id}")
        print(f"  Stage: {deal.stage}")
        print(f"  timeline_confirmed: {deal.timeline_confirmed} (Type: {type(deal.timeline_confirmed)})")
        print(f"  budget_confirmed: {deal.budget_confirmed}")
        print(f"  authority_confirmed: {deal.authority_confirmed}")
        print(f"  need_confirmed: {deal.need_confirmed}")
        print(f"  risk_flags: {deal.risk_flags}")
        
        # Query PendingAction for this deal
        pa_res = await db.execute(
            select(PendingAction).where(PendingAction.entity_id == deal.id)
        )
        actions = pa_res.scalars().all()
        print("\nPending Actions for this deal:")
        for action in actions:
            print(f"  - ID: {action.id} | Type: {action.action_type} | Status: {action.status} | Reason: {action.reason[:100]}...")

if __name__ == "__main__":
    asyncio.run(check_galvin())

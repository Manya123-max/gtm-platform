import asyncio
from app.core.database import AsyncSessionLocal
from app.models.models import UserInput, Contact, ContactUserInputAssociation
from sqlalchemy import select, func

async def check_all_history():
    async with AsyncSessionLocal() as db:
        uis = (await db.execute(select(UserInput).order_by(UserInput.id.asc()))).scalars().all()
        print(f'Total Search History runs: {len(uis)}')
        for ui in uis:
            assoc_count = await db.scalar(
                select(func.count(ContactUserInputAssociation.contact_id))
                .where(ContactUserInputAssociation.user_input_id == ui.id)
            )
            direct_count = await db.scalar(
                select(func.count(Contact.id))
                .where(Contact.user_input_id == ui.id)
            )
            cname = getattr(ui, 'our_company_name', 'N/A')
            print(f'  UserInput ID: {ui.id} | company: {cname} | direct Contact.user_input_id: {direct_count} | assoc table: {assoc_count}')

if __name__ == '__main__':
    asyncio.run(check_all_history())

import uuid
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.models import (
    User, UserInput, Contact, ContactUserInputAssociation
)
from app.api.v1 import InputData, submit_input
from app.agents.a1_prospect import ProspectAgent


async def _create_test_user(email: str, name: str) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash="test_hashed_pwd",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def test_submit_input_with_existing_user_input_id_updates_in_place():
    """Verify that submitting with an existing user_input_id updates the record in-place without creating a duplicate search."""
    user = await _create_test_user(f"tester_{uuid.uuid4().hex[:6]}@example.com", "Test User")

    async with AsyncSessionLocal() as db:
        initial_input = UserInput(
            user_id=user.id,
            our_company_name="Initial Vendor",
            our_services="Initial Services",
            target_location="Austin, TX",
            target_company_size="50-200",
            target_job_titles="VP Sales",
        )
        db.add(initial_input)
        await db.commit()
        await db.refresh(initial_input)
        initial_id = initial_input.id

    # Now simulate re-running / updating the same search form
    payload = InputData(
        user_input_id=initial_id,
        our_company_name="Updated Vendor Corp",
        our_services="Updated Cloud Solutions",
        target_location="San Francisco, CA",
        target_company_size="100-500",
        target_job_titles="CTO, VP Engineering",
        company_lookalike="Stripe, Twilio",
    )

    async with AsyncSessionLocal() as db:
        res = await submit_input(data=payload, current_user=user, db=db)
        assert res["status"] == "success"
        assert res["user_input_id"] == initial_id

        # Verify in DB: ID is identical, values updated
        updated_rec = await db.get(UserInput, initial_id)
        assert updated_rec is not None
        assert updated_rec.our_company_name == "Updated Vendor Corp"
        assert updated_rec.target_location == "San Francisco, CA"
        assert updated_rec.company_lookalike == "Stripe, Twilio"

        # Verify no duplicate UserInput record was created for this user
        all_user_inputs = (
            await db.execute(select(UserInput).where(UserInput.user_id == user.id))
        ).scalars().all()
        assert len(all_user_inputs) == 1


async def test_rerun_preserves_existing_contacts_and_appends_new_prospects():
    """Verify that re-running for an existing search NEVER clears previous contacts and appends newly discovered ones."""
    user = await _create_test_user(f"tester2_{uuid.uuid4().hex[:6]}@example.com", "Test User 2")

    async with AsyncSessionLocal() as db:
        search_input = UserInput(
            user_id=user.id,
            our_company_name="SaaS Metrics",
            our_services="Analytics",
            target_location="US",
            target_company_size="50-1000",
            target_job_titles="VP Sales",
        )
        db.add(search_input)
        await db.commit()
        await db.refresh(search_input)
        input_id = search_input.id

        # Pre-seed 2 contacts already collected in this search
        old_c1 = Contact(
            user_id=user.id,
            user_input_id=input_id,
            email=f"prior1_{uuid.uuid4().hex[:6]}@domain.com",
            first_name="Alice",
            last_name="Old",
            company="Alpha Corp",
            title="VP Sales",
            apollo_id=f"ap_{uuid.uuid4().hex[:8]}",
            icp_score=85.0,
            win_pattern_score=85.0,
            do_not_contact=False,
        )
        old_c2 = Contact(
            user_id=user.id,
            user_input_id=input_id,
            email=f"prior2_{uuid.uuid4().hex[:6]}@domain.com",
            first_name="Bob",
            last_name="Old",
            company="Beta Inc",
            title="Head of Sales",
            apollo_id=f"ap_{uuid.uuid4().hex[:8]}",
            icp_score=78.0,
            win_pattern_score=78.0,
            do_not_contact=False,
        )
        db.add_all([old_c1, old_c2])
        await db.flush()
        db.add(ContactUserInputAssociation(contact_id=old_c1.id, user_input_id=input_id))
        db.add(ContactUserInputAssociation(contact_id=old_c2.id, user_input_id=input_id))
        await db.commit()

        # Re-run A1 save_contacts for the SAME input_id:
        # Candidate 1: old_c1 (already in DB)
        # Candidate 2: brand-new contact (Charlie New)
        new_email = f"new_{uuid.uuid4().hex[:6]}@gammainc.com"
        new_apollo_id = f"ap_{uuid.uuid4().hex[:8]}"

        candidates = [
            {
                "email": old_c1.email,
                "first_name": "Alice",
                "last_name": "Old",
                "company": "Alpha Corp",
                "title": "VP Sales",
                "apollo_id": old_c1.apollo_id,
                "win_pattern_score": 85.0,
                "source": "apollo",
            },
            {
                "email": new_email,
                "first_name": "Charlie",
                "last_name": "New",
                "company": "Gamma Tech",
                "title": "VP Sales",
                "apollo_id": new_apollo_id,
                "win_pattern_score": 90.0,
                "source": "apollo",
            },
        ]

        agent = ProspectAgent(db)
        save_res = await agent._save_contacts(
            contacts=candidates,
            user_id=user.id,
            user_input_id=input_id,
        )
        assert save_res["saved_count"] >= 1

        # Check total contacts associated with input_id
        assoc_ids_q = select(ContactUserInputAssociation.contact_id).where(
            ContactUserInputAssociation.user_input_id == input_id
        )
        all_for_search = (
            await db.execute(
                select(Contact).where(Contact.id.in_(assoc_ids_q))
            )
        ).scalars().all()

        # Must have ALL 3 contacts: the 2 previous ones + the newly added one!
        emails_in_search = {c.email for c in all_for_search}
        assert old_c1.email in emails_in_search, "Previous contact Alice was cleared!"
        assert old_c2.email in emails_in_search, "Previous contact Bob was cleared!"
        assert new_email in emails_in_search, "New prospect Charlie was not added to search!"
        assert len(all_for_search) == 3


if __name__ == "__main__":
    import asyncio
    async def main():
        print("Running test 1: test_submit_input_with_existing_user_input_id_updates_in_place...")
        await test_submit_input_with_existing_user_input_id_updates_in_place()
        print("✓ Test 1 PASSED: Search history updated in-place with same user_input_id, zero duplicate searches.")

        print("Running test 2: test_rerun_preserves_existing_contacts_and_appends_new_prospects...")
        await test_rerun_preserves_existing_contacts_and_appends_new_prospects()
        print("✓ Test 2 PASSED: Previous contacts preserved and newly discovered prospects appended to same search list.")

        print("\nAll rerun search and prospect add-on tests PASSED successfully!")

    asyncio.run(main())


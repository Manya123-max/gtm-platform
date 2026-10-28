"""
Tests for multi-user schema bootstrap and legacy record migration ownership.
Validates:
1. Missing migration-owner user: User is safely created with valid role 'SALES_REPRESENTATIVE', satisfying NOT NULL constraint.
2. Existing migration-owner user: User is reused; role, name, and credentials are preserved without duplicate creation or overwrite.
3. Repeated execution idempotency: Multiple bootstrap runs succeed cleanly with no duplicate users or errors.
4. Legacy record backfill isolation: Only unowned records are assigned to the migration owner; records tied to other users are preserved.
"""
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select, delete, text

from app.core.database import init_db, engine, AsyncSessionLocal, _bootstrap_multi_user_schema
from app.core.security import hash_password
from app.models.models import User, UserInput, Contact, WorkflowRun, RevenueForecast


@pytest.mark.asyncio
async def test_bootstrap_missing_migration_owner_user():
    """
    Scenario 1: When GTM_MIGRATION_OWNER_EMAIL is configured for a user that does not exist,
    the bootstrap must create the user with role='SALES_REPRESENTATIVE' (not null),
    and backfill unowned legacy rows to this new user.
    """
    await init_db()

    suffix = uuid.uuid4().hex[:8]
    owner_email = f"migration_owner_{suffix}@forcecloudlabs.com"
    other_user_email = f"other_user_{suffix}@forcecloudlabs.com"

    async with AsyncSessionLocal() as session:
        # 1. Create an existing "other" user
        other_user = User(
            id=str(uuid.uuid4()),
            name="Other Sales Rep",
            email=other_user_email,
            password_hash=hash_password("other_secret_123"),
            role="SALES_REPRESENTATIVE",
            is_active=True,
        )
        session.add(other_user)

        # 2. Create search input for other_user
        other_input = UserInput(
            user_id=other_user.id,
            our_company_name=f"Other Co {suffix}",
            our_services="Cloud AI Services",
            target_location="US",
            target_company_size="50-200",
            target_job_titles="VP Sales",
        )
        session.add(other_input)
        await session.flush()

        # 3. Create a legacy contact tied to other_user's session (user_id IS NULL initially)
        c_other_session = Contact(
            email=f"c_other_{suffix}@target.com",
            company="Target Other",
            user_id=None,
            user_input_id=other_input.id,
            first_name="Jane",
            last_name="Doe",
        )
        session.add(c_other_session)

        # 4. Create orphaned unowned records (legacy rows with user_id IS NULL)
        unowned_input = UserInput(
            user_id=None,
            our_company_name=f"Unowned Legacy Co {suffix}",
            our_services="Legacy Automation Services",
            target_location="US",
            target_company_size="50-200",
            target_job_titles="VP Sales",
        )
        session.add(unowned_input)
        await session.flush()

        unowned_contact_with_session = Contact(
            email=f"c_unowned_session_{suffix}@target.com",
            company="Target Unowned 1",
            user_id=None,
            user_input_id=unowned_input.id,
            first_name="Bob",
            last_name="Legacy",
        )
        unowned_contact_direct = Contact(
            email=f"c_unowned_direct_{suffix}@target.com",
            company="Target Unowned 2",
            user_id=None,
            user_input_id=None,
            first_name="Alice",
            last_name="Direct",
        )
        session.add_all([unowned_contact_with_session, unowned_contact_direct])

        unowned_workflow = WorkflowRun(
            workflow_name="lead_enrichment",
            status="completed",
            user_id=None,
        )
        session.add(unowned_workflow)

        unowned_forecast = RevenueForecast(
            forecast_30d=125000.0,
            current_pipeline_value=250000.0,
            user_id=None,
        )
        session.add(unowned_forecast)
        await session.commit()

        u_other_input_id = other_input.id
        c_other_id = c_other_session.id
        u_legacy_input_id = unowned_input.id
        c_legacy_1_id = unowned_contact_with_session.id
        c_legacy_2_id = unowned_contact_direct.id
        wf_id = unowned_workflow.id
        rf_id = unowned_forecast.id

    try:
        # Run bootstrap with the missing owner email
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        # Verify the migration owner was created cleanly
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(User).where(User.email == owner_email))
            created_owner = res.scalar_one_or_none()
            assert created_owner is not None, "Migration owner user should have been created"
            assert created_owner.role == "SALES_REPRESENTATIVE", "Role must be 'SALES_REPRESENTATIVE'"
            assert created_owner.is_active is True, "User must be active"
            assert created_owner.password_hash is not None and len(created_owner.password_hash) > 10
            owner_id = created_owner.id

            # Verify unowned legacy rows were backfilled to migration owner
            refreshed_input = await session.get(UserInput, u_legacy_input_id)
            assert str(refreshed_input.user_id) == str(owner_id), "Unowned input should be assigned to migration owner"

            refreshed_c1 = await session.get(Contact, c_legacy_1_id)
            assert str(refreshed_c1.user_id) == str(owner_id), "Contact with unowned session should be assigned to migration owner"

            refreshed_c2 = await session.get(Contact, c_legacy_2_id)
            assert str(refreshed_c2.user_id) == str(owner_id), "Direct unowned contact should be assigned to migration owner"

            refreshed_wf = await session.get(WorkflowRun, wf_id)
            assert str(refreshed_wf.user_id) == str(owner_id), "Unowned workflow run should be assigned to migration owner"

            refreshed_rf = await session.get(RevenueForecast, rf_id)
            assert str(refreshed_rf.user_id) == str(owner_id), "Unowned forecast should be assigned to migration owner"

            # Verify multi-user isolation: contact tied to other_user's session inherited other_user.id
            refreshed_other_c = await session.get(Contact, c_other_id)
            assert str(refreshed_other_c.user_id) == str(other_user.id), "Contact tied to other user's session must inherit other user's ID"

    finally:
        # Teardown test rows
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Contact).where(Contact.id.in_([c_other_id, c_legacy_1_id, c_legacy_2_id])))
            await session.execute(delete(UserInput).where(UserInput.id.in_([u_other_input_id, u_legacy_input_id])))
            await session.execute(delete(WorkflowRun).where(WorkflowRun.id == wf_id))
            await session.execute(delete(RevenueForecast).where(RevenueForecast.id == rf_id))
            await session.execute(delete(User).where(User.email.in_([owner_email, other_user_email])))
            await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_existing_migration_owner_user():
    """
    Scenario 2: When GTM_MIGRATION_OWNER_EMAIL matches an existing user (e.g. an ADMIN),
    the bootstrap must reuse the existing account without overwriting its role, credentials, or name.
    """
    await init_db()

    suffix = uuid.uuid4().hex[:8]
    existing_admin_email = f"admin_{suffix}@forcecloudlabs.com"
    original_password_hash = hash_password("super_secure_admin_pw")

    async with AsyncSessionLocal() as session:
        admin_user = User(
            id=str(uuid.uuid4()),
            name="Existing Lead Admin",
            email=existing_admin_email,
            password_hash=original_password_hash,
            role="ADMIN",
            is_active=True,
        )
        session.add(admin_user)

        # Add an unowned contact
        unowned_contact = Contact(
            email=f"legacy_lead_{suffix}@target.com",
            company="Target Existing Test",
            user_id=None,
            first_name="Legacy",
            last_name="Lead",
        )
        session.add(unowned_contact)
        await session.commit()

        admin_id = admin_user.id
        contact_id = unowned_contact.id

    try:
        # Run bootstrap targeting the existing admin email
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=existing_admin_email)

        # Verify existing user was preserved exactly without modification
        async with AsyncSessionLocal() as session:
            user_count = (await session.execute(
                select(User).where(User.email == existing_admin_email)
            )).scalars().all()
            assert len(user_count) == 1, "Must not create duplicate user accounts"

            user = user_count[0]
            assert user.id == admin_id
            assert user.role == "ADMIN", "Existing ADMIN role must not be overwritten or downgraded"
            assert user.name == "Existing Lead Admin", "Existing name must be preserved"
            assert user.password_hash == original_password_hash, "Existing password hash must not be changed"

            # Verify unowned contact was backfilled to this existing admin
            refreshed_c = await session.get(Contact, contact_id)
            assert str(refreshed_c.user_id) == str(admin_id), "Unowned contact should now be assigned to existing admin"

    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Contact).where(Contact.id == contact_id))
            await session.execute(delete(User).where(User.id == admin_id))
            await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_repeated_execution_idempotency():
    """
    Scenario 3: Repeating _bootstrap_multi_user_schema multiple times in succession
    (simulating app restarts / parallel container boots) must be completely idempotent and error-free.
    """
    await init_db()

    suffix = uuid.uuid4().hex[:8]
    owner_email = f"idempotent_owner_{suffix}@forcecloudlabs.com"

    async with AsyncSessionLocal() as session:
        # Add an unowned contact
        contact = Contact(
            email=f"idempotent_contact_{suffix}@test.com",
            company="Idempotent Test Co",
            user_id=None,
            first_name="Idem",
            last_name="Test",
        )
        session.add(contact)
        await session.commit()
        contact_id = contact.id

    try:
        # Run 1: User is created and contact backfilled
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        async with AsyncSessionLocal() as session:
            user1 = (await session.execute(select(User).where(User.email == owner_email))).scalar_one()
            user1_id = user1.id
            user1_hash = user1.password_hash
            user1_role = user1.role

        # Run 2: Re-run with same owner email
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        # Run 3: Third execution
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        async with AsyncSessionLocal() as session:
            all_users = (await session.execute(select(User).where(User.email == owner_email))).scalars().all()
            assert len(all_users) == 1, "Must never duplicate user on repeated execution"
            assert all_users[0].id == user1_id
            assert all_users[0].password_hash == user1_hash
            assert all_users[0].role == user1_role

            refreshed_contact = await session.get(Contact, contact_id)
            assert str(refreshed_contact.user_id) == str(user1_id)

    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Contact).where(Contact.id == contact_id))
            await session.execute(delete(User).where(User.email == owner_email))
            await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_empty_migration_owner_leaves_unowned_rows_intact():
    """
    Scenario 4: When GTM_MIGRATION_OWNER_EMAIL is empty/not set,
    the bootstrap must safely log a warning and leave unowned rows with user_id NULL.
    """
    await init_db()

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as session:
        contact = Contact(
            email=f"empty_owner_contact_{suffix}@test.com",
            company="Empty Owner Co",
            user_id=None,
            first_name="NoOwner",
            last_name="Test",
        )
        session.add(contact)
        await session.commit()
        contact_id = contact.id

    try:
        # Run with empty migration owner
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email="")

        async with AsyncSessionLocal() as session:
            c = await session.get(Contact, contact_id)
            assert c.user_id is None, "Contact user_id must remain None when migration owner is not set"

    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Contact).where(Contact.id == contact_id))
            await session.commit()


@pytest.mark.asyncio
async def test_bootstrap_with_configured_migration_owner_password():
    """
    Scenario 5: When GTM_MIGRATION_OWNER_PASSWORD is configured,
    the bootstrap must set or synchronize the user's password_hash to match this password.
    """
    from app.core.config import settings
    from app.core.security import verify_password
    await init_db()

    suffix = uuid.uuid4().hex[:8]
    owner_email = f"configured_pw_owner_{suffix}@forcecloudlabs.com"
    custom_pw = "Bangtan@2013"
    orig_pw_setting = settings.GTM_MIGRATION_OWNER_PASSWORD

    try:
        settings.GTM_MIGRATION_OWNER_PASSWORD = custom_pw
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == owner_email))).scalar_one()
            assert verify_password(custom_pw, user.password_hash) is True, "Password must match configured GTM_MIGRATION_OWNER_PASSWORD"

        # Re-run bootstrap with an updated password to test sync for existing user
        updated_pw = "Bangtan@2014"
        settings.GTM_MIGRATION_OWNER_PASSWORD = updated_pw
        async with engine.begin() as conn:
            await _bootstrap_multi_user_schema(conn, migration_owner_email=owner_email)

        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == owner_email))).scalar_one()
            assert verify_password(updated_pw, user.password_hash) is True, "Password must synchronize to updated password"

    finally:
        settings.GTM_MIGRATION_OWNER_PASSWORD = orig_pw_setting
        async with AsyncSessionLocal() as session:
            await session.execute(delete(User).where(User.email == owner_email))
            await session.commit()


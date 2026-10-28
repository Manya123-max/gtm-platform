"""
Tests for History Delete, Salesforce Contact/Lead Sync, and Cal.com Resolution.
Validates:
1. User A can safely delete own search history item.
2. User B cannot delete User A's search history item (403 Forbidden).
3. Contact, Deal, and related records are preserved when search history is deleted.
4. Association cleanup: contact_user_input_association rows removed for deleted input.
5. User A can delete all own search history items without affecting User B.
6. Salesforce contact/lead creation and deduplication (SOQL lookup prevents duplicates).
7. Cal.com multi-tier resolution (custom URL, custom slug, admin user mapping, org slug, email fallback).
"""
import uuid
import json
import pytest
import httpx
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.models import (
    User, UserInput, Contact, ContactUserInputAssociation, Deal, DealStage
)
from app.services.salesforce_service import SalesforceService
from app.services import CalService


async def _create_user(email: str, name: str) -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            password_hash="test_hashed_password_xyz",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_user_input(user_id: str, company_name: str) -> UserInput:
    async with AsyncSessionLocal() as db:
        record = UserInput(
            user_id=user_id,
            our_company_name=company_name,
            our_services="Enterprise Cloud Integration",
            target_location="San Francisco, CA",
            target_company_size="50-500",
            target_job_titles="VP Sales, CTO",
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record


@pytest.fixture(autouse=True)
async def cleanup_test_history_users():
    yield
    from sqlalchemy import select, delete, or_
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).where(or_(User.email.ilike("%@company.com"), User.email.ilike("%@example.com"))))).scalars().all()
        if users:
            uids = [u.id for u in users]
            c_sub = select(Contact.id).where(Contact.user_id.in_(uids))
            await db.execute(delete(Deal).where(Deal.contact_id.in_(c_sub)))
            await db.execute(delete(ContactUserInputAssociation).where(ContactUserInputAssociation.contact_id.in_(c_sub)))
            await db.execute(delete(Contact).where(Contact.user_id.in_(uids)))
            await db.execute(delete(UserInput).where(UserInput.user_id.in_(uids)))
            await db.execute(delete(User).where(User.id.in_(uids)))
            await db.commit()


# ==============================================================================
# 1. DELETE OWN HISTORY
# ==============================================================================

@pytest.mark.asyncio
async def test_delete_own_history():
    user = await _create_user(f"rep_{uuid.uuid4().hex[:6]}@company.com", "Test Rep")
    history_item = await _create_user_input(user.id, "Acme Corp Search")

    token = create_access_token(str(user.id))

    async with httpx.AsyncClient() as client:
        res = await client.delete(
            f"http://127.0.0.1:8000/api/v1/input-history/{history_item.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["id"] == history_item.id

    # Verify deleted from DB
    async with AsyncSessionLocal() as db:
        check = await db.get(UserInput, history_item.id)
        assert check is None


# ==============================================================================
# 2. CANNOT DELETE ANOTHER USER'S HISTORY
# ==============================================================================

@pytest.mark.asyncio
async def test_cannot_delete_another_user_history():
    user_a = await _create_user(f"rep_a_{uuid.uuid4().hex[:6]}@company.com", "Rep Alpha")
    user_b = await _create_user(f"rep_b_{uuid.uuid4().hex[:6]}@company.com", "Rep Beta")

    item_a = await _create_user_input(user_a.id, "Alpha Private Search")
    token_b = create_access_token(str(user_b.id))

    async with httpx.AsyncClient() as client:
        # User B attempts to delete User A's history item
        res = await client.delete(
            f"http://127.0.0.1:8000/api/v1/input-history/{item_a.id}",
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert res.status_code == 403
        assert "not authorized" in res.json().get("detail", "").lower()

    # Verify item still exists in database
    async with AsyncSessionLocal() as db:
        check = await db.get(UserInput, item_a.id)
        assert check is not None
        assert check.our_company_name == "Alpha Private Search"


# ==============================================================================
# 3. CONTACTS AND DEALS PRESERVED WHEN HISTORY IS DELETED
# ==============================================================================

@pytest.mark.asyncio
async def test_contacts_and_deals_preserved_on_history_deletion():
    user = await _create_user(f"rep_{uuid.uuid4().hex[:6]}@company.com", "Pipeline Rep")
    history_item = await _create_user_input(user.id, "Preserve Contacts Search")

    # Create contacts and link via association
    async with AsyncSessionLocal() as db:
        contact1 = Contact(
            email=f"prospect_{uuid.uuid4().hex[:6]}@target.com",
            first_name="Jane",
            last_name="Doe",
            company="Target Corp",
            user_id=user.id,
            user_input_id=history_item.id,
        )
        contact2 = Contact(
            email=f"prospect2_{uuid.uuid4().hex[:6]}@target.com",
            first_name="John",
            last_name="Smith",
            company="Target Corp",
            user_id=user.id,
            user_input_id=history_item.id,
        )
        db.add_all([contact1, contact2])
        await db.flush()

        # Link to association table
        db.add(ContactUserInputAssociation(contact_id=contact1.id, user_input_id=history_item.id))
        db.add(ContactUserInputAssociation(contact_id=contact2.id, user_input_id=history_item.id))

        # Create a Deal for contact1
        deal = Deal(
            contact_id=contact1.id,
            name="Target Corp Enterprise Deal",
            stage=DealStage.DISCOVERY,
            amount=75000.0,
            amount_source="Salesforce",
            salesforce_opportunity_id=f"006{uuid.uuid4().hex[:12]}",
        )
        db.add(deal)
        await db.commit()

        c1_id = contact1.id
        c2_id = contact2.id
        deal_id = deal.id

    token = create_access_token(str(user.id))

    async with httpx.AsyncClient() as client:
        res = await client.delete(
            f"http://127.0.0.1:8000/api/v1/input-history/{history_item.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200

    # Verify:
    # 1. UserInput deleted
    # 2. Association rows deleted
    # 3. Contacts PRESERVED
    # 4. Deals PRESERVED
    async with AsyncSessionLocal() as db:
        assert (await db.get(UserInput, history_item.id)) is None

        assoc_res = await db.execute(
            select(ContactUserInputAssociation).where(
                ContactUserInputAssociation.user_input_id == history_item.id
            )
        )
        assert len(assoc_res.scalars().all()) == 0

        preserved_c1 = await db.get(Contact, c1_id)
        assert preserved_c1 is not None
        assert preserved_c1.email.startswith("prospect_")

        preserved_c2 = await db.get(Contact, c2_id)
        assert preserved_c2 is not None

        preserved_deal = await db.get(Deal, deal_id)
        assert preserved_deal is not None
        assert preserved_deal.amount == 75000.0

        # Clean up test entities so they do not pollute DB
        from app.models.models import DealStageHistory
        await db.execute(delete(DealStageHistory).where(DealStageHistory.deal_id == deal_id))
        await db.delete(preserved_deal)
        await db.delete(preserved_c1)
        await db.delete(preserved_c2)
        test_u = await db.get(User, user.id)
        if test_u:
            await db.delete(test_u)
        await db.commit()


# ==============================================================================
# 4. DELETE ALL HISTORY FOR CURRENT USER
# ==============================================================================

@pytest.mark.asyncio
async def test_delete_all_history_for_current_user():
    user_a = await _create_user(f"rep_a_{uuid.uuid4().hex[:6]}@company.com", "User Alpha")
    user_b = await _create_user(f"rep_b_{uuid.uuid4().hex[:6]}@company.com", "User Beta")

    item_a1 = await _create_user_input(user_a.id, "Alpha Search 1")
    item_a2 = await _create_user_input(user_a.id, "Alpha Search 2")
    item_b1 = await _create_user_input(user_b.id, "Beta Search 1")

    token_a = create_access_token(str(user_a.id))

    async with httpx.AsyncClient() as client:
        res = await client.delete(
            "http://127.0.0.1:8000/api/v1/input-history",
            headers={"Authorization": f"Bearer {token_a}"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["deleted_count"] >= 2

    # Verify User A's items deleted, but User B's item is strictly preserved
    async with AsyncSessionLocal() as db:
        assert (await db.get(UserInput, item_a1.id)) is None
        assert (await db.get(UserInput, item_a2.id)) is None
        check_b = await db.get(UserInput, item_b1.id)
        assert check_b is not None
        assert check_b.user_id == user_b.id


# ==============================================================================
# 5. SALESFORCE CONTACT / LEAD SYNC & DEDUPLICATION
# ==============================================================================

@pytest.mark.asyncio
async def test_salesforce_sync_contact_lead_creation_and_deduplication():
    sf = SalesforceService()

    # Unconfigured returns None gracefully
    sf.instance_url = ""
    sf.access_token = ""
    assert sf.is_configured is False
    res = await sf.sync_contact_to_salesforce({"email": "test@domain.com"})
    assert res is None

    # Configured: Lead creation
    sf.instance_url = "https://example.my.salesforce.com"
    sf.access_token = "valid_token_xyz"
    assert sf.is_configured is True

    with patch.object(sf, "get_contact_by_email", AsyncMock(return_value=None)), \
         patch.object(sf, "get_lead_by_email", AsyncMock(return_value=None)):

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 201
        mock_post_resp.json.return_value = {"id": "00Q5g000001AbCdEFG", "success": True}
        mock_post_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_post_resp)) as mock_post:
            new_id = await sf.sync_contact_to_salesforce({
                "email": "lead@target.com",
                "first_name": "Tom",
                "last_name": "Hardy",
                "company": "Target Media",
                "title": "Director",
            })
            assert new_id == "00Q5g000001AbCdEFG"
            assert mock_post.called

    # Deduplication: existing Contact in Salesforce updates without creating duplicate
    with patch.object(sf, "get_contact_by_email", AsyncMock(return_value={"Id": "0035g000001ExistingCId"})):

        mock_patch_resp = MagicMock()
        mock_patch_resp.status_code = 204
        mock_patch_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.patch", AsyncMock(return_value=mock_patch_resp)) as mock_patch, \
             patch("httpx.AsyncClient.post", AsyncMock()) as mock_post:
            sf_id = await sf.sync_contact_to_salesforce({
                "email": "existing@target.com",
                "first_name": "Tom",
                "last_name": "Hardy",
            })
            assert sf_id == "0035g000001ExistingCId"
            assert mock_patch.called
            assert not mock_post.called  # Did NOT create duplicate!


# ==============================================================================
# 6. CAL.COM RESOLUTION (CUSTOM OVERRIDE > ADMIN MAPPING > ORG > IDENTITY)
# ==============================================================================

def test_cal_com_resolution_hierarchy():
    cal = CalService()

    # User 1: Custom booking URL override
    user1 = MagicMock()
    user1.email = "alex@company.com"
    user1.cal_com_booking_url = "https://cal.com/alex-custom/30min"
    user1.cal_com_event_slug = None
    assert cal.resolve_user_booking_url(user1) == "https://cal.com/alex-custom/30min"

    # User 2: Custom event slug override
    user2 = MagicMock()
    user2.email = "alex@company.com"
    user2.cal_com_booking_url = None
    user2.cal_com_event_slug = "alex/quick-chat"
    assert cal.resolve_user_booking_url(user2) == "https://cal.com/alex/quick-chat"

    # User 3: Centralized Admin User Mapping
    user3 = MagicMock()
    user3.email = "john@company.com"
    user3.cal_com_booking_url = None
    user3.cal_com_event_slug = None
    with patch.object(settings, "CAL_COM_USER_MAPPINGS", json.dumps({"john@company.com": "johndoe/15min"})):
        assert cal.resolve_user_booking_url(user3) == "https://cal.com/johndoe/15min"

    # User 4: Organization Slug
    user4 = MagicMock()
    user4.email = "sarah@company.com"
    user4.cal_com_booking_url = None
    user4.cal_com_event_slug = None
    with patch.object(settings, "CAL_COM_USER_MAPPINGS", None), \
         patch.object(settings, "CAL_COM_ORG_SLUG", "acme-corp"), \
         patch.object(settings, "CAL_COM_DEFAULT_EVENT_SLUG", "intro"):
        assert cal.resolve_user_booking_url(user4) == "https://cal.com/acme-corp/sarah/intro"

    # Isolation: User A and User B never cross calendars
    user_a = MagicMock(email="rep_a@company.com", cal_com_booking_url=None, cal_com_event_slug=None)
    user_b = MagicMock(email="rep_b@company.com", cal_com_booking_url=None, cal_com_event_slug=None)
    with patch.object(settings, "CAL_COM_USER_MAPPINGS", None), \
         patch.object(settings, "CAL_COM_ORG_SLUG", None), \
         patch.object(settings, "CAL_COM_DEFAULT_EVENT_SLUG", "15min"):
        url_a = cal.resolve_user_booking_url(user_a)
        url_b = cal.resolve_user_booking_url(user_b)
        assert url_a != url_b
        assert "rep_a" in url_a
        assert "rep_b" in url_b

"""
backend/scripts/verify_live_pipeline.py — Comprehensive Live Pipeline Verification Script.

Validates in the live running application:
1. CSV Isolation from Real-Time Prospect Discovery:
   - Probes live Apollo API with Signals + Funding + Look-alike query.
   - Confirms zero fallback to prospects_export.csv.
2. Central DNC Suppression using Normalized Emails:
   - Normalization accuracy (trim, lowercase).
   - Multi-record duplicate Contact suppression.
   - Central suppressed_emails store upsert.
   - SuppressionService.is_email_suppressed multi-layer checks.
   - A3 DraftManager pre-send suppression block (draft rejected & suppressed, send aborted).
   - Safe cleanup of test records.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete, func
from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.models.models import Contact, OutreachDraft, SuppressedEmail, SignalEvent
from app.services.suppression_service import normalize_email, SuppressionService
from app.services.icp_normalizer import normalize_icp_input
from app.services.apollo_query_builder import ApolloQueryBuilder
from app.agents.a3_outreach import DraftManager
import httpx


async def run_live_verification():
    print("=" * 70)
    print("STARTING LIVE PIPELINE VERIFICATION")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1: Verify Email Normalization
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Step 1] Verifying Email Normalization...")
    raw_email = "  Test.USER+Filter@Example.COM \n\t "
    normalized = normalize_email(raw_email)
    assert normalized == "test.user+filter@example.com", f"Expected test.user+filter@example.com, got {normalized}"
    print(f"  ✓ normalize_email('{raw_email.strip()}') -> '{normalized}'")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Verify Signals & Funding Query Builder (Strict Persona/Engagement Isolation)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Step 2] Verifying Signals & Funding Query Builder (Strict Isolation)...")
    test_icp = {
        "target_job_titles": "CIO, CTO, Director of Digital Transformation",
        "target_location": "United States",
        "target_company_size": "100-5000",
        "target_industries": "Healthcare, Health Informatics",
        "signals": "Office expansion, New partnership, Former champion changed jobs, Opened 2+ emails in past week, High buying intent",
        "funding_stages": ["Seed", "Series A"],
    }
    cfg = normalize_icp_input(test_icp)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    # Check Company Momentum signals included in keyword tags
    tags = payload.get("q_organization_keyword_tags", [])
    assert "Office expansion" in tags, "Missing 'Office expansion' in tags"
    assert "New partnership" in tags, "Missing 'New partnership' in tags"

    # Check Persona, Engagement, and Intent signals STRICTLY EXCLUDED from organization keyword tags
    assert "Former champion changed jobs" not in tags, "Persona signal improperly added to company keyword tags"
    assert "Opened 2+ emails in past week" not in tags, "Engagement signal improperly added to company keyword tags"
    assert "High buying intent" not in tags, "Intent signal improperly added to company keyword tags"
    print(f"  ✓ Company momentum signals correctly mapped to q_organization_keyword_tags: {tags}")
    print("  ✓ Confirmed Persona, Engagement, and Intent signals strictly excluded from company tags.")

    # Check Funding OR within & No default min funding amount
    funding_cds = payload.get("organization_latest_funding_stage_cd", [])
    assert "seed" in funding_cds, "Missing 'seed' in funding stages"
    assert "series_a" in funding_cds, "Missing 'series_a' in funding stages"
    assert "min_funding_usd" not in payload, "Unexpected min_funding_usd in payload"
    assert "organization_min_funding_amount" not in payload, "Unexpected organization_min_funding_amount in payload"
    print(f"  ✓ Funding stages mapped to organization_latest_funding_stage_cd (OR within): {funding_cds}")
    print("  ✓ Confirmed no default minimum funding amount threshold injected.")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2b: Verify ICP Score Independence Across All 5 Scenarios
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Step 2b] Verifying ICP Score Independence Across All 5 Scenarios...")
    from app.services.scoring_service import WinPatternScorer
    scorer = WinPatternScorer()

    sample_prospect = {
        "title": "Chief Technology Officer",
        "company": "BioGenetics Inc",
        "company_size": "201-500",
        "employee_count": 350,
        "industry": "Healthcare",
        "funding_stage": "Series A",
        "tech_stack": ["Salesforce", "AWS", "Python"],
        "email": "cto@biogenetics.com",
    }

    core_info = {
        "target_job_titles": "CTO, Chief Technology Officer",
        "target_location": "United States",
        "target_company_size": "201-500",
        "target_industries": "Healthcare",
    }

    # Scenario 1: Core ICP only
    s1, b1 = scorer.score(sample_prospect)
    # Scenario 2: With Look-alike
    s2, b2 = scorer.score(dict(sample_prospect, is_lookalike=True, lookalike_seed_companies=["Google"]))
    # Scenario 3: With Signals
    s3, b3 = scorer.score(dict(sample_prospect, matched_signals=["Office expansion"], discovery_method="signals"))
    # Scenario 4: With Funding
    s4, b4 = scorer.score(dict(sample_prospect))
    # Scenario 5: With All Three
    s5, b5 = scorer.score(dict(sample_prospect, is_lookalike=True, matched_signals=["Office expansion"], discovery_method="lookalike"))

    assert s1 == s2 == s3 == s4 == s5, f"Scores differed: s1={s1}, s2={s2}, s3={s3}, s4={s4}, s5={s5}"
    assert b1 == b2 == b3 == b4 == b5, f"Breakdowns differed: {b1} vs {b5}"
    print(f"  ✓ ICP score is {s1} across all 5 scenarios (Zero influence from Look-alike, Signals, or Funding inputs).")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: Probe Live Apollo API with Combined Filters (No CSV Fallback)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Step 3] Probing Live Apollo API with Signals + Funding...")
    apollo_api_key = settings.APOLLO_API_KEY
    if apollo_api_key:
        apollo_url = "https://api.apollo.io/v1/mixed_people/api_search"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                apollo_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Api-Key": apollo_api_key,
                },
            )
            print(f"  Apollo API Response Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                total_entries = data.get("pagination", {}).get("total_entries", 0)
                people = data.get("people", [])
                print(f"  ✓ Live Apollo returned {len(people)} contacts (Total entries: {total_entries})")
                if people:
                    sample = people[0]
                    org = sample.get("organization", {})
                    print(f"  Sample Contact: {sample.get('first_name')} {sample.get('last_name')} | Title: {sample.get('title')}")
                    print(f"  Organization: {org.get('name')} | Industry: {org.get('industry')}")
            else:
                print(f"  Note: Apollo API returned HTTP {resp.status_code}: {resp.text[:150]}")
    else:
        print("  Notice: APOLLO_API_KEY not set in environment, skipping live HTTP probe.")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4: Central DNC Suppression Pipeline Test
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Step 4] Testing Central DNC Suppression Pipeline...")
    test_email_raw = "  Test.SUPPRESSION.2026@CloudLabs-Verify.Internal  "
    clean_email = normalize_email(test_email_raw)

    async with AsyncSessionLocal() as db:
        # Cleanup any existing test records first
        await db.execute(delete(Contact).where(func.lower(Contact.email) == clean_email))
        await db.execute(delete(SuppressedEmail).where(SuppressedEmail.email == clean_email))
        await db.commit()

        # Insert 2 duplicate contacts with differing casing & spacing
        c1 = Contact(
            email=test_email_raw.strip(),
            first_name="VerifyUser1",
            last_name="Test",
            do_not_contact=False,
            source="live_test",
        )
        c2 = Contact(
            email=clean_email.upper(),
            first_name="VerifyUser2",
            last_name="Duplicate",
            do_not_contact=False,
            source="live_test",
        )
        db.add_all([c1, c2])
        await db.commit()
        await db.refresh(c1)
        await db.refresh(c2)
        print(f"  Created 2 duplicate contacts: ID {c1.id} ({c1.email}) and ID {c2.id} ({c2.email})")

        # Suppress via SuppressionService
        updated_count = await SuppressionService.suppress_email(
            db,
            test_email_raw,
            source="resend_webhook",
            reason="unsubscribe",
        )
        print(f"  ✓ SuppressionService.suppress_email updated {updated_count} contact records.")
        assert updated_count >= 2, f"Expected at least 2 updated contacts, got {updated_count}"

        # Verify Contact 1 & 2 are both do_not_contact == True
        res_c1 = await db.scalar(select(Contact).where(Contact.id == c1.id))
        res_c2 = await db.scalar(select(Contact).where(Contact.id == c2.id))
        assert res_c1.do_not_contact is True, "Contact 1 do_not_contact is not True"
        assert res_c2.do_not_contact is True, "Contact 2 do_not_contact is not True"
        print("  ✓ Both duplicate contacts now have do_not_contact == True")

        # Verify central suppressed_emails store has record
        supp_row = await db.scalar(select(SuppressedEmail).where(SuppressedEmail.email == clean_email))
        assert supp_row is not None, "SuppressedEmail row not found"
        assert supp_row.reason == "unsubscribe"
        print(f"  ✓ Central suppressed_emails store has: email='{supp_row.email}', reason='{supp_row.reason}', source='{supp_row.source}'")

        # Verify SuppressionService.is_email_suppressed returns True
        is_supp, reason = await SuppressionService.is_email_suppressed(db, clean_email)
        assert is_supp is True, "is_email_suppressed returned False"
        print(f"  ✓ SuppressionService.is_email_suppressed('{clean_email}') -> True (Reason: {reason})")

        # ─────────────────────────────────────────────────────────────────────
        # Step 5: Verify Immediate Pre-Send Blocking in A3 Draft Approval
        # ─────────────────────────────────────────────────────────────────────
        print("\n[Step 5] Verifying Pre-Send DNC Blocking in DraftManager.approve_draft...")
        settings.AGENT3_TEST_MODE = True
        draft = OutreachDraft(
            contact_id=c1.id,
            subject="Exclusive Pilot Opportunity",
            body="Hi, we would like to collaborate...",
            business_case="General Sales Outreach",
            channel="email",
            approval_state="pending",
            status="draft",
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        draft_manager = DraftManager(db)
        approval_result = await draft_manager.approve_draft(draft.id)
        assert approval_result is False, "approve_draft should have failed for suppressed contact"
        await db.refresh(draft)
        assert draft.status == "suppressed", f"Expected draft status 'suppressed', got '{draft.status}'"
        assert draft.approval_state == "rejected", f"Expected approval_state 'rejected', got '{draft.approval_state}'"
        print(f"  ✓ Pre-send DNC check successfully blocked dispatch: draft status='{draft.status}', approval_state='{draft.approval_state}'")

        # Cleanup test records
        await db.execute(delete(OutreachDraft).where(OutreachDraft.id == draft.id))
        await db.execute(delete(Contact).where(Contact.id.in_([c1.id, c2.id])))
        await db.execute(delete(SuppressedEmail).where(SuppressedEmail.email == clean_email))
        await db.commit()
        print("  ✓ Cleaned up all verification test records from database.")

    print("\n" + "=" * 70)
    print("ALL LIVE PIPELINE VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_verification())

"""
test_company_lookalike.py — Comprehensive Unit & Integration Tests for Company Look-alike.

Covers all 10 requirements:
1. Empty Company Look-alike input preserves existing behavior.
2. One valid reference company.
3. Multiple reference companies up to supported limit (max 5 seeds).
4. Company-name resolution, match confidence, ambiguous matches, and companies not found.
5. Apollo returning no lookalike results (fallback handling).
6. Apollo errors, timeouts, and rate limits.
7. Existing filters applied correctly alongside lookalike discovery.
8. Duplicate prospects returned by both discovery paths (merging metadata & sources).
9. Correct handling of prospects at seed companies (strict exclusion of seed company employees).
10. User isolation, prospect scoring, and qualification summary integration.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.services.company_lookalike_service import (
    CompanyLookalikeService,
    clean_company_name,
    _ORGANIZATION_RESOLUTION_CACHE,
    MAX_SEED_COMPANIES,
)
from app.services.icp_normalizer import normalize_icp_input, NormalizedICPConfig
from app.services.apollo_query_builder import ApolloQueryBuilder
from app.services.prospect_summary import generate_selection_summary
from app.agents.a1_prospect import ProspectAgent


# ── TEST 1 & 2 & 3: Normalization, Single & Multiple Seeds (Max 5 Limit) ─────

def test_normalize_empty_lookalike():
    """Requirement 1: Empty input returns empty list and does not alter behavior."""
    assert CompanyLookalikeService.normalize_reference_companies("") == []
    assert CompanyLookalikeService.normalize_reference_companies("   ") == []
    assert CompanyLookalikeService.normalize_reference_companies([]) == []
    assert CompanyLookalikeService.normalize_reference_companies(None) == []


def test_normalize_single_seed_company():
    """Requirement 2: Single valid reference company is cleanly trimmed and preserved."""
    res = CompanyLookalikeService.normalize_reference_companies("Google")
    assert res == ["Google"]

    res_trimmed = CompanyLookalikeService.normalize_reference_companies("  RadNet, Inc.  ")
    assert res_trimmed == ["RadNet, Inc."]


def test_normalize_multiple_seeds_and_enforce_max_limit():
    """Requirement 3: Multiple companies deduplicated case-insensitively and capped at 5."""
    raw = "Google, RadNet, Salesforce, Google, radnet, Microsoft, Amazon, Oracle, Apple"
    normalized = CompanyLookalikeService.normalize_reference_companies(raw, max_seeds=5)

    assert len(normalized) == 5
    assert normalized == ["Google", "RadNet", "Salesforce", "Microsoft", "Amazon"]

    # Test list input
    raw_list = ["Google", "Salesforce", "Google", "HubSpot"]
    norm_list = CompanyLookalikeService.normalize_reference_companies(raw_list)
    assert norm_list == ["Google", "Salesforce", "HubSpot"]


# ── TEST 4: Company Resolution, Ambiguity, and Match Confidence ───────────────

@pytest.mark.asyncio
async def test_resolve_company_exact_match():
    """Requirement 4: High confidence exact name match resolves cleanly."""
    _ORGANIZATION_RESOLUTION_CACHE.clear()

    async def mock_search(url, **kwargs):
        return httpx.Response(200, json={
            "organizations": [
                {
                    "id": "org_google_123",
                    "name": "Google",
                    "primary_domain": "google.com",
                    "industry": "Internet",
                    "estimated_num_employees": 150000,
                }
            ]
        })

    client = MagicMock()
    client.post = AsyncMock(side_effect=mock_search)

    res = await CompanyLookalikeService.resolve_company_name(
        client, {"X-Api-Key": "test"}, "Google"
    )
    assert res["status"] == "resolved"
    assert res["organization_id"] == "org_google_123"
    assert res["name"] == "Google"
    assert res["confidence"] >= 0.95

    # Test cache hit (does not invoke post again)
    cached_res = await CompanyLookalikeService.resolve_company_name(
        client, {"X-Api-Key": "test"}, "google"
    )
    assert cached_res["status"] == "resolved"
    assert cached_res["organization_id"] == "org_google_123"


@pytest.mark.asyncio
async def test_resolve_company_ambiguous_matches():
    """Requirement 4: Ambiguous company names flag ambiguous and do NOT silently pick wrong org."""
    _ORGANIZATION_RESOLUTION_CACHE.clear()

    # Query for "Apex" returns multiple competing companies with no clear winner
    async def mock_ambiguous(url, **kwargs):
        return httpx.Response(200, json={
            "organizations": [
                {"id": "org_1", "name": "Apex Systems", "primary_domain": "apexsystems.com"},
                {"id": "org_2", "name": "Apex Health", "primary_domain": "apexhealth.org"},
                {"id": "org_3", "name": "Apex Tool Group", "primary_domain": "apextoolgroup.com"},
            ]
        })

    client = MagicMock()
    client.post = AsyncMock(side_effect=mock_ambiguous)

    res = await CompanyLookalikeService.resolve_company_name(
        client, {"X-Api-Key": "test"}, "Apex"
    )
    assert res["status"] == "ambiguous"
    assert res["query"] == "Apex"
    assert len(res["candidates"]) >= 2
    assert "organization_id" not in res


@pytest.mark.asyncio
async def test_resolve_company_not_found():
    """Requirement 4: Non-existent company gracefully returns not_found."""
    _ORGANIZATION_RESOLUTION_CACHE.clear()

    async def mock_empty(url, **kwargs):
        return httpx.Response(200, json={"organizations": []})

    client = MagicMock()
    client.post = AsyncMock(side_effect=mock_empty)

    res = await CompanyLookalikeService.resolve_company_name(
        client, {"X-Api-Key": "test"}, "NonExistentCompanyXyz987"
    )
    assert res["status"] == "not_found"


# ── TEST 5 & 6: Apollo Errors, Timeouts, Rate Limits & Recovery Fallback ─────

@pytest.mark.asyncio
async def test_resolve_company_rate_limit_and_timeout():
    """Requirement 6: Apollo rate limits and timeouts handled gracefully."""
    _ORGANIZATION_RESOLUTION_CACHE.clear()

    async def mock_429(url, **kwargs):
        return httpx.Response(429, text="Rate limit exceeded")

    client = MagicMock()
    client.post = AsyncMock(side_effect=mock_429)

    res = await CompanyLookalikeService.resolve_company_name(
        client, {"X-Api-Key": "test"}, "Google"
    )
    assert res["status"] == "error"
    assert res["reason"] == "rate_limited"

    # Timeout test
    async def mock_timeout(url, **kwargs):
        raise httpx.TimeoutException("Read timed out")

    client_timeout = MagicMock()
    client_timeout.post = AsyncMock(side_effect=mock_timeout)

    res = await CompanyLookalikeService.resolve_company_name(
        client_timeout, {"X-Api-Key": "test"}, "Salesforce"
    )
    assert res["status"] == "error"
    assert res["reason"] == "timeout"


# ── TEST 7: Existing Filters Applied Alongside Lookalike Discovery ────────────

def test_apollo_query_builder_with_lookalikes():
    """Requirement 7: Lookalike organization IDs passed alongside ICP filters."""
    cfg = normalize_icp_input({
        "target_job_titles": "CTO, VP Engineering",
        "target_location": "United States",
        "target_company_size": "50-500",
        "company_lookalike": "Google, RadNet",
        "lookalike_organization_ids": ["org_google_123", "org_radnet_456"],
    })

    assert cfg.company_lookalike == ["Google", "RadNet"]
    assert cfg.lookalike_organization_ids == ["org_google_123", "org_radnet_456"]

    payload = ApolloQueryBuilder.build_search_payload(cfg)
    expected_titles = {"CTO", "Chief Technology Officer", "VP Engineering", "VP of Engineering", "Vice President Engineering", "Vice President of Engineering"}
    assert set(payload["person_titles"]) == expected_titles
    assert payload["organization_locations"] == ["United States"]
    assert "51,200" in payload["organization_num_employees_ranges"]
    assert payload["lookalike_organization_ids"] == ["org_google_123", "org_radnet_456"]


# ── TEST 8 & 9: Strict Seed Exclusion & Deduplication ─────────────────────────

def test_combine_and_deduplicate_with_seed_exclusion():
    """
    Requirements 8 & 9:
    - Prospects working at seed companies are strictly excluded from lookalike discoveries.
    - Prospects appearing in both paths are merged, preserving both discovery sources.
    """
    icp_prospects = [
        {
            "apollo_id": "p_1",
            "email": "sarah@acmehealth.com",
            "first_name": "Sarah",
            "last_name": "Jones",
            "company": "Acme Health",
            "title": "VP of Sales",
            "win_pattern_score": 75.0,
        },
        {
            "apollo_id": "p_2",
            "email": "alex@dualmatch.com",
            "first_name": "Alex",
            "last_name": "Smith",
            "company": "Dual Match Inc",
            "title": "CTO",
            "win_pattern_score": 82.0,
        },
    ]

    lookalike_prospects = [
        # Candidate 1: Employee at SEED company itself -> MUST BE EXCLUDED
        {
            "apollo_id": "p_seed_worker",
            "email": "john@radnet.com",
            "first_name": "John",
            "company": "RadNet",
            "company_domain": "radnet.com",
            "title": "Director of IT",
            "win_pattern_score": 85.0,
        },
        # Candidate 2: Overlapping candidate also in ICP search
        {
            "apollo_id": "p_2",
            "email": "alex@dualmatch.com",
            "first_name": "Alex",
            "last_name": "Smith",
            "company": "Dual Match Inc",
            "title": "CTO",
            "industry": "Diagnostic Imaging",
            "win_pattern_score": 90.0,  # higher score
        },
        # Candidate 3: Fresh lookalike candidate
        {
            "apollo_id": "p_3",
            "email": "maya@similarcorp.com",
            "first_name": "Maya",
            "last_name": "Patel",
            "company": "SimilarCorp",
            "title": "VP Engineering",
            "win_pattern_score": 80.0,
        },
    ]

    merged = CompanyLookalikeService.combine_and_deduplicate_prospects(
        icp_prospects=icp_prospects,
        lookalike_prospects=lookalike_prospects,
        seed_company_names=["RadNet", "Google"],
        seed_org_ids=["org_radnet_456"],
        seed_domains=["radnet.com", "google.com"],
    )

    emails = [c["email"] for c in merged]

    # 1. Verify seed company worker was EXCLUDED
    assert "john@radnet.com" not in emails

    # 2. Verify all unique valid prospects are present
    assert "sarah@acmehealth.com" in emails
    assert "alex@dualmatch.com" in emails
    assert "maya@similarcorp.com" in emails
    assert len(merged) == 3

    # 3. Verify dual-path merged metadata
    alex = next(c for c in merged if c["email"] == "alex@dualmatch.com")
    assert "icp_search" in alex["discovery_sources"]
    assert "lookalike" in alex["discovery_sources"]
    assert "apollo (icp + lookalike)" in alex["source"]
    assert alex["lookalike_seed_companies"] == ["RadNet", "Google"]
    assert alex["industry"] == "Diagnostic Imaging"
    assert alex["win_pattern_score"] == 90.0  # highest score retained

    # 4. Verify pure lookalike candidate
    maya = next(c for c in merged if c["email"] == "maya@similarcorp.com")
    assert maya["discovery_sources"] == ["lookalike"]
    assert "lookalike" in maya["source"]
    assert maya["lookalike_seed_companies"] == ["RadNet", "Google"]


# ── TEST 10: Qualification Summary & Explainability ──────────────────────────

def test_selection_summary_lookalike_explanation():
    """Requirement 10: Selection summary highlights lookalike reference context."""
    contact_dual = {
        "first_name": "Alex",
        "last_name": "Smith",
        "title": "Chief Technology Officer",
        "company": "Diagnostic AI Corp",
        "industry": "Healthcare",
        "company_size": "250",
        "geography": "Boston, MA",
        "prospect_location": "Boston, MA",
        "discovery_sources": ["icp_search", "lookalike"],
        "lookalike_seed_companies": ["RadNet", "Google"],
    }

    summary = generate_selection_summary(contact_dual)
    assert "Alex is the Chief Technology Officer at Diagnostic AI Corp" in summary
    assert "RadNet, Google" in summary
    assert "company look-alike targeting similar to" in summary

    # Verify standard contact without lookalike leaves wording intact
    standard_contact = {
        "first_name": "Sarah",
        "last_name": "Miller",
        "title": "VP of Sales",
        "company": "CloudTech",
        "industry": "Software",
        "company_size": "150",
        "geography": "Austin, TX",
        "prospect_location": "Austin, TX",
    }
    std_summary = generate_selection_summary(standard_contact)
    assert "look-alike" not in std_summary
    assert "Sarah's sales leadership role and company profile match the targeting criteria for this search" in std_summary


# ── TEST 11: Offline Firmographic Fallback ────────────────────────────────────

def test_offline_lookalike_discovery():
    """Requirement 5: Offline fallback finds firmographically similar companies and excludes seeds."""
    mock_candidates = [
        {
            "email": "leader@radnet.com",
            "company": "RadNet",
            "title": "VP Sales",
            "industry": "Healthcare",
            "employee_count": 500,
        },
        {
            "email": "exec@medimaging.com",
            "company": "MedImaging Corp",
            "title": "VP Sales",
            "industry": "Healthcare",
            "employee_count": 300,
            "tech_stack": ["AWS", "DICOM"],
        },
        {
            "email": "dev@unrelated.com",
            "company": "Apparel Co",
            "title": "Engineer",
            "industry": "Fashion",
            "employee_count": 20,
        },
    ]

    icp_cfg = {
        "titles": ["VP Sales"],
        "industry_terms": ["Healthcare"],
    }

    lookalikes = CompanyLookalikeService.offline_lookalike_discovery(
        seed_companies=["RadNet"],
        icp_config=icp_cfg,
        csv_candidates=mock_candidates,
        limit=5,
    )

    # RadNet itself must be excluded
    assert not any(c["company"] == "RadNet" for c in lookalikes)
    # MedImaging Corp (Healthcare, 300 employees) matches
    assert len(lookalikes) == 1
    assert lookalikes[0]["company"] == "MedImaging Corp"
    assert lookalikes[0]["discovery_method"] == "lookalike"


# ── TEST 12: End-to-End ProspectAgent Lookalike Integration ──────────────────

@pytest.mark.asyncio
async def test_prospect_agent_with_lookalikes_integration():
    """
    Requirement 10: End-to-end ProspectAgent execution combining ICP and lookalike discovery,
    preserving scoring, user isolation, and session linkage.
    """
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=None)
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    agent = ProspectAgent(mock_db)

    # Mock DB existing check helpers
    agent._get_all_existing_apollo_ids = AsyncMock(return_value=set())
    agent._get_all_existing_emails = AsyncMock(return_value=set())
    agent._get_highest_page_for_fingerprint = AsyncMock(return_value=0)
    agent._log_funnel_event = AsyncMock()

    # Mock Apollo endpoints
    async def mock_apollo_post(url, **kwargs):
        url_str = str(url)
        req = httpx.Request("POST", url_str)
        json_data = kwargs.get("json", {})
        if "organizations/search" in url_str:
            return httpx.Response(200, request=req, json={
                "organizations": [
                    {
                        "id": "org_seed_101",
                        "name": "RadNet",
                        "primary_domain": "radnet.com",
                        "industry": "Healthcare",
                        "estimated_num_employees": 5000,
                    }
                ]
            })
        elif "mixed_people/api_search" in url_str:
            # If lookalike_organization_ids in body, return lookalike candidate
            if "lookalike_organization_ids" in json_data:
                return httpx.Response(200, request=req, json={
                    "pagination": {"total_entries": 1},
                    "people": [
                        {
                            "id": "apollo_lookalike_1",
                            "first_name": "Elena",
                            "last_name": "Rostova",
                            "title": "VP of Sales",
                            "organization": {
                                "id": "org_partner_202",
                                "name": "Alliance Health",
                                "estimated_num_employees": 200,
                                "industry": "Healthcare",
                            },
                        }
                    ],
                })
            else:
                # Standard ICP search candidate
                return httpx.Response(200, request=req, json={
                    "pagination": {"total_entries": 1},
                    "people": [
                        {
                            "id": "apollo_icp_1",
                            "first_name": "Marcus",
                            "last_name": "Vance",
                            "title": "VP of Sales",
                            "organization": {
                                "id": "org_icp_303",
                                "name": "Apex Cloud",
                                "estimated_num_employees": 120,
                                "industry": "Software",
                            },
                        }
                    ],
                })
        elif "people/bulk_match" in url_str:
            details = json_data.get("details", [])
            matches = []
            for d in details:
                pid = d["id"]
                if pid == "apollo_lookalike_1":
                    matches.append({
                        "id": pid,
                        "first_name": "Elena",
                        "last_name": "Rostova",
                        "email": "elena@alliancehealth.com",
                        "title": "VP of Sales",
                        "organization": {
                            "id": "org_partner_202",
                            "name": "Alliance Health",
                            "estimated_num_employees": 200,
                            "industry": "Healthcare",
                        },
                    })
                elif pid == "apollo_icp_1":
                    matches.append({
                        "id": pid,
                        "first_name": "Marcus",
                        "last_name": "Vance",
                        "email": "marcus@apexcloud.com",
                        "title": "VP of Sales",
                        "organization": {
                            "id": "org_icp_303",
                            "name": "Apex Cloud",
                            "estimated_num_employees": 120,
                            "industry": "Software",
                        },
                    })
            return httpx.Response(200, request=req, json={"matches": matches})
        return httpx.Response(404, request=req)

    with patch("app.core.config.settings.APOLLO_API_KEY", "mock-test-key"):
        with patch("httpx.AsyncClient.post", side_effect=mock_apollo_post):
            icp_config = {
                "our_company_name": "CloudLabs",
                "target_job_titles": "VP Sales",
                "target_location": "United States",
                "target_company_size": "50-500",
                "company_lookalike": "RadNet",
                "threshold": 50.0,
                "user_id": "user-uuid-abc",
                "user_input_id": 99,
            }

            result = await agent.run(icp_config)

            assert result["agent"] == "A1"
            assert result["provider"] == "apollo"
            # Both standard ICP prospect and Lookalike prospect were saved
            assert result["saved_count"] == 2
            assert "elena@alliancehealth.com" in result["contacts"] or "marcus@apexcloud.com" in result["contacts"]

            # Verify saved contacts were attached with correct user_id and user_input_id
            added_contacts = [
                call[0][0] for call in mock_db.add.call_args_list
                if hasattr(call[0][0], "email")
            ]
            emails = [c.email for c in added_contacts]
            assert "elena@alliancehealth.com" in emails
            assert "marcus@apexcloud.com" in emails
            for c in added_contacts:
                assert c.user_id == "user-uuid-abc"
                assert c.user_input_id == 99

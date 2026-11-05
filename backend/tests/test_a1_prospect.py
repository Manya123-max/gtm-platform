"""
Unit & Integration Tests for Agent 1 (A1) Prospect Agent.
All Apollo HTTP responses are strictly mocked. Zero real network calls.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.core.database import init_db, close_db, AsyncSessionLocal
from app.models.models import Contact, UserInput, FunnelEvent, User
from app.agents.a1_prospect import ProspectAgent
from app.services.icp_normalizer import normalize_icp_input, NormalizedICPConfig
from app.services.apollo_query_builder import ApolloQueryBuilder
from app.agents.industry_tag_map import INDUSTRY_TAG_MAP


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session():
    await init_db()
    async with AsyncSessionLocal() as session:
        yield session


# ── Test A: ICP Normalization ────────────────────────────────────────────────

def test_icp_normalization_comprehensive():
    raw_input = {
        "our_company_name": "CloudLabs",
        "our_services": "AI Consulting, Cloud Migration",
        "target_location": "United States, UK",
        "target_industries": "SaaS, Fintech, Quantum Computing",
        "target_company_size": "51-500",
        "target_keywords": "kubernetes, machine learning",
        "target_job_titles": "VP Sales, CRO, Head of Sales",
        "user_id": "test-user-123",
        "user_input_id": 42,
    }

    norm = normalize_icp_input(raw_input)

    # 1. Location mapping
    assert "United States" in norm.organization_locations
    assert "United Kingdom" in norm.organization_locations

    # 2. Company size mapping to discrete Apollo buckets
    assert "51,200" in norm.employee_ranges
    assert "201,500" in norm.employee_ranges

    # 3. Industry tag resolution
    assert INDUSTRY_TAG_MAP["saas"] in norm.industry_tag_ids
    assert INDUSTRY_TAG_MAP["fintech"] in norm.industry_tag_ids
    # "quantum computing" is unmatched, should be folded into org_keyword_tags
    assert "quantum computing" in norm.org_keyword_tags

    # 4. Target keywords
    assert "kubernetes" in norm.org_keyword_tags
    assert "machine learning" in norm.org_keyword_tags

    # 5. Vendor services strictly isolated
    assert "AI Consulting" not in norm.org_keyword_tags
    assert "Cloud Migration" not in norm.org_keyword_tags
    assert norm.vendor_services == "AI Consulting, Cloud Migration"

    # 6. Titles and seniorities
    assert any("VP" in t or "Vice President" in t for t in norm.titles)
    assert any("CRO" in t or "Chief Revenue Officer" in t for t in norm.titles)
    assert "vp" in norm.seniorities
    assert "c_suite" in norm.seniorities
    assert "head" in norm.seniorities

    # 7. Metadata
    assert norm.user_id == "test-user-123"
    assert norm.user_input_id == 42
    assert norm.requested_count == 25


# ── Test B: Seniority Inference ──────────────────────────────────────────────

def test_seniority_inference():
    tests = [
        ("CTO, Chief Technology Officer", ["c_suite"]),
        ("VP Engineering, Vice President Sales", ["vp"]),
        ("Head of Product, Head of AI", ["head"]),
        ("Director of Security", ["director"]),
        ("Engineering Manager", ["manager"]),
        ("Lead Data Scientist, Senior Engineer", ["senior"]),
        ("Founder, Co-Founder", ["founder"]),
    ]

    for titles, expected_seniorities in tests:
        norm = normalize_icp_input({"target_job_titles": titles})
        for sen in expected_seniorities:
            assert sen in norm.seniorities, f"Expected {sen} for {titles}, got {norm.seniorities}"


# ── Test C & D: Apollo Query Builder & Vendor Service Isolation ──────────────

def test_apollo_query_builder():
    raw_input = {
        "our_services": "DevOps Consulting",
        "target_location": "US",
        "target_industries": "SaaS",
        "target_company_size": "50-200",
        "target_keywords": "b2b, enterprise",
        "target_job_titles": "VP Sales, CRO",
    }
    norm = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(norm, page=2, per_page=50)

    # Validate exact Apollo parameter names
    assert payload["page"] == 2
    assert payload["per_page"] == 50
    assert payload["organization_locations"] == ["United States"]
    assert "51,200" in payload["organization_num_employees_ranges"]
    assert payload["organization_industry_tag_ids"] == [INDUSTRY_TAG_MAP["saas"]]
    assert "b2b" in payload["q_organization_keyword_tags"]
    assert "enterprise" in payload["q_organization_keyword_tags"]
    assert "DevOps Consulting" not in payload["q_organization_keyword_tags"]
    assert "c_suite" in payload["person_seniorities"]
    assert "vp" in payload["person_seniorities"]

    # Check sanitized representation
    sanitized = ApolloQueryBuilder.to_sanitized_dict(payload)
    assert "api_key" not in sanitized
    assert "token" not in sanitized


# ── TEST 1: Prequalification Happens Before Enrichment ───────────────────────

@pytest.mark.asyncio
async def test_prequalification_before_enrichment(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Generate 100 search stubs:
    # 20 valid VP Sales at Software Co (pre-qualifies)
    # 80 Interns or Assistants (fails pre-qualification)
    stubs = []
    for i in range(100):
        if i < 20:
            stubs.append({
                "id": f"apollo-qual-{test_run_id}-{i}",
                "first_name": f"Leader{i}",
                "last_name": "Sales",
                "title": "VP of Sales",
                "organization": {
                    "id": f"org-q-{test_run_id}-{i}",
                    "name": f"CloudTech {i}",
                    "country": "United States",
                    "estimated_num_employees": 150,
                    "industry": "Software",
                },
            })
        else:
            stubs.append({
                "id": f"apollo-unqual-{test_run_id}-{i}",
                "first_name": f"Intern{i}",
                "last_name": "Student",
                "title": "Summer Intern",
                "organization": {
                    "id": f"org-unq-{test_run_id}-{i}",
                    "name": f"Unrelated Org {i}",
                    "country": "United States",
                    "estimated_num_employees": 150,
                },
            })

    enriched_ids: List[str] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 100}, "people": stubs})
        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = []
            for d in details:
                pid = d["id"]
                enriched_ids.append(pid)
                matches.append({
                    "id": pid,
                    "first_name": "Leader",
                    "last_name": "Sales",
                    "email": f"{pid}@cloudtech.com",
                    "title": "VP of Sales",
                    "organization": {"name": "CloudTech", "estimated_num_employees": 150, "industry": "Software"},
                })
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "United States",
            "target_company_size": "51-500",
            "requested_count": 20,
            "threshold": 60,
        }
        result = await agent.run(config)

    # 1. Exactly the 20 pre-qualified candidates were sent to bulk_match
    assert len(enriched_ids) == 20
    assert all("apollo-qual" in pid for pid in enriched_ids)
    # 2. None of the 80 interns entered bulk_match
    assert not any("apollo-unqual" in pid for pid in enriched_ids)
    assert result["telemetry"]["prequalification_rejected"] == 80
    assert result["telemetry"]["prequalified_candidates"] == 20


# ── TEST 2: Never Enrich Obviously Unqualified Candidates ────────────────────

@pytest.mark.asyncio
async def test_never_enrich_obviously_unqualified_candidates(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    stubs = [
        # Wrong title / role
        {
            "id": f"unq-title-{test_run_id}",
            "first_name": "Bob",
            "last_name": "Helper",
            "title": "Administrative Assistant to CEO",
            "organization": {"name": "Tech Corp", "country": "United States", "estimated_num_employees": 100},
        },
        # Wrong country (Germany when targeting US)
        {
            "id": f"unq-loc-{test_run_id}",
            "first_name": "Hans",
            "last_name": "Schmidt",
            "title": "VP of Sales",
            "organization": {"name": "Berlin Tech", "country": "Germany", "estimated_num_employees": 100},
        },
        # Wrong size (15,000 employees when targeting 51-500)
        {
            "id": f"unq-size-{test_run_id}",
            "first_name": "Alice",
            "last_name": "BigCorp",
            "title": "VP Sales",
            "organization": {"name": "MegaCorp", "country": "United States", "estimated_num_employees": 15000},
        },
        # Valid candidate
        {
            "id": f"qual-lead-{test_run_id}",
            "first_name": "Sarah",
            "last_name": "Valid",
            "title": "VP Sales",
            "organization": {"name": "SaaS Co", "country": "United States", "estimated_num_employees": 150},
        },
    ]

    bulk_match_ids: List[str] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 4}, "people": stubs})
        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            for d in details:
                bulk_match_ids.append(d["id"])
            return httpx.Response(200, json={"matches": [{
                "id": f"qual-lead-{test_run_id}",
                "first_name": "Sarah",
                "last_name": "Valid",
                "email": f"sarah-{test_run_id}@saasco.com",
                "title": "VP Sales",
                "organization": {"name": "SaaS Co", "estimated_num_employees": 150, "industry": "Software"},
            }]})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "United States",
            "target_company_size": "51-500",
            "requested_count": 5,
            "threshold": 60,
        }
        result = await agent.run(config)

    # Only the 1 valid candidate was enriched
    assert bulk_match_ids == [f"qual-lead-{test_run_id}"]
    assert result["telemetry"]["prequalification_rejected"] == 3


# ── TEST 3: Replenishment Across Pages Until 25 Final Qualified ──────────────

@pytest.mark.asyncio
async def test_replenishment_across_pages(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Page 1: 10 qualified
    p1 = [
        {
            "id": f"p1-{test_run_id}-{i}",
            "first_name": f"P1User{i}",
            "last_name": "Lead",
            "title": "VP of Sales",
            "organization": {"name": f"P1 Corp {i}", "country": "United States", "estimated_num_employees": 150, "industry": "Software"},
        }
        for i in range(10)
    ]
    # Page 2: 10 qualified
    p2 = [
        {
            "id": f"p2-{test_run_id}-{i}",
            "first_name": f"P2User{i}",
            "last_name": "Lead",
            "title": "Chief Revenue Officer",
            "organization": {"name": f"P2 Corp {i}", "country": "United States", "estimated_num_employees": 200, "industry": "Software"},
        }
        for i in range(10)
    ]
    # Page 3: 10 qualified (5 needed to reach 25)
    p3 = [
        {
            "id": f"p3-{test_run_id}-{i}",
            "first_name": f"P3User{i}",
            "last_name": "Lead",
            "title": "Head of Sales",
            "organization": {"name": f"P3 Corp {i}", "country": "United States", "estimated_num_employees": 120, "industry": "Software"},
        }
        for i in range(10)
    ]

    pages_called: List[int] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            pages_called.append(page)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p2})
            elif page == 3:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p3})
            return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "User",
                    "last_name": "Lead",
                    "email": f"{d['id']}@company.com",
                    "title": "VP of Sales",
                    "organization": {"name": "Corp", "estimated_num_employees": 150, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales, CRO, Head of Sales",
            "target_location": "United States",
            "target_company_size": "51-500",
            "requested_count": 25,
            "threshold": 60,
        }
        result = await agent.run(config)

    # All 3 pages were traversed sequentially
    assert pages_called == [1, 2, 3]
    assert result["qualified_count"] == 25
    assert result["saved_count"] == 25


# ── TEST 4: 7-Day Deduplication Searches Deeper ───────────────────────────────

@pytest.mark.asyncio
async def test_7_day_deduplication_searches_deeper(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Pre-populate 5 contacts in database enriched 2 days ago
    for i in range(5):
        db_session.add(
            Contact(
                email=f"recent{i}-{test_run_id}@existing.com",
                first_name="Recent",
                last_name=f"Lead{i}",
                title="VP Sales",
                apollo_id=f"apollo-recent-{test_run_id}-{i}",
                enriched_at=datetime.utcnow() - timedelta(days=2),
            )
        )
    await db_session.commit()

    # Page 1 contains the 5 recently enriched contacts + 5 fresh contacts
    p1 = [
        {
            "id": f"apollo-recent-{test_run_id}-{i}",
            "first_name": f"Recent{i}",
            "last_name": "Lead",
            "title": "VP Sales",
            "organization": {"name": "Old Corp", "country": "United States", "estimated_num_employees": 150, "industry": "Software"},
        }
        for i in range(5)
    ] + [
        {
            "id": f"apollo-p1-fresh-{test_run_id}-{i}",
            "first_name": f"FreshP1{i}",
            "last_name": "Lead",
            "title": "VP Sales",
            "organization": {"name": "Fresh Corp", "country": "United States", "estimated_num_employees": 150, "industry": "Software"},
        }
        for i in range(5)
    ]

    # Page 2 contains 10 fresh contacts to satisfy requested_count = 10
    p2 = [
        {
            "id": f"apollo-p2-fresh-{test_run_id}-{i}",
            "first_name": f"FreshP2{i}",
            "last_name": "Lead",
            "title": "VP Sales",
            "organization": {"name": "Fresh Corp 2", "country": "United States", "estimated_num_employees": 150, "industry": "Software"},
        }
        for i in range(10)
    ]

    enriched_ids: List[str] = []
    pages_called: List[int] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            pages_called.append(page)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p2})
            return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            for d in details:
                enriched_ids.append(d["id"])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Fresh",
                    "last_name": "Lead",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Fresh Corp", "estimated_num_employees": 150, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    recent_ids = [f"apollo-recent-{test_run_id}-{i}" for i in range(5)]

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 15,
            "threshold": 60,
        }

        res = await agent.run(config)
        assert res["qualified_count"] == 15
        # Verify 7-day excluded candidates were NEVER enriched
        for r_id in recent_ids:
            assert r_id not in enriched_ids
        assert res["telemetry"]["recently_enriched_excluded"] == 5
        assert 1 in pages_called and 2 in pages_called


# ── TEST 5: Insufficient First Page Continues to Target ──────────────────────


@pytest.mark.asyncio
async def test_insufficient_first_page_continues_to_target(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Page 1: 5 qualified
    p1 = [{"id": f"p1-{test_run_id}-{i}", "first_name": f"P1User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P1Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(5)]
    # Page 2: 8 qualified
    p2 = [{"id": f"p2-{test_run_id}-{i}", "first_name": f"P2User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P2Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(8)]
    # Page 3: 15 qualified (12 needed)
    p3 = [{"id": f"p3-{test_run_id}-{i}", "first_name": f"P3User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P3Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(15)]

    pages_called: List[int] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            pages_called.append(page)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p2})
            elif page == 3:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p3})
            return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Test",
                    "last_name": "User",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Corp", "estimated_num_employees": 100, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 25,
            "threshold": 60,
        }
        result = await agent.run(config)

    assert pages_called == [1, 2, 3]
    assert result["qualified_count"] == 25


# ── TEST 6: Apollo Exhausted Returns Exact Count (No DB Hijack) ───────────────

@pytest.mark.asyncio
async def test_apollo_exhausted_returns_exact_count(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Insert 10 legacy DB contacts that MUST NOT be hijacked
    for i in range(10):
        db_session.add(
            Contact(
                email=f"legacy-{test_run_id}-{i}@oldcorp.com",
                first_name="Old",
                last_name="User",
                title="VP Sales",
                user_input_id=None,
            )
        )
    await db_session.commit()

    # Apollo has only 17 prospects total across 2 pages, then exhausts on page 3
    p1 = [{"id": f"p1-{test_run_id}-{i}", "first_name": f"P1User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P1Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(10)]
    p2 = [{"id": f"p2-{test_run_id}-{i}", "first_name": f"P2User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P2Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(7)]

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": p2})
            return httpx.Response(200, json={"pagination": {"total_entries": 300}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Test",
                    "last_name": "User",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Corp", "estimated_num_employees": 100, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 25,  # Requested 25, but only 17 exist
            "threshold": 60,
        }
        result = await agent.run(config)

    # Returns exactly 17 prospects with exhaustion reason
    assert result["qualified_count"] == 17
    assert result["saved_count"] == 17
    assert result["telemetry"]["exhaustion_reason"] == "apollo_exhausted"


# ── TEST 7: Enrichment Batching In Chunks of 10 ───────────────────────────────

@pytest.mark.asyncio
async def test_enrichment_batching_chunks_of_10(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # 25 candidates to enrich in one page
    people = [
        {
            "id": f"apollo-{test_run_id}-{i}",
            "first_name": f"Lead{i}",
            "last_name": "Test",
            "title": "VP Sales",
            "organization": {"name": f"Company {i}", "country": "US", "estimated_num_employees": 150, "industry": "Software"},
        }
        for i in range(25)
    ]

    bulk_match_batch_sizes: List[int] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 25}, "people": people})
        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            bulk_match_batch_sizes.append(len(details))
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Lead",
                    "last_name": "Test",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Company", "estimated_num_employees": 150, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 25,
            "threshold": 60,
        }
        result = await agent.run(config)

    # Bulk match must be called in batches of [10, 10, 5]
    assert bulk_match_batch_sizes == [10, 10, 5], f"Expected [10, 10, 5], got {bulk_match_batch_sizes}"
    assert result["qualified_count"] == 25


# ── TEST 8: No Duplicate Apollo IDs Across Overlapping Pages ─────────────────

@pytest.mark.asyncio
async def test_no_duplicate_apollo_ids_across_pages(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Page 1: 5 leads
    p1 = [{"id": f"lead-{test_run_id}-{i}", "first_name": f"P1User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P1Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(5)]
    # Page 2: 3 duplicate leads from Page 1 + 5 new leads
    p2 = [
        {"id": f"lead-{test_run_id}-0", "first_name": "P1User0", "last_name": "Lead", "title": "VP Sales", "organization": {"name": "P1Corp0", "country": "US", "estimated_num_employees": 100, "industry": "Software"}},
        {"id": f"lead-{test_run_id}-1", "first_name": "P1User1", "last_name": "Lead", "title": "VP Sales", "organization": {"name": "P1Corp1", "country": "US", "estimated_num_employees": 100, "industry": "Software"}},
        {"id": f"lead-{test_run_id}-2", "first_name": "P1User2", "last_name": "Lead", "title": "VP Sales", "organization": {"name": "P1Corp2", "country": "US", "estimated_num_employees": 100, "industry": "Software"}},
    ] + [{"id": f"lead-{test_run_id}-{i}", "first_name": f"P2User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P2Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(5, 10)]

    enriched_ids: List[str] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p2})
            return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            for d in details:
                enriched_ids.append(d["id"])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Test",
                    "last_name": "User",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Corp", "estimated_num_employees": 100, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 10,
            "threshold": 60,
        }
        result = await agent.run(config)

    # Every Apollo ID was enriched at most once
    assert len(enriched_ids) == len(set(enriched_ids)) == 10
    assert result["telemetry"]["duplicate_candidates"] >= 3


# ── TEST 9: Final Threshold Replenishes Rather Than Lowering ─────────────────

@pytest.mark.asyncio
async def test_final_threshold_replenishes_rather_than_lowering(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Page 1: 10 people, but after enrichment 6 have poor scores (< 70) and 4 pass
    p1 = [{"id": f"p1-{test_run_id}-{i}", "first_name": f"P1User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P1Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(10)]
    # Page 2: 10 people, after enrichment 6 pass
    p2 = [{"id": f"p2-{test_run_id}-{i}", "first_name": f"P2User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P2Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(10)]

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p2})
            return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = []
            for d in details:
                pid = d["id"]
                idx = int(pid.split("-")[-1])
                if "p1" in pid:
                    # 4 pass (VP Sales + Software + 100), 6 fail (Associate)
                    title = "VP Sales" if idx < 4 else "Sales Associate"
                else:
                    title = "VP Sales" if idx < 6 else "Sales Associate"
                matches.append({
                    "id": pid,
                    "first_name": "Test",
                    "last_name": "User",
                    "email": f"{pid}@company.com",
                    "title": title,
                    "organization": {"name": "Corp", "estimated_num_employees": 100, "industry": "Software"},
                })
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 10,
            "threshold": 70,  # High threshold
        }
        result = await agent.run(config)

    # 4 from P1 + 6 from P2 = 10 qualified
    assert result["qualified_count"] == 10
    # Verified threshold was strictly applied: no associates in final contacts
    for email in result["contacts"]:
        assert not email.endswith(("-4@company.com", "-5@company.com", "-6@company.com"))


# ── TEST 10: Same ICP Repeated Searches Deeper ───────────────────────────────

@pytest.mark.asyncio
async def test_same_icp_repeated_searches_deeper(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    # Shared Apollo database of candidates
    p1 = [{"id": f"p1-{test_run_id}-{i}", "first_name": f"P1User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P1Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(10)]
    p2 = [{"id": f"p2-{test_run_id}-{i}", "first_name": f"P2User{i}", "last_name": "Lead", "title": "VP Sales", "organization": {"name": f"P2Corp{i}", "country": "US", "estimated_num_employees": 100, "industry": "Software"}} for i in range(10)]

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            page = json_data.get("page", 1)
            if page == 1:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p1})
            elif page == 2:
                return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": p2})
            return httpx.Response(200, json={"pagination": {"total_entries": 200}, "people": []})

        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Test",
                    "last_name": "User",
                    "email": f"{d['id']}@company.com",
                    "title": "VP Sales",
                    "organization": {"name": "Corp", "estimated_num_employees": 100, "industry": "Software"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "requested_count": 10,
            "threshold": 60,
        }

        # ── RUN 1: Discovers and enriches 10 prospects from Page 1
        res1 = await agent.run(config)
        assert res1["qualified_count"] == 10
        assert res1["telemetry"]["pages_requested"] == 1

        # ── RUN 2: Same ICP. Page 1 candidates are now in 7-day exclusion, so A1 paginates to Page 2!
        res2 = await agent.run(config)
        assert res2["qualified_count"] == 10
        assert res2["telemetry"]["pages_requested"] == 2
        assert res2["telemetry"]["recently_enriched_excluded"] == 10



# ── TEST J: Empty Apollo Search (No Database Hijack Hack) ────────────────────

@pytest.mark.asyncio
async def test_empty_search_does_not_hijack_database(db_session):
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    ui = UserInput(
        our_company_name="TestCo",
        our_services="Consulting",
        target_location="Antarctica",
        target_company_size="10-50",
        target_job_titles="Nonexistent Role",
    )
    db_session.add(ui)
    await db_session.flush()

    for i in range(5):
        db_session.add(
            Contact(
                email=f"legacy{i}-{test_run_id}@oldcorp.com",
                first_name="Legacy",
                last_name=f"User{i}",
                title="Accountant",
                user_input_id=None,
            )
        )
    await db_session.commit()

    async def mock_post(url, **kwargs):
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 0}, "people": []})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "Nonexistent Role",
            "target_location": "Antarctica",
            "user_input_id": ui.id,
        }
        result = await agent.run(config)

    assert result["qualified_count"] == 0
    assert result["saved_count"] == 0
    assert result["contact_ids"] == []

    legacy_res = await db_session.execute(select(Contact).where(Contact.user_input_id == ui.id))
    hijacked = legacy_res.scalars().all()
    assert len(hijacked) == 0, "Database fallback hack was invoked! It must return 0 results."


# ── TEST K: Multi-User Isolation ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_user_isolation(db_session):
    agent = ProspectAgent(db_session)
    user_id_1 = str(uuid.uuid4())
    test_run_id = uuid.uuid4().hex[:6]

    user = User(id=user_id_1, name="Test User", email=f"user-{test_run_id}@example.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    ui = UserInput(
        our_company_name="MyCo",
        our_services="Sales",
        target_location="US",
        target_company_size="50-200",
        target_job_titles="VP Sales",
        user_id=user_id_1,
    )
    db_session.add(ui)
    await db_session.flush()

    user1_email = f"charlie-{test_run_id}@saasco.com"
    search_people = [
        {
            "id": f"apollo-user1-lead-{test_run_id}",
            "first_name": "Charlie",
            "last_name": "Brown",
            "title": "VP Sales",
            "organization": {"name": "SaaS Co", "country": "US", "estimated_num_employees": 100, "industry": "Software"},
        }
    ]
    enriched_matches = [
        {
            "id": f"apollo-user1-lead-{test_run_id}",
            "first_name": "Charlie",
            "last_name": "Brown",
            "email": user1_email,
            "title": "VP Sales",
            "organization": {"name": "SaaS Co", "estimated_num_employees": 100, "industry": "Software"},
        }
    ]

    async def mock_post(url, **kwargs):
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 1}, "people": search_people})
        elif "people/bulk_match" in str(url):
            return httpx.Response(200, json={"matches": enriched_matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "VP Sales",
            "target_location": "US",
            "user_id": user_id_1,
            "user_input_id": ui.id,
            "threshold": 50,
        }
        result = await agent.run(config)

    res = await db_session.execute(select(Contact).where(Contact.email == user1_email))
    contact = res.scalar_one_or_none()
    assert contact is not None
    assert contact.user_id == user_id_1
    assert contact.user_input_id == ui.id


# ── TEST L: Apollo Error Handling ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apollo_error_handling(db_session):
    agent = ProspectAgent(db_session)

    # 1. Test HTTP 429 Rate Limit
    async def mock_429(url, **kwargs):
        return httpx.Response(429, text="Rate limit exceeded")

    with patch("httpx.AsyncClient.post", side_effect=mock_429):
        res = await agent.run({"target_job_titles": "VP Sales"})
        assert res["qualified_count"] == 0
        assert "429" in res["reason"] or "http_429" in res["telemetry"]["exhaustion_reason"]

    # 2. Test HTTP 500 Server Error
    async def mock_500(url, **kwargs):
        return httpx.Response(500, text="Internal Server Error")

    with patch("httpx.AsyncClient.post", side_effect=mock_500):
        res = await agent.run({"target_job_titles": "VP Sales"})
        assert res["qualified_count"] == 0
        assert "500" in res["reason"] or "http_500" in res["telemetry"]["exhaustion_reason"]

    # 3. Test Timeout Exception
    async def mock_timeout(url, **kwargs):
        raise httpx.ReadTimeout("Request timed out")

    with patch("httpx.AsyncClient.post", side_effect=mock_timeout):
        res = await agent.run({"target_job_titles": "VP Sales"})
        assert res["qualified_count"] == 0
        assert "failed" in res["reason"] or "apollo_request_failed" in res["telemetry"]["exhaustion_reason"]


# ── TEST M: Hard Industry Qualification Rejects Unrelated Industries ─────────

@pytest.mark.asyncio
async def test_hard_industry_qualification_rejects_unrelated_industries(db_session):
    """
    Verifies that for an ICP targeting 'Health Care', candidates from unrelated
    industries (Apparel, Government, Translation, Computer Hardware, Networking,
    Consulting, Insurance) are rejected at the search stub stage and NEVER sent to bulk_match,
    even if they have senior CTO/CIO titles.
    """
    agent = ProspectAgent(db_session)
    test_run_id = uuid.uuid4().hex[:6]

    candidates = [
        # Qualified Healthcare candidates
        {"id": f"hosp-{test_run_id}", "first_name": "Alice", "last_name": "Doc", "title": "Chief Technology Officer", "organization": {"name": "General Hospital", "country": "US", "estimated_num_employees": 200, "industry": "Hospital & Health Care"}},
        {"id": f"med-{test_run_id}", "first_name": "Bob", "last_name": "Doc", "title": "Chief Information Officer", "organization": {"name": "Metro Clinic", "country": "US", "estimated_num_employees": 150, "industry": "Medical Practice"}},
        {"id": f"hc-{test_run_id}", "first_name": "Carol", "last_name": "Doc", "title": "VP Engineering", "organization": {"name": "Health Plus", "country": "US", "estimated_num_employees": 100, "industry": "Health Care"}},

        # Unrelated industries that MUST be rejected
        {"id": f"apparel-{test_run_id}", "first_name": "Dan", "last_name": "Style", "title": "Chief Technology Officer", "organization": {"name": "Fashion Hub", "country": "US", "estimated_num_employees": 200, "industry": "Apparel & Fashion"}},
        {"id": f"gov-{test_run_id}", "first_name": "Eve", "last_name": "Civil", "title": "Chief Information Officer", "organization": {"name": "City Dept", "country": "US", "estimated_num_employees": 300, "industry": "Government Administration"}},
        {"id": f"trans-{test_run_id}", "first_name": "Frank", "last_name": "Lang", "title": "Chief Technology Officer", "organization": {"name": "Lingua Corp", "country": "US", "estimated_num_employees": 100, "industry": "Translation & Localization"}},
        {"id": f"hw-{test_run_id}", "first_name": "Grace", "last_name": "Chip", "title": "VP Technology", "organization": {"name": "Hardware Corp", "country": "US", "estimated_num_employees": 200, "industry": "Computer Hardware"}},
        {"id": f"net-{test_run_id}", "first_name": "Heidi", "last_name": "Router", "title": "Chief Technology Officer", "organization": {"name": "Cisco Partner", "country": "US", "estimated_num_employees": 150, "industry": "Computer Networking"}},
        {"id": f"consult-{test_run_id}", "first_name": "Ivan", "last_name": "Advisor", "title": "Chief Information Officer", "organization": {"name": "Bain Corp", "country": "US", "estimated_num_employees": 250, "industry": "Management Consulting"}},
        {"id": f"insur-{test_run_id}", "first_name": "Judy", "last_name": "Claim", "title": "Chief Technology Officer", "organization": {"name": "State Farm", "country": "US", "estimated_num_employees": 400, "industry": "Insurance"}},
    ]

    bulk_match_ids: List[str] = []

    async def mock_post(url, **kwargs):
        json_data = kwargs.get("json", {})
        if "mixed_people/api_search" in str(url):
            return httpx.Response(200, json={"pagination": {"total_entries": 10}, "people": candidates})
        elif "people/bulk_match" in str(url):
            details = json_data.get("details", [])
            for d in details:
                bulk_match_ids.append(d["id"])
            matches = [
                {
                    "id": d["id"],
                    "first_name": "Matched",
                    "last_name": "User",
                    "email": f"{d['id']}@healthdomain.com",
                    "title": "CTO",
                    "organization": {"name": "Health Co", "estimated_num_employees": 150, "industry": "Hospital & Health Care"},
                }
                for d in details
            ]
            return httpx.Response(200, json={"matches": matches})
        return httpx.Response(404)

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        config = {
            "target_job_titles": "CTO, CIO, VP Engineering",
            "target_location": "USA",
            "target_industries": "Health Care",
            "requested_count": 25,
            "threshold": 60,
        }
        res = await agent.run(config)

        # Assert ONLY the 3 healthcare candidates were enriched
        assert len(bulk_match_ids) == 3
        assert f"hosp-{test_run_id}" in bulk_match_ids
        assert f"med-{test_run_id}" in bulk_match_ids
        assert f"hc-{test_run_id}" in bulk_match_ids

        # Assert unrelated industries were NEVER sent to bulk_match
        assert f"apparel-{test_run_id}" not in bulk_match_ids
        assert f"gov-{test_run_id}" not in bulk_match_ids
        assert f"trans-{test_run_id}" not in bulk_match_ids
        assert f"hw-{test_run_id}" not in bulk_match_ids
        assert f"net-{test_run_id}" not in bulk_match_ids
        assert f"consult-{test_run_id}" not in bulk_match_ids
        assert f"insur-{test_run_id}" not in bulk_match_ids

        # Assert telemetry accurately records 7 industry rejections
        assert res["telemetry"]["industry_rejected"] == 7
        assert res["telemetry"]["prequalified_candidates"] == 3


# ── TEST N: Technology Keywords Qualification & Multi-term Handling ─────────

@pytest.mark.asyncio
async def test_technology_keywords_qualification(db_session):
    """
    Tests ICP with Target Industries: Health Care and Technology Keyword: Teleradiology.
    1. Healthcare org with teleradiology passes.
    2. Apparel org with teleradiology fails hard industry check.
    3. Healthcare org without teleradiology fails when technology_keywords_required=True, passes when False.
    """
    test_run_id = uuid.uuid4().hex[:6]

    cand_health_tele = {
        "id": f"ht-{test_run_id}", "first_name": "Helen", "last_name": "Ray", "title": "VP Technology",
        "organization": {"name": "RadNet Health", "country": "US", "estimated_num_employees": 150, "industry": "Hospital & Health Care", "keywords": ["teleradiology", "imaging"]}
    }
    cand_apparel_tele = {
        "id": f"at-{test_run_id}", "first_name": "Adam", "last_name": "Cloth", "title": "VP Technology",
        "organization": {"name": "Smart Clothing", "country": "US", "estimated_num_employees": 150, "industry": "Apparel & Fashion", "keywords": ["teleradiology"]}
    }
    cand_health_general = {
        "id": f"hg-{test_run_id}", "first_name": "Greg", "last_name": "Nurse", "title": "VP Technology",
        "organization": {"name": "General Clinic", "country": "US", "estimated_num_employees": 150, "industry": "Medical Practice"}
    }

    # Strict technology keywords required
    norm_strict = normalize_icp_input({
        "target_job_titles": "VP Technology",
        "target_location": "USA",
        "target_industries": "Health Care",
        "target_technology_keywords": "Teleradiology",
        "technology_keywords_required": True,
    })
    assert ProspectAgent._is_prequalified(cand_health_tele, norm_strict) is True
    assert ProspectAgent._is_prequalified(cand_apparel_tele, norm_strict) is False  # Fails industry
    assert ProspectAgent._is_prequalified(cand_health_general, norm_strict) is False  # Fails technology

    # Optional technology keywords
    norm_optional = normalize_icp_input({
        "target_job_titles": "VP Technology",
        "target_location": "USA",
        "target_industries": "Health Care, Deep Tech, Deep Health, Teleradiology",
        "technology_keywords_required": False,
    })
    assert "health care" in norm_optional.industry_terms
    assert "deep tech" in norm_optional.technology_keywords
    assert "teleradiology" in norm_optional.technology_keywords
    assert ProspectAgent._is_prequalified(cand_health_tele, norm_optional) is True
    assert ProspectAgent._is_prequalified(cand_apparel_tele, norm_optional) is False  # Fails industry
    assert ProspectAgent._is_prequalified(cand_health_general, norm_optional) is True  # Passes industry


# ── TEST O: Missing Industry Evaluates Org-Level Evidence ────────────────────

@pytest.mark.asyncio
async def test_missing_industry_evaluates_org_evidence(db_session):
    """
    Verifies that when Apollo returns NO industry in search stub:
    - Candidate with supporting org-level evidence (org name, keywords, desc) PASSES.
    - Candidate with no org-level evidence is REJECTED (insufficient evidence).
    """
    test_run_id = uuid.uuid4().hex[:6]

    norm_cfg = normalize_icp_input({
        "target_job_titles": "Chief Technology Officer",
        "target_location": "USA",
        "target_industries": "Health Care",
    })

    # Stub with missing industry but strong org name / keywords evidence
    stub_with_evidence = {
        "id": f"ev1-{test_run_id}", "first_name": "Sam", "last_name": "Doc", "title": "Chief Technology Officer",
        "organization": {"name": "Community Health Center", "country": "US", "estimated_num_employees": 100, "industry": None, "keywords": ["health", "clinic"]}
    }
    assert ProspectAgent._is_prequalified(stub_with_evidence, norm_cfg) is True

    # Stub with missing industry and no supporting org evidence
    stub_no_evidence = {
        "id": f"noev-{test_run_id}", "first_name": "Tom", "last_name": "Tech", "title": "Chief Technology Officer",
        "organization": {"name": "Global Solutions LLC", "country": "US", "estimated_num_employees": 100, "industry": None, "keywords": ["business", "consulting"]}
    }
    is_prequal, reason = ProspectAgent._check_prequalification(stub_no_evidence, norm_cfg)
    assert is_prequal is False
    assert reason == "industry_rejected"


# ── TEST P: Task 8 Specific Industry Filtering & Normalization Scenarios ──────

@pytest.mark.asyncio
async def test_task_8_apollo_industry_filtering_scenarios(db_session):
    """
    Explicitly tests all 10 scenarios outlined in Task 8:
    1. No industry supplied -> passes.
    2. Exact industry match ("healthcare" -> "healthcare") -> passes.
    3. Common variation ("healthcare" -> "hospital & health care") -> passes.
    4. Unrelated industry ("healthcare" -> "construction") -> rejected.
    5. Missing Apollo industry + org evidence ("telehealth" in desc) -> passes.
    6. Missing Apollo industry + no evidence -> rejected.
    7. Unknown industry ("teleradiology") -> fallback keyword input in query builder.
    8. Technology required (required=True + no match) -> rejected.
    9. Technology optional (required=False + no match) -> passes.
    10. Duplicate industry inputs ("healthcare, healthcare, health care") -> no duplicate tag IDs.
    """
    # 1. No industry supplied -> industry qualification passes
    cfg_no_industry = normalize_icp_input({"target_job_titles": "CTO", "target_location": "USA"})
    cand_any_industry = {"id": "c1", "title": "CTO", "organization": {"name": "Any Corp", "country": "USA", "industry": "construction"}}
    assert ProspectAgent._matches_target_industry(cand_any_industry, cfg_no_industry) is True

    # 2. Exact industry match: target = "healthcare", Apollo industry = "healthcare" -> passes
    cfg_healthcare = normalize_icp_input({"target_job_titles": "CTO", "target_location": "USA", "target_industries": "healthcare"})
    cand_exact_hc = {"id": "c2", "title": "CTO", "organization": {"name": "Health Co", "country": "USA", "industry": "healthcare"}}
    assert ProspectAgent._matches_target_industry(cand_exact_hc, cfg_healthcare) is True

    # 3. Common variation: target = "healthcare", Apollo industry = "hospital & health care" -> passes
    cand_variation_hc = {"id": "c3", "title": "CTO", "organization": {"name": "City Hospital", "country": "USA", "industry": "hospital & health care"}}
    assert ProspectAgent._matches_target_industry(cand_variation_hc, cfg_healthcare) is True

    # 4. Unrelated industry: target = "healthcare", Apollo industry = "construction" -> rejected
    cand_unrelated = {"id": "c4", "title": "CTO", "organization": {"name": "Build Co", "country": "USA", "industry": "construction"}}
    assert ProspectAgent._matches_target_industry(cand_unrelated, cfg_healthcare) is False

    # 5. Missing Apollo industry but organization description contains "telehealth" -> passes
    cand_missing_ind_with_desc = {
        "id": "c5", "title": "CTO",
        "organization": {"name": "Virtual Med", "country": "USA", "industry": "", "short_description": "A modern telehealth provider"}
    }
    assert ProspectAgent._matches_target_industry(cand_missing_ind_with_desc, cfg_healthcare) is True

    # 6. Missing Apollo industry and no supporting evidence -> rejected
    cand_missing_ind_no_desc = {
        "id": "c6", "title": "CTO",
        "organization": {"name": "Acme Tools", "country": "USA", "industry": "", "short_description": "Hand tools and hardware"}
    }
    assert ProspectAgent._matches_target_industry(cand_missing_ind_no_desc, cfg_healthcare) is False

    # 7. Unknown industry: target = "teleradiology" -> preserved as fallback keyword in org_keyword_tags
    cfg_unknown = normalize_icp_input({"target_job_titles": "CTO", "target_location": "USA", "target_industries": "teleradiology"})
    assert "teleradiology" in cfg_unknown.technology_keywords
    assert "teleradiology" in cfg_unknown.org_keyword_tags
    payload = ApolloQueryBuilder.build_search_payload(cfg_unknown)
    assert "teleradiology" in payload.get("q_organization_keyword_tags", [])

    # 8. Technology required: required=True, no matching org tech/evidence -> rejected
    cfg_tech_req = normalize_icp_input({
        "target_job_titles": "CTO", "target_location": "USA",
        "target_industries": "healthcare", "target_technology_keywords": "teleradiology",
        "technology_keywords_required": True
    })
    cand_hc_no_tech = {"id": "c8", "title": "CTO", "organization": {"name": "General Health", "country": "USA", "industry": "healthcare"}}
    assert ProspectAgent._matches_target_technology(cand_hc_no_tech, cfg_tech_req) is False
    assert ProspectAgent._is_prequalified(cand_hc_no_tech, cfg_tech_req) is False

    # 9. Technology optional: required=False, no matching org tech -> passes
    cfg_tech_opt = normalize_icp_input({
        "target_job_titles": "CTO", "target_location": "USA",
        "target_industries": "healthcare", "target_technology_keywords": "teleradiology",
        "technology_keywords_required": False
    })
    assert ProspectAgent._matches_target_technology(cand_hc_no_tech, cfg_tech_opt) is True
    assert ProspectAgent._is_prequalified(cand_hc_no_tech, cfg_tech_opt) is True

    # 10. Duplicate industry inputs: "healthcare, healthcare, health care" -> exactly 1 unique tag ID
    cfg_dups = normalize_icp_input({"target_industries": "healthcare, healthcare, health care"})
    assert len(cfg_dups.industry_tag_ids) == 1
    assert cfg_dups.industry_tag_ids == ["5567cd4773696439ab0a0000"]



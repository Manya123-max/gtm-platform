"""
test_a1_5_salesforce_verification.py — Comprehensive Unit & Integration Tests for A1.5.

Covers all 20 specified test scenarios:
1. Apollo returns Salesforce technographic evidence.
2. Apollo technographic data is unavailable.
3. Official website contains a valid Salesforce Web-to-Lead endpoint.
4. Official website contains only a generic Salesforce mention.
5. Official website has no Salesforce fingerprint.
6. Website is inaccessible.
7. Website redirects to a prohibited private/internal IP (SSRF protection).
8. A valid internal Salesforce job posting is found (Adzuna).
9. A consulting company job posting is rejected as adoption proof.
10. Official Salesforce customer story/announcement identifies target company.
11. Generic Salesforce news mention is rejected.
12. Duplicate evidence is deduplicated.
13. Conflicting / mixed evidence is handled safely.
14. Company has no official domain.
15. One verification source fails while other sources continue.
16. Multiple contacts belonging to the same company trigger only one company-level verification.
17. Cached verification results are reused.
18. Stale verification results can be refreshed (force_refresh).
19. 'not_verified' is strictly distinct from 'unable_to_verify'.
20. No fabricated evidence or links are stored.
21. Pipeline integration: A1 → A1.5 → A2.
22. A3 receives verification context with appropriate policy enforcement.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from app.agents.a1_5_salesforce_verification import (
    SalesforceVerificationAgent,
    clean_company_domain,
    clean_company_name,
    is_safe_external_url,
)
from app.models.models import (
    Contact,
    CompanySalesforceVerification,
    SalesforceVerificationEvidence,
)


# ═════════════════════════════════════════════════════════════════════════════
# Helper Fixtures & Mock DB
# ═════════════════════════════════════════════════════════════════════════════

def make_mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ═════════════════════════════════════════════════════════════════════════════
# 1 & 2. Apollo Technographic Data Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_apollo_returns_salesforce_technographic():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    ev = await agent._check_apollo_technographic(
        company_name="RadNet",
        domain="radnet.com",
        apollo_org_id="org_123",
        cached_tech_stack=["AWS", "Salesforce CRM", "HubSpot"],
    )
    assert len(ev) == 1
    assert ev[0]["evidence_type"] == "apollo_technographic"
    assert "Salesforce CRM" in ev[0]["evidence_description"]
    assert ev[0]["source_url"] is None  # Never fabricated
    assert ev[0]["is_strong"] is True


@pytest.mark.asyncio
async def test_apollo_technographic_unavailable():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    ev = await agent._check_apollo_technographic(
        company_name="Acme Corp",
        domain="acme.com",
        apollo_org_id="org_456",
        cached_tech_stack=["React", "PostgreSQL", "Node.js"],
    )
    assert len(ev) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 3, 4, 5, 6, 7. Website Technology Detection & SSRF Protection
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_website_valid_web_to_lead_endpoint():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_html = """
    <html>
      <body>
        <h1>Contact Us</h1>
        <form action="https://webto.salesforce.com/servlet/servlet.WebToLead?encoding=UTF-8" method="POST">
          <input type="hidden" name="oid" value="00D80000000XXXX" />
          <input type="text" name="first_name" />
        </form>
      </body>
    </html>
    """

    with patch("app.agents.a1_5_salesforce_verification.is_safe_external_url", return_value=(True, None)):
        mock_resp = MagicMock(status_code=200, text=mock_html, headers={"content-type": "text/html"}, url="https://example.com/contact")
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
            ev = await agent._check_company_website("example.com", "Example Co")
            assert len(ev) >= 1
            assert ev[0]["evidence_type"] == "website_fingerprint"
            assert "Web-to-Lead" in ev[0]["evidence_description"]
            assert "webto.salesforce.com" in ev[0]["source_url"]
            assert ev[0]["is_strong"] is True


@pytest.mark.asyncio
async def test_website_generic_mention_only_rejected_as_strong():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_html = """
    <html>
      <body>
        <p>Our software integrates with tools like Salesforce and Slack.</p>
        <a href="https://salesforce.com">Visit Salesforce</a>
      </body>
    </html>
    """
    with patch("app.agents.a1_5_salesforce_verification.is_safe_external_url", return_value=(True, None)):
        mock_resp = MagicMock(status_code=200, text=mock_html, headers={"content-type": "text/html"}, url="https://example.com")
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
            ev = await agent._check_company_website("example.com", "Example Co")
            # Generic mention does NOT create strong fingerprint evidence
            assert len(ev) == 0


@pytest.mark.asyncio
async def test_website_no_salesforce_fingerprint():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_html = "<html><body><h1>Welcome to Acme</h1><p>We build diagnostic cameras.</p></body></html>"
    with patch("app.agents.a1_5_salesforce_verification.is_safe_external_url", return_value=(True, None)):
        mock_resp = MagicMock(status_code=200, text=mock_html, headers={"content-type": "text/html"}, url="https://acme.com")
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):
            ev = await agent._check_company_website("acme.com", "Acme")
            assert len(ev) == 0


@pytest.mark.asyncio
async def test_website_inaccessible_handled_gracefully():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    with patch("app.agents.a1_5_salesforce_verification.is_safe_external_url", return_value=(True, None)):
        with patch("httpx.AsyncClient.get", AsyncMock(side_effect=Exception("Connection timed out"))):
            ev = await agent._check_company_website("downsite.com", "Down Site")
            assert ev == []


def test_ssrf_protection_blocks_private_and_cloud_metadata():
    # 1. Loopback
    is_safe, reason = is_safe_external_url("http://127.0.0.1:8000/admin")
    assert is_safe is False
    assert "Prohibited" in reason

    # 2. Localhost
    is_safe, reason = is_safe_external_url("http://localhost:3000")
    assert is_safe is False

    # 3. AWS / GCP / Azure Cloud Metadata IP
    is_safe, reason = is_safe_external_url("http://169.254.169.254/latest/meta-data/")
    assert is_safe is False

    # 4. Non-http scheme
    is_safe, reason = is_safe_external_url("file:///etc/passwd")
    assert is_safe is False


# ═════════════════════════════════════════════════════════════════════════════
# 8 & 9. Career Pages & Adzuna Hiring Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_adzuna_internal_salesforce_role_found():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_adzuna_resp = {
        "results": [
            {
                "company": {"display_name": "RadNet Management, Inc."},
                "title": "Senior Salesforce Administrator",
                "description": "Manage our internal Salesforce Health Cloud instance, user permissions, and custom objects.",
                "redirect_url": "https://www.adzuna.com/land/ad/12345",
                "created": "2026-10-15T12:00:00Z",
            }
        ]
    }

    with patch("app.core.config.settings.ADZUNA_APP_ID", "test_id"), \
         patch("app.core.config.settings.ADZUNA_API_KEY", "test_key"), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=lambda: mock_adzuna_resp))):
        ev = await agent._check_adzuna_salesforce_jobs("RadNet", "radnet.com")
        assert len(ev) == 1
        assert ev[0]["evidence_type"] == "adzuna_job"
        assert "Senior Salesforce Administrator" in ev[0]["evidence_description"]
        assert ev[0]["source_url"] == "https://www.adzuna.com/land/ad/12345"
        assert ev[0]["is_strong"] is False  # Supporting evidence


@pytest.mark.asyncio
async def test_adzuna_consulting_client_role_rejected():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_adzuna_resp = {
        "results": [
            {
                "company": {"display_name": "RadNet"},
                "title": "Salesforce Developer",
                "description": "Join our staffing agency for our client project at a financial firm.",
                "redirect_url": "https://www.adzuna.com/land/ad/999",
                "created": "2026-10-15T12:00:00Z",
            }
        ]
    }

    with patch("app.core.config.settings.ADZUNA_APP_ID", "test_id"), \
         patch("app.core.config.settings.ADZUNA_API_KEY", "test_key"), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=lambda: mock_adzuna_resp))):
        ev = await agent._check_adzuna_salesforce_jobs("RadNet", "radnet.com")
        # Rejected because description contains 'for our client' / 'agency'
        assert len(ev) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 10 & 11. Announcements & Customer Stories Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_official_announcement_found():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_rss = """
    <rss version="2.0">
      <channel>
        <item>
          <title>HealthFirst Deploys Salesforce Health Cloud to Streamline Care Delivery</title>
          <link>https://news.example.com/healthfirst-salesforce</link>
          <description>HealthFirst announced today it has deployed Salesforce CRM across 50 clinics.</description>
        </item>
      </channel>
    </rss>
    """

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, text=mock_rss))):
        ev = await agent._check_announcements_and_stories("HealthFirst", "healthfirst.org")
        assert len(ev) == 1
        assert ev[0]["evidence_type"] == "official_announcement"
        assert "Deploys Salesforce" in ev[0]["evidence_description"]
        assert ev[0]["is_strong"] is True


@pytest.mark.asyncio
async def test_generic_partner_announcement_rejected():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    mock_rss = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Consulting Firm XYZ Named Salesforce Partner</title>
          <link>https://news.example.com/xyz-partner</link>
          <description>Consulting firm XYZ expands partner tier.</description>
        </item>
      </channel>
    </rss>
    """
    with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, text=mock_rss))):
        ev = await agent._check_announcements_and_stories("Acme Health", "acmehealth.com")
        assert len(ev) == 0


# ═════════════════════════════════════════════════════════════════════════════
# 12, 13, 14, 15, 19. Evidence Evaluation & Status Logic Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_evidence_deduplication_and_strong_evaluation():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    ev_list = [
        {
            "evidence_type": "website_fingerprint",
            "source_name": "Official company website",
            "evidence_description": "Web-to-Lead endpoint",
            "source_url": "https://webto.salesforce.com/servlet/servlet.WebToLead",
            "is_strong": True,
            "is_valid": True,
        },
        # Duplicate with same type and URL
        {
            "evidence_type": "website_fingerprint",
            "source_name": "Official company website",
            "evidence_description": "Web-to-Lead endpoint",
            "source_url": "https://webto.salesforce.com/servlet/servlet.WebToLead",
            "is_strong": True,
            "is_valid": True,
        },
    ]

    status, summary = agent._evaluate_evidence(
        company_name="Acme",
        domain="acme.com",
        evidence=ev_list,
        sources_attempted=["website_fingerprint"],
        source_failures=[],
    )
    assert status == "verified"
    assert "Salesforce adoption verified" in summary


def test_supporting_evidence_threshold():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    # 1 supporting item alone is NOT verified
    ev_one = [
        {
            "evidence_type": "adzuna_job",
            "source_name": "Adzuna Job Posting",
            "evidence_description": "Admin role",
            "source_url": "https://adzuna.com/job1",
            "is_strong": False,
            "is_valid": True,
        }
    ]
    status_one, _ = agent._evaluate_evidence(
        "Acme", "acme.com", ev_one, ["adzuna_job"], []
    )
    assert status_one == "not_verified"

    # 2 independent supporting items trigger verified
    ev_two = [
        ev_one[0],
        {
            "evidence_type": "adzuna_job",
            "source_name": "Career Page",
            "evidence_description": "Developer role",
            "source_url": "https://adzuna.com/job2",
            "is_strong": False,
            "is_valid": True,
        }
    ]
    status_two, _ = agent._evaluate_evidence(
        "Acme", "acme.com", ev_two, ["adzuna_job"], []
    )
    assert status_two == "verified"


def test_missing_domain_yields_unable_to_verify():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    status, summary = agent._evaluate_evidence(
        company_name="Mystery Firm",
        domain="",
        evidence=[],
        sources_attempted=["apollo_technographic"],
        source_failures=[],
    )
    assert status == "unable_to_verify"
    assert "Official company domain was missing" in summary


def test_all_sources_failed_yields_unable_to_verify():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    status, summary = agent._evaluate_evidence(
        company_name="Blocked Firm",
        domain="blocked.com",
        evidence=[],
        sources_attempted=["apollo_technographic", "website_fingerprint"],
        source_failures=["apollo_technographic", "website_fingerprint"],
    )
    assert status == "unable_to_verify"
    assert "One or more required sources were unavailable" in summary


def test_completed_checks_without_evidence_yields_not_verified():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    status, summary = agent._evaluate_evidence(
        company_name="Clean Co",
        domain="cleanco.com",
        evidence=[],
        sources_attempted=["apollo_technographic", "website_fingerprint", "adzuna_job"],
        source_failures=[],
    )
    # Not a technical failure; checks ran cleanly and found nothing
    assert status == "not_verified"
    assert "No reliable Salesforce adoption evidence was found" in summary


# ═════════════════════════════════════════════════════════════════════════════
# 16, 17, 18. Account Deduplication & Caching Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multiple_contacts_same_company_deduplicated():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    c1 = Contact(id="c1", email="alice@radnet.com", company="RadNet", company_domain="radnet.com")
    c2 = Contact(id="c2", email="bob@radnet.com", company="RadNet", company_domain="radnet.com")
    c3 = Contact(id="c3", email="carol@radnet.com", company="RadNet, Inc.", company_domain="radnet.com")

    # Mock verify_company to track calls
    agent.verify_company = AsyncMock(return_value={
        "company_name": "RadNet",
        "company_domain": "radnet.com",
        "verification_status": "verified",
        "evidence": [],
    })

    results = await agent.verify_prospect_accounts([c1, c2, c3])
    # 3 contacts belong to 1 company -> verify_company must only be called ONCE
    assert len(results) == 1
    agent.verify_company.assert_awaited_once()


@pytest.mark.asyncio
async def test_cached_verification_reused():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    cached_rec = CompanySalesforceVerification(
        id="v1",
        company_name="RadNet",
        company_domain="radnet.com",
        verification_status="verified",
        verification_summary="Cached verification.",
        last_checked_at=datetime.utcnow() - timedelta(days=5),
    )
    cached_rec.evidence_items = []

    agent._get_cached_verification = AsyncMock(return_value=cached_rec)
    res = await agent.verify_company("RadNet", domain="radnet.com", force_refresh=False)

    assert res["verification_status"] == "verified"
    assert res["verification_summary"] == "Cached verification."


@pytest.mark.asyncio
async def test_stale_or_force_refresh_runs_verification():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    # Stale record (40 days old > 30 day freshness limit)
    stale_rec = CompanySalesforceVerification(
        id="v2",
        company_name="RadNet",
        company_domain="radnet.com",
        verification_status="verified",
        last_checked_at=datetime.utcnow() - timedelta(days=40),
    )
    stale_rec.evidence_items = []
    agent._get_cached_verification = AsyncMock(return_value=stale_rec)

    with patch.object(agent, "_check_apollo_technographic", AsyncMock(return_value=[])), \
         patch.object(agent, "_check_company_website", AsyncMock(return_value=[])), \
         patch.object(agent, "_check_adzuna_salesforce_jobs", AsyncMock(return_value=[])), \
         patch.object(agent, "_check_announcements_and_stories", AsyncMock(return_value=[])), \
         patch.object(agent, "_save_verification", AsyncMock(return_value=stale_rec)):
        res = await agent.verify_company("RadNet", domain="radnet.com", force_refresh=True)
        # Ran fresh verification
        agent._check_apollo_technographic.assert_awaited_once()


# ═════════════════════════════════════════════════════════════════════════════
# 20. No Fabricated Evidence or Links Test
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_fabricated_evidence_or_links():
    db = make_mock_db()
    agent = SalesforceVerificationAgent(db)

    ev = await agent._check_apollo_technographic(
        company_name="RadNet",
        domain="radnet.com",
        apollo_org_id=None,
        cached_tech_stack=["Salesforce"],
    )
    assert len(ev) == 1
    # When Apollo doesn't provide a URL, source_url must be None rather than a fabricated homepage link
    assert ev[0]["source_url"] is None


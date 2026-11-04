import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.models import Contact, SignalEvent, SignalType
from app.agents.a2_signal import SignalAgent, TechStackHTMLParser
from app.services.signal_formatter import (
    clean_html_text,
    format_clean_signal_summary,
    resolve_signal_article_url,
    generate_factual_signal_summary,
)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    # Mock execute for registry, existing signals, etc.
    scalar_mock = MagicMock()
    scalar_mock.all.return_value = []
    scalar_mock.scalar_one_or_none.return_value = None
    res_mock = MagicMock()
    res_mock.scalars.return_value = scalar_mock
    res_mock.scalar_one_or_none.return_value = None
    res_mock.scalar.return_value = None
    db.execute.return_value = res_mock
    return db


@pytest.fixture
def sample_contact():
    contact = Contact(
        id="c1111111-1111-1111-1111-111111111111",
        email="alex@4cecloud.com",
        first_name="Alex",
        last_name="Mercer",
        company="4CE Cloud",
        company_domain="4cecloud.com",
        industry="Cloud Consulting",
        title="VP of Engineering",
        geography="United States",
        icp_score=85.0,
        do_not_contact=False,
    )
    return contact


# ═══════════════════════════════════════════════════════════════════════════
# 1. ADZUNA TESTS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_adzuna_leadership_job_is_job_posting_not_new_hire(mock_db, sample_contact):
    """Ensure leadership job ads from Adzuna are classified as JOB_POSTING (hiring demand), NOT NEW_HIRE."""
    agent = SignalAgent(mock_db)

    adzuna_response = {
        "results": [
            {
                "id": "job123",
                "title": "VP of Sales & Alliances",
                "company": {"display_name": "4CE Cloud"},
                "description": "We are seeking a seasoned VP of Sales to lead commercial outreach.",
                "redirect_url": "https://www.adzuna.com/land/12345",
                "created": "2026-10-15T12:00:00Z",
                "location": {"display_name": "San Francisco, CA"},
            }
        ]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = adzuna_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        with patch("app.core.config.settings.ADZUNA_APP_ID", "test_id"), \
             patch("app.core.config.settings.ADZUNA_API_KEY", "test_key"):
            signals = await agent._check_job_postings(sample_contact, {SignalType.JOB_POSTING: 0.60})

    assert len(signals) >= 1
    # Verify that NO signal is classified as NEW_HIRE
    signal_types = [s["signal_type"] for s in signals]
    assert SignalType.NEW_HIRE not in signal_types
    assert SignalType.JOB_POSTING in signal_types

    job_sig = next(s for s in signals if s["signal_type"] == SignalType.JOB_POSTING)
    assert job_sig["raw_data"]["url"] == "https://www.adzuna.com/land/12345"
    assert "VP of Sales" in job_sig["raw_data"]["headline"]
    assert job_sig["occurred_at"] == datetime(2026, 10, 15, 12, 0, 0)


def test_adzuna_recruitment_agency_excluded():
    """Ensure recruitment agency postings are not falsely matched to target company."""
    # Robert Half posting should not match 4CE Cloud
    assert not SignalAgent._is_company_name_match("Robert Half International", "4ce cloud", "4CE Cloud")
    assert not SignalAgent._is_company_name_match("Randstad Staffing", "4ce cloud", "4CE Cloud")
    # Real employer should match
    assert SignalAgent._is_company_name_match("4CE Cloud Inc", "4ce cloud", "4CE Cloud")


# ═══════════════════════════════════════════════════════════════════════════
# 2. PREDICTLEADS TESTS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_predictleads_technologies_classified_as_observed(mock_db, sample_contact):
    """PredictLeads technologies without recent change evidence are classified as TECH_STACK_OBSERVED."""
    agent = SignalAgent(mock_db)

    tech_data = {
        "data": [
            {
                "attributes": {
                    "name": "Salesforce Sales Cloud",
                    "category": "crm",
                    "first_seen_at": "2026-10-01T00:00:00Z"
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        def side_effect(url, **kwargs):
            m = MagicMock()
            if "technologies" in url:
                m.status_code = 200
                m.json.return_value = tech_data
            else:
                m.status_code = 404
                m.json.return_value = {}
            return m

        mock_get.side_effect = side_effect

        with patch("app.core.config.settings.PREDICTLEADS_API_KEY", "test_key"), \
             patch("app.core.config.settings.PREDICTLEADS_API_TOKEN", "test_tok"):
            signals = await agent._check_predictleads(sample_contact, {SignalType.TECH_STACK_OBSERVED: 0.40})

    assert len(signals) == 1
    assert signals[0]["signal_type"] == SignalType.TECH_STACK_OBSERVED
    assert "Salesforce Sales Cloud" in signals[0]["raw_data"]["technologies"]
    assert "active enterprise technology usage" in signals[0]["raw_data"]["description"].lower()


@pytest.mark.asyncio
async def test_predictleads_graceful_handling_on_402_billing_limit(mock_db, sample_contact):
    """PredictLeads handles HTTP 402 payment_required without crashing and disables itself."""
    agent = SignalAgent(mock_db)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.json.return_value = {"error": {"type": "payment_required"}}
        mock_get.return_value = mock_resp

        with patch("app.core.config.settings.PREDICTLEADS_API_KEY", "test_key"), \
             patch("app.core.config.settings.PREDICTLEADS_API_TOKEN", "test_tok"):
            signals = await agent._check_predictleads(sample_contact, {})

    assert signals == []
    assert agent._predictleads_disabled is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. CURRENTS & NEWS DEDUPLICATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_headline_relevance_prevents_generic_collisions():
    """Ensure generic nouns like 'target' or 'bridge' don't match idioms."""
    assert not SignalAgent._is_headline_relevant("Sales team hit target for Q3", "target", "Target Corp")
    assert not SignalAgent._is_headline_relevant("Bridge financing secured for expansion", "bridge", "Bridge Systems")
    assert SignalAgent._is_headline_relevant("4CE Cloud partners with Health Systems", "4ce cloud", "4CE Cloud")


def test_cross_source_news_deduplication():
    """Deduplicate identical news events between Google News, Currents, and NewsAPI."""
    sig1_raw = {
        "headline": "4CE Cloud Announces Expansion into Healthcare AI Market - Yahoo Finance",
        "url": "https://finance.yahoo.com/news/4ce-cloud-expansion-1234.html"
    }
    sig2_raw = {
        "headline": "4CE Cloud Announces Expansion into Healthcare AI Market",
        "url": "https://news.google.com/articles/CAIiE..."
    }

    # Normalized headlines overlap substantially
    assert SignalAgent._signals_overlap("news_expansion", sig1_raw, "news_expansion", sig2_raw, timedelta(0))


# ═══════════════════════════════════════════════════════════════════════════
# 4. APIFY REDDIT TESTS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_apify_handles_403_hard_limit_gracefully(mock_db, sample_contact):
    """Apify Reddit scraper handles HTTP 403 platform usage limits without generating mock signals."""
    agent = SignalAgent(mock_db)

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {
            "error": {"type": "platform-feature-disabled", "message": "Monthly usage hard limit exceeded"}
        }
        mock_post.return_value = mock_resp

        with patch("app.core.config.settings.APIFY_API_TOKEN", "apify_test_token"):
            signals = await agent._check_apify(sample_contact, {})

    assert signals == []
    assert agent._apify_disabled is True


# ═══════════════════════════════════════════════════════════════════════════
# 5. WEBSITE TECH STACK FINGERPRINTING & EVIDENCE URL TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_html_parser_extracts_exact_script_url():
    """Verify TechStackHTMLParser extracts exact script and form URLs."""
    html_sample = """
    <html>
      <head>
        <script src="https://pi.pardot.com/pd.js?aid=98765"></script>
        <link href="https://service.force.com/embeddedservice/5.0/esw.min.css" rel="stylesheet" />
      </head>
      <body>
        <form action="https://webto.salesforce.com/servlet/servlet.WebToLead?encoding=UTF-8" method="POST">
          <input type="hidden" name="oid" value="00D50000000XXXX" />
        </form>
      </body>
    </html>
    """
    parser = TechStackHTMLParser(base_url="https://4cecloud.com")
    parser.feed(html_sample)

    assert len(parser.detected_items) == 3
    scripts = [it for it in parser.detected_items if it["tag"] == "script"]
    assert scripts[0]["resource_url"] == "https://pi.pardot.com/pd.js?aid=98765"
    assert scripts[0]["tech"] == "Salesforce"

    forms = [it for it in parser.detected_items if it["tag"] == "form"]
    assert forms[0]["resource_url"] == "https://webto.salesforce.com/servlet/servlet.WebToLead?encoding=UTF-8"


@pytest.mark.asyncio
async def test_website_tech_stack_scraping_is_deprecated(mock_db, sample_contact):
    """Website tech stack HTML scraping is deprecated per user requirements; returns [] and does not emit company website homepage signals."""
    agent = SignalAgent(mock_db)
    signals = await agent._check_website_tech_stack(sample_contact, {SignalType.TECH_STACK_OBSERVED: 0.40})
    assert signals == []


# ═══════════════════════════════════════════════════════════════════════════
# 6. EVIDENCE FORMATTER & SOURCE DISPLAY TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_signal_formatter_factual_summary():
    """Ensure factual summary generates grounded text without converting jobs to hires."""
    job_summary = generate_factual_signal_summary(
        signal_type="job_posting",
        headline="Senior Salesforce Health Cloud Architect",
        company="RadNet",
    )
    assert "Active hiring demand" in job_summary
    assert "hired" not in job_summary.lower()

    observed_summary = generate_factual_signal_summary(
        signal_type="tech_stack_observed",
        headline="Enterprise tech stack observed on radnet.com: Salesforce",
        company="RadNet",
    )
    assert "Verified enterprise technology usage" in observed_summary


def test_enrich_signal_metadata_job_posting():
    from app.services.signal_formatter import enrich_signal_metadata
    raw = {
        "job_title": "Senior Salesforce Developer",
        "roles": ["Senior Salesforce Developer", "Developer"],
        "locations": ["Dallas, TX"],
    }
    enriched = enrich_signal_metadata(
        sig_type="job_posting",
        raw_data=raw,
        company="Acme Corp",
        summary="Acme Corp hiring Senior Salesforce Developer"
    )
    assert enriched["department"] == "Engineering & IT"
    assert enriched["employment_type"] == "Full-time"
    assert "Acme Corp published an active vacancy" in enriched["company_context"]
    assert "selection_summary" not in enriched["company_context"]


def test_enrich_signal_metadata_funding_round():
    from app.services.signal_formatter import enrich_signal_metadata
    raw = {
        "headline": "Acme Corp raises $25M in Series B led by Sequoia",
        "description": "Acme Corp announced $25 million in Series B funding led by Sequoia to accelerate operations.",
    }
    enriched = enrich_signal_metadata(
        sig_type="funding_round",
        raw_data=raw,
        company="Acme Corp"
    )
    assert enriched["funding_stage"] == "Series B"
    assert "$25" in enriched["amount"]
    assert "Sequoia" in enriched["lead_investor"]
    assert "employment_type" not in enriched
    assert "Acme Corp completed a Series B financing round" in enriched["company_context"]


def test_enrich_signal_metadata_new_hire():
    from app.services.signal_formatter import enrich_signal_metadata
    raw = {
        "headline": "Acme Corp appoints Sarah Connor as Chief Technology Officer",
        "description": "Acme Corp welcomes Sarah Connor as Chief Technology Officer after strategic expansion.",
    }
    enriched = enrich_signal_metadata(
        sig_type="new_hire",
        raw_data=raw,
        company="Acme Corp"
    )
    assert "Chief Technology Officer" in enriched["new_designation"]
    assert enriched["department"] == "Technology & Engineering"
    assert "employment_type" not in enriched
    assert "Sarah Connor" in enriched["appointed_person"]
    assert "Sarah Connor" in enriched["company_context"]


def test_enrich_signal_metadata_tech_stack_observed():
    from app.services.signal_formatter import enrich_signal_metadata
    raw = {
        "technologies": ["Salesforce", "Marketo"],
        "is_html_inspection": True,
        "page_url": "https://acme.com",
    }
    enriched = enrich_signal_metadata(
        sig_type="tech_stack_observed",
        raw_data=raw,
        company="Acme Corp"
    )
    assert enriched["detection_method"] == "HTML Inspection"
    assert "Salesforce, Marketo" in enriched["company_context"]
    assert "verified active usage, not a newly confirmed adoption" in enriched["company_context"]



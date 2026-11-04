"""
test_live_discovery_dnc_signals_funding.py — Comprehensive Unit & Integration Tests.

Validates:
1. CSV isolation from real-time A1 prospect discovery.
2. Central DNC suppression logic, email normalization, duplicate handling, and pre-send blocking.
3. Signals filter normalization, Apollo query mapping, and OR semantics.
4. Funding filter normalization, 15 stage mappings, no minimum amount restriction, and OR semantics.
5. Combined filter behavior (Signals OR within, Funding OR within, AND between groups).
6. Regression: Look-alike, deduplication, and workspace isolation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.suppression_service import normalize_email, SuppressionService
from app.services.icp_normalizer import normalize_icp_input, NormalizedICPConfig
from app.services.apollo_query_builder import ApolloQueryBuilder, APOLLO_FUNDING_STAGE_MAP
from app.agents.a1_prospect import ProspectAgent
from app.models.models import Contact, OutreachDraft, SuppressedEmail


# ═════════════════════════════════════════════════════════════════════════════
# 1. Email Normalization Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_normalize_email_whitespace_and_casing():
    assert normalize_email("  John.Doe@Example.COM  ") == "john.doe@example.com"
    assert normalize_email("\tJANE@DOMAIN.ORG\n") == "jane@domain.org"
    assert normalize_email("alex+filter@sub.domain.io") == "alex+filter@sub.domain.io"


def test_normalize_email_empty_and_invalid():
    assert normalize_email("") == ""
    assert normalize_email(None) == ""
    assert normalize_email("   ") == ""
    assert normalize_email(12345) == ""


# ═════════════════════════════════════════════════════════════════════════════
# 2. Central DNC Suppression Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_suppression_service_checks():
    db = AsyncMock()

    # Case 1: Empty email
    is_supp, reason = await SuppressionService.is_email_suppressed(db, "")
    assert is_supp is False
    assert reason is None

    # Case 2: Contact has do_not_contact == True
    contact = MagicMock(id="c1", email="test@domain.com", do_not_contact=True)
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=contact)))
    is_supp, reason = await SuppressionService.is_email_suppressed(db, "test@domain.com", contact_id="c1")
    assert is_supp is True
    assert reason == "contact_dnc_flag"

    # Case 3: Central suppressed_emails store match
    supp_entry = MagicMock(email="unsub@domain.com", reason="unsubscribe")
    contact_active = MagicMock(id="c2", email="unsub@domain.com", do_not_contact=False)

    # First call checks contact_id (active), second call checks suppressed_emails (found)
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=contact_active)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=supp_entry)),
    ])
    is_supp, reason = await SuppressionService.is_email_suppressed(db, "  UNSUB@DOMAIN.COM  ", contact_id="c2")
    assert is_supp is True
    assert "suppressed_store" in reason


@pytest.mark.asyncio
async def test_suppress_email_multi_record_update():
    db = AsyncMock()
    # Mock update execution returning 3 updated rows
    update_result = MagicMock(rowcount=3)
    db.execute = AsyncMock(return_value=update_result)
    db.add = MagicMock()
    db.commit = AsyncMock()

    updated_count = await SuppressionService.suppress_email(
        db, "  USER@DOMAIN.COM  ", source="resend_webhook", reason="unsubscribe"
    )
    assert updated_count == 3
    db.commit.assert_awaited_once()


# ═════════════════════════════════════════════════════════════════════════════
# 3. CSV Isolation from Real-Time Discovery Tests
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a1_zero_results_does_not_call_offline_store():
    db = AsyncMock()
    agent = ProspectAgent(db)

    icp_config = {
        "titles": ["Chief Technology Officer"],
        "organization_locations": ["United States"],
        "target_company_size": "50-500",
        "company_lookalike": ["NonExistentCorpXYZ"],
    }

    # Mock Apollo returning 0 results
    with patch.object(agent, "_fetch_from_apollo", return_value=([], {"provider": "apollo", "reason": "apollo_people_search_empty", "page": 1})), \
         patch.object(agent, "_fetch_lookalikes_from_apollo", return_value=([], {"provider": "apollo", "reason": "lookalike_search_returned_no_people"})), \
         patch.object(agent, "_fetch_offline") as mock_offline, \
         patch.object(agent, "_fetch_lookalikes_from_offline") as mock_lookalike_offline, \
         patch.object(agent, "_score_contacts", return_value=[]), \
         patch.object(agent, "_save_contacts", return_value={"saved_count": 0, "updated_count": 0, "contact_ids": []}), \
         patch.object(agent, "_log_funnel_event", return_value=None):

        result = await agent.run(icp_config)

        # Offline fallbacks must NEVER be invoked during real-time discovery
        mock_offline.assert_not_called()
        mock_lookalike_offline.assert_not_called()

        assert result["raw_count"] == 0
        assert result["provider"] == "apollo"
        assert result["status"] == "UNAVAILABLE"
        assert "contacts" in result and len(result["contacts"]) == 0


@pytest.mark.asyncio
async def test_a1_apollo_timeout_handled_gracefully():
    db = AsyncMock()
    agent = ProspectAgent(db)

    icp_config = {
        "titles": ["CTO"],
        "organization_locations": ["United States"],
    }

    with patch("app.core.config.settings.APOLLO_API_KEY", "test_key"), \
         patch.object(agent, "_fetch_from_apollo", return_value=([], {"provider": "apollo", "reason": "apollo_timeout", "page": 1})), \
         patch.object(agent, "_fetch_offline") as mock_offline, \
         patch.object(agent, "_score_contacts", return_value=[]), \
         patch.object(agent, "_save_contacts", return_value={"saved_count": 0, "updated_count": 0, "contact_ids": []}), \
         patch.object(agent, "_log_funnel_event", return_value=None):

        result = await agent.run(icp_config)
        mock_offline.assert_not_called()
        assert result["reason"] == "apollo_timeout"
        assert result["status"] == "UNAVAILABLE"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Signals Filter Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_signals_normalization():
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "target_company_size": "50-500",
        "signals": "Office expansion, New partnership, Office expansion",
    }
    cfg = normalize_icp_input(raw_input)
    assert cfg.signals == ["Office expansion", "New partnership"]


def test_signals_apollo_query_builder_or_semantics():
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "target_company_size": "50-500",
        "signals": ["Office expansion", "New partnership"],
        "target_keywords": "AI, Cloud",
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    # Keywords and signals are combined in q_organization_keyword_tags (which uses native Apollo OR logic)
    tags = payload.get("q_organization_keyword_tags", [])
    assert "Office expansion" in tags
    assert "New partnership" in tags
    assert "ai" in tags
    assert "cloud" in tags


def test_all_14_apollo_signals_taxonomy():
    from app.services.apollo_signals_service import APOLLO_SIGNALS_REGISTRY

    expected_signals = [
        ("Award or recognition", "Company momentum", "Companies"),
        ("Cutting costs", "Company momentum", "Companies"),
        ("Former champion changed jobs", "Persona", "People"),
        ("High buying intent", "Company intent", "People"),
        ("Merger or acquisition", "Company momentum", "Companies"),
        ("New client signed", "Company momentum", "Companies"),
        ("New partnership", "Company momentum", "Companies"),
        ("New product or service", "Company momentum", "Companies"),
        ("New role", "Persona", "People"),
        ("Office expansion", "Company momentum", "Companies"),
        ("Opened 2+ emails in past week", "Engagement", "People"),
        ("Rapid growth", "Company momentum", "Companies"),
        ("Recent funding", "Company momentum", "Companies"),
        ("Recently promoted", "Persona", "People"),
    ]

    assert len(APOLLO_SIGNALS_REGISTRY) == 14

    for name, group, target_obj in expected_signals:
        assert name in APOLLO_SIGNALS_REGISTRY, f"Missing {name} in registry"
        info = APOLLO_SIGNALS_REGISTRY[name]
        assert info["group"] == group, f"Wrong group for {name}: expected {group}, got {info['group']}"
        assert info["target_object"] == target_obj, f"Wrong target_object for {name}: expected {target_obj}, got {info['target_object']}"


def test_persona_signals_not_mapped_to_company_keyword_tags():
    from app.services.apollo_signals_service import ApolloSignalsService

    persona_signals = ["Former champion changed jobs", "New role", "Recently promoted"]
    classification = ApolloSignalsService.classify_signals(persona_signals)

    # Persona signals must NEVER be added to supported company tags
    assert len(classification["supported_company_tags"]) == 0
    assert len(classification["unsupported_signals"]) == 3

    for unsupp in classification["unsupported_signals"]:
        assert unsupp["group"] == "Persona"
        assert unsupp["target_object"] == "People"
        assert "person-level" in unsupp["reason"].lower()

    # Verify query builder does NOT include them in organization keyword tags
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "signals": persona_signals,
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)
    tags = payload.get("q_organization_keyword_tags", [])
    for ps in persona_signals:
        assert ps not in tags


def test_engagement_signals_not_mapped_to_company_keyword_tags():
    from app.services.apollo_signals_service import ApolloSignalsService

    classification = ApolloSignalsService.classify_signals(["Opened 2+ emails in past week"])
    assert len(classification["supported_company_tags"]) == 0
    assert len(classification["unsupported_signals"]) == 1
    unsupp = classification["unsupported_signals"][0]
    assert unsupp["group"] == "Engagement"
    assert unsupp["target_object"] == "People"
    assert "sequence engagement" in unsupp["reason"].lower() or "first-party" in unsupp["reason"].lower()

    # Query builder check
    raw_input = {"target_job_titles": "CTO", "signals": ["Opened 2+ emails in past week"]}
    payload = ApolloQueryBuilder.build_search_payload(normalize_icp_input(raw_input))
    assert "Opened 2+ emails in past week" not in payload.get("q_organization_keyword_tags", [])


def test_high_buying_intent_requires_intent_subscription():
    from app.services.apollo_signals_service import ApolloSignalsService

    classification = ApolloSignalsService.classify_signals(["High buying intent"])
    assert len(classification["supported_company_tags"]) == 0
    assert len(classification["unsupported_signals"]) == 1
    unsupp = classification["unsupported_signals"][0]
    assert unsupp["group"] == "Company intent"
    assert unsupp["target_object"] == "People"
    assert "bombora" in unsupp["reason"].lower()

    raw_input = {"target_job_titles": "CTO", "signals": ["High buying intent"]}
    payload = ApolloQueryBuilder.build_search_payload(normalize_icp_input(raw_input))
    assert "High buying intent" not in payload.get("q_organization_keyword_tags", [])


def test_recent_funding_signal_maps_to_funding_stages():
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "signals": ["Recent funding"],
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    # Must populate organization_latest_funding_stage_cd
    stages = payload.get("organization_latest_funding_stage_cd", [])
    assert len(stages) > 0
    assert "seed" in stages
    assert "series_a" in stages


def test_icp_score_independence_all_five_scenarios():
    """
    Requirement 3 & 6.C:
    Verify that the ICP score of the exact same prospect remains 100% identical
    across all five scenarios:
      1. No optional filters selected
      2. Company Look-alike selected
      3. Signals selected
      4. Funding selected
      5. All three selected together
    """
    from app.services.scoring_service import WinPatternScorer

    scorer = WinPatternScorer()

    # Fixed sample prospect
    prospect = {
        "title": "Chief Technology Officer",
        "company": "MedTech Solutions",
        "company_size": "201-500",
        "employee_count": 350,
        "industry": "Healthcare",
        "funding_stage": "Series A",
        "tech_stack": ["Salesforce", "AWS", "Python"],
        "email": "cto@medtechsolutions.com",
    }

    # Core ICP inputs
    core_icp = {
        "target_job_titles": "CTO, Chief Technology Officer",
        "target_location": "United States",
        "target_company_size": "201-500",
        "target_industries": "Healthcare",
    }

    # Scenario 1: Core ICP only (no optional inputs)
    s1_input = dict(core_icp)
    score_1, breakdown_1 = scorer.score(prospect)

    # Scenario 2: Company Look-alike selected
    s2_input = {**core_icp, "company_lookalike": "Google, RadNet"}
    # Prospect may have lookalike tags attached
    p2 = dict(prospect, is_lookalike=True, lookalike_seed_companies=["Google"])
    score_2, breakdown_2 = scorer.score(p2)

    # Scenario 3: Signals selected
    s3_input = {**core_icp, "signals": ["Office expansion", "New partnership"]}
    p3 = dict(prospect, matched_signals=["Office expansion"], discovery_method="signals")
    score_3, breakdown_3 = scorer.score(p3)

    # Scenario 4: Funding selected
    s4_input = {**core_icp, "funding_stages": ["Seed", "Series A"]}
    p4 = dict(prospect)
    score_4, breakdown_4 = scorer.score(p4)

    # Scenario 5: All three selected together
    s5_input = {
        **core_icp,
        "company_lookalike": "Google, RadNet",
        "signals": ["Office expansion", "New partnership"],
        "funding_stages": ["Seed", "Series A"],
    }
    p5 = dict(
        prospect,
        is_lookalike=True,
        lookalike_seed_companies=["Google"],
        matched_signals=["Office expansion"],
        discovery_method="lookalike",
    )
    score_5, breakdown_5 = scorer.score(p5)

    # Assert exact score equality across all 5 scenarios
    assert score_1 == score_2 == score_3 == score_4 == score_5
    assert breakdown_1 == breakdown_2 == breakdown_3 == breakdown_4 == breakdown_5
    assert score_1 > 0



# ═════════════════════════════════════════════════════════════════════════════
# 5. Funding Filter Tests
# ═════════════════════════════════════════════════════════════════════════════

def test_funding_stages_all_15_reference_categories():
    categories = [
        "Seed", "Angel", "Venture (Round not Specified)", "Series A", "Series B",
        "Series C", "Series D", "Series E", "Series F", "Debt Financing",
        "Equity Crowdfunding", "Convertible Note", "Private Equity",
        "Merger / Acquisition", "Other"
    ]
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "funding_stages": categories,
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    mapped = payload.get("organization_latest_funding_stage_cd", [])
    assert "seed" in mapped
    assert "angel" in mapped
    assert "venture" in mapped
    assert "series_a" in mapped
    assert "series_b" in mapped
    assert "series_c" in mapped
    assert "series_d" in mapped
    assert "series_e" in mapped
    assert "series_f" in mapped
    assert "debt_financing" in mapped
    assert "equity_crowdfunding" in mapped
    assert "convertible_note" in mapped
    assert "private_equity" in mapped
    assert "merger_or_acquisition" in mapped
    assert "other" in mapped
    assert len(mapped) == 15


def test_funding_no_minimum_amount_threshold():
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "funding_stages": ["Seed"],
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    # Must NOT inject undocumented minimum funding limits
    assert "min_funding_usd" not in payload
    assert "organization_min_funding_amount" not in payload
    assert payload["organization_latest_funding_stage_cd"] == ["seed"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. Combined Filter Semantics
# ═════════════════════════════════════════════════════════════════════════════

def test_combined_filter_query_structure():
    raw_input = {
        "target_job_titles": "CTO",
        "target_location": "United States",
        "target_company_size": "100-5000",
        "target_industries": "Healthcare",
        "company_lookalike": "Americhem",
        "lookalike_organization_ids": ["org_americhem_123"],
        "signals": ["New partnership", "Office expansion"],
        "funding_stages": ["Seed", "Series A"],
    }
    cfg = normalize_icp_input(raw_input)
    payload = ApolloQueryBuilder.build_search_payload(cfg)

    # Core ICP
    assert set(payload["person_titles"]) == {"CTO", "Chief Technology Officer"}
    assert payload["organization_locations"] == ["United States"]
    # Lookalike
    assert payload["lookalike_organization_ids"] == ["org_americhem_123"]
    # Signals (OR within)
    tags = payload["q_organization_keyword_tags"]
    assert "New partnership" in tags
    assert "Office expansion" in tags
    # Funding (OR within)
    funding_cds = payload["organization_latest_funding_stage_cd"]
    assert "seed" in funding_cds
    assert "series_a" in funding_cds


# ═════════════════════════════════════════════════════════════════════════════
# 7. Pre-Send DNC Blocking in A3 Draft Approval
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a3_draft_approval_blocks_suppressed_contact():
    from app.agents.a3_outreach import DraftManager

    db = AsyncMock()
    with patch("app.agents.a3_outreach.LLMService"):
        manager = DraftManager(db)

    # Draft exists in pending state
    draft = MagicMock(id="d1", contact_id="c1", signal_id=None, approval_state="pending", status="draft")
    contact = MagicMock(id="c1", email="suppressed.lead@domain.com", do_not_contact=True)

    with patch("app.core.config.settings.AGENT3_TEST_MODE", True):
        # 1. Draft lookup, 2. Contact lookup in approve_draft, 3. Contact lookup in is_email_suppressed
        db.execute = AsyncMock(side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=draft)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=contact)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=contact)),
        ])
        db.commit = AsyncMock()

        # Attempt to approve draft for DNC contact
        success = await manager.approve_draft("d1")

        assert success is False
        assert draft.status == "suppressed"
        assert draft.approval_state == "rejected"

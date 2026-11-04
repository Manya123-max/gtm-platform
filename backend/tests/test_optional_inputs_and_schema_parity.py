"""
Automated validation for Production Database Schema Mismatch, Safe Alembic Migration,
and Optional Input Handling (company_lookalike, signals, funding_stages).

Covers:
1. Alembic single migration head & schema parity with SQLAlchemy UserInput model.
2. All 8 required input combinations for the three optional fields:
   - Scenario 1: All three optional fields omitted.
   - Scenario 2: All three fields explicitly null.
   - Scenario 3: All three fields empty strings/empty lists.
   - Scenario 4: Only Company Lookalike populated.
   - Scenario 5: Only Signals populated.
   - Scenario 6: Only Funding Stages populated.
   - Scenario 7: Signals and Funding Stages populated together.
   - Scenario 8: All three fields populated.
3. Input validation, database persistence, WorkflowRun creation, and A1 config construction.
4. Verification that empty optional fields NEVER create restrictive filters.
"""
import pytest
from pydantic import ValidationError
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.api.v1 import InputData
from app.models.models import UserInput, WorkflowRun
from app.core.database import AsyncSessionLocal
from app.services.icp_normalizer import normalize_icp_input
from app.services.apollo_query_builder import ApolloQueryBuilder
from app.orchestrator.orchestrator_service import OrchestratorService
from app.workers.orchestrator_tasks import build_pipeline_chain


def test_alembic_single_head_and_migration_parity():
    """Verify that Alembic has exactly one head and includes the new migration."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 Alembic head, got {heads}"
    head_rev = heads[0]
    assert head_rev == "h4c9d0e1f2g3", f"Expected head to be h4c9d0e1f2g3, got {head_rev}"

    # Verify migration script exists and has upgrade/downgrade
    rev = script.get_revision("h4c9d0e1f2g3")
    assert rev is not None
    assert rev.down_revision == "g3b8c9d0e1f2"


def test_user_input_model_columns_parity():
    """Verify SQLAlchemy UserInput model declares all 13 required columns including the 3 optional fields."""
    table = UserInput.__table__
    columns = table.c

    expected_cols = [
        "id", "our_company_name", "our_services", "target_location",
        "target_industries", "target_company_size", "target_keywords",
        "company_lookalike", "signals", "funding_stages",
        "target_job_titles", "created_at", "user_id"
    ]
    for col_name in expected_cols:
        assert col_name in columns, f"Missing column {col_name} in UserInput table"

    # Verify optionality (nullable)
    assert columns["company_lookalike"].nullable is True
    assert columns["signals"].nullable is True
    assert columns["funding_stages"].nullable is True


# ── The 8 Optional Input Scenarios ──────────────────────────────────────────

BASE_VALID_ICP = {
    "our_company_name": "Acme Corp",
    "our_services": "B2B Sales Automation",
    "target_location": "San Francisco, CA",
    "target_industries": "SaaS, Cloud Software",
    "target_company_size": "50-500",
    "target_keywords": "sales intelligence, lead gen",
    "target_job_titles": "VP Sales, Head of Revenue",
}


@pytest.mark.parametrize("scenario_idx,extra_payload,expected_lookalike,expected_signals,expected_funding", [
    # 1. All three optional fields omitted
    (1, {}, "", "", ""),
    # 2. All three fields explicitly null
    (2, {"company_lookalike": None, "signals": None, "funding_stages": None}, "", "", ""),
    # 3. All three fields empty strings or empty lists
    (3, {"company_lookalike": "", "signals": [], "funding_stages": ""}, "", "", ""),
    # 4. Only Company Lookalike populated
    (4, {"company_lookalike": "Google, Salesforce", "signals": None, "funding_stages": ""}, "Google, Salesforce", "", ""),
    # 5. Only Signals populated
    (5, {"company_lookalike": None, "signals": ["New funding", "Office expansion"], "funding_stages": None}, "", "New funding, Office expansion", ""),
    # 6. Only Funding Stages populated
    (6, {"company_lookalike": "", "signals": "", "funding_stages": ["Seed", "Series A"]}, "", "", "Seed, Series A"),
    # 7. Signals and Funding Stages populated together (Lookalike empty)
    (7, {"company_lookalike": None, "signals": "Recent funding", "funding_stages": "Series B"}, "", "Recent funding", "Series B"),
    # 8. All three fields populated
    (8, {"company_lookalike": "Microsoft", "signals": "Hiring surge", "funding_stages": "Growth"}, "Microsoft", "Hiring surge", "Growth"),
])
def test_input_data_pydantic_validation_and_normalization(
    scenario_idx, extra_payload, expected_lookalike, expected_signals, expected_funding
):
    """Verify that InputData schema accepts all 8 permutations without error and normalizes properly."""
    raw = {**BASE_VALID_ICP, **extra_payload}
    parsed = InputData(**raw)

    assert parsed.company_lookalike == expected_lookalike
    assert parsed.signals == expected_signals
    assert parsed.funding_stages == expected_funding
    assert parsed.our_company_name == "Acme Corp"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario_idx,extra_payload", [
    (1, {}),
    (2, {"company_lookalike": None, "signals": None, "funding_stages": None}),
    (3, {"company_lookalike": "", "signals": [], "funding_stages": ""}),
    (4, {"company_lookalike": "Google, Salesforce", "signals": None, "funding_stages": ""}),
    (5, {"company_lookalike": None, "signals": ["New funding"], "funding_stages": None}),
    (6, {"company_lookalike": "", "signals": "", "funding_stages": ["Seed", "Series A"]}),
    (7, {"company_lookalike": None, "signals": "Recent funding", "funding_stages": "Series B"}),
    (8, {"company_lookalike": "Microsoft", "signals": "Hiring surge", "funding_stages": "Growth"}),
])
async def test_database_persistence_and_workflow_dispatch(scenario_idx, extra_payload):
    """
    Verify that in all 8 scenarios:
    1. UserInput row persists cleanly without missing column errors.
    2. WorkflowRun is created with correct agent pipeline.
    3. Celery pipeline chain is built without error.
    4. ICP normalizer and query builder treat empty fields as non-restrictive.
    """
    raw_payload = {**BASE_VALID_ICP, **extra_payload}
    input_data = InputData(**raw_payload)

    async with AsyncSessionLocal() as db_session:
        # 1. Database persistence
        record = UserInput(
            our_company_name=input_data.our_company_name,
            our_services=input_data.our_services,
            target_location=input_data.target_location,
            target_industries=input_data.target_industries or None,
            target_company_size=input_data.target_company_size,
            target_keywords=input_data.target_keywords or None,
            company_lookalike=input_data.company_lookalike or None,
            signals=input_data.signals or None,
            funding_stages=input_data.funding_stages or None,
            target_job_titles=input_data.target_job_titles,
        )
        db_session.add(record)
        await db_session.commit()
        await db_session.refresh(record)

        assert record.id is not None
        if extra_payload.get("company_lookalike"):
            assert record.company_lookalike is not None
        else:
            assert record.company_lookalike is None

        # 2. Workflow creation
        orchestrator = OrchestratorService(db_session)
        workflow = await orchestrator.create_workflow_run(
            workflow_name=f"test_run_scenario_{scenario_idx}",
            input_payload={"user_input_id": record.id},
        )
        assert workflow.id is not None
        assert workflow.status == "queued"

        # 3. Normalization & A1 query building check
        norm_cfg = normalize_icp_input({
            **raw_payload,
            "company_lookalike": input_data.company_lookalike,
            "signals": input_data.signals,
            "funding_stages": input_data.funding_stages,
        })

        apollo_payload = ApolloQueryBuilder.build_search_payload(norm_cfg)

        # Required ICP fields must always be present
        assert len(apollo_payload.get("person_titles", [])) > 0
        assert len(apollo_payload.get("organization_locations", [])) > 0
        assert len(apollo_payload.get("organization_num_employees_ranges", [])) > 0

        # Non-restrictive verification:
        if scenario_idx in (1, 2, 3):
            # When all 3 are empty, NO funding or signals restrictions are added
            assert "organization_latest_funding_stage_cd" not in apollo_payload
            assert norm_cfg.company_lookalike == []
            assert norm_cfg.signals == []
            assert norm_cfg.funding_stages == []
        elif scenario_idx == 4:
            # Only lookalike
            assert len(norm_cfg.company_lookalike) > 0
            assert norm_cfg.signals == []
            assert norm_cfg.funding_stages == []
            assert "organization_latest_funding_stage_cd" not in apollo_payload
        elif scenario_idx == 5:
            # Only signals
            assert len(norm_cfg.signals) > 0
            assert norm_cfg.company_lookalike == []
        elif scenario_idx == 6:
            # Only funding stages
            assert len(norm_cfg.funding_stages) > 0
            assert norm_cfg.company_lookalike == []
            assert "organization_latest_funding_stage_cd" in apollo_payload
            assert len(apollo_payload["organization_latest_funding_stage_cd"]) > 0

        # 4. Celery chain construction
        chain_obj = build_pipeline_chain(
            workflow_run_id=workflow.id,
            agent_ids=["A1", "A2", "A3", "A5", "A6", "A7"],
            payload={"icp_config": norm_cfg.to_dict()},
        )
        assert chain_obj is not None

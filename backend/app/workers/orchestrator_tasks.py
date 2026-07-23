import asyncio
from typing import Any, Dict, List, Optional
from app.core.config import settings
import structlog
from celery import chain
from sqlalchemy import select
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.orchestrator.orchestrator_service import OrchestratorService

logger = structlog.get_logger()


def run_async(coro: Any) -> Any:
    """
    Run an async coroutine inside a synchronous Celery task.
    """
    return asyncio.run(coro)


def normalize_previous_result(
    previous_result: Any,
) -> Dict[str, Any]:
    """
    Celery chains pass the result of the previous task as the first
    positional argument. Normalize that value into a dictionary.
    """
    if isinstance(previous_result, dict):
        return dict(previous_result)

    if previous_result is None:
        return {}

    return {
        "previous_result": previous_result,
    }


@celery_app.task(
    name="app.workers.orchestrator_tasks.run_agent_node",
    queue="agents",
    bind=True,
)
def run_agent_node(
    self: Any,
    previous_result: Optional[Dict[str, Any]] = None,
    workflow_run_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute one GTM agent inside an orchestrated workflow.

    When this task is part of a Celery chain, previous_result contains
    the output from the preceding agent.
    """

    async def _run() -> Dict[str, Any]:
        from app.agents.a1_prospect import ProspectAgent
        from app.agents.a2_signal import SignalAgent
        from app.agents.a3_outreach import OutreachAgent
        from app.agents.a5_deal import DealAgent
        from app.agents.a6_content import ContentAgent
        from app.agents.a7_revenue import RevenueAgent

        if not workflow_run_id:
            raise ValueError("workflow_run_id is required")

        if not agent_id:
            raise ValueError("agent_id is required")

        current_workflow_id: str = workflow_run_id
        current_agent_id: str = agent_id.upper()

        previous: Dict[str, Any] = normalize_previous_result(
            previous_result
        )

        payload_data: Dict[str, Any] = dict(payload or {})

        async with AsyncSessionLocal() as db:
            orchestrator = OrchestratorService(db)

            await orchestrator.mark_workflow_running(
                current_workflow_id,
                current_agent_id,
            )

            await orchestrator.mark_agent_running(
                current_workflow_id,
                current_agent_id,
            )

            try:
                raw_result: Any

                if current_agent_id == "A1":
                    cfg_value = payload_data.get("icp_config")

                    if isinstance(cfg_value, dict):
                        cfg: Dict[str, Any] = dict(cfg_value)
                    else:
                        from app.models.models import UserInput
                        stmt = select(UserInput).order_by(UserInput.id.desc()).limit(1)
                        res = await db.execute(stmt)
                        user_input = res.scalars().first()
                        if user_input:
                            titles = [t.strip() for t in user_input.job_title.split(",") if t.strip()]
                            geographies = [g.strip() for g in user_input.location.split(",") if g.strip()]
                            def to_apollo_ranges(size_str: str) -> list:
                                try:
                                    parts = size_str.replace("-", ",").split(",")
                                    low = int(parts[0].strip())
                                    high = int(parts[-1].strip()) if len(parts) > 1 else low
                                    apollo_ranges = [
                                        ("1,10", 1, 10), ("11,50", 11, 50), ("51,200", 51, 200),
                                        ("201,500", 201, 500), ("501,1000", 501, 1000),
                                        ("1001,5000", 1001, 5000), ("5001,10000", 5001, 10000),
                                    ]
                                    return [label for label, lo, hi in apollo_ranges if lo <= high and hi >= low]
                                except Exception:
                                    return ["51,200"]

                            employee_ranges = to_apollo_ranges(user_input.company_size) or ["51,200"]
                            # Build keyword list from keywords + services
                            keyword_list: list = []
                            if user_input.keywords:
                                keyword_list.extend([k.strip() for k in user_input.keywords.split(",") if k.strip()])
                            if user_input.services:
                                keyword_list.extend([s.strip() for s in user_input.services.split(",") if s.strip()])
                            cfg = {
                                "titles": titles,
                                "geographies": geographies,
                                "employee_ranges": employee_ranges,
                                "keywords": " ".join(keyword_list) if keyword_list else None,
                                # company_name intentionally omitted — that's YOUR company, not the target
                                "threshold": settings.ICP_SCORE_THRESHOLD,
                                "limit": 25,
                                "user_input_id": user_input.id,
                            }
                        else:
                            cfg = {
                                # Empty titles keep manual test runs broad.
                                "titles": [],
                                "employee_ranges": [
                                    "11,200",
                                    "201,1000",
                                ],
                                "limit": 25,
                            }

                    raw_result = await ProspectAgent(db).run(cfg)

                elif current_agent_id == "A2":
                    contact_ids = (
                        payload_data.get("contact_ids")
                        or previous.get("contact_ids")
                        or previous.get("inserted_contact_ids")
                        or []
                    )

                    raw_result = await SignalAgent(db).run(
                        contact_ids
                    )

                elif current_agent_id == "A3":
                    contact_signal_pairs = (
                        payload_data.get(
                            "contact_signal_pairs"
                        )
                        or previous.get(
                            "contact_signal_pairs"
                        )
                        or []
                    )

                    raw_result = await OutreachAgent(db).run(
                        contact_signal_pairs
                    )

                elif current_agent_id == "A5":
                    raw_result = await DealAgent(
                        db
                    ).run_daily_deal_scan()

                elif current_agent_id == "A6":
                    icp_segments = payload_data.get(
                        "icp_segments"
                    )

                    raw_result = await ContentAgent(db).run(
                        icp_segments
                    )

                elif current_agent_id == "A7":
                    raw_result = await RevenueAgent(db).run()

                else:
                    raise ValueError(
                        f"Unsupported agent_id: "
                        f"{current_agent_id}"
                    )

                if isinstance(raw_result, dict):
                    result: Dict[str, Any] = dict(
                        raw_result
                    )
                else:
                    result = {
                        "result": raw_result,
                    }

                result["_agent_id"] = current_agent_id
                result[
                    "_workflow_run_id"
                ] = current_workflow_id

                await orchestrator.mark_agent_completed(
                    current_workflow_id,
                    current_agent_id,
                    result,
                )

                logger.info(
                    "Agent node completed",
                    workflow_run_id=current_workflow_id,
                    agent_id=current_agent_id,
                    task_id=getattr(
                        self.request,
                        "id",
                        None,
                    ),
                    result=result,
                )

                return result

            except Exception as exc:
                await db.rollback()

                error_message = str(exc)

                try:
                    await orchestrator.mark_agent_failed(
                        current_workflow_id,
                        current_agent_id,
                        error_message,
                    )

                    await orchestrator.mark_workflow_failed(
                        current_workflow_id,
                        (
                            f"{current_agent_id} failed: "
                            f"{error_message}"
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist workflow failure",
                        workflow_run_id=current_workflow_id,
                        agent_id=current_agent_id,
                    )

                logger.exception(
                    "Agent node failed",
                    workflow_run_id=current_workflow_id,
                    agent_id=current_agent_id,
                    task_id=getattr(
                        self.request,
                        "id",
                        None,
                    ),
                    error=error_message,
                )

                raise

    return run_async(_run())


@celery_app.task(
    name=(
        "app.workers.orchestrator_tasks."
        "mark_workflow_completed"
    ),
    queue="agents",
)
def mark_workflow_completed(
    previous_result: Optional[Dict[str, Any]] = None,
    workflow_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Final task in an orchestrator chain.

    It receives the last agent result and marks the workflow as
    completed.
    """
    if not workflow_run_id:
        raise ValueError("workflow_run_id is required")

    current_workflow_id: str = workflow_run_id

    async def _run() -> Dict[str, Any]:
        result: Dict[str, Any] = normalize_previous_result(
            previous_result
        )

        async with AsyncSessionLocal() as db:
            orchestrator = OrchestratorService(db)

            await orchestrator.mark_workflow_completed(
                current_workflow_id,
                result,
            )

        response: Dict[str, Any] = {
            "workflow_run_id": current_workflow_id,
            "status": "completed",
            "result": result,
        }

        logger.info(
            "Workflow completed",
            workflow_run_id=current_workflow_id,
            result=result,
        )

        return response

    return run_async(_run())


def build_pipeline_chain(
    workflow_run_id: str,
    agent_ids: List[str],
    payload: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Build a Celery chain for one or more GTM agents.

    For a manual A1 run:
        agent_ids=["A1"]

    For a complete pipeline:
        agent_ids=["A1", "A2", "A3", "A5", "A6", "A7"]
    """
    if not workflow_run_id:
        raise ValueError("workflow_run_id is required")

    normalized_agent_ids: List[str] = [
        str(item).upper()
        for item in agent_ids
        if str(item).strip()
    ]

    if not normalized_agent_ids:
        raise ValueError(
            "At least one agent_id is required"
        )

    pipeline_payload: Dict[str, Any] = dict(
        payload or {}
    )

    signatures = [
        run_agent_node.s(
            workflow_run_id=workflow_run_id,
            agent_id=current_agent_id,
            payload=pipeline_payload,
        )
        for current_agent_id in normalized_agent_ids
    ]

    signatures.append(
        mark_workflow_completed.s(
            workflow_run_id=workflow_run_id
        )
    )

    return chain(*signatures)
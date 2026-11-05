import asyncio
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def run_pipeline():
    from app.core.database import AsyncSessionLocal
    from app.orchestrator.agent_graph import get_enabled_pipeline
    from app.orchestrator.orchestrator_service import OrchestratorService
    from app.workers.orchestrator_tasks import build_pipeline_chain

    print("========================================")
    print(" GTM Platform — Orchestrator Pipeline")
    print("========================================")

    agent_ids = get_enabled_pipeline()
    # Ensure sequential valid pipeline: A1, A2, A3, A5, A6, A7
    pipeline_agents = [a for a in agent_ids if a != "A4"]
    print(f"Pipeline Agents to run: {' -> '.join(pipeline_agents)}")

    async with AsyncSessionLocal() as db:
        orchestrator = OrchestratorService(db)
        workflow = await orchestrator.create_workflow_run(
            workflow_name="cli_full_orchestrator_run",
            input_payload={"agent_ids": pipeline_agents, "triggered_via": "CLI"}
        )
        for agent_id in pipeline_agents:
            await orchestrator.create_agent_execution(
                workflow_run_id=workflow.id,
                agent_id=agent_id,
                input_payload={},
            )
        workflow_id = workflow.id

    print(f"Created Workflow Run ID: {workflow_id}")
    print("Dispatching Celery chain...")

    chain_task = build_pipeline_chain(
        workflow_run_id=workflow_id,
        agent_ids=pipeline_agents,
        payload={}
    )
    async_result = chain_task.apply_async()
    print(f"Celery Chain Task ID: {async_result.id}")
    print("\n--- Monitoring Pipeline Execution ---")

    last_statuses = {}
    completed = False
    start_time = time.time()

    while not completed and (time.time() - start_time < 300):
        await asyncio.sleep(2)
        async with AsyncSessionLocal() as db:
            status_data = await orchestrator.get_workflow_status(workflow_id)
            wf = status_data.get("workflow") or {}
            agents = status_data.get("agents") or []

            for agent in agents:
                aid = agent["agent_id"]
                st = agent["status"]
                if last_statuses.get(aid) != st:
                    last_statuses[aid] = st
                    print(f"[{time.strftime('%H:%M:%S')}] Agent {aid} ({agent['agent_name']}): {st.upper()}")
                    if st == "completed" and agent.get("output_payload"):
                        summary_keys = {k: v for k, v in agent["output_payload"].items() if not k.startswith("_")}
                        print(f"       Output: {json.dumps(summary_keys, default=str)[:200]}...")
                    elif st == "failed":
                        print(f"       Error: {agent.get('error_message')}")

            wf_status = wf.get("status")
            if wf_status in ["completed", "failed"]:
                completed = True
                print(f"\n========================================")
                print(f" Workflow {workflow_id} Finished with status: {wf_status.upper()}")
                if wf.get("error_message"):
                    print(f" Error: {wf.get('error_message')}")
                print(f"========================================")
                break

if __name__ == "__main__":
    asyncio.run(run_pipeline())

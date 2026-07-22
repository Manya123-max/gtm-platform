from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import WorkflowRun, AgentExecution
from app.orchestrator.agent_graph import AGENT_GRAPH


class OrchestratorService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_workflow_run(
        self,
        workflow_name: str,
        input_payload: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRun:
        run = WorkflowRun(
            workflow_name=workflow_name,
            status="queued",
            input_payload=input_payload or {},
            created_at=datetime.utcnow(),
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def create_agent_execution(
        self,
        workflow_run_id: str,
        agent_id: str,
        input_payload: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> AgentExecution:
        agent_config = AGENT_GRAPH.get(agent_id, {})

        execution = AgentExecution(
            workflow_run_id=workflow_run_id,
            agent_id=agent_id,
            agent_name=agent_config.get("name", agent_id),
            task_id=task_id,
            status="queued",
            input_payload=input_payload or {},
            created_at=datetime.utcnow(),
        )

        self.db.add(execution)
        await self.db.commit()
        await self.db.refresh(execution)
        return execution

    async def mark_workflow_running(self, workflow_run_id: str, current_agent: str):
        result = await self.db.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        )
        run = result.scalar_one_or_none()

        if run:
            run.status = "running"
            run.current_agent = current_agent
            if not run.started_at:
                run.started_at = datetime.utcnow()
            await self.db.commit()

    async def mark_workflow_completed(
        self,
        workflow_run_id: str,
        output_payload: Optional[Dict[str, Any]] = None,
    ):
        result = await self.db.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        )
        run = result.scalar_one_or_none()

        if run:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.output_payload = output_payload or {}
            run.current_agent = None
            await self.db.commit()

    async def mark_workflow_failed(self, workflow_run_id: str, error: str):
        result = await self.db.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        )
        run = result.scalar_one_or_none()

        if run:
            run.status = "failed"
            run.error_message = error
            run.completed_at = datetime.utcnow()
            await self.db.commit()

    async def mark_agent_running(self, workflow_run_id: str, agent_id: str):
        result = await self.db.execute(
            select(AgentExecution).where(
                AgentExecution.workflow_run_id == workflow_run_id,
                AgentExecution.agent_id == agent_id,
            )
        )
        execution = result.scalar_one_or_none()

        if execution:
            execution.status = "running"
            execution.started_at = datetime.utcnow()
            await self.db.commit()

    async def mark_agent_completed(
        self,
        workflow_run_id: str,
        agent_id: str,
        output_payload: Optional[Dict[str, Any]] = None,
    ):
        result = await self.db.execute(
            select(AgentExecution).where(
                AgentExecution.workflow_run_id == workflow_run_id,
                AgentExecution.agent_id == agent_id,
            )
        )
        execution = result.scalar_one_or_none()

        if execution:
            execution.status = "completed"
            execution.completed_at = datetime.utcnow()
            execution.output_payload = output_payload or {}
            await self.db.commit()

    async def mark_agent_failed(
        self,
        workflow_run_id: str,
        agent_id: str,
        error: str,
    ):
        result = await self.db.execute(
            select(AgentExecution).where(
                AgentExecution.workflow_run_id == workflow_run_id,
                AgentExecution.agent_id == agent_id,
            )
        )
        execution = result.scalar_one_or_none()

        if execution:
            execution.status = "failed"
            execution.error_message = error
            execution.completed_at = datetime.utcnow()
            await self.db.commit()

    async def get_workflow_status(self, workflow_run_id: str) -> Dict[str, Any]:
        run_result = await self.db.execute(
            select(WorkflowRun).where(WorkflowRun.id == workflow_run_id)
        )
        run = run_result.scalar_one_or_none()

        executions_result = await self.db.execute(
            select(AgentExecution)
            .where(AgentExecution.workflow_run_id == workflow_run_id)
            .order_by(AgentExecution.created_at.asc())
        )
        executions = executions_result.scalars().all()

        return {
            "workflow": {
                "id": run.id,
                "workflow_name": run.workflow_name,
                "status": run.status,
                "current_agent": run.current_agent,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "error_message": run.error_message,
            } if run else None,
            "agents": [
                {
                    "agent_id": item.agent_id,
                    "agent_name": item.agent_name,
                    "status": item.status,
                    "task_id": item.task_id,
                    "started_at": item.started_at,
                    "completed_at": item.completed_at,
                    "error_message": item.error_message,
                    "output_payload": item.output_payload,
                }
                for item in executions
            ],
        }
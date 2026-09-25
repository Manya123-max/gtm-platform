import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import select, func
from app.models.models import WorkflowRun, Contact, UserInput, ContactUserInputAssociation, AgentExecution

async def run():
    async with AsyncSessionLocal() as db:
        print("=== LATEST AGENT EXECUTIONS ===")
        execs = (await db.execute(select(AgentExecution).order_by(AgentExecution.started_at.desc()).limit(10))).scalars().all()
        for e in execs:
            print(f"Agent: {e.agent_id} | Status: {e.status} | Err: {e.error_message}")
            print(f"  Output: {str(e.output_payload)[:200]}")
        print("=== LATEST WORKFLOW RUNS ===")
        runs = (await db.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(5))).scalars().all()
        for r in runs:
            print(f"ID: {r.id} | Status: {r.status} | Agent: {r.current_agent} | Err: {r.error_message}")
            print(f"  Output: {str(r.output_payload)[:200]}")
        
        print("\n=== TOTAL CONTACTS IN DB ===")
        cnt = (await db.execute(select(func.count(Contact.id)))).scalar()
        print(f"Total contacts count: {cnt}")
        
        recent_contacts = (await db.execute(select(Contact).order_by(Contact.created_at.desc()).limit(5))).scalars().all()
        for c in recent_contacts:
            print(f"  - {c.id} | {c.first_name} {c.last_name} | {c.company} | user_input_id: {c.user_input_id} | icp: {c.icp_score}")
        
        print("\n=== CONTACT USER INPUT ASSOCIATIONS ===")
        assocs = (await db.execute(select(ContactUserInputAssociation).limit(10))).scalars().all()
        print(f"Assocs count: {len(assocs)}")
        for a in assocs:
            print(f"  - Contact: {a.contact_id} -> UserInput: {a.user_input_id}")

        print("\n=== LATEST USER INPUTS ===")
        inputs = (await db.execute(select(UserInput).order_by(UserInput.id.desc()).limit(3))).scalars().all()
        for u in inputs:
            print(f"  - ID: {u.id} | Company: {u.our_company_name} | Titles: {u.target_job_titles} | Loc: {u.target_location}")

if __name__ == "__main__":
    asyncio.run(run())

import asyncio
import os
import sys
import argparse
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def run_agent(agent_name: str):
    from app.core.database import AsyncSessionLocal

    agent_name = agent_name.upper().strip()
    db = AsyncSessionLocal()
    try:
        print(f"========================================")
        print(f" Starting agent: {agent_name}")
        print(f"========================================")

        if agent_name in ["A1", "PROSPECT"]:
            from app.agents.a1_prospect import ProspectAgent
            agent = ProspectAgent(db)
            config = {
                "titles": ["VP of Sales", "Chief Revenue Officer", "Director of Sales", "Head of Sales"],
                "geographies": ["United States"],
                "employee_ranges": ["51,200", "201,500"],
                "limit": 10,
            }
            res = await agent.run(config)
        elif agent_name in ["A2", "SIGNAL"]:
            from app.agents.a2_signal import SignalAgent
            agent = SignalAgent(db)
            res = await agent.run()
        elif agent_name in ["A3", "OUTREACH"]:
            from app.agents.a3_outreach import OutreachAgent
            agent = OutreachAgent(db)
            res = await agent.run()
        elif agent_name in ["A5", "DEAL"]:
            from app.agents.a5_deal import DealAgent
            agent = DealAgent(db)
            res = await agent.run_daily_deal_scan()
        elif agent_name in ["A6", "CONTENT"]:
            from app.agents.a6_content import ContentAgent
            agent = ContentAgent(db)
            res = await agent.run()
        elif agent_name in ["A7", "REVENUE"]:
            from app.agents.a7_revenue import RevenueAgent
            agent = RevenueAgent(db)
            res = await agent.run()
        else:
            print(f"Unknown agent: {agent_name}. Valid options: A1, A2, A3, A5, A6, A7")
            return

        print(f"\n========================================")
        print(f" Agent {agent_name} Execution Complete")
        print(f"========================================")
        print(json.dumps(res, indent=2, default=str))
    except Exception as e:
        print(f"\n[ERROR] Failed to run agent {agent_name}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()

def main():
    parser = argparse.ArgumentParser(description="Run a GTM Platform agent directly.")
    parser.add_argument(
        "agent",
        nargs="?",
        default="A2",
        help="Agent identifier: A1 (Prospect), A2 (Signal), A3 (Outreach), A5 (Deal), A6 (Content), A7 (Revenue)"
    )
    args = parser.parse_args()
    asyncio.run(run_agent(args.agent))

if __name__ == "__main__":
    main()

from typing import Dict, List, Optional


AGENT_GRAPH = {
    "A1": {
        "name": "Prospect Intelligence",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": [],
        "next": ["A2"],
        "enabled": True,
    },
    "A2": {
        "name": "Signal Intelligence",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": ["A1"],
        "next": ["A3"],
        "enabled": True,
    },
    "A3": {
        "name": "Multi-Channel Outreach",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": ["A2"],
        "next": ["A5"],
        "enabled": True,
    },
    "A4": {
        "name": "Conversation Intelligence",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": [],
        "next": ["A5"],
        "enabled": False,
        "mode": "webhook",
    },
    "A5": {
        "name": "Deal Intelligence",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": ["A3"],
        "next": ["A6"],
        "enabled": True,
    },
    "A6": {
        "name": "Content Intelligence",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": ["A5"],
        "next": ["A7"],
        "enabled": True,
    },
    "A7": {
        "name": "Predictive Revenue",
        "task": "app.workers.orchestrator_tasks.run_agent_node",
        "depends_on": ["A6"],
        "next": [],
        "enabled": True,
    },
}


MANUAL_AGENT_TASKS = {
    "A1": "app.workers.scheduler_tasks.run_prospect_agent",
    "A2": "app.workers.scheduler_tasks.run_signal_agent",
    "A3": "app.workers.scheduler_tasks.run_outreach_agent",
    "A5": "app.workers.scheduler_tasks.run_deal_scan",
    "A6": "app.workers.scheduler_tasks.run_content_agent",
    "A7": "app.workers.scheduler_tasks.run_revenue_agent",
}


def get_agent(agent_id: str) -> Optional[Dict]:
    return AGENT_GRAPH.get(agent_id)


def get_next_agents(agent_id: str) -> List[str]:
    agent = get_agent(agent_id)
    if not agent:
        return []
    return agent.get("next", [])


def get_enabled_pipeline() -> List[str]:
    return [
        agent_id
        for agent_id, config in AGENT_GRAPH.items()
        if config.get("enabled") is True
    ]
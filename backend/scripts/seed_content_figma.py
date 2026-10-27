import asyncio
from datetime import datetime
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import GeneratedContent

CONTENT_ITEMS = [
    {
        "id": "e1011111-1111-1111-1111-111111111111",
        "title": "The 'Hidden Headcount' of GTM Ops: How Automation Replaces the Cost of Senior Technical Writers and Sales Ops Analysts — Sales Deck Outline",
        "content_format": "sales_deck_outline",
        "icp_segment": "Media Production / Financial Services / Professional Services",
        "topic": "The 'Hidden Headcount' of GTM Ops",
        "content": """Slide 1: The Hidden Headcount Drain in Your GTM Budget
Visual Layout Suggestion: Split-screen graphic contrasting an escalating corporate OpEx chart on the left with a stack of active job postings for Senior Technical Writers and Sales Ops Analysts on the right.
Key Talking Points:
• Hiring specialized talent to manage manual content distribution, proposal generation, and operational reporting creates hidden recurring costs.
• In Media Production, Financial Services, and Professional Services, the cost of staffing technical documentation and sales enablement outpaces conversion velocity.
• Why automated pipelines compress sales cycles from 45 days down to under 12 days.

Slide 2: Architectural Breakdown: Automation vs. Headcount Expansion
Visual Layout Suggestion: Multi-tier workflow diagram illustrating Apollo enrichment, intent signal capture, and automated generative Haiku drafts directly syncing to CRM.
Key Talking Points:
• Replacing routine operational drag with deterministic event loops.
• Freeing senior strategic personnel to focus on high-touch closing and enterprise deal governance.""",
        "engagement_score": 0.94,
        "used_in_outreach": False,
        "published": False,
        "created_at": datetime(2026, 10, 13, 10, 0, 0),
    },
    {
        "id": "e1022222-2222-2222-2222-222222222222",
        "title": "The 'Hidden Headcount' of GTM Ops: How Automation Replaces the Cost of Senior Technical Writers and Sales Ops Analysts — Blog Article",
        "content_format": "blog_article",
        "icp_segment": "Media Production / Financial Services / Professional Services",
        "topic": "The 'Hidden Headcount' of GTM Ops",
        "content": """## The Hiring Trap: Why Your Next Open Requisition Is Masking a Broken GTM Architecture

When enterprise job boards light up with requisitions for Senior Technical Writers, Sales Operations Analysts, and enablement coordinators, leadership usually frames it as a growth metric. Headcount expansion signals momentum.

Yet in fast-moving sectors—Media Production, Financial Services, and Professional Services—hiring specialized personnel to manually author collateral, normalize data across CRMs, and generate outbound sequences is often an expensive band-aid over structural operational latency.

### The Real Cost of 'Human Glue'
High-value knowledge workers frequently spend 60% of their bandwidth acting as "human middleware":
1. Copy-pasting metrics between Salesforce and slide decks.
2. Manually drafting personalized pitch summaries for incoming signals.
3. Troubleshooting mismatched lead stages across disparate tools.

By replacing this manual friction with autonomous GTM pipelines, modern revenue leaders reclaim both their OpEx budget and their execution speed.""",
        "engagement_score": 0.91,
        "used_in_outreach": False,
        "published": True,
        "created_at": datetime(2026, 10, 13, 10, 5, 0),
    },
    {
        "id": "e1033333-3333-3333-3333-333333333333",
        "title": "The 'Hidden Headcount' of GTM Ops: How Automation Replaces the Cost of Senior Technical Writers and Sales Ops Analysts — Case Study",
        "content_format": "case_study",
        "icp_segment": "Media Production / Financial Services / Professional Services",
        "topic": "The 'Hidden Headcount' of GTM Ops",
        "content": """### 1. Executive Summary
In a volatile economic climate, the default corporate response to scaling Go-To-Market (GTM) operations is a familiar one: open requisitions. When market demand stretches existing resources, organizations routinely post job openings for Senior Technical Writers and Sales Operations Analysts.

### 2. The Client Challenge
A mid-market professional services firm with 240 employees was experiencing severe operational bottlenecks. Their sales teams were spending an average of 18 hours per week writing custom technical proposals, managing lead enrichment, and synthesizing competitive battle cards.

### 3. The Autonomous Transformation
By deploying an agentic GTM orchestration platform:
• Inbound intent signals triggered automated sequence generation within 90 seconds.
• Deal risks and competitive differentiation were dynamically mapped from live call transcripts.
• Annual OpEx savings totaled $420,000 in deferred headcount costs.""",
        "engagement_score": 0.88,
        "used_in_outreach": False,
        "published": False,
        "created_at": datetime(2026, 10, 13, 10, 10, 0),
    },
    {
        "id": "e1044444-4444-4444-4444-444444444444",
        "title": "The 'Hidden Headcount' of GTM Ops: How Automation Replaces the Cost of Senior Technical Writers and Sales Ops Analysts — Email Sequence",
        "content_format": "email_sequence",
        "icp_segment": "Media Production / Financial Services / Professional Services",
        "topic": "The 'Hidden Headcount' of GTM Ops",
        "content": """### Subject: {company}'s gtm headcount

Hi {first_name},

Noticed {company} is scaling out senior GTM roles. While headcount signals growth, relying on expensive talent for manual content distribution and ops creates heavy OpEx drag. Instead of adding overhead, what if automation handled the heavy lifting?

We help high-growth firms in Media Production and Professional Services automate technical documentation and multi-channel sequence generation—cutting cycle times by 65%.

Do you have 10 minutes this Thursday to walk through how other revenue leaders are solving this?

Best,
P P Shree Lakshmi""",
        "engagement_score": 0.86,
        "used_in_outreach": False,
        "published": False,
        "created_at": datetime(2026, 10, 13, 10, 15, 0),
    },
    {
        "id": "e1055555-5555-5555-5555-555555555555",
        "title": "The 'Hidden Headcount' of GTM Ops: How Automation Replaces the Cost of Senior Technical Writers and Sales Ops Analysts — Linkedin Post",
        "content_format": "linkedin_post",
        "icp_segment": "Media Production / Financial Services / Professional Services",
        "topic": "The 'Hidden Headcount' of GTM Ops",
        "content": """When CFOs look at GTM budgets, they often treat headcount as the primary lever for scale. Yet, hiring specialized talent to manage manual content distribution and reporting is a lagging indicator of inefficient operational architecture. Organizations frequently expand their OpEx by recruiting for roles that autonomous pipelines can execute in milliseconds.

Here is the new reality:
• Technical writers shouldn't be copy-pasting API specs into one-pagers.
• Sales Ops analysts shouldn't be manually matching intent signals to CRM accounts.
• Strategic teams should focus on enterprise negotiation and client delivery.

Automation isn't just about efficiency—it's about operational velocity.

#GTM #RevenueOperations #SalesAutomation #B2BGrowth #AIEnterprise""",
        "engagement_score": 0.95,
        "used_in_outreach": False,
        "published": True,
        "created_at": datetime(2026, 10, 13, 10, 20, 0),
    },
]

async def seed_content():
    async with AsyncSessionLocal() as db:
        for spec in CONTENT_ITEMS:
            existing = await db.get(GeneratedContent, spec["id"])
            if not existing:
                item = GeneratedContent(**spec)
                db.add(item)
            else:
                for k, v in spec.items():
                    setattr(existing, k, v)
        await db.commit()
        print(f"Successfully seeded {len(CONTENT_ITEMS)} content items.")

if __name__ == "__main__":
    asyncio.run(seed_content())

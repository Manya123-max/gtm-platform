"""
Seed script — populates the database with sample data so every
dashboard page shows real content on first launch.

Run with Docker:
    docker-compose exec backend python scripts/seed.py

Run without Docker:
    cd backend && python scripts/seed.py
"""
import asyncio
import os
import sys
import random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://gtm:gtmpass@localhost:5432/gtm_platform"
)


async def seed():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import text

    engine = create_async_engine(DATABASE_URL, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    from app.models.models import (
        Contact, SignalEvent, SignalConversionRegistry, OutreachLog,
        PromptVariant, ConversationThread, Deal, DealStageHistory,
        PendingAction, FunnelEvent, GeneratedContent, RevenueForecast,
        ActionStatus, SignalType
    )
    from app.core.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables ready.")

    async with Session() as db:

        # ── Contacts ────────────────────────────────────────────────────
        print("Seeding contacts...")
        raw = [
            ("sarah.chen@growthops.io",        "Sarah",  "Chen",      "VP of Sales",              "GrowthOps",   "growthops.io",  "SaaS",             "51-200",  "Series B", "San Francisco, CA", 91.0),
            ("marcus.johnson@scalepath.com",    "Marcus", "Johnson",   "Chief Revenue Officer",    "ScalePath",   "scalepath.com", "B2B Technology",   "201-500", "Series C", "New York, NY",      88.0),
            ("priya.patel@revstack.ai",         "Priya",  "Patel",     "Director of Revenue Ops",  "RevStack AI", "revstack.ai",   "AI/ML SaaS",       "11-50",   "Series A", "Austin, TX",        85.0),
            ("tom.wright@databridge.co",        "Tom",    "Wright",    "Head of Sales",            "DataBridge",  "databridge.co", "Data Infra",       "51-200",  "Series B", "Chicago, IL",       83.0),
            ("lisa.wang@pipelineco.io",         "Lisa",   "Wang",      "VP Revenue",               "PipelineCo",  "pipelineco.io", "SaaS",             "51-200",  "Series A", "Boston, MA",        79.0),
            ("james.miller@salesforge.com",     "James",  "Miller",    "Sales Director",           "SalesForge",  "salesforge.com","Sales Technology", "201-500", "Series B", "Denver, CO",        76.0),
            ("anna.thompson@growthleap.io",     "Anna",   "Thompson",  "CRO",                      "GrowthLeap",  "growthleap.io", "E-commerce",       "11-50",   "Seed",     "Los Angeles, CA",   72.0),
            ("david.kim@metrics360.com",        "David",  "Kim",       "VP Sales Operations",      "Metrics360",  "metrics360.com","Analytics SaaS",   "51-200",  "Series A", "Seattle, WA",       70.0),
            ("rachel.green@outbound.ai",        "Rachel", "Green",     "Director of Sales",        "Outbound AI", "outbound.ai",   "AI SaaS",          "11-50",   "Series A", "Miami, FL",         68.0),
            ("chris.davis@salenova.com",        "Chris",  "Davis",     "Head of Growth",           "SaleNova",    "salenova.com",  "SaaS",             "11-50",   "Seed",     "Atlanta, GA",       65.0),
        ]
        contacts = []
        for (email, fn, ln, title, company, domain,
             industry, size, funding, geo, score) in raw:
            c = Contact(
                email=email, first_name=fn, last_name=ln, title=title,
                company=company, company_domain=domain, industry=industry,
                company_size=size, funding_stage=funding, geography=geo,
                icp_score=score, win_pattern_score=score,
                icp_score_breakdown={"method": "rule_based", "title": 18,
                                     "company_size": 18, "funding_stage": 20,
                                     "industry": 20, "has_tech_stack": 5},
                email_valid=True, email_verified=True,
                verified_at=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
                enriched_at=datetime.utcnow() - timedelta(days=random.randint(1, 14)),
                readiness_score=0.0,
                source="seeded",
            )
            db.add(c)
            contacts.append(c)
        await db.commit()
        for c in contacts:
            await db.refresh(c)
        print(f"  ✓ {len(contacts)} contacts")

        # ── Signals ─────────────────────────────────────────────────────
        print("Seeding signals...")
        sig_raw = [
            (contacts[0], SignalType.FUNDING_ROUND,    "newsapi_funding", 0.60,
             {"headline": "GrowthOps raises $18M Series B", "round_type": "Series B", "amount_mentioned": "$18M"}),
            (contacts[1], SignalType.NEW_HIRE,         "newsapi_general", 0.65,
             {"headline": "ScalePath names new CRO", "trigger": "leadership_news"}),
            (contacts[2], SignalType.JOB_POSTING,      "adzuna",          0.45,
             {"job_count": 4, "roles": ["SDR Manager", "BDR Team Lead"]}),
            (contacts[3], SignalType.TECH_STACK_CHANGE,"website_fingerprint", 0.75,
             {"added": ["Salesforce", "Gong"], "removed": ["HubSpot CRM"]}),
            (contacts[4], SignalType.FUNDING_ROUND,    "newsapi_funding", 0.60,
             {"headline": "PipelineCo closes $9M Series A", "amount_mentioned": "$9M"}),
            (contacts[5], SignalType.NEW_HIRE,         "adzuna",          0.65,
             {"trigger": "leadership_hire", "roles": ["VP of Sales"]}),
            (contacts[6], SignalType.NEWS_EXPANSION,   "newsapi_general", 0.25,
             {"headline": "GrowthLeap expands to European markets"}),
            (contacts[7], SignalType.JOB_POSTING,      "adzuna",          0.45,
             {"job_count": 6, "roles": ["SDR", "BDR"]}),
            (contacts[8], SignalType.FUNDING_ROUND,    "newsapi_funding", 0.60,
             {"headline": "Outbound AI secures $5.5M Series A", "amount_mentioned": "$5.5M"}),
        ]
        signals = []
        for (contact, sig_type, source, conf, raw_data) in sig_raw:
            s = SignalEvent(
                contact_id=contact.id, signal_type=sig_type,
                signal_source=source, confidence=conf, conversion_weight=conf,
                raw_data=raw_data, processed=False, triggered_outreach=False,
                detected_at=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
            )
            db.add(s)
            signals.append(s)
            contact.signal_type = sig_type
            contact.signal_score = conf * 100
            contact.latest_signal_at = s.detected_at
        await db.commit()
        print(f"  ✓ {len(signals)} signals")

        # ── Signal Registry ──────────────────────────────────────────────
        print("Seeding signal registry...")
        for sig_type, rate, n in [
            (SignalType.TECH_STACK_CHANGE, 0.72, 34),
            (SignalType.NEW_HIRE,          0.61, 52),
            (SignalType.FUNDING_ROUND,     0.58, 41),
            (SignalType.JOB_POSTING,       0.43, 67),
            (SignalType.EARNINGS_CALL,     0.64, 18),
            (SignalType.COMPETITOR_REVIEW, 0.38, 23),
            (SignalType.NEWS_EXPANSION,    0.22, 29),
            (SignalType.SOCIAL_ENGAGEMENT, 0.14, 45),
        ]:
            db.add(SignalConversionRegistry(
                signal_type=sig_type, conversion_rate=rate, sample_size=n,
                last_calibrated_at=datetime.utcnow() - timedelta(days=12),
            ))
        await db.commit()
        print("  ✓ Signal registry")

        # ── Prompt Variants ──────────────────────────────────────────────
        print("Seeding prompt variants...")
        for v_id, sig_type, rr, sends, replies in [
            ("funding_v1",   SignalType.FUNDING_ROUND, 0.148, 81,  12),
            ("newhire_v1",   SignalType.NEW_HIRE,      0.112, 62,  7),
            ("jobpost_v1",   SignalType.JOB_POSTING,   0.078, 103, 8),
        ]:
            db.add(PromptVariant(
                id=v_id, signal_type=sig_type, channel="email",
                system_prompt=f"Write concise B2B cold emails for {sig_type} signals. Under 120 words.",
                user_prompt_template="Write to {{first_name}} at {{company}}. Signal: {{signal_type}}.",
                reply_rate=rr, send_count=sends, reply_count=replies,
                meeting_count=max(1, replies // 3),
            ))
        await db.commit()
        print("  ✓ Prompt variants")

        # ── Outreach Logs ────────────────────────────────────────────────
        print("Seeding outreach logs...")
        for i, contact in enumerate(contacts[:7]):
            db.add(OutreachLog(
                contact_id=contact.id,
                campaign_type=signals[i].signal_type if i < len(signals) else SignalType.JOB_POSTING,
                channel="email",
                subject=f"Quick question about {contact.company}'s growth",
                body_preview=f"Hi {contact.first_name}, noticed {contact.company} has been making moves recently...",
                prompt_variant_id="funding_v1" if i < 2 else "newhire_v1",
                signal_id=signals[i].id if i < len(signals) else None,
                opened=i < 5, open_count=random.randint(1, 3) if i < 5 else 0,
                replied=i < 3, meeting_booked=(i == 0),
                sent_at=datetime.utcnow() - timedelta(days=random.randint(1, 14)),
                replied_at=datetime.utcnow() - timedelta(days=random.randint(1, 5)) if i < 3 else None,
            ))
        await db.commit()
        print("  ✓ Outreach logs")

        # ── Conversation Threads ─────────────────────────────────────────
        print("Seeding conversation threads...")
        threads = [
            (contacts[0], [
                ("email_sent",    "outbound", "Hi Sarah, congrats on the Series B. Teams scaling post-funding usually hit outbound bottlenecks fast. Worth 20 mins?", None, None, 0),
                ("reply_received","inbound",  "Thanks! Yes we're feeling growing pains. What does your platform do exactly?", "interested", 0.85, 25),
                ("email_sent",    "outbound", "7 AI agents — prospecting, signals, outreach, CRM, content, forecasting. 3-day setup. Free demo Thursday?", None, None, 0),
                ("reply_received","inbound",  "Thursday 2pm PST works. Send a cal link?", "interested", 0.92, 20),
            ]),
            (contacts[1], [
                ("email_sent",    "outbound", "Marcus — saw you joined ScalePath as CRO. New leaders usually audit the GTM stack in first 60 days. AI tooling on your list?", None, None, 0),
                ("reply_received","inbound",  "Actually yes. We're evaluating outbound stack right now. Send me a one-pager?", "interested", 0.78, 25),
            ]),
            (contacts[3], [
                ("email_sent",    "outbound", "Tom — noticed DataBridge switched from HubSpot to Salesforce. That transition is when teams re-evaluate everything.", None, None, 0),
                ("reply_received","inbound",  "Good timing. We're in the middle of that chaos. What do you offer?", "interested", 0.81, 25),
            ]),
        ]
        for contact, events in threads:
            score = 0.0
            for ev_type, direction, content, intent, conf, delta in events:
                score = min(100.0, score + delta)
                db.add(ConversationThread(
                    contact_id=contact.id, event_type=ev_type,
                    direction=direction, channel="email", content=content,
                    intent=intent, intent_confidence=conf,
                    readiness_score_delta=float(delta), readiness_score_after=score,
                    occurred_at=datetime.utcnow() - timedelta(hours=random.randint(6, 72)),
                ))
            contact.readiness_score = score
        await db.commit()
        print("  ✓ Conversation threads")

        # ── Deals ────────────────────────────────────────────────────────
        print("Seeding deals...")
        deal_raw = [
            ("GrowthOps — Platform Deal",  "proposal",    24000, contacts[0], 8,  0.2, True,  True,  True,  False),
            ("ScalePath — Enterprise",     "demo",         48000, contacts[1], 5,  0.0, True,  False, True,  False),
            ("RevStack AI — Startup",      "discovery",    9600,  contacts[2], 12, 0.4, False, False, True,  False),
            ("DataBridge — Pro Plan",      "negotiation",  36000, contacts[3], 19, 0.6, True,  True,  True,  True),
            ("PipelineCo — Growth",        "proposal",     18000, contacts[4], 23, 0.5, True,  False, True,  False),
            ("SalesForge — Team Plan",     "prospecting",  7200,  contacts[5], 3,  0.0, False, False, False, False),
        ]
        deals = []
        for (name, stage, amount, contact, days, risk,
             budget, authority, need, timeline) in deal_raw:
            d = Deal(
                name=name, stage=stage, amount=amount, contact_id=contact.id,
                days_in_current_stage=days, risk_score=risk,
                budget_confirmed=budget, authority_confirmed=authority,
                need_confirmed=need, timeline_confirmed=timeline,
                owner_email="rep@yourcompany.com",
                stage_entered_at=datetime.utcnow() - timedelta(days=days),
                risk_flags=[{
                    "type": "stage_stall", "severity": "high",
                    "description": f"In {stage} for {days} days — above average.",
                }] if risk >= 0.4 else [],
            )
            db.add(d)
            deals.append(d)
        await db.commit()
        for d in deals:
            db.add(DealStageHistory(
                deal_id=d.id, from_stage="prospecting", to_stage=d.stage,
                days_in_from_stage=random.randint(2, 6),
                transitioned_at=datetime.utcnow() - timedelta(days=d.days_in_current_stage),
            ))
        await db.commit()
        print(f"  ✓ {len(deals)} deals + stage history")

        # ── Pending Actions ──────────────────────────────────────────────
        print("Seeding pending actions...")
        for atype, eid, rec, current, reason in [
            ("stage_stall",      deals[3].id, "Move to closed_won or re-qualify",     "negotiation", "In negotiation 19d — avg is 9d."),
            ("incomplete_bant",  deals[1].id, "Confirm authority before next call",   "demo",        "Authority not confirmed at demo stage."),
            ("stage_stall",      deals[4].id, "Set explicit decision deadline",       "proposal",    "In proposal 23d without agreement."),
            ("response_slowdown",deals[2].id, "Try a different stakeholder",          "discovery",   "Response time grew 24h → 72h over last 3 touches."),
        ]:
            db.add(PendingAction(
                action_type=atype, entity_type="deal", entity_id=str(eid),
                recommended_value=rec, current_value=current, reason=reason,
                agent_id="A5", status=ActionStatus.PENDING,
                expires_at=datetime.utcnow() + timedelta(days=3),
            ))
        await db.commit()
        print("  ✓ Pending actions")

        # ── Funnel Events ────────────────────────────────────────────────
        print("Seeding funnel events...")
        for ev_type, count in [
            ("prospect_batch_completed", 4),  ("email_sent", 54),
            ("email_draft_created", 12),       ("signal_batch_completed", 18),
            ("reply_received", 18),            ("meeting_booked", 9),
            ("transcript_processed", 6),       ("content_batch_completed", 3),
            ("forecast_calculated", 2),
        ]:
            for _ in range(count):
                db.add(FunnelEvent(
                    event_type=ev_type, agent_id="A1",
                    contact_id=random.choice(contacts).id if random.random() > 0.3 else None,
                    event_metadata={"seeded": True},
                    timestamp=datetime.utcnow() - timedelta(
                        days=random.randint(0, 28), hours=random.randint(0, 23)),
                ))
        await db.commit()
        print("  ✓ Funnel events")

        # ── Generated Content ────────────────────────────────────────────
        print("Seeding generated content...")
        for title, fmt, segment, content in [
            ("Why B2B Outbound Fails — LinkedIn Post", "linkedin_post", "B2B SaaS",
             "Most B2B outbound fails for one reason: teams send the same email to everyone.\n\nThe company that just raised a Series B has completely different problems than the one at seed stage.\n\nPersonalization is matching your message to the specific moment they're in.\n\nWhat moment is your prospect in right now?"),
            ("How Series B Companies Scale GTM Without Hiring — Blog", "blog_article", "Series B SaaS",
             "The funding is in the bank. The board wants 3x growth. The instinct is to hire.\n\nBut the fastest-growing B2B SaaS companies at Series B aren't just hiring more reps. They're building systems that make each rep dramatically more effective.\n\nHere is what that looks like in practice..."),
            ("Email Sequence — New VP Hire Signal", "email_sequence", "Sales Technology",
             "Email 1 (Day 2):\nSubject: Congrats on the new role\n\nHi {first_name},\n\nSaw you joined {company} as {title} — congrats. New sales leaders typically audit tools in the first 60 days. AI agents on your radar?\n\n{sender}"),
        ]:
            db.add(GeneratedContent(
                title=title, content_format=fmt, icp_segment=segment,
                topic=title, content=content,
                used_in_outreach=(fmt == "email_sequence"),
            ))
        await db.commit()
        print("  ✓ Content pieces")

        # ── Revenue Forecast ─────────────────────────────────────────────
        print("Seeding revenue forecast...")
        total = sum(d.amount or 0 for d in deals)
        db.add(RevenueForecast(
            forecast_30d=total * 0.22,
            forecast_60d=total * 0.51,
            forecast_90d=total * 0.74,
            current_pipeline_value=total,
            bottleneck_stage="proposal",
            bottleneck_description="Proposal conversion 28% vs 41% historical baseline. 2 deals stalled >20 days.",
            recommended_lever="Set explicit decision deadlines. Involve procurement earlier to prevent stalls.",
            stage_conversion_rates={
                "prospecting_to_discovery": 0.41,
                "discovery_to_demo": 0.58,
                "demo_to_proposal": 0.44,
                "proposal_to_negotiation": 0.28,
                "negotiation_to_closed_won": 0.71,
            },
            stage_velocity_days={
                "prospecting": 4.2, "discovery": 7.8, "demo": 5.1,
                "proposal": 16.4, "negotiation": 11.2,
            },
            calculated_at=datetime.utcnow() - timedelta(hours=4),
        ))
        await db.commit()
        print("  ✓ Revenue forecast")

    await engine.dispose()
    print(f"""
╔══════════════════════════════════════════════════╗
║        Seed complete — open the platform         ║
╠══════════════════════════════════════════════════╣
║  Frontend   →  http://localhost:3000             ║
║  API docs   →  http://localhost:8000/api/docs    ║
╠══════════════════════════════════════════════════╣
║  10 contacts  |  9 signals  |  6 deals           ║
║  Pipeline: ${total:,.0f}                          ║
╚══════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    asyncio.run(seed())

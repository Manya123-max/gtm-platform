import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.models import RevenueForecast, FunnelEvent, Contact

async def seed_revenue():
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()

        # 1. Seed latest pristine RevenueForecast matching Figma screenshot
        forecast_id = 'f1011111-1111-1111-1111-111111111111'
        forecast_data = {
            'forecast_30d': 21522.0,
            'forecast_60d': 98132.0,
            'forecast_90d': 176298.0,
            'current_pipeline_value': 1112800.0,
            'bottleneck_stage': 'Proposal Stage Bottleneck',
            'bottleneck_description': 'Proposal stage conversion is 0.0% vs 50.0% benchmark (100% deficit) (2 deals currently stalled >20 days).',
            'recommended_lever': 'Shorten proposal evaluation cycles. Set clear decision deadlines and engage IT security/procurement stakeholders earlier.',
            'stage_conversion_rates': {
                'Demo Transition': 0.45,
                'Discovery Transition': 0.55,
                'Proposal Transition': 0.00,
                'Prospecting Transition': 0.45,
                'Negotiation Transition': 0.65
            },
            'stage_velocity_days': {
                'Demo Transition': 14,
                'Discovery Transition': 21,
                'Proposal Transition': 25,
                'Prospecting Transition': 7,
                'Negotiation Transition': 18
            },
            'user_id': None,
            'calculated_at': now + timedelta(minutes=5)
        }

        existing = await db.get(RevenueForecast, forecast_id)
        if not existing:
            f = RevenueForecast(id=forecast_id, **forecast_data)
            db.add(f)
        else:
            for k, v in forecast_data.items():
                setattr(existing, k, v)

        # 2. Seed recent FunnelEvents for Activity Log (30 days): reply received, timeout approval required
        contact_res = await db.execute(select(Contact.id).where(Contact.user_id.is_(None)).limit(1))
        contact_id = contact_res.scalars().first()

        if contact_id:
            for i in range(24):
                fe = FunnelEvent(
                    contact_id=contact_id,
                    event_type='reply received',
                    agent_id='A4',
                    event_metadata={},
                    timestamp=now - timedelta(days=i % 25, hours=i)
                )
                db.add(fe)

            for i in range(10):
                fe = FunnelEvent(
                    contact_id=contact_id,
                    event_type='timeout approval required',
                    agent_id='A3',
                    event_metadata={},
                    timestamp=now - timedelta(days=(i * 2) % 25, hours=i)
                )
                db.add(fe)

        await db.commit()
        print('Revenue forecast and activity funnel events successfully seeded!')

if __name__ == '__main__':
    asyncio.run(seed_revenue())

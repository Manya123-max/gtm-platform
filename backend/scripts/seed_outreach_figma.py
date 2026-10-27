import asyncio
from datetime import datetime, timedelta
from app.core.database import AsyncSessionLocal
from sqlalchemy import select
from app.models.models import Contact, OutreachDraft

async def seed_outreach():
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        
        # 1. Contacts Data
        contacts_specs = [
            {
                'id': 'c1011111-1111-1111-1111-111111111111',
                'first_name': 'Xiangyang',
                'last_name': 'Wang',
                'title': 'Chief Technology Officer',
                'email': 'wangx@arrivent.com',
                'company': 'ArriVent Biopharma',
                'industry': 'Biotechnology',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1022222-2222-2222-2222-222222222222',
                'first_name': 'Moshe',
                'last_name': 'Renewable',
                'title': 'VP Operations',
                'email': 'moshe@ukko.ag',
                'company': 'Ukko',
                'industry': 'AgTech & Clean Energy',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1033333-3333-3333-3333-333333333333',
                'first_name': 'John',
                'last_name': 'Henderson',
                'title': 'Head of Growth',
                'email': 'john@helio.energy',
                'company': 'HELIO',
                'industry': 'Clean Energy',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1044444-4444-4444-4444-444444444444',
                'first_name': 'David',
                'last_name': 'Vance',
                'title': 'VP Digital Strategy',
                'email': 'dvance@usdm.com',
                'company': 'USDM Life Sciences',
                'industry': 'Life Sciences',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1055555-5555-5555-5555-555555555555',
                'first_name': 'Rui',
                'last_name': 'Chen',
                'title': 'VP Corporate Development',
                'email': 'rui.chen@adarx.com',
                'company': 'ADARx Pharmaceuticals Inc.',
                'industry': 'Pharmaceuticals',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1066666-6666-6666-6666-666666666666',
                'first_name': 'Gregory',
                'last_name': 'Sullivan',
                'title': 'Chief Medical Officer & VP Strategy',
                'email': 'gregory.sullivan@tonixpharma.com',
                'company': 'Tonix Pharmaceuticals',
                'industry': 'Pharmaceuticals',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1077777-7777-7777-7777-777777777777',
                'first_name': 'Michael',
                'last_name': 'Gordon',
                'title': 'VP Commercial Operations',
                'email': 'mgordon@mnghealth.com',
                'company': 'MNG Health',
                'industry': 'Healthcare Technology',
                'source': 'apollo',
                'user_id': None
            },
            {
                'id': 'c1088888-8888-8888-8888-888888888888',
                'first_name': 'Mike',
                'last_name': 'Evans',
                'title': 'Managing Director',
                'email': 'mike.evans@momentumls.com',
                'company': 'Momentum Life Sciences',
                'industry': 'Life Sciences',
                'source': 'apollo',
                'user_id': None
            }
        ]

        for cs in contacts_specs:
            c = await db.get(Contact, cs['id'])
            if not c:
                c = Contact(**cs)
                db.add(c)
            else:
                for k, v in cs.items():
                    setattr(c, k, v)
        await db.commit()

        # 2. 11 Exact Drafts for Active Session matching Figma
        drafts_specs = [
            {
                'id': 'd1011111-1111-1111-1111-111111111111',
                'contact_id': 'c1011111-1111-1111-1111-111111111111',
                'subject': 'CRM & GTM operations at ArriVent Biopharma',
                'business_case': 'General Sales Outreach',
                'matched_services': ['CRM consulting', 'GTM automation'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(minutes=10),
                'body': """Hi Xiangyang,

As CTO at ArriVent, you're likely balancing operational efficiency with strategic execution, especially following recent updates regarding Firmonertinib.

We help research firms automate GTM operations and integrate cloud CRM systems. Given ArriVent's scale, I wanted to see how you are currently handling Salesforce data enrichment and lead management.

Do you have 10 minutes for a brief call to discuss streamlining these processes?

Best,
P P Shree Lakshmi

Feel free to select a convenient time on my calendar: https://cal.com/shree-lakshmi-iaqqsz/30min?name=Xiangyang+Wang&email=wangx%40arrivent.com"""
            },
            {
                'id': 'd1022222-2222-2222-2222-222222222222',
                'contact_id': 'c1022222-2222-2222-2222-222222222222',
                'subject': "Smart scaling for Ukko Renewable's $50M expansion",
                'business_case': 'Funding Round',
                'matched_services': ['GTM scaling', 'Cloud CRM'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(minutes=20),
                'body': """Hi Moshe,

Congratulations on Ukko Renewable's recent $50M funding round!

As you scale operations across new markets, automating GTM execution and aligning CRM data will be vital to sustaining this momentum. We help high-growth teams integrate AI-driven intelligence into their sales pipelines.

Would you be open to a 10-minute chat next week to discuss your scale-up roadmap?

Best,
P P Shree Lakshmi

Feel free to select a convenient time on my calendar: https://cal.com/shree-lakshmi-iaqqsz/30min?name=Moshe&email=moshe%40ukko.ag"""
            },
            {
                'id': 'd1033333-3333-3333-3333-333333333333',
                'contact_id': 'c1022222-2222-2222-2222-222222222222',
                'subject': 'Congrats on the $50M Series, Moshe!',
                'business_case': 'Funding Round',
                'matched_services': ['Funding celebration', 'GTM alignment'],
                'channel': 'email',
                'status': 'failed',
                'approval_state': 'rejected',
                'created_at': now - timedelta(minutes=30),
                'body': """Hi Moshe,

Saw the news regarding the $50M Series announcement — congratulations!

Wanted to check in and see how your sales team is preparing for the hiring surge and inbound demand.

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1044444-4444-4444-4444-444444444444',
                'contact_id': 'c1033333-3333-3333-3333-333333333333',
                'subject': 'Optimizing GTM and CRM operations at HELIO',
                'business_case': 'General Sales Outreach',
                'matched_services': ['CRM consulting', 'Lead enrichment'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(minutes=40),
                'body': """Hi John,

Given HELIO's rapid market expansion, streamlining CRM processes and lead scoring is essential to maximize outbound efficiency.

We specialize in full-cycle GTM automation for clean energy pioneers. Would you have 10 minutes this week for a brief introductory call?

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1055555-5555-5555-5555-555555555555',
                'contact_id': 'c1044444-4444-4444-4444-444444444444',
                'subject': 'Accelerating digital transformation at USDM Life Sciences',
                'business_case': 'Digital Transformation',
                'matched_services': ['Compliance automation', 'CRM migration'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(minutes=50),
                'body': """Hi David,

Noticed USDM Life Sciences is accelerating digital transformation initiatives across regulatory compliance and cloud architecture.

We help life sciences leaders automate data pipelines and CRM workflows with full auditability. Would you be open to a short exchange on how peer firms approach this?

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1066666-6666-6666-6666-666666666666',
                'contact_id': 'c1011111-1111-1111-1111-111111111111',
                'subject': 'Accelerating digital transformation at ArriVent Biopharma',
                'business_case': 'Digital Transformation',
                'matched_services': ['Clinical ops integration', 'Salesforce CRM'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=1),
                'body': """Hi Xiangyang,

Following up on ArriVent's pipeline expansion, we are supporting biopharma engineering teams in automating their Salesforce CRM and clinical trial tracking.

Would love to share a few benchmarks from our recent enterprise deployments if you have 10 minutes.

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1077777-7777-7777-7777-777777777777',
                'contact_id': 'c1055555-5555-5555-5555-555555555555',
                'subject': 'Congrats on the US IPO filing, Rui!',
                'business_case': 'Funding Round',
                'matched_services': ['IPO scale', 'Executive outreach'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=2),
                'body': """Hi Rui,

Huge congratulations on ADARx Pharmaceuticals' US IPO filing! An incredible milestone for your RNA therapeutics pipeline.

As public market visibility increases, maintaining rigorous GTM and investor engagement tracking becomes critical. We provide automated stakeholder intelligence for biopharma leaders.

Let's connect for 10 minutes when convenient.

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1088888-8888-8888-8888-888888888888',
                'contact_id': 'c1033333-3333-3333-3333-333333333333',
                'subject': 'Congrats on the federal investment milestone, John!',
                'business_case': 'Funding Round',
                'matched_services': ['Federal grant scale', 'GTM acceleration'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=3),
                'body': """Hi John,

Congratulations on securing the federal investment award for HELIO!

With public sector backing, scaling partner channels and enterprise sales workflows will be the next major phase. Would love to share insights on how we help energy tech firms orchestrate their sales stack.

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1099999-9999-9999-9999-999999999999',
                'contact_id': 'c1066666-6666-6666-6666-666666666666',
                'subject': 'Accelerating digital transformation at Tonix Pharmaceuticals',
                'business_case': 'Digital Transformation',
                'matched_services': ['Pharma GTM', 'Cloud infrastructure'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=4),
                'body': """Hi Gregory,

As Tonix advances its therapeutic pipeline, modernizing commercial ops and CRM data readiness can dramatically speed up market access.

We empower biopharma teams with automated GTM execution. Would you have a few minutes for a high-level briefing?

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1100000-0000-0000-0000-000000000000',
                'contact_id': 'c1077777-7777-7777-7777-777777777777',
                'subject': 'Optimizing your new ZoomInfo stack',
                'business_case': 'AI Automation',
                'matched_services': ['Tech stack integration', 'Data hygiene'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=5),
                'body': """Hi Michael,

Saw that MNG Health recently rolled out new data stack integrations including ZoomInfo.

Many commercial operations leaders find that without automated lead routing and CRM hygiene, contact data decays quickly. We help bridge that gap seamlessly.

Let's grab 10 minutes this week if you'd like to compare notes.

Best,
P P Shree Lakshmi"""
            },
            {
                'id': 'd1110000-0000-0000-0000-000000000000',
                'contact_id': 'c1088888-8888-8888-8888-888888888888',
                'subject': 'Congrats on the growth investment, Mike!',
                'business_case': 'Funding Round',
                'matched_services': ['Growth capital advisory', 'Sales operations'],
                'channel': 'email',
                'status': 'pending',
                'approval_state': 'pending',
                'created_at': now - timedelta(hours=6),
                'body': """Hi Mike,

Congratulations on the recent growth investment for Momentum Life Sciences!

Scaling operations while keeping sales cycles lean is a top priority following new capital injection. We'd love to share how our AI GTM platform helps firms scale outreach with zero headcount overhead.

Do you have 10 minutes for a brief introduction?

Best,
P P Shree Lakshmi"""
            }
        ]

        for ds in drafts_specs:
            d = await db.get(OutreachDraft, ds['id'])
            if not d:
                d = OutreachDraft(**ds)
                db.add(d)
            else:
                for k, v in ds.items():
                    setattr(d, k, v)
        await db.commit()

        # Adjust historical count: make exactly 31 approved/historical drafts
        all_drafts = (await db.execute(select(OutreachDraft))).scalars().all()
        active_ids = {ds['id'] for ds in drafts_specs}
        other_drafts = [d for d in all_drafts if d.id not in active_ids]
        
        for idx, od in enumerate(other_drafts):
            if idx < 31:
                od.approval_state = 'approved'
                od.status = 'sent'
            else:
                await db.delete(od)
        await db.commit()

        print(f'Successfully seeded! Active: {len(drafts_specs)}, History in DB: {len(other_drafts[:31])}')

if __name__ == '__main__':
    asyncio.run(seed_outreach())

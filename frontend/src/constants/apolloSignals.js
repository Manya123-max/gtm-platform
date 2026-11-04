/**
 * Apollo Signals Master Taxonomy (All 14 signals from Apollo interface)
 *
 * Signal Groups:
 * 1. Company momentum (Target Object: Companies)
 * 2. Company intent (Target Object: People)
 * 3. Persona (Target Object: People)
 * 4. Engagement (Target Object: People)
 */

export const APOLLO_SIGNALS = [
    // ── Group 1: Company momentum (Target Object: Companies) ──
    {
        name: 'Award or recognition',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company recently won an industry award or prestigious public recognition.',
        supportStatus: 'partial',
        supportBadge: 'Via News Tag',
        supported: true,
    },
    {
        name: 'Cutting costs',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company announces cost restructuring, hiring freezes, or facility consolidation.',
        supportStatus: 'unsupported',
        supportBadge: 'Requires Events Stream',
        supported: false,
    },
    {
        name: 'Merger or acquisition',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company acquired another organization or announced a merger.',
        supportStatus: 'partial',
        supportBadge: 'M&A / News Tag',
        supported: true,
    },
    {
        name: 'New client signed',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company publicly announced securing a major new commercial customer or contract.',
        supportStatus: 'unsupported',
        supportBadge: 'Requires Events Stream',
        supported: false,
    },
    {
        name: 'New partnership',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company formed a strategic alliance, technology integration, or reseller partnership.',
        supportStatus: 'partial',
        supportBadge: 'Via News Tag',
        supported: true,
    },
    {
        name: 'New product or service',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company announced or launched a new software product, platform version, or service.',
        supportStatus: 'partial',
        supportBadge: 'Via News Tag',
        supported: true,
    },
    {
        name: 'Office expansion',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company opened new regional offices, facilities, or expanded corporate footprint.',
        supportStatus: 'partial',
        supportBadge: 'Via News Tag',
        supported: true,
    },
    {
        name: 'Rapid growth',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company experiencing rapid headcount acceleration or exceptional business scaling.',
        supportStatus: 'partial',
        supportBadge: 'Growth / Keyword Tag',
        supported: true,
    },
    {
        name: 'Recent funding',
        group: 'Company momentum',
        targetObject: 'Companies',
        description: 'Company recently closed a venture capital, seed, debt, or growth funding round.',
        supportStatus: 'supported',
        supportBadge: 'Fully Supported',
        supported: true,
    },

    // ── Group 2: Company intent (Target Object: People) ──
    {
        name: 'High buying intent',
        group: 'Company intent',
        targetObject: 'People',
        description: 'Prospects at organizations exhibiting surging digital research activity on relevant B2B topics (Bombora Intent).',
        supportStatus: 'requires_addon',
        supportBadge: 'Requires Bombora Intent Plan',
        supported: false,
    },

    // ── Group 3: Persona (Target Object: People) ──
    {
        name: 'Former champion changed jobs',
        group: 'Persona',
        targetObject: 'People',
        description: 'A contact or champion from a previous deal in your CRM moved to a new company.',
        supportStatus: 'requires_crm',
        supportBadge: 'Requires CRM Integration',
        supported: false,
    },
    {
        name: 'New role',
        group: 'Persona',
        targetObject: 'People',
        description: 'Individual recently started in a new job role or company (last 30-90 days).',
        supportStatus: 'requires_plays',
        supportBadge: 'Requires Job Change Plays',
        supported: false,
    },
    {
        name: 'Recently promoted',
        group: 'Persona',
        targetObject: 'People',
        description: 'Individual was promoted internally within their organization in the last 3-6 months.',
        supportStatus: 'requires_plays',
        supportBadge: 'Requires Job Change Plays',
        supported: false,
    },

    // ── Group 4: Engagement (Target Object: People) ──
    {
        name: 'Opened 2+ emails in past week',
        group: 'Engagement',
        targetObject: 'People',
        description: 'Lead opened 2+ outreach emails in the past 7 days (outbound sequence engagement metric).',
        supportStatus: 'requires_sequence',
        supportBadge: 'Active Sequences Only',
        supported: false,
    },
];

export const SIGNAL_GROUP_ORDER = [
    'Company momentum',
    'Company intent',
    'Persona',
    'Engagement',
];


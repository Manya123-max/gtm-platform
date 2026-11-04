import {
  Briefcase,
  UserCheck,
  CreditCard,
  TrendingUp,
  Building2,
  Radio,
  MessageSquare,
  Zap,
  FileText,
} from 'lucide-react'

/**
 * Humanizes raw signal source string.
 */
export function humanizeSource(source) {
  if (!source) return 'Verified Source'
  const s = String(source).toLowerCase().trim()
  if (s.includes('adzuna')) return 'Adzuna Job Board'
  if (s.includes('currents')) return 'Currents News'
  if (s.includes('newsapi')) return 'NewsAPI'
  if (s.includes('predictleads')) return 'PredictLeads'
  if (s.includes('google')) return 'Google News'
  if (s.includes('website_fingerprint')) return 'Website Fingerprint'
  if (s.includes('apify') || s.includes('reddit')) return 'Reddit Community'
  if (s.includes('linkedin')) return 'LinkedIn'
  if (s.includes('sec')) return 'SEC Edgar'
  return source.replace(/_/g, ' ').replace(/\b[a-z]/g, c => c.toUpperCase())
}

/**
 * Inactive or safe date formatter.
 */
export function formatDisplayDate(dateStr) {
  if (!dateStr) return null
  try {
    const s = String(dateStr).trim()
    const isIsoNaive = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)
    const normalizedStr = isIsoNaive ? `${s}Z` : s
    const d = new Date(normalizedStr)
    if (isNaN(d.getTime())) return null
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return null
  }
}

/**
 * Derives visual metadata (icon, display label) for each signal type.
 */
export function getSignalMeta(sig) {
  if (!sig) return { title: 'Signal', displayType: 'Signal', icon: FileText }
  const sigType = (sig.signal_type || '').toLowerCase()
  const raw = sig.raw_data || {}
  const headline = raw.headline || raw.title || sig.summary || ''

  if (sigType === 'job_posting' || (sigType.includes('job') && !sigType.includes('hire'))) {
    const isLead = raw.trigger === 'leadership_job_opening' || Boolean(raw.is_leadership_role)
    return {
      title: headline || (isLead ? 'Leadership Requisition' : 'Job Vacancy'),
      displayType: isLead ? 'Leadership Requisition' : 'Job Posting',
      icon: Briefcase,
    }
  }

  if (sigType === 'new_hire' || sigType.includes('hire') || raw.trigger === 'leadership_hire') {
    return {
      title: headline || 'Leadership Appointment',
      displayType: 'Leadership Appointment',
      icon: UserCheck,
    }
  }

  if (sigType === 'funding_round' || sigType.includes('funding')) {
    const stage = raw.funding_stage || raw.round_type
    const label = stage ? `${stage} Funding` : 'Funding Round'
    return {
      title: headline || label,
      displayType: label,
      icon: CreditCard,
    }
  }

  if (sigType === 'news_expansion' || sigType.includes('expansion') || sigType.includes('news')) {
    const subtype = raw.subtype || (raw.trigger ? raw.trigger.replace(/_/g, ' ') : null)
    let label = 'Business Expansion'
    let icon = TrendingUp
    if (subtype) {
      const subLow = subtype.toLowerCase()
      if (subLow.includes('office')) {
        label = 'Office Expansion'
        icon = Building2
      } else if (subLow.includes('partner')) {
        label = 'New Partnership'
        icon = TrendingUp
      } else if (subLow.includes('acqui') || subLow.includes('merger')) {
        label = 'Merger or Acquisition'
        icon = Building2
      } else if (subLow.includes('product') || subLow.includes('launch')) {
        label = 'Product Launch'
        icon = TrendingUp
      } else if (subLow.includes('geographic')) {
        label = 'Geographic Expansion'
        icon = TrendingUp
      } else {
        label = subtype
      }
    }
    return {
      title: headline || label,
      displayType: label,
      icon,
    }
  }

  if (sigType === 'earnings_call' || sigType.includes('earnings')) {
    return {
      title: headline || 'Earnings Announcement',
      displayType: 'Earnings Announcement',
      icon: Radio,
    }
  }

  if (sigType === 'social_engagement' || sigType.includes('social') || sigType.includes('reddit')) {
    return {
      title: headline || 'Customer Discussion',
      displayType: 'Customer Discussion',
      icon: MessageSquare,
    }
  }

  if (sigType === 'tech_stack_observed' || (sigType.includes('tech') && sigType.includes('observed')) || sig.signal_source === 'website_fingerprint') {
    return {
      title: headline || 'Active Technology Observed',
      displayType: 'Active Technology Observed',
      icon: Zap,
    }
  }

  if (sigType === 'tech_stack_change' || sigType.includes('tech') || sigType.includes('stack')) {
    return {
      title: headline || 'Active Technology Observed',
      displayType: 'Active Technology Observed',
      icon: Zap,
    }
  }

  return {
    title: headline || 'Business Signal',
    displayType: sig.signal_type ? sig.signal_type.replace(/_/g, ' ').replace(/\b[a-z]/g, c => c.toUpperCase()) : 'Market Signal',
    icon: FileText,
  }
}

/**
 * Extracts signal-type-specific details for presentation.
 * STRICT ISOLATION: Never pulls prospect/contact profile summaries, ICP fit reasons, or candidate experience!
 */
export function extractSignalDetails(sig, contact = {}) {
  if (!sig) return null
  const meta = getSignalMeta(sig)
  const raw = sig.raw_data || {}
  const company = (contact?.company || raw.company || 'Target Account').trim()
  const sigType = (sig.signal_type || '').toLowerCase()

  // 1. Headline (actual source headline)
  let headline = raw.headline || raw.title || raw.job_title
  if (!headline && sig.summary) {
    headline = sig.summary
  }
  if (!headline) {
    headline = meta.displayType
  }
  if (typeof headline === 'string' && headline === headline.toLowerCase()) {
    headline = headline.replace(/\b[a-z]/g, c => c.toUpperCase())
  }

  // 2. Subtitle Activity Label
  let activityLabel = 'Market activity'
  if (sigType === 'job_posting' || (sigType.includes('job') && !sigType.includes('hire'))) {
    activityLabel = 'Hiring vacancy'
  } else if (sigType === 'new_hire' || sigType.includes('hire')) {
    activityLabel = 'Leadership appointment'
  } else if (sigType === 'funding_round' || sigType.includes('funding')) {
    activityLabel = 'Financing event'
  } else if (sigType === 'news_expansion' || sigType.includes('expansion') || sigType.includes('news')) {
    activityLabel = raw.subtype ? raw.subtype.toLowerCase() : 'Market expansion'
  } else if (sigType === 'earnings_call' || sigType.includes('earnings')) {
    activityLabel = 'Financial results'
  } else if (sigType === 'social_engagement' || sigType.includes('social') || sigType.includes('reddit')) {
    activityLabel = 'Community discussions'
  } else if (sigType === 'tech_stack_observed' || sigType === 'tech_stack_change' || sigType.includes('tech') || sig.signal_source === 'website_fingerprint') {
    activityLabel = 'Technology observation'
  }

  // 3. What happened narrative (Grounded exclusively in signal event text)
  let whatHappened = ''
  if (raw.description && raw.description.length > 20) {
    whatHappened = raw.description
  } else if (sig.summary && !sig.summary.toLowerCase().startsWith('detected')) {
    whatHappened = sig.summary
  } else if (sigType === 'job_posting') {
    whatHappened = `The company published an active job opening for ${headline}.`
  } else if (sigType === 'new_hire') {
    whatHappened = `${company} announced an executive appointment: ${headline}.`
  } else if (sigType === 'funding_round') {
    whatHappened = `${company} secured a financing round to support operations and commercial expansion.`
  } else if (sigType === 'news_expansion') {
    whatHappened = `${company} announced commercial development: ${headline}.`
  } else if (sigType === 'earnings_call') {
    whatHappened = `${company} reported financial and operational results: ${headline}.`
  } else if (sigType === 'social_engagement') {
    whatHappened = `Community discussions concerning ${company} were published on public discussion platforms.`
  } else if (sigType === 'tech_stack_observed' || sigType === 'tech_stack_change' || sigType.includes('tech') || sig.signal_source === 'website_fingerprint') {
    whatHappened = `Direct website inspection observed active enterprise sales/CRM technology usage on the company website.`
  } else {
    whatHappened = `Verified ${meta.displayType.toLowerCase()} event recorded for ${company}.`
  }

  // 4. Dynamic Source Details grid (Type-Specific!)
  const sourceDetails = []

  if (sigType === 'job_posting' || (sigType.includes('job') && !sigType.includes('hire'))) {
    // Job Posting fields
    const dept = raw.department || inferDepartment(`${headline} ${whatHappened} ${(raw.roles || []).join(' ')}`)
    if (dept) sourceDetails.push({ label: 'Department', value: dept })
    const empType = raw.employment_type || (raw.contract_type ? raw.contract_type.replace(/_/g, ' ') : 'Full-time')
    sourceDetails.push({ label: 'Employment type', value: empType.charAt(0).toUpperCase() + empType.slice(1) })
    const loc = raw.location || (Array.isArray(raw.locations) && raw.locations[0]) || null
    if (loc) sourceDetails.push({ label: 'Location', value: loc })
    const postDate = raw.published_at || sig.occurred_at
    if (postDate) {
      const formatted = formatDisplayDate(postDate)
      if (formatted) sourceDetails.push({ label: 'Posted date', value: formatted })
    }
  } else if (sigType === 'new_hire' || sigType.includes('hire')) {
    // New Hire fields
    const person = raw.appointed_person || 'Executive Leadership'
    sourceDetails.push({ label: 'Appointed person', value: person })
    const desig = raw.new_designation || raw.role || 'Executive Appointment'
    sourceDetails.push({ label: 'New designation', value: desig })
    const dept = raw.department || inferDepartment(`${headline} ${desig}`)
    if (dept) sourceDetails.push({ label: 'Department / Function', value: dept })
    const appDate = raw.published_at || sig.occurred_at
    if (appDate) {
      const formatted = formatDisplayDate(appDate)
      if (formatted) sourceDetails.push({ label: 'Appointment date', value: formatted })
    }
  } else if (sigType === 'funding_round' || sigType.includes('funding')) {
    // Funding Round fields
    const stage = raw.funding_stage || raw.round_type || 'Growth Round'
    sourceDetails.push({ label: 'Funding stage', value: stage })
    if (raw.amount) {
      sourceDetails.push({ label: 'Amount raised', value: String(raw.amount) })
    }
    if (raw.lead_investor) {
      sourceDetails.push({ label: 'Lead investor', value: raw.lead_investor })
    }
    const fundDate = raw.published_at || sig.occurred_at
    if (fundDate) {
      const formatted = formatDisplayDate(fundDate)
      if (formatted) sourceDetails.push({ label: 'Funding date', value: formatted })
    }
  } else if (sigType === 'news_expansion' || sigType.includes('expansion') || sigType.includes('news')) {
    // News Expansion fields
    const subtype = raw.subtype || (raw.trigger ? raw.trigger.replace(/_/g, ' ') : 'Business Expansion')
    sourceDetails.push({ label: 'Event type', value: subtype })
    if (raw.location || (Array.isArray(raw.locations) && raw.locations[0])) {
      sourceDetails.push({ label: 'Location / Region', value: raw.location || raw.locations[0] })
    }
    if (raw.partner_company) {
      sourceDetails.push({ label: 'Partner entity', value: raw.partner_company })
    }
    const evtDate = raw.published_at || sig.occurred_at
    if (evtDate) {
      const formatted = formatDisplayDate(evtDate)
      if (formatted) sourceDetails.push({ label: 'Event date', value: formatted })
    }
  } else if (sigType === 'earnings_call' || sigType.includes('earnings')) {
    // Earnings fields
    const period = raw.reporting_period || 'Quarterly'
    sourceDetails.push({ label: 'Reporting period', value: period })
    if (raw.revenue) sourceDetails.push({ label: 'Revenue', value: String(raw.revenue) })
    if (raw.net_income) sourceDetails.push({ label: 'Net income', value: String(raw.net_income) })
    const callDate = raw.published_at || sig.occurred_at
    if (callDate) {
      const formatted = formatDisplayDate(callDate)
      if (formatted) sourceDetails.push({ label: 'Announcement date', value: formatted })
    }
  } else if (sigType === 'social_engagement' || sigType.includes('social') || sigType.includes('reddit')) {
    // Social Engagement fields
    sourceDetails.push({ label: 'Platform', value: raw.platform || 'Reddit' })
    if (raw.subreddit) sourceDetails.push({ label: 'Community', value: raw.subreddit })
    if (raw.mention_count != null) sourceDetails.push({ label: 'Mentions recorded', value: String(raw.mention_count) })
    const pubDate = raw.published_at || sig.occurred_at
    if (pubDate) {
      const formatted = formatDisplayDate(pubDate)
      if (formatted) sourceDetails.push({ label: 'Post date', value: formatted })
    }
  } else if (sigType === 'tech_stack_observed' || sigType === 'tech_stack_change' || sigType.includes('tech') || sigType.includes('stack')) {
    // Tech Stack fields
    const techStr = (raw.technologies || []).join(', ') || 'Enterprise Stack'
    sourceDetails.push({ label: 'Technologies detected', value: techStr })
    const method = raw.detection_method || (raw.is_html_inspection ? 'HTML Inspection' : 'Resource Detection')
    sourceDetails.push({ label: 'Detection method', value: method })
    if (raw.page_url) {
      sourceDetails.push({ label: 'Inspected page', value: raw.page_url.replace(/^https?:\/\//, '').split('/')[0] })
    }
    const obsDate = raw.published_at || sig.occurred_at
    if (obsDate) {
      const formatted = formatDisplayDate(obsDate)
      if (formatted) sourceDetails.push({ label: 'Observed date', value: formatted })
    }
  }

  // 5. Company context (STRICTLY signal-grounded, NEVER prospect summary or ICP explanation!)
  let companyContext = ''
  if (raw.company_context && raw.company_context.length > 20) {
    companyContext = raw.company_context
  } else {
    // Deterministic factual fallback grounded ONLY in signal facts
    if (sigType === 'job_posting') {
      const roleName = headline.replace(/^Leadership (?:Hiring )?Requisition:\s*/i, '')
      companyContext = `${company} published an active job requisition for ${roleName}. The opening indicates active hiring demand and team expansion.`
    } else if (sigType === 'new_hire') {
      companyContext = `${company} announced an executive appointment: ${headline}. This leadership movement strengthens strategic operations.`
    } else if (sigType === 'funding_round') {
      const stage = raw.funding_stage || raw.round_type || 'growth'
      companyContext = `${company} completed a ${stage} financing round to accelerate business operations and commercial expansion.`
    } else if (sigType === 'news_expansion') {
      companyContext = `${company} announced commercial development: ${headline}. This event represents active market expansion and growth.`
    } else if (sigType === 'earnings_call') {
      companyContext = `${company} reported financial updates and operational performance for the reporting period.`
    } else if (sigType === 'social_engagement') {
      companyContext = `Public community discussions concerning ${company} were identified on online forums regarding product usage and workflows.`
    } else if (sigType === 'tech_stack_observed' || sigType === 'tech_stack_change' || sigType.includes('tech') || sig.signal_source === 'website_fingerprint') {
      const techStr = (raw.technologies || []).join(', ') || 'sales/CRM tools'
      companyContext = `Direct website inspection observed active usage of ${techStr} on ${company}'s domain. This reflects verified active usage, not a newly confirmed adoption event.`
    } else {
      companyContext = `Verified market event recorded for ${company}: ${headline}.`
    }
  }

  // 6. Pills (Roles / Locations / Technologies) - Shown ONLY when genuinely relevant!
  let pillsTitle = null
  let pills = []
  let totalCount = 0

  if (sigType === 'job_posting' && Array.isArray(raw.roles) && raw.roles.length > 0) {
    pillsTitle = 'Roles mentioned'
    const cleaned = raw.roles
      .map(r => (typeof r === 'string' ? r.trim() : (r?.title || r?.name || String(r)).trim()))
      .filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned))
      .slice(0, 8)
      .map(r => r.replace(/\b[a-z]/g, c => c.toUpperCase()))
  } else if ((sigType === 'news_expansion' || sigType === 'job_posting') && Array.isArray(raw.locations) && raw.locations.length > 0) {
    pillsTitle = 'Locations detected'
    const cleaned = raw.locations.map(l => String(l).trim()).filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned)).slice(0, 8)
  } else if ((sigType === 'tech_stack_observed' || sigType === 'tech_stack_change') && Array.isArray(raw.technologies) && raw.technologies.length > 0) {
    pillsTitle = 'Technologies detected'
    const cleaned = raw.technologies.map(t => String(t).trim()).filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned)).slice(0, 8)
  }

  // 7. Score (0 - 100)
  let score = 50
  if (sig.confidence != null) {
    score = Math.round(sig.confidence > 1 ? sig.confidence : sig.confidence * 100)
  } else if (sig.conversion_weight != null) {
    score = Math.round(sig.conversion_weight > 1 ? sig.conversion_weight : sig.conversion_weight * 100)
  }
  score = Math.min(100, Math.max(0, score))

  // 8. Genuine Source URL (Must point to an external article, filing, or posting — never the company homepage!)
  let rawUrl = raw.url || raw.redirect_url
  let sourceUrl = null
  if (rawUrl && typeof rawUrl === 'string') {
    const cleanU = rawUrl.trim()
    if (cleanU.startsWith('http://') || cleanU.startsWith('https://')) {
      const isCompanyWebsite = Boolean(raw.is_company_website) || sig.signal_source === 'website_fingerprint'
      let isBaseDomain = false
      try {
        const parsed = new URL(cleanU)
        if (parsed.pathname === '/' || parsed.pathname === '') {
          isBaseDomain = true
        }
      } catch {}

      if (!isCompanyWebsite && !isBaseDomain) {
        sourceUrl = cleanU
      }
    }
  }

  return {
    meta,
    company,
    activityLabel,
    headline,
    whatHappened,
    sourceDetails,
    companyContext,
    pillsTitle,
    pills,
    totalCount,
    score,
    sourceUrl,
    sourceName: humanizeSource(sig.signal_source),
  }
}

/**
 * Department inference helper based on text keywords.
 */
function inferDepartment(text) {
  if (!text) return 'General Management'
  const t = text.toLowerCase()
  if (t.match(/account|finance|payroll|audit|treasur|cfo|controller|billing|tax/)) {
    return 'Finance & Accounting'
  }
  if (t.match(/sales|bdr|sdr|account exec|revenue|cro|business develop|commercial/)) {
    return 'Sales & Revenue'
  }
  if (t.match(/engineer|software|developer|devops|data|qa|architect|tech|frontend|backend|fullstack|it /)) {
    return 'Engineering & IT'
  }
  if (t.match(/market|growth|content|seo|campaign|brand|demand gen|pr/)) {
    return 'Marketing & Growth'
  }
  if (t.match(/hr|people|talent|recruit|human resource/)) {
    return 'People & HR'
  }
  if (t.match(/product|ux|ui|design/)) {
    return 'Product & Design'
  }
  if (t.match(/legal|compliance|counsel/)) {
    return 'Legal & Compliance'
  }
  return 'Executive Leadership'
}

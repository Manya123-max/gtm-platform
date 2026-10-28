import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import {
  fetchContact,
  fetchThread,
  fetchSignals,
  summarizeSignals
} from '../api'
import {
  Mail,
  ExternalLink,
  Sparkles,
  RefreshCw,
  MessageSquare,
  FileText,
  CreditCard,
  Briefcase,
  Zap,
  Radio,
  X,
  ChevronRight
} from 'lucide-react'

function formatDisplayDate(dateStr) {
  if (!dateStr) return ''
  try {
    const s = String(dateStr).trim()
    const isIsoNaive = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)
    const normalizedStr = isIsoNaive ? `${s}Z` : s
    const d = new Date(normalizedStr)
    if (isNaN(d.getTime())) return String(dateStr)
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return String(dateStr)
  }
}

function formatSignalRecency(dateStr) {
  if (!dateStr) return 'recently'
  try {
    const s = String(dateStr).trim()
    const isIsoNaive = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)
    const normalizedStr = isIsoNaive ? `${s}Z` : s
    const d = new Date(normalizedStr)
    if (isNaN(d.getTime())) return 'recently'
    const now = new Date()
    const diffMs = now - d
    if (diffMs < 0) return 'today'
    const diffHours = diffMs / (1000 * 60 * 60)
    if (diffHours < 24) return 'today'
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays === 1) return '1d ago'
    if (diffDays < 30) return `${diffDays}d ago`
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  } catch {
    return 'recently'
  }
}

function getSignalMeta(sig) {
  const t = (sig.signal_type || '').toLowerCase()
  const raw = sig.raw_data || {}
  const headline = raw.headline || raw.title || sig.summary || ''

  if (t.includes('expansion') || t.includes('news')) {
    return {
      title: headline && !headline.toLowerCase().startsWith('news') ? headline : 'News Expansion',
      displayType: 'News Expansion',
      icon: FileText,
    }
  }
  if (t.includes('funding')) {
    return {
      title: headline && !headline.toLowerCase().startsWith('funding') ? headline : 'Funding Round',
      displayType: 'Funding Round',
      icon: CreditCard,
    }
  }
  if (t.includes('job') || t.includes('hire') || t.includes('posting')) {
    return {
      title: headline && !headline.toLowerCase().startsWith('job') ? headline : 'Job Posting',
      displayType: 'Job Posting',
      icon: Briefcase,
    }
  }
  if (t.includes('tech') || t.includes('stack')) {
    return {
      title: headline && !headline.toLowerCase().startsWith('tech') ? headline : 'Tech Change',
      displayType: 'Tech Change',
      icon: Zap,
    }
  }
  if (t.includes('earnings')) {
    return {
      title: headline && !headline.toLowerCase().startsWith('earnings') ? headline : 'Earnings Call',
      displayType: 'Earnings Call',
      icon: Radio,
    }
  }

  return {
    title: headline || 'Business Activity',
    displayType: sig.signal_type ? sig.signal_type.replace(/_/g, ' ') : 'Market Signal',
    icon: FileText,
  }
}

function humanizeSource(source) {
  if (!source) return 'Verified Signal'
  const s = String(source).toLowerCase()
  if (s.includes('adzuna')) return 'Adzuna'
  if (s.includes('currents')) return 'Currents'
  if (s.includes('newsapi')) return 'NewsAPI'
  if (s.includes('predictleads')) return 'PredictLeads'
  if (s.includes('google')) return 'Google News'
  if (s.includes('linkedin')) return 'LinkedIn'
  if (s.includes('sec')) return 'SEC Edgar'
  return source.charAt(0).toUpperCase() + source.slice(1)
}

function inferDepartment(text) {
  if (!text) return 'Go-To-Market Operations'
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
  if (t.match(/product|ux|ui|designer/)) {
    return 'Product Management'
  }
  if (t.match(/people|hr|talent|recruit|staffing/)) {
    return 'People & Talent'
  }
  if (t.match(/operat|logistics|supply|procure|facility|admin/)) {
    return 'Operations'
  }
  if (t.match(/legal|counsel|compliance|regulatory/)) {
    return 'Legal & Compliance'
  }
  if (t.match(/medical|clinical|healthcare|physician|nurse/)) {
    return 'Clinical & Healthcare'
  }
  return 'Corporate Operations'
}

function inferEmploymentType(raw, sigType) {
  if (raw.employment_type) return String(raw.employment_type)
  if (raw.contract_type) {
    const ct = String(raw.contract_type).toLowerCase()
    if (ct.includes('perm') || ct.includes('full')) return 'Full Time, Permanent'
    if (ct.includes('contract')) return 'Contract'
    return raw.contract_type
  }
  if (raw.contract_time) {
    const ct = String(raw.contract_time).toLowerCase()
    if (ct.includes('full')) return 'Full Time, Exempt'
    if (ct.includes('part')) return 'Part Time'
    return raw.contract_time
  }
  if (raw.trigger) {
    return raw.trigger.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }
  if (sigType.includes('job') || sigType.includes('hire')) {
    return 'Full Time, Exempt'
  }
  if (Array.isArray(raw.locations) && raw.locations.length > 0) {
    return `${raw.locations.length} Locations`
  }
  return 'Verified Active'
}

function extractSignalDetails(sig, contact) {
  if (!sig) return null
  const meta = getSignalMeta(sig)
  const raw = sig.raw_data || {}
  const company = contact?.company || 'Account'
  const sigType = (sig.signal_type || '').toLowerCase()

  // Real headline extraction
  let headline = raw.headline || raw.title
  if (!headline && Array.isArray(raw.roles) && raw.roles.length > 0) {
    headline = typeof raw.roles[0] === 'string' ? raw.roles[0] : (raw.roles[0]?.title || '')
  }
  if (!headline && sig.summary) {
    headline = sig.summary
  }
  if (!headline) {
    headline = meta.displayType
  }
  if (headline && typeof headline === 'string' && headline === headline.toLowerCase()) {
    headline = headline.replace(/\b[a-z]/g, c => c.toUpperCase())
  }

  // Activity label for subtitle: e.g. "Impiricus • Hiring activity"
  let activityLabel = 'Market activity'
  if (sigType.includes('job') || sigType.includes('hire')) {
    activityLabel = 'Hiring activity'
  } else if (sigType.includes('expansion') || sigType.includes('news')) {
    activityLabel = raw.trigger ? raw.trigger.replace(/_/g, ' ') : 'Geographic expansion'
  } else if (sigType.includes('funding')) {
    activityLabel = 'Funding round'
  } else if (sigType.includes('tech')) {
    activityLabel = 'Tech stack update'
  } else if (sigType.includes('earnings')) {
    activityLabel = 'Earnings & Financials'
  }

  // What happened narrative
  let whatHappened = ''
  if (sig.summary && !sig.summary.toLowerCase().startsWith('detected')) {
    whatHappened = sig.summary
  } else if (raw.description && raw.description.length > 15) {
    whatHappened = raw.description
  } else if (sigType.includes('job') || sigType.includes('hire')) {
    whatHappened = `${company} reported hiring activity for this role.`
  } else if (sigType.includes('expansion')) {
    whatHappened = `${company} reported expansion activity into new regional markets.`
  } else if (sigType.includes('funding')) {
    whatHappened = `${company} secured new financing round to accelerate growth.`
  } else {
    whatHappened = `Verified ${meta.displayType.toLowerCase()} signal detected for ${company}.`
  }

  // Department
  let department = raw.department || raw.category
  if (!department) {
    department = inferDepartment(`${headline} ${whatHappened} ${(raw.roles || []).join(' ')}`)
  }

  // Employment Type
  const employmentType = inferEmploymentType(raw, sigType)

  // Company context
  let companyContext = contact?.selection_summary
  if (!companyContext || companyContext.length < 30) {
    const ind = contact?.industry ? ` in the ${contact.industry} industry` : ''
    const geo = contact?.geography ? ` based in ${contact.geography}` : ''
    const icp = contact?.icp_score != null ? ` with an ICP fit score of ${Math.round(contact.icp_score)}/100` : ''
    companyContext = `${company} is an active enterprise account${ind}${geo}${icp}. Recent market and hiring activity indicate high go-to-market relevance.`
  }

  // Roles or Locations Mentioned
  let pillsTitle = 'Roles mentioned'
  let pills = []
  let totalCount = 0

  if (Array.isArray(raw.roles) && raw.roles.length > 0) {
    pillsTitle = 'Roles mentioned'
    const cleaned = raw.roles
      .map(r => typeof r === 'string' ? r.trim() : (r?.title || r?.name || String(r)).trim())
      .filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned))
      .slice(0, 8)
      .map(r => r.replace(/\b[a-z]/g, c => c.toUpperCase()))
  } else if (Array.isArray(raw.locations) && raw.locations.length > 0) {
    pillsTitle = 'Locations detected'
    const cleaned = raw.locations.map(l => String(l).trim()).filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned)).slice(0, 8)
  } else if (Array.isArray(raw.keywords) && raw.keywords.length > 0) {
    pillsTitle = 'Topics mentioned'
    const cleaned = raw.keywords.map(k => String(k).trim()).filter(Boolean)
    totalCount = cleaned.length
    pills = Array.from(new Set(cleaned)).slice(0, 8)
  }

  // Signal Score (0 - 100)
  let score = 50
  if (sig.confidence != null) {
    score = Math.round(sig.confidence > 1 ? sig.confidence : sig.confidence * 100)
  } else if (sig.conversion_weight != null) {
    score = Math.round(sig.conversion_weight > 1 ? sig.conversion_weight : sig.conversion_weight * 100)
  } else if (contact?.signal_score != null) {
    score = Math.round(contact.signal_score)
  }
  score = Math.min(100, Math.max(0, score))

  // Source URL
  let sourceUrl = raw.url || raw.redirect_url
  if (!sourceUrl && contact?.website) {
    sourceUrl = contact.website.startsWith('http') ? contact.website : `https://${contact.website}`
  }
  if (!sourceUrl) {
    sourceUrl = `https://www.google.com/search?q=${encodeURIComponent(`${company} ${headline}`)}`
  }

  return {
    meta,
    company,
    activityLabel,
    headline,
    whatHappened,
    department,
    employmentType,
    companyContext,
    pillsTitle,
    pills,
    totalCount,
    score,
    sourceUrl,
    sourceName: humanizeSource(sig.signal_source),
  }
}

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(false)
  const [selectedSignal, setSelectedSignal] = useState(null)

  // Live queries
  const { data: contact, isLoading, refetch: refetchContact } = useQuery({
    queryKey: ['contact', id],
    queryFn: () => fetchContact(id),
    refetchInterval: 15_000,
  })

  const { data: signals = [], refetch: refetchSignals } = useQuery({
    queryKey: ['signals', id],
    queryFn: () => fetchSignals(id),
    refetchInterval: 15_000,
  })

  const { data: thread = [] } = useQuery({
    queryKey: ['thread', id],
    queryFn: () => fetchThread(id),
    refetchInterval: 10_000,
  })

  // Handle Signal Summarization / Refresh
  const handleRefreshSignals = async () => {
    setIsRefreshing(true)
    try {
      await summarizeSignals(id)
      await Promise.all([refetchContact(), refetchSignals()])
    } catch (err) {
      console.error('Refresh signals failed:', err)
    } finally {
      setIsRefreshing(false)
    }
  }

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto py-20 text-center text-xs text-gray-400">
        Loading account details…
      </div>
    )
  }

  if (!contact) {
    return (
      <div className="max-w-6xl mx-auto py-20 text-center text-xs text-gray-500">
        Contact not found.
      </div>
    )
  }

  // Formatting variables
  const initials = `${contact.first_name?.[0] || ''}${contact.last_name?.[0] || ''}`.toUpperCase() || 'P'
  const icpScore = contact.icp_score != null ? Math.round(contact.icp_score) : 0
  const sigScore = (contact.primary_signal_score ?? contact.signal_score) != null ? Math.round(contact.primary_signal_score ?? contact.signal_score) : 0
  const fitText = icpScore >= 75 ? 'Strong ICP fit' : icpScore >= 60 ? 'Promising ICP fit' : 'Moderate ICP fit'
  const sigType = contact.primary_signal_type || contact.signal_type || 'buying signals'
  const sigTypeLabel = sigType.replace(/_/g, ' ')
  const recencyText = formatSignalRecency(contact.primary_signal_at || contact.latest_signal_at)

  // Construct dynamic fallback signal summary if not already present
  const defaultSummary = contact.signal_summary || (
    `${contact.company || 'The account'} has recent activity associated with ${sigTypeLabel}. These events indicate business activity relevant to go-to-market operations.`
  )

  return (
    <div className="w-full space-y-6 pb-16 selection:bg-[#5B4EFF]/15">
      
      {/* ── Breadcrumb & Page Header matching Figma ── */}
      <div>
        <div className="flex items-center gap-1.5 text-xs text-gray-400 font-medium mb-1">
          <button
            type="button"
            onClick={() => navigate('/contacts')}
            className="hover:text-[#5B4EFF] transition-colors cursor-pointer"
          >
            Prospect
          </button>
          <span>›</span>
          <span className="font-bold text-gray-900">Account</span>
        </div>

        <h1 className="text-2xl sm:text-[26px] font-bold text-[#111827] tracking-tight">
          Account
        </h1>
        <p className="text-xs text-gray-400 font-medium mt-0.5">
          Prospect Intelligence Graph
        </p>
      </div>

      {/* ── Main Two-Column Layout ── */}
      <div className="flex flex-col lg:flex-row gap-6 items-start">
        
        {/* ── Left Column: Profile & Account Details ── */}
        <div className="w-full lg:w-[410px] shrink-0 bg-white rounded-3xl border border-gray-100 shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 space-y-5">
          
          {/* Profile Header */}
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-13 h-13 rounded-full bg-[#ECE8FE] text-[#5B4EFF] font-bold text-base flex items-center justify-center shrink-0">
                {initials}
              </div>
              <div className="min-w-0">
                <h2 className="text-base sm:text-lg font-bold text-gray-900 leading-snug truncate">
                  {contact.first_name} {contact.last_name}
                </h2>
                <p className="text-xs text-gray-400 font-medium mt-0.5 truncate">
                  {contact.title || 'Executive'}
                </p>
              </div>
            </div>

            {/* Tier Badge */}
            <span className="bg-[#DCFCE7] text-[#16A34A] border border-[#BBF7D0] rounded-lg px-2.5 py-0.5 text-xs font-semibold shrink-0">
              {contact.tier_label || `Tier ${contact.tier || 1}`}
            </span>
          </div>

          {/* Descriptive fit summary sentence */}
          <p className="text-xs text-gray-500 leading-relaxed font-normal">
            {fitText} ({icpScore}) with recent verified buying intent: {sigTypeLabel} (score {sigScore}, detected {recencyText}).
          </p>

          {/* Email & LinkedIn */}
          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-2 text-gray-500">
              <Mail size={13} className="text-gray-400 shrink-0" />
              <a
                href={`mailto:${contact.email}`}
                className="hover:text-[#5B4EFF] transition-colors truncate"
              >
                {contact.email}
              </a>
            </div>

            {contact.linkedin_url && (
              <div className="flex items-center gap-2">
                <ExternalLink size={13} className="text-[#5B4EFF] shrink-0" />
                <a
                  href={contact.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs font-semibold text-[#5B4EFF] hover:underline truncate"
                >
                  View LinkedIn Profile
                </a>
              </div>
            )}
          </div>

          <div className="border-t border-gray-100" />

          {/* Company & Location Attributes */}
          <div className="space-y-3 text-xs">
            <div className="flex items-start justify-between gap-4">
              <span className="text-gray-400 font-medium shrink-0">Company</span>
              <span className="font-bold text-gray-900 text-right">{contact.company || 'Not specified'}</span>
            </div>
            <div className="flex items-start justify-between gap-4">
              <span className="text-gray-400 font-medium shrink-0">Industry</span>
              <span className="font-bold text-gray-900 text-right">{contact.industry || 'Not specified'}</span>
            </div>
            <div className="flex items-start justify-between gap-4">
              <span className="text-gray-400 font-medium shrink-0">Company location</span>
              <span className="font-bold text-gray-900 text-right">{contact.geography || 'Not specified'}</span>
            </div>
            <div className="flex items-start justify-between gap-4">
              <span className="text-gray-400 font-medium shrink-0">Prospect location</span>
              <span className="font-bold text-gray-900 text-right">
                {contact.prospect_location || contact.geography || 'Not specified'}
              </span>
            </div>
            <div className="flex items-start justify-between gap-4">
              <span className="text-gray-400 font-medium shrink-0">Work mode</span>
              <span className="font-bold text-gray-900 text-right">{contact.work_mode || 'Not specified'}</span>
            </div>
          </div>

          <div className="border-t border-gray-100" />

          {/* Why this prospect */}
          <div>
            <h3 className="text-xs font-bold text-[#5B4EFF] mb-1.5">
              Why this prospect
            </h3>
            <p className={`text-xs text-gray-500 leading-relaxed font-normal ${!isSummaryExpanded ? 'line-clamp-4' : ''}`}>
              {contact.selection_summary || (
                `${contact.first_name} is the ${contact.title || 'leader'} at ${contact.company}. The account profile and technical requirements match the targeting criteria for this search.`
              )}
            </p>
            {contact.selection_summary && contact.selection_summary.length > 180 && (
              <button
                type="button"
                onClick={() => setIsSummaryExpanded(prev => !prev)}
                className="text-xs font-semibold text-[#5B4EFF] hover:underline mt-1 cursor-pointer block"
              >
                {isSummaryExpanded ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>

          <div className="border-t border-gray-100" />

          {/* Scores & Readiness Grid */}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-0.5">ICP score</div>
                <div className="text-2xl font-bold text-gray-900">
                  {contact.icp_score != null ? Math.round(contact.icp_score) : '—'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-0.5">Signal score</div>
                <div className="text-2xl font-bold text-gray-900">
                  {(contact.primary_signal_score ?? contact.signal_score) != null
                    ? Math.round(contact.primary_signal_score ?? contact.signal_score)
                    : '—'}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 items-center">
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-0.5">Readiness</div>
                <div className="text-lg font-bold text-gray-900">
                  {Math.round(contact.readiness_score || 0)}%
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 font-medium mb-1">Status</div>
                <span className="inline-block bg-[#DCFCE7] text-[#16A34A] border border-[#BBF7D0] rounded-full px-3 py-0.5 text-xs font-medium">
                  Active
                </span>
              </div>
            </div>
          </div>

        </div>

        {/* ── Right Column: Signal Intelligence & Conversation Thread ── */}
        <div className="flex-1 space-y-6 min-w-0 w-full">
          
          {/* Card 1: Signal Intelligence */}
          <div className="bg-white rounded-3xl border border-[#ECE8FE] shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 space-y-4">
            
            {/* Header */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-bold text-[#5B4EFF]">
                <Sparkles size={14} className="text-[#5B4EFF]" />
                <span>Signal Intelligence · {signals.length} {signals.length === 1 ? 'signal' : 'signals'} detected</span>
              </div>

              {/* Refresh button */}
              <button
                type="button"
                onClick={handleRefreshSignals}
                disabled={isRefreshing}
                className="bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.98] text-white rounded-xl px-3.5 py-1.5 text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all cursor-pointer disabled:opacity-60"
              >
                <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>

            {/* Summary Callout Box */}
            <div className="bg-[#F9F8FE] border border-[#ECE8FE] rounded-2xl p-4 text-xs text-gray-600 leading-relaxed font-normal">
              {defaultSummary}
            </div>

            {/* Signals List / Grid matching Figma */}
            <div className="space-y-3">
              {signals.length === 0 ? (
                <div className="py-8 text-center text-xs text-gray-400">
                  No signals detected for this account yet.
                </div>
              ) : (
                signals.map((sig) => {
                  const details = extractSignalDetails(sig, contact)
                  const meta = details.meta
                  const Icon = meta.icon

                  return (
                    <div
                      key={sig.id}
                      onClick={() => setSelectedSignal(sig)}
                      className="rounded-2xl border border-gray-100/90 bg-white p-4 flex items-center justify-between gap-4 hover:border-[#5B4EFF]/40 hover:shadow-xs transition-all cursor-pointer group"
                    >
                      <div className="flex items-center gap-3.5 min-w-0">
                        <div className="w-11 h-11 rounded-2xl bg-[#F7F5FF] border border-[#ECE8FE] text-[#5B4EFF] flex items-center justify-center shrink-0 group-hover:bg-[#ECE8FE] transition-colors">
                          <Icon size={18} />
                        </div>
                        <div className="min-w-0 space-y-0.5">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold text-gray-900 group-hover:text-[#5B4EFF] transition-colors truncate">
                              {meta.displayType}
                            </span>
                            <span className="bg-gray-100 text-gray-500 rounded-md px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                              {details.sourceName}
                            </span>
                          </div>
                          <div className="text-xs text-gray-600 font-medium truncate">
                            {details.headline}
                          </div>
                          <div className="text-[11px] text-gray-400 font-normal flex items-center gap-2">
                            <span>Detected on {formatDisplayDate(sig.detected_at)}</span>
                            {details.pills.length > 0 && (
                              <>
                                <span>•</span>
                                <span className="text-[#5B4EFF] font-medium">
                                  {details.totalCount || details.pills.length} {details.pillsTitle.toLowerCase()}
                                </span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 shrink-0">
                        <div className="text-right">
                          <div className="text-[10px] text-gray-400 font-medium">Score</div>
                          <div className="text-xs font-bold text-gray-900">{details.score}/100</div>
                        </div>
                        <div className="w-7 h-7 rounded-lg bg-gray-50 group-hover:bg-[#F3F0FF] text-gray-400 group-hover:text-[#5B4EFF] flex items-center justify-center transition-colors">
                          <ChevronRight size={14} />
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

          </div>

          {/* Card 2: Conversation Thread */}
          <div className="bg-white rounded-3xl border border-gray-100 shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 space-y-4">
            
            {/* Header */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <MessageSquare size={14} className="text-[#5B4EFF]" />
                <span className="text-xs font-bold text-gray-900">Conversation Thread</span>
                <span className="bg-gray-100 text-gray-500 rounded-full px-2 py-0.5 text-[10px] font-medium">
                  {thread.length} messages
                </span>
              </div>

              <div className="flex items-center gap-1.5 text-xs text-gray-500 font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                <span>Live Sync Active</span>
              </div>
            </div>

            {/* Conversation content */}
            {thread.length === 0 ? (
              <div className="text-xs text-gray-400 py-16 text-center font-normal">
                No email interactions recorded yet
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                {thread.map((msg, idx) => (
                  <div key={idx} className="p-3.5 rounded-xl border border-gray-100 bg-[#FBFBFE] space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-bold text-gray-900">{msg.sender || contact.email}</span>
                      <span className="text-[10px] text-gray-400">{formatDisplayDate(msg.sent_at || msg.created_at)}</span>
                    </div>
                    {msg.subject && (
                      <div className="text-xs font-semibold text-gray-700">{msg.subject}</div>
                    )}
                    <p className="text-xs text-gray-600 whitespace-pre-wrap leading-relaxed">{msg.body}</p>
                  </div>
                ))}
              </div>
            )}

          </div>

        </div>

      </div>

      {/* ── Signal Detail Modal matching Figma ── */}
      {selectedSignal && (() => {
        const details = extractSignalDetails(selectedSignal, contact)
        const meta = details.meta
        const Icon = meta.icon

        return (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150"
            onClick={() => setSelectedSignal(null)}
          >
            <div
              className="bg-white rounded-3xl max-w-2xl sm:max-w-3xl w-full p-6 sm:p-7 shadow-2xl border border-gray-100 relative max-h-[92vh] overflow-y-auto space-y-6 animate-in zoom-in-95 duration-150"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3.5 min-w-0">
                  <div className="w-12 h-12 rounded-2xl bg-[#F7F5FF] border border-[#ECE8FE] text-[#5B4EFF] flex items-center justify-center shrink-0">
                    <Icon size={22} />
                  </div>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-gray-400">
                      Signal detail
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-gray-900 leading-tight truncate">
                      {meta.displayType}
                    </h2>
                    <p className="text-xs text-gray-500 font-medium mt-0.5 truncate">
                      {details.company} • {details.activityLabel}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setSelectedSignal(null)}
                  className="text-gray-400 hover:text-gray-600 p-1.5 rounded-full hover:bg-gray-100 transition-colors cursor-pointer shrink-0"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Two-Column Body */}
              <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
                
                {/* Left Column (What happened, Source details, Company context, Roles mentioned) */}
                <div className="md:col-span-7 space-y-5 min-w-0">
                  
                  {/* What happened */}
                  <div>
                    <div className="text-xs font-semibold text-gray-400">
                      What happened
                    </div>
                    <h3 className="text-base sm:text-lg font-bold text-gray-900 mt-1 leading-snug">
                      {details.headline}
                    </h3>
                    <p className="text-xs text-gray-500 leading-relaxed font-normal mt-1">
                      {details.whatHappened}
                    </p>
                  </div>

                  {/* Source details */}
                  <div>
                    <div className="text-xs font-semibold text-gray-400 mb-2">
                      Source details
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <div className="text-[11px] font-semibold text-gray-400">
                          Department
                        </div>
                        <div className="text-xs font-bold text-gray-900 mt-0.5 truncate">
                          {details.department}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] font-semibold text-gray-400">
                          Employment type
                        </div>
                        <div className="text-xs font-bold text-gray-900 mt-0.5 truncate">
                          {details.employmentType}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Company context */}
                  <div>
                    <div className="text-xs font-semibold text-gray-400 mb-1">
                      Company context
                    </div>
                    <p className="text-xs text-gray-600 leading-relaxed font-normal">
                      {details.companyContext}
                    </p>
                  </div>

                  {/* Roles mentioned (or Locations detected) */}
                  {details.pills.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-bold text-gray-900">{details.pillsTitle}</span>
                        <span className="bg-[#F3F0FF] text-[#5B4EFF] font-bold text-[10px] px-2 py-0.5 rounded-full border border-[#ECE8FE]">
                          {details.totalCount || details.pills.length}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {details.pills.map((item, idx) => (
                          <span
                            key={idx}
                            className="bg-[#F8F7FF] text-[#5B4EFF] border border-[#ECE8FE] rounded-full px-3 py-1 text-xs font-medium"
                          >
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                </div>

                {/* Right Column (Signal overview) */}
                <div className="md:col-span-5 min-w-0">
                  <div className="rounded-2xl border border-gray-100/90 bg-[#FBFBFE] p-5 space-y-4 shadow-xs">
                    <h4 className="text-xs font-bold text-gray-900">
                      Signal overview
                    </h4>

                    <div>
                      <div className="text-[11px] font-semibold text-gray-400">
                        Signal type
                      </div>
                      <div className="text-xs font-bold text-gray-900 mt-0.5">
                        {meta.displayType}
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] font-semibold text-gray-400">
                        Detected
                      </div>
                      <div className="text-xs font-bold text-gray-900 mt-0.5">
                        {formatDisplayDate(selectedSignal.detected_at)}
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] font-semibold text-gray-400">
                        Source
                      </div>
                      <div className="text-xs font-bold text-gray-900 mt-0.5">
                        {details.sourceName}
                      </div>
                    </div>

                    <div>
                      <div className="text-[11px] font-semibold text-gray-400">
                        Signal score
                      </div>
                      <div className="text-2xl font-bold text-gray-900 mt-0.5">
                        {details.score}{' '}
                        <span className="text-sm font-semibold text-gray-400">/ 100</span>
                      </div>
                      <div className="w-full bg-[#EAE8F8] h-2 rounded-full overflow-hidden mt-2">
                        <div
                          className="bg-[#5B4EFF] h-full rounded-full transition-all duration-300"
                          style={{ width: `${details.score}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

              </div>

              {/* Modal Footer */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setSelectedSignal(null)}
                  className="px-5 py-2 rounded-xl text-xs font-semibold text-gray-700 bg-white border border-gray-200 hover:bg-gray-50 active:scale-[0.98] transition-all cursor-pointer"
                >
                  Close
                </button>
                
                <a
                  href={details.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-5 py-2 rounded-xl text-xs font-semibold text-white bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.98] transition-all flex items-center gap-1.5 shadow-sm cursor-pointer"
                >
                  <span>View original source</span>
                  <ExternalLink size={12} />
                </a>
              </div>

            </div>
          </div>
        )
      })()}

    </div>
  )
}

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
  X
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
    <div className="max-w-7xl mx-auto space-y-6 pb-16 selection:bg-[#5B4EFF]/15">
      
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

            {/* Signals List */}
            <div className="space-y-3">
              {signals.length === 0 ? (
                <div className="py-8 text-center text-xs text-gray-400">
                  No signals detected for this account yet.
                </div>
              ) : (
                signals.map((sig) => {
                  const meta = getSignalMeta(sig)
                  const Icon = meta.icon
                  return (
                    <div
                      key={sig.id}
                      onClick={() => setSelectedSignal(sig)}
                      className="rounded-2xl border border-gray-100/90 bg-white p-3.5 flex items-center gap-3.5 hover:border-[#D6CEFC] hover:shadow-xs transition-all cursor-pointer group"
                    >
                      <div className="w-10 h-10 rounded-xl bg-[#F3F0FF] text-[#5B4EFF] flex items-center justify-center shrink-0 group-hover:bg-[#ECE8FE] transition-colors">
                        <Icon size={16} />
                      </div>
                      <div className="flex-1 min-w-0 pr-2">
                        <div className="text-xs font-bold text-gray-900 group-hover:text-[#5B4EFF] transition-colors truncate">
                          {meta.displayType}
                        </div>
                        <div className="text-[11px] text-gray-400 mt-0.5 font-normal truncate">
                          Detected on {formatDisplayDate(sig.detected_at)}
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

      {/* ── Optional Signal Detail Modal ── */}
      {selectedSignal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-gray-100 space-y-4 animate-in fade-in duration-150">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-sm font-bold text-gray-900">
                  {getSignalMeta(selectedSignal).displayType}
                </h3>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  Detected on {formatDisplayDate(selectedSignal.detected_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setSelectedSignal(null)}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-full cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-4 rounded-2xl bg-[#F9F8FE] border border-[#ECE8FE] text-xs text-gray-700 leading-relaxed">
              {selectedSignal.summary || selectedSignal.raw_data?.description || 'Event verified from external signal source.'}
            </div>

            {selectedSignal.raw_data?.url && (
              <a
                href={selectedSignal.raw_data.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#5B4EFF] hover:underline"
              >
                <span>View Original Source</span>
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        </div>
      )}

    </div>
  )
}

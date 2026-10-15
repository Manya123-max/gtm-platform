import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchContact, fetchThread, fetchSignals, fetchDeals, summarizeSignals } from '../api'
import { 
  ArrowLeft, Mail, Building2, MapPin, Zap, MessageSquare, X, Link, 
  Sparkles, ExternalLink, Briefcase, Layers 
} from 'lucide-react'
import DealDetailModal from '../components/DealDetailModal'

function formatDisplayDate(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return String(dateStr)
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return String(dateStr)
  }
}

function humanizeSource(src) {
  if (!src) return 'Verified Source'
  const s = String(src).toLowerCase().trim()
  if (s.includes('google_news') || s.includes('google news')) return 'Google News'
  if (s.includes('adzuna')) return 'Adzuna'
  if (s.includes('predictleads')) return 'PredictLeads'
  if (s.includes('website_fingerprint') || s.includes('company_website') || s.includes('website')) return 'Company Website'
  if (s.includes('newsapi')) return 'News API'
  if (s.includes('sec_edgar') || s.includes('sec')) return 'SEC EDGAR'
  if (s.includes('reddit')) return 'Reddit'
  if (s.includes('linkedin')) return 'LinkedIn'
  return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function stripHtml(input) {
  if (!input || typeof input !== 'string') return ''
  let text = input.replace(/<[^>]*>/g, ' ')
  // Strip unclosed tags like <a href="...
  text = text.replace(/<[a-zA-Z\/][^>]*$/g, '')
  // Replace common HTML entities
  text = text
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
  // Clean dangling href markup if any
  text = text.replace(/href\s*=\s*['"][^'"]*['"]?/gi, '')
  return text.replace(/\s+/g, ' ').trim()
}

function cleanFactualText(input) {
  if (!input || typeof input !== 'string') return ''
  let text = stripHtml(input)
  // Strip repeating 'Job Description Job Description...' boilerplate
  text = text.replace(/^(job description\s*)+/gi, '')
  text = text.replace(/\b(job description\s*){2,}/gi, 'Job Description: ')
  return text.trim()
}

function formatSignalSummary(raw) {
  if (!raw || typeof raw !== 'string') return ''
  const trimmed = raw.trim()
  if (!trimmed) return ''
  
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || trimmed.includes("'s1':") || trimmed.includes('"s1":')) {
    try {
      const parsed = JSON.parse(trimmed)
      if (typeof parsed === 'object' && parsed !== null) {
        const parts = Object.values(parsed).filter(v => typeof v === 'string' && v.trim())
        if (parts.length > 0) return parts.join(' ')
      }
    } catch {
      const matches = [...trimmed.matchAll(/['"][a-zA-Z0-9_-]+['"]\s*:\s*['"]([^'"]+)['"]/g)]
      if (matches.length > 0) {
        return matches.map(m => m[1].trim()).filter(Boolean).join(' ')
      }
    }
  }
  return cleanFactualText(trimmed)
}

function getSignalSourceInfo(signal) {
  if (!signal) return { url: null, isAvailable: false }
  const raw = signal.raw_data || {}
  const rawUrl = raw.url || raw.link || signal.source_url
  
  if (!rawUrl || typeof rawUrl !== 'string' || !rawUrl.startsWith('http')) {
    return { url: null, isAvailable: false }
  }
  
  // Never substitute company website for an article/job posting
  if (raw.is_company_website) {
    return { url: null, isAvailable: false }
  }

  // For external news/job signals, ensure we don't open the root company homepage as an "article"
  const isArticleOrJobSignal = ['news_expansion', 'job_posting', 'funding_round', 'new_hire', 'earnings_report'].includes(
    String(signal.signal_type || '').toLowerCase()
  )
  if (isArticleOrJobSignal && signal.signal_source !== 'website_fingerprint') {
    try {
      const parsedUrl = new URL(rawUrl)
      if ((parsedUrl.pathname === '/' || parsedUrl.pathname === '') && !parsedUrl.search && !parsedUrl.hash) {
        return { url: null, isAvailable: false }
      }
    } catch {
      return { url: null, isAvailable: false }
    }
  }

  return {
    url: rawUrl,
    isAvailable: true,
  }
}

function getWhatHappened(signal, contact) {
  if (!signal) return ''
  const company = contact?.company || 'The account'
  const raw = signal.raw_data || {}
  const headline = cleanFactualText(raw.headline || raw.title || raw.job_title || '')
  const sigType = (signal.signal_type || '').toLowerCase().replace(/_/g, ' ')

  if (headline) {
    if (sigType.includes('job') || sigType.includes('hire')) {
      if (headline.toLowerCase().includes('seeking') || headline.toLowerCase().includes('engineer') || headline.toLowerCase().includes('manager') || headline.toLowerCase().includes('tech')) {
        return `${company} posted an active job opening for ${headline}.`
      }
      return `${company} reported hiring activity: ${headline}.`
    }
    if (sigType.includes('expansion')) {
      if (headline.toLowerCase().startsWith('geographic expansion detected via hiring in:')) {
        const locs = headline.replace(/geographic expansion detected via hiring in:\s*/i, '').trim()
        return `${company} reported geographic hiring and commercial expansion in ${locs}.`
      }
      return `${company} reported commercial expansion activity: ${headline}.`
    }
    if (sigType.includes('funding')) {
      return `${company} announced investment and funding activity: ${headline}.`
    }
    if (sigType.includes('tech') || sigType.includes('stack')) {
      return `${company} updated technical infrastructure: ${headline}.`
    }
    return `${company} reported ${sigType} activity: ${headline}.`
  }

  const cleanSummary = cleanFactualText(signal.summary || '')
  if (cleanSummary && !cleanSummary.toLowerCase().startsWith('http') && cleanSummary.length > 20) {
    return cleanSummary
  }

  return `${company} demonstrated verified activity categorized under ${sigType}.`
}

function getSourceDetails(signal, contact) {
  if (!signal) return ''
  const raw = signal.raw_data || {}
  const desc = cleanFactualText(raw.description || '')
  const headline = cleanFactualText(raw.headline || raw.title || '')
  const sourceName = humanizeSource(signal.signal_source)
  const detectedDate = formatDisplayDate(signal.detected_at) || 'recent date'

  if (desc && desc.length > 25 && !desc.toLowerCase().startsWith('http') && desc.toLowerCase() !== headline.toLowerCase()) {
    if (desc.length > 300) {
      const match = desc.slice(0, 300).match(/^(.*[.!?])\s/s)
      if (match && match[1].length > 100) {
        return match[1]
      }
      return `${desc.slice(0, 280)}...`
    }
    return desc
  }

  const cleanSummary = cleanFactualText(signal.summary || '')
  if (cleanSummary && cleanSummary.length > 25 && !cleanSummary.toLowerCase().startsWith('http') && cleanSummary.toLowerCase() !== headline.toLowerCase()) {
    return cleanSummary
  }

  if (headline) {
    return `Verified via ${sourceName} on ${detectedDate}. Event record: "${headline}".`
  }

  return `Verified business event detected via ${sourceName} on ${detectedDate}.`
}

function splitIntoSentences(text) {
  if (!text || typeof text !== 'string') return []
  const matches = text.match(/[^.!?]+[.!?]+(\s|$)/g)
  if (!matches || matches.length === 0) return [text.trim()]
  return matches.map(s => s.trim()).filter(Boolean)
}

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [selectedSignal, setSelectedSignal] = useState(null)
  const [selectedDeal, setSelectedDeal] = useState(null)
  const [isSummarizing, setIsSummarizing] = useState(false)
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(false)
  const [isAllSignalsExpanded, setIsAllSignalsExpanded] = useState(false)

  const { data: contact, isLoading, refetch: refetchContact } = useQuery({
    queryKey: ['contact', id],
    queryFn: () => fetchContact(id),
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
  })
  const { data: thread = [] } = useQuery({
    queryKey: ['thread', id],
    queryFn: () => fetchThread(id),
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
  })
  const { data: signals = [] } = useQuery({ queryKey: ['signals', id], queryFn: () => fetchSignals(id) })
  const { data: deals = [] } = useQuery({ queryKey: ['deals', 'contact', id], queryFn: () => fetchDeals({ contact_id: id }) })

  const handleSummarize = async () => {
    setIsSummarizing(true)
    try {
      await summarizeSignals(id)
      await refetchContact()
    } catch (err) {
      console.error(err)
    } finally {
      setIsSummarizing(false)
    }
  }

  if (isLoading) return <div className="text-gray-600 text-sm p-8">Loading...</div>
  if (!contact) return <div className="text-gray-600 text-sm p-8">Contact not found</div>

  const scoreColor = (contact.icp_score || 0) >= 80 ? 'text-emerald-600'
    : (contact.icp_score || 0) >= 60 ? 'text-blue-600' : 'text-amber-600'

  return (
    <div className="w-full max-w-6xl mx-auto pb-10">
      {/* Back Button */}
      <button 
        onClick={() => navigate('/contacts')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 mb-5 transition-colors cursor-pointer"
      >
        <ArrowLeft size={14} /> Back to contacts
      </button>

      {/* Main 2-Column Responsive Layout: Left ~40%, Right ~60% */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">
        {/* Left Information Panel: 2 cols out of 5 = 40% */}
        <div className="lg:col-span-2 card">
          <div className="mb-4">
            <div className="w-10 h-10 rounded-full bg-blue-100 border border-blue-200/80 flex items-center justify-center text-blue-700 font-semibold text-sm mb-3">
              {contact.first_name?.[0]}{contact.last_name?.[0]}
            </div>
            <div className="text-base font-semibold text-slate-900">
              {contact.first_name} {contact.last_name}
            </div>
            {contact.title && <div className="text-xs text-slate-500 mt-0.5">{contact.title}</div>}
            {contact.tier && (
              <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                  contact.tier === 1 ? 'bg-emerald-50 border-emerald-300 text-emerald-800' :
                  contact.tier === 2 ? 'bg-blue-50 border-blue-300 text-blue-800' :
                  'bg-slate-100 border-slate-300 text-slate-700'
                }`}>
                  {contact.tier === 1 && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>}
                  <span>{contact.tier_label || `Tier ${contact.tier}`}</span>
                </span>
                {contact.tier_reason && (
                  <span className="text-[11px] text-slate-500" title={contact.tier_reason}>
                    {contact.tier_reason}
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="space-y-3 text-xs">
            <div className="flex items-start gap-2.5 text-slate-600">
              <Mail size={13} className="text-slate-400 shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-700 break-all">{contact.email || 'Email unavailable'}</span>
              </div>
            </div>

            {contact.linkedin_url && (
              <div className="flex items-start gap-2.5 text-slate-600">
                <Link size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <a 
                    href={contact.linkedin_url} 
                    target="_blank" 
                    rel="noopener noreferrer" 
                    className="text-blue-600 hover:text-blue-700 transition-colors font-medium break-all"
                  >
                    View LinkedIn Profile
                  </a>
                </div>
              </div>
            )}

            {/* Structured Company & Location Information */}
            <div className="pt-2.5 border-t border-slate-200/70 space-y-2.5">
              <div className="flex items-start gap-2.5">
                <Building2 size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Company</div>
                  <div className="text-slate-800 font-semibold mt-0.5 break-words">
                    {contact.company || 'Not specified'}
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-2.5">
                <Layers size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Industry</div>
                  <div className="text-slate-800 font-medium mt-0.5 capitalize break-words">
                    {contact.industry || 'Not specified'}
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-2.5">
                <Building2 size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Company Location</div>
                  <div className="text-slate-800 font-medium mt-0.5 break-words">
                    {contact.geography || 'Not specified'}
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-2.5">
                <MapPin size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Prospect Location</div>
                  <div className="text-slate-800 font-medium mt-0.5 break-words">
                    {contact.prospect_location || 'Location not provided'}
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-2.5">
                <Briefcase size={13} className="text-slate-400 shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Work Mode</div>
                  <div className="text-slate-800 font-medium mt-0.5 capitalize break-words">
                    {contact.work_mode && !['none', 'unknown'].includes(contact.work_mode.toLowerCase())
                      ? contact.work_mode
                      : 'Not specified'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Why This Prospect Qualification Summary */}
          {contact.selection_summary && (() => {
            const sentences = splitIntoSentences(contact.selection_summary)
            const isLong = sentences.length > 2
            const displayedText = (isLong && !isSummaryExpanded)
              ? sentences.slice(0, 2).join(' ')
              : contact.selection_summary

            return (
              <div className="mt-4 pt-3 border-t border-slate-200/70">
                <div className="text-[11px] font-bold text-blue-600 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
                  <Sparkles size={12} className="text-blue-500" />
                  <span>Why this prospect</span>
                </div>
                <div className="text-xs text-slate-700 leading-relaxed bg-blue-50/70 p-3.5 rounded-xl border border-blue-200/80 shadow-2xs">
                  <p>{displayedText}</p>
                  {isLong && (
                    <button
                      type="button"
                      onClick={() => setIsSummaryExpanded(!isSummaryExpanded)}
                      className="mt-2 text-[11px] font-semibold text-blue-600 hover:text-blue-800 transition-colors inline-flex items-center gap-1 cursor-pointer"
                    >
                      {isSummaryExpanded ? 'Show less' : 'Show more'}
                    </button>
                  )}
                </div>
              </div>
            )
          })()}

          {/* Scores & Status */}
          <div className="mt-4 pt-4 border-t border-slate-200/70 space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">ICP Score</span>
              <span className={`font-semibold ${scoreColor}`}>{contact.icp_score?.toFixed(0) ?? '—'}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Signal Score</span>
              <span className={`font-semibold ${contact.signal_score != null ? (contact.signal_score >= 80 ? 'text-emerald-600' : contact.signal_score >= 60 ? 'text-blue-600' : contact.signal_score >= 40 ? 'text-amber-600' : 'text-slate-600') : 'text-slate-400'}`}>
                {contact.signal_score != null ? contact.signal_score.toFixed(0) : '—'}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Readiness</span>
              <span className="text-slate-700 font-medium">{contact.readiness_score?.toFixed(0)}%</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-slate-500">Status</span>
              <span className={`font-medium ${contact.do_not_contact ? 'text-red-600' : 'text-emerald-600'}`}>
                {contact.do_not_contact ? 'DNC' : 'Active'}
              </span>
            </div>
            {contact.funding_stage && (
              <div className="flex justify-between text-xs">
                <span className="text-slate-500">Funding</span>
                <span className="text-slate-700 capitalize font-medium">{contact.funding_stage}</span>
              </div>
            )}
          </div>

          {/* Associated Active Deals Card */}
          {deals.length > 0 && (
            <div className="mt-4 pt-4 border-t border-slate-200/70 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                  <Briefcase size={12} className="text-blue-600" />
                  <span>Associated Deals ({deals.length})</span>
                </div>
                <span className="text-[10px] text-blue-600 font-medium">Click to view</span>
              </div>
              <div className="space-y-1.5">
                {deals.map(d => (
                  <div
                    key={d.id}
                    onClick={() => setSelectedDeal(d)}
                    className="p-2.5 rounded-lg bg-slate-50 hover:bg-slate-100/90 cursor-pointer transition-all border border-slate-200/80 hover:border-blue-400 group"
                  >
                    <div className="flex items-start justify-between gap-1.5">
                      <div className="text-xs font-semibold text-slate-800 group-hover:text-blue-600 transition-colors truncate">
                        {d.name}
                      </div>
                      {d.amount != null && (
                        <span className="text-[11px] font-bold text-slate-700 font-mono shrink-0">
                          ${(d.amount/1000).toFixed(0)}k
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-1">
                      <span className="capitalize text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded font-medium border border-blue-200/60">
                        {d.stage}
                      </span>
                      <span>·</span>
                      <span>{d.days_in_current_stage ?? 0}d in stage</span>
                      {d.deal_health_score != null && (
                        <>
                          <span>·</span>
                          <span className="text-emerald-600 font-semibold">
                            Health: {Math.round(d.deal_health_score)}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Panel: 3 cols out of 5 = 60% */}
        <div className="lg:col-span-3 space-y-5">
          {/* Signal Intelligence Section */}
          <div className="card">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <Zap size={14} className="text-amber-500" />
                <span className="text-sm font-semibold text-slate-800">
                  Signal Intelligence · {signals.length} {signals.length === 1 ? 'signal detected' : 'signals detected'}
                </span>
              </div>
              <button
                onClick={handleSummarize}
                disabled={isSummarizing}
                className="flex items-center gap-1.5 text-xs font-medium text-amber-800 bg-amber-50 hover:bg-amber-100 border border-amber-200 px-3 py-1.5 rounded-lg transition-all shadow-2xs disabled:opacity-50 cursor-pointer"
              >
                <Sparkles size={12} className={`text-amber-600 ${isSummarizing ? "animate-spin" : ""}`} />
                {isSummarizing ? "Summarizing..." : "Refresh AI Summary"}
              </button>
            </div>

            {/* 2-line LLM Summary */}
            <div className="bg-amber-50/50 border border-amber-200/60 rounded-xl p-3 mb-3">
              <p className="text-xs text-amber-950 font-medium leading-relaxed">
                {formatSignalSummary(contact.signal_summary) || (signals.length > 0
                  ? `Activity detected across ${signals.length} event(s). Click Refresh AI Summary to analyze.`
                  : "No buying signals detected yet. Agent 2 continues monitoring public and proprietary sources.")}
              </p>
            </div>

            {/* Signal List */}
            {signals.length === 0 ? (
              <div className="text-xs text-slate-500 py-4 text-center">No signals detected yet</div>
            ) : (
              <div className="space-y-2">
                {(isAllSignalsExpanded ? signals : signals.slice(0, 5)).map(s => {
                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedSignal(s)}
                      className="p-3 rounded-lg bg-slate-50 hover:bg-slate-100/80 border border-slate-200/60 cursor-pointer transition-colors"
                    >
                      <div className="flex items-start gap-3">
                        <div className="flex-1">
                          <div className="text-xs font-semibold text-slate-800 capitalize">
                            {s.signal_type?.replace(/_/g,' ')}
                          </div>
                          <div className="text-[11px] text-slate-500 mt-0.5">
                            Detected on {formatDisplayDate(s.detected_at)}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}

                {signals.length > 5 && (
                  <div className="pt-1 text-center">
                    <button
                      type="button"
                      onClick={() => setIsAllSignalsExpanded(!isAllSignalsExpanded)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors py-1 cursor-pointer"
                    >
                      {isAllSignalsExpanded
                        ? 'Show fewer signals'
                        : `+ Show ${signals.length - 5} more signals`}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Conversation Thread */}
          <div className="card">
            <div className="flex items-center justify-between mb-4 border-b border-gray-800/10 pb-2.5">
              <div className="flex items-center gap-2">
                <MessageSquare size={14} className="text-blue-500" />
                <span className="text-sm font-semibold text-gray-800">Conversation Thread</span>
                <span className="badge badge-blue">{thread.length} messages</span>
              </div>
              <div className="text-[11px] text-gray-500 flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                <span>Live Sync Active</span>
              </div>
            </div>

            {thread.length === 0 ? (
              <div className="text-xs text-gray-400 py-8 text-center">No email interactions recorded yet</div>
            ) : (
              <div className="space-y-4 max-h-[560px] overflow-y-auto pr-1">
                {thread.map((t, idx) => {
                  const isOutbound = t.direction === 'outbound' || t.event_type === 'email_sent' || t.event_type === 'reply_sent'
                  const prospectName = `${contact.first_name || ''} ${contact.last_name || ''}`.trim() || 'Prospect'
                  const prospectInitials = `${contact.first_name?.[0] || 'P'}${contact.last_name?.[0] || ''}`

                  return (
                    <div key={t.id || idx} className="space-y-3 pt-3 border-t border-gray-200/60 first:border-0 first:pt-0">
                      {isOutbound ? (
                        <div className="flex items-start gap-2.5 max-w-[90%] ml-auto flex-row-reverse">
                          <div className="w-8 h-8 rounded-full bg-emerald-600 text-white font-bold text-xs flex items-center justify-center shrink-0 border border-emerald-500 shadow-sm">
                            You
                          </div>
                          <div className="space-y-1.5 text-right w-full">
                            <div className="p-3.5 rounded-2xl rounded-tr-none bg-[#ECFDF5] text-[#064E3B] border border-[#A7F3D0] shadow-2xs text-xs leading-relaxed text-left whitespace-pre-line font-normal">
                              <div className="flex items-center justify-between gap-2 pb-1.5 mb-1.5 border-b border-emerald-200/80 text-[11px] font-semibold text-emerald-800">
                                <span className="inline-flex items-center gap-1">
                                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>
                                  Sent Message
                                </span>
                                <span className="text-[10px] text-emerald-700 font-normal">
                                  {t.sent_at || t.occurred_at ? new Date(t.sent_at || t.occurred_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Sent'}
                                </span>
                              </div>
                              <div className="text-slate-800 whitespace-pre-line">
                                {t.content}
                              </div>
                            </div>
                            <div className="flex items-center justify-end gap-2 text-[10px] text-slate-500 px-1">
                              <span className="font-medium text-emerald-700">Sent by You</span>
                              {t.channel && <span>· Via {t.channel.toUpperCase()}</span>}
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="space-y-3">
                          <div className="flex items-start gap-2.5 max-w-[90%]">
                            <div className="w-8 h-8 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 border border-blue-500 shadow-sm">
                              {prospectInitials}
                            </div>
                            <div className="space-y-1 w-full">
                              <div className="p-3.5 rounded-2xl rounded-tl-none bg-[#EFF6FF] text-[#1E3A8A] border border-[#BFDBFE] shadow-2xs text-xs leading-relaxed">
                                <div className="flex items-center justify-between gap-2 pb-1.5 mb-1.5 border-b border-blue-200/80 text-[11px] font-semibold text-blue-900">
                                  <span className="inline-flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-blue-600"></span>
                                    Received Email
                                  </span>
                                  <span className="text-[10px] text-blue-700 font-normal">
                                    {t.occurred_at ? new Date(t.occurred_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                                  </span>
                                </div>
                                <div className="text-slate-800 whitespace-pre-line">
                                  {t.content}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 text-[10px] text-slate-500 px-1 flex-wrap">
                                <span className="font-semibold text-blue-900">{prospectName}</span>
                                {t.intent && (
                                  <>
                                    <span>·</span>
                                    <span className="text-blue-800 bg-blue-100/80 border border-blue-300/80 px-1.5 py-0.2 rounded capitalize font-medium">
                                      {t.intent.replace(/_/g, ' ')}
                                    </span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Individual Signal Detail Modal */}
      {selectedSignal && (() => {
        const sourceInfo = getSignalSourceInfo(selectedSignal)
        const whatHappened = getWhatHappened(selectedSignal, contact)
        const sourceDetails = getSourceDetails(selectedSignal, contact)
        const signalTypeLabel = (selectedSignal.signal_type || 'buying_signal').replace(/_/g, ' ')
        const sourceName = humanizeSource(selectedSignal.signal_source)

        return (
          <div 
            className="fixed inset-0 bg-slate-900/40 backdrop-blur-xs z-50 flex items-center justify-center p-4 animate-fadeIn"
            onClick={() => setSelectedSignal(null)}
          >
            <div 
              className="bg-white rounded-2xl p-6 max-w-lg w-full shadow-2xl border border-slate-200/80 relative flex flex-col gap-4 animate-scaleUp text-slate-800"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Close Button */}
              <button 
                onClick={() => setSelectedSignal(null)}
                className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-all cursor-pointer"
                title="Close modal"
              >
                <X size={16} />
              </button>

              {/* Modal Header */}
              <div className="pr-8">
                <div className="flex items-center gap-1.5 text-xs font-bold text-amber-600 uppercase tracking-wider">
                  <Zap size={12} className="text-amber-500" />
                  <span>Signal Detail</span>
                </div>
                <h2 className="text-lg font-bold capitalize text-slate-900 mt-1">
                  {signalTypeLabel}
                </h2>
              </div>

              {/* Divider */}
              <div className="h-px bg-slate-200/80 w-full" />

              {/* Top Metadata Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-50/80 p-3 rounded-xl border border-slate-200/60">
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Signal Type</div>
                  <div className="text-xs font-bold text-slate-700 capitalize mt-0.5 truncate">
                    {signalTypeLabel}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Detected</div>
                  <div className="text-xs font-bold text-slate-700 mt-0.5 truncate">
                    {formatDisplayDate(selectedSignal.detected_at) || 'Recently'}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Signal Score</div>
                  <div className="text-xs font-bold text-slate-700 mt-0.5">
                    {Math.round((selectedSignal.confidence || 0) * 100)} / 100
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400">Source</div>
                  <div className="text-xs font-bold text-slate-700 mt-0.5 truncate">
                    {sourceName}
                  </div>
                </div>
              </div>

              {/* Content Body */}
              <div className="space-y-4 max-h-[380px] overflow-y-auto pr-1">
                {/* WHAT HAPPENED */}
                <div>
                  <div className="text-[11px] uppercase font-bold tracking-wider text-slate-500 mb-1">
                    What Happened
                  </div>
                  <div className="text-xs text-slate-800 leading-relaxed p-3 bg-blue-50/50 rounded-xl border border-blue-200/60 font-medium">
                    {whatHappened}
                  </div>
                </div>

                {/* SOURCE DETAILS */}
                <div>
                  <div className="text-[11px] uppercase font-bold tracking-wider text-slate-500 mb-1">
                    Source Details
                  </div>
                  <div className="text-xs text-slate-700 leading-relaxed p-3 bg-slate-50 rounded-xl border border-slate-200/70">
                    {sourceDetails}
                  </div>
                </div>

                {/* ORIGINAL SOURCE */}
                <div>
                  <div className="text-[11px] uppercase font-bold tracking-wider text-slate-500 mb-1">
                    Original Source
                  </div>
                  <div className="pt-0.5">
                    {sourceInfo.isAvailable ? (
                      <a 
                        href={sourceInfo.url} 
                        target="_blank" 
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-600 hover:text-blue-800 transition-colors group"
                      >
                        <span>View Original Source</span>
                        <ExternalLink size={12} className="group-hover:translate-x-0.5 transition-transform" />
                      </a>
                    ) : (
                      <span className="text-xs text-slate-400 font-medium">
                        Original source unavailable
                      </span>
                    )}
                  </div>
                </div>

                {/* Optional Structured Metadata Pills (e.g. Roles, Technologies) */}
                {selectedSignal.raw_data?.roles && selectedSignal.raw_data.roles.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Roles Mentioned</div>
                    <div className="flex flex-wrap gap-1">
                      {selectedSignal.raw_data.roles.map((role, idx) => (
                        <span key={idx} className="bg-amber-50 text-amber-800 border border-amber-200/70 rounded-md px-2 py-0.5 text-[11px] font-medium">
                          {role}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {selectedSignal.raw_data?.technologies && selectedSignal.raw_data.technologies.length > 0 && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-slate-400 mb-1">Technologies Detected</div>
                    <div className="flex flex-wrap gap-1">
                      {selectedSignal.raw_data.technologies.map((tech, idx) => (
                        <span key={idx} className="bg-emerald-50 text-emerald-800 border border-emerald-200/70 rounded-md px-2 py-0.5 text-[11px] font-medium">
                          {tech}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      {/* Interactive Deal Detail Modal */}
      {selectedDeal && (
        <DealDetailModal 
          selectedDeal={selectedDeal} 
          onClose={() => setSelectedDeal(null)} 
        />
      )}
    </div>
  )
}

import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import {
  fetchContact,
  fetchThread,
  fetchSignals,
  summarizeSignals,
  fetchSalesforceVerification,
  verifySalesforce,
  fetchContactDrafts
} from '../api'
import {
  extractSignalDetails,
  getSignalMeta,
  humanizeSource,
  formatDisplayDate,
} from '../utils/signalPresentationMapper'
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
  ChevronRight,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  HelpCircle
} from 'lucide-react'

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

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()

  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isVerifyingSalesforce, setIsVerifyingSalesforce] = useState(false)
  const [isSummaryExpanded, setIsSummaryExpanded] = useState(false)
  const [selectedSignal, setSelectedSignal] = useState(null)

  // Live queries
  const { data: contact, isLoading, refetch: refetchContact } = useQuery({
    queryKey: ['contact', id],
    queryFn: () => fetchContact(id),
    refetchInterval: 15_000,
  })

  const { data: salesforceVer, refetch: refetchSalesforceVer } = useQuery({
    queryKey: ['salesforceVerification', id],
    queryFn: () => fetchSalesforceVerification(id),
    refetchInterval: 30_000,
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

  const { data: drafts = [], isLoading: isDraftsLoading } = useQuery({
    queryKey: ['contactDrafts', id],
    queryFn: () => fetchContactDrafts(id),
    refetchInterval: 15_000,
    enabled: Boolean(id),
  })

  // Salesforce Account Verification Data (evaluated safely above early returns for hooks compliance)
  const verData = contact?.salesforce_verification || salesforceVer
  const verStatus = verData?.verification_status || 'pending'
  const evidenceList = verData?.evidence_items || verData?.evidence || []
  const lastCheckedText = useMemo(() => {
    if (verStatus === 'pending') return 'Verification pending'
    if (verData?.last_checked_at) {
      return formatDisplayDate(verData.last_checked_at) || 'Checked recently'
    }
    return 'Not yet verified'
  }, [verStatus, verData?.last_checked_at])

  // Handle Manual Salesforce Verification / Re-verify
  const handleVerifySalesforce = async () => {
    setIsVerifyingSalesforce(true)
    try {
      await verifySalesforce(id)
      await Promise.all([refetchContact(), refetchSalesforceVer()])
    } catch (err) {
      console.error('Verify Salesforce failed:', err)
    } finally {
      setIsVerifyingSalesforce(false)
    }
  }

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
                {contact.do_not_contact ? (
                  <span className="inline-block bg-red-100 text-red-700 border border-red-200 rounded-full px-3 py-0.5 text-xs font-semibold">
                    Do Not Contact
                  </span>
                ) : (
                  <span className="inline-block bg-[#DCFCE7] text-[#16A34A] border border-[#BBF7D0] rounded-full px-3 py-0.5 text-xs font-medium">
                    Active
                  </span>
                )}
              </div>
            </div>
          </div>

        </div>

        {/* ── Right Column: Salesforce Verification, Signal Intelligence & Conversation Thread ── */}
        <div className="flex-1 space-y-6 min-w-0 w-full">
          
          {/* ── Salesforce Account Verification Card (Phase 2) ── */}
          <div className="bg-white rounded-3xl border border-gray-100 shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 space-y-4">
            
            {/* Header & Status */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-[#00A1E0]/10 text-[#00A1E0] flex items-center justify-center shrink-0">
                  <ShieldCheck size={20} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight">
                    Salesforce Account Verification
                  </h3>
                  <p className="text-xs text-gray-500 font-medium">
                    Company: <span className="font-bold text-gray-800">{contact.company || 'Not specified'}</span>
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {verStatus === 'verified' && (
                  <span className="inline-flex items-center gap-1.5 bg-[#DCFCE7] text-[#16A34A] border border-[#BBF7D0] rounded-xl px-3 py-1 text-xs font-bold shadow-xs">
                    <CheckCircle2 size={13} />
                    <span>Salesforce Verified</span>
                  </span>
                )}
                {verStatus === 'not_verified' && (
                  <span className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-700 border border-amber-200 rounded-xl px-3 py-1 text-xs font-bold shadow-xs">
                    <AlertCircle size={13} />
                    <span>Not Verified</span>
                  </span>
                )}
                {verStatus === 'unable_to_verify' && (
                  <span className="inline-flex items-center gap-1.5 bg-gray-100 text-gray-600 border border-gray-200 rounded-xl px-3 py-1 text-xs font-bold shadow-xs">
                    <HelpCircle size={13} />
                    <span>Unable to Verify</span>
                  </span>
                )}
                {verStatus === 'pending' && (
                  <span className="inline-flex items-center gap-1.5 bg-slate-100 text-slate-600 border border-slate-200 rounded-xl px-3 py-1 text-xs font-semibold">
                    <span>Verification Pending</span>
                  </span>
                )}

                <button
                  type="button"
                  onClick={handleVerifySalesforce}
                  disabled={isVerifyingSalesforce}
                  className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 rounded-xl px-3 py-1 text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Check or refresh Salesforce account verification"
                >
                  <RefreshCw size={12} className={isVerifyingSalesforce ? 'animate-spin' : ''} />
                  <span>{isVerifyingSalesforce ? 'Verifying…' : 'Re-verify'}</span>
                </button>
              </div>
            </div>

            {/* Timestamps */}
            <div className="text-xs text-gray-400 font-medium pt-0.5">
              <span>Last checked: {lastCheckedText}</span>
            </div>

            {/* Status explanation callouts */}
            {verStatus === 'not_verified' && (
              <div className="bg-amber-50/60 border border-amber-100 text-amber-900 rounded-2xl p-3.5 text-xs leading-relaxed font-normal">
                No reliable Salesforce adoption evidence was found during the verification process. This does not establish that the company does not use Salesforce.
              </div>
            )}

            {verStatus === 'unable_to_verify' && (
              <div className="bg-gray-50 border border-gray-200 text-gray-700 rounded-2xl p-3.5 text-xs leading-relaxed font-normal">
                Verification could not be completed. One or more required sources were unavailable or the company could not be reliably identified.
              </div>
            )}

            {verStatus === 'pending' && (
              <div className="bg-slate-50 border border-slate-200 text-slate-600 rounded-2xl p-3.5 text-xs leading-relaxed font-normal">
                Salesforce verification is pending.
              </div>
            )}

            {verData?.verification_summary && verStatus === 'verified' && (
              <div className="bg-[#F0FDF4] border border-[#DCFCE7] text-gray-700 rounded-2xl p-3.5 text-xs leading-relaxed font-normal">
                {verData.verification_summary}
              </div>
            )}

            {/* Evidence items list */}
            <div className="space-y-3 pt-1">
              <div className="text-xs font-bold text-gray-700 uppercase tracking-wider">
                Verification evidence
              </div>

              {evidenceList.length === 0 ? (
                <div className="py-4 text-center text-xs text-gray-400 bg-gray-50/50 rounded-2xl border border-dashed border-gray-200">
                  {verStatus === 'pending' ? 'Verification has not run yet.' : 'No reliable evidence records captured.'}
                </div>
              ) : (
                evidenceList.map((item, idx) => (
                  <div key={item.id || idx} className="rounded-2xl border border-gray-100 bg-[#FAFAFC] p-4 text-xs space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-gray-900 flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-white border border-gray-200 text-gray-600 text-[10px] flex items-center justify-center font-bold">
                          {idx + 1}
                        </span>
                        <span>{item.source_name || humanizeSource(item.evidence_type)}</span>
                      </span>
                      {item.checked_at && (
                        <span className="text-[11px] text-gray-400 font-normal">
                          Checked {formatDisplayDate(item.checked_at)}
                        </span>
                      )}
                    </div>

                    <p className="text-gray-600 leading-relaxed font-normal pl-7">
                      {item.evidence_description}
                    </p>

                    <div className="pl-7 pt-0.5 flex items-center justify-between gap-3 flex-wrap">
                      {item.source_url ? (
                        <a
                          href={item.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[#5B4EFF] hover:underline font-semibold"
                        >
                          <span>Source: [View original evidence]</span>
                          <ExternalLink size={11} />
                        </a>
                      ) : (
                        <span className="text-gray-400 italic">
                          Direct source link unavailable (Apollo structured technographic profile)
                        </span>
                      )}

                      {item.evidence_date && (
                        <span className="text-[11px] text-gray-400">
                          Evidence date: {formatDisplayDate(item.evidence_date)}
                        </span>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

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
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-bold text-gray-900 group-hover:text-[#5B4EFF] transition-colors truncate">
                              {meta.displayType}
                            </span>
                            <span className="bg-gray-100 text-gray-500 rounded-md px-1.5 py-0.5 text-[10px] font-medium shrink-0">
                              {details.sourceName}
                            </span>
                            {details.freshness && (
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold shrink-0 ${
                                details.freshness.status === 'Hot'
                                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                  : details.freshness.status === 'Recent'
                                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                                  : details.freshness.status === 'Moderate'
                                  ? 'bg-amber-50 text-amber-700 border border-amber-200'
                                  : 'bg-gray-100 text-gray-500 border border-gray-200'
                              }`}>
                                {details.freshness.label}
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-gray-600 font-medium truncate">
                            {details.headline}
                          </div>
                          <div className="text-[11px] text-gray-400 font-normal flex items-center gap-2 flex-wrap">
                            {details.eventDate ? <span>Event date: {details.eventDate}</span> : <span>Detected: {formatDisplayDate(sig.detected_at)}</span>}
                            {details.publishedAt && <span>• Published: {details.publishedAt}</span>}
                            {details.discoveredAt && <span>• Discovered: {details.discoveredAt}</span>}
                            {details.pills && details.pills.length > 0 && details.pillsTitle && (
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

          {/* Card 1.5: Generated Outreach Drafts (Signal Personalisation & Traceability) */}
          <div className="bg-white rounded-3xl border border-[#ECE8FE] shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs font-bold text-[#5B4EFF]">
                <Mail size={14} className="text-[#5B4EFF]" />
                <span>Generated Outreach Drafts · {drafts.length} {drafts.length === 1 ? 'draft' : 'drafts'}</span>
              </div>
              {isDraftsLoading && (
                <div className="text-[11px] text-gray-400 font-medium animate-pulse">Syncing drafts…</div>
              )}
            </div>

            {drafts.length === 0 ? (
              <div className="py-8 text-center text-xs text-gray-400 bg-[#FAF9FF] rounded-2xl border border-dashed border-[#ECE8FE]">
                No outreach drafts generated yet for this prospect. Trigger Agent 3 to generate signal-tailored email copy.
              </div>
            ) : (
              <div className="space-y-4">
                {drafts.map((draft) => {
                  const matched = draft.matched_services || {}
                  const reasoning = draft.personalisation_reasoning || matched.personalisation_reasoning || draft.business_case || ''
                  const primarySig = draft.selected_primary_signal || matched.selected_primary_signal || (draft.signal ? (draft.signal.signal_type || draft.signal.summary) : null)
                  const category = draft.signal_category || matched.signal_category || 'signal-based'
                  const services = Array.isArray(matched) ? matched : (matched.services || [])

                  const statusColor =
                    draft.status === 'sent' || draft.approval_state === 'approved'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : draft.status === 'rejected' || draft.approval_state === 'rejected'
                      ? 'bg-rose-50 text-rose-700 border-rose-200'
                      : 'bg-amber-50 text-amber-700 border-amber-200'

                  return (
                    <div key={draft.id} className="rounded-2xl border border-gray-100 bg-[#FAF9FF]/60 p-5 space-y-3.5 hover:border-[#5B4EFF]/30 transition-all">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-bold text-gray-900">{draft.subject || 'No Subject'}</span>
                            <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border uppercase tracking-wider ${statusColor}`}>
                              {draft.approval_state || draft.status || 'pending'}
                            </span>
                            <span className="bg-[#5B4EFF]/10 text-[#5B4EFF] border border-[#5B4EFF]/20 rounded-full px-2.5 py-0.5 text-[10px] font-semibold">
                              {category}
                            </span>
                          </div>
                          {primarySig && (
                            <div className="text-[11px] text-gray-500 font-medium">
                              Grounded in signal: <span className="text-gray-800 font-semibold">{primarySig}</span>
                            </div>
                          )}
                        </div>
                        {draft.created_at && (
                          <span className="text-[11px] text-gray-400 font-medium">
                            {formatDisplayDate(draft.created_at)}
                          </span>
                        )}
                      </div>

                      {reasoning && (
                        <div className="bg-amber-50/70 border border-amber-200/60 rounded-xl p-3 text-xs text-amber-900 leading-relaxed">
                          <strong className="font-semibold text-amber-950">Why this copy was drafted: </strong>
                          <span>{reasoning}</span>
                        </div>
                      )}

                      {services.length > 0 && (
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-[11px] font-semibold text-gray-500">Matched offerings:</span>
                          {services.map((srv, sIdx) => (
                            <span key={sIdx} className="bg-white border border-gray-200 text-gray-700 rounded-lg px-2 py-0.5 text-[10px] font-medium">
                              {srv}
                            </span>
                          ))}
                        </div>
                      )}

                      <div className="bg-white rounded-xl border border-gray-200/80 p-4 text-xs text-gray-700 leading-relaxed font-normal whitespace-pre-wrap font-sans">
                        {draft.body}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
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

                  {/* Source details - Dynamic 2-column grid driven by signal type */}
                  {details.sourceDetails && details.sourceDetails.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-gray-400 mb-2">
                        Source details
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        {details.sourceDetails.map((item, idx) => (
                          <div key={idx} className="min-w-0">
                            <div className="text-[11px] font-semibold text-gray-400">
                              {item.label}
                            </div>
                            <div className="text-xs font-bold text-gray-900 mt-0.5 truncate" title={item.value}>
                              {item.value}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Company context - Strictly signal-grounded, zero prospect summary leakage */}
                  <div>
                    <div className="text-xs font-semibold text-gray-400 mb-1">
                      Company context
                    </div>
                    <p className="text-xs text-gray-600 leading-relaxed font-normal">
                      {details.companyContext}
                    </p>
                  </div>

                  {/* Roles / Locations / Technologies Mentioned */}
                  {details.pills && details.pills.length > 0 && details.pillsTitle && (
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
                
                {details.sourceUrl ? (
                  <a
                    href={details.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-5 py-2 rounded-xl text-xs font-semibold text-white bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.98] transition-all flex items-center gap-1.5 shadow-sm cursor-pointer"
                  >
                    <span>View original source</span>
                    <ExternalLink size={12} />
                  </a>
                ) : (
                  <span className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 bg-gray-50 border border-gray-200">
                    Direct source link unavailable
                  </span>
                )}
              </div>

            </div>
          </div>
        )
      })()}

    </div>
  )
}

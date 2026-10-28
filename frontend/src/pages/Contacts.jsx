import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Search, ChevronDown, ChevronLeft, ChevronRight, Play, Filter, ExternalLink } from 'lucide-react'
import { fetchContacts, fetchTierSummary, runOrchestratorWorkflow, DEFAULT_PIPELINE_AGENTS } from '../api'
import { useSession } from '../context/SessionContext'

function formatSignalRecency(dateStr) {
  if (!dateStr) return null
  try {
    const s = String(dateStr).trim()
    const isIsoNaive = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)
    const normalizedStr = isIsoNaive ? `${s}Z` : s
    const d = new Date(normalizedStr)
    if (isNaN(d.getTime())) return null
    const now = new Date()
    const diffMs = now - d
    if (diffMs < 0) return 'Today'
    const diffHours = diffMs / (1000 * 60 * 60)
    if (diffHours < 24) return 'Today'
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays === 1) return '1d ago'
    if (diffDays < 30) return `${diffDays}d ago`
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  } catch {
    return null
  }
}

function getSignalBadgeInfo(type) {
  if (!type) return null
  const t = type.toLowerCase()
  if (t.includes('funding')) {
    return { label: 'Funding', bg: 'bg-[#F3E8FF]', text: 'text-[#9333EA]', border: 'border-[#E9D5FF]' }
  }
  if (t.includes('tech') || t.includes('stack')) {
    return { label: 'Tech Change', bg: 'bg-[#D1FAE5]', text: 'text-[#059669]', border: 'border-[#A7F3D0]' }
  }
  if (t.includes('news') || t.includes('expansion')) {
    return { label: 'News', bg: 'bg-[#F1F5F9]', text: 'text-[#475569]', border: 'border-[#E2E8F0]' }
  }
  if (t.includes('earnings')) {
    return { label: 'Earnings Call', bg: 'bg-[#E0F2FE]', text: 'text-[#0284C7]', border: 'border-[#BAE6FD]' }
  }
  if (t.includes('job') || t.includes('hire') || t.includes('posting')) {
    return { label: 'Job Posting', bg: 'bg-[#FEF3C7]', text: 'text-[#D97706]', border: 'border-[#FDE68A]' }
  }
  return { label: type.replace(/_/g, ' '), bg: 'bg-gray-100', text: 'text-gray-700', border: 'border-gray-200' }
}

export default function Contacts() {
  const navigate = useNavigate()
  const { activeSessionId } = useSession()

  // State
  const [search, setSearch] = useState('')
  const [selectedScoreFilter, setSelectedScoreFilter] = useState('all') // 'all' | 'tier1' | 'tier2' | 'tier3' | 'signals'
  const [selectedSort, setSelectedSort] = useState('newest') // 'newest' | 'score' | 'signal_score' | 'name'
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const [showFilterBar, setShowFilterBar] = useState(false)
  const [industryFilter, setIndustryFilter] = useState('all')
  const [isRunningGtm, setIsRunningGtm] = useState(false)

  // Fetch live contacts from backend
  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts', activeSessionId, selectedSort],
    queryFn: () =>
      fetchContacts({
        limit: 100,
        sort_by: selectedSort === 'score' ? 'score' : selectedSort === 'signal_score' ? 'signal_score' : 'newest',
        sort_order: 'desc',
        ...(activeSessionId != null ? { user_input_id: activeSessionId } : {}),
      }),
  })

  // Trigger Full GTM Pipeline
  const handleRunFullGtm = async () => {
    setIsRunningGtm(true)
    try {
      const res = await runOrchestratorWorkflow({
        workflowName: 'manual_full_gtm',
        agentIds: DEFAULT_PIPELINE_AGENTS,
      })
      navigate('/agents', { state: { runId: res?.workflow?.id || res?.id } })
    } catch (err) {
      console.error('Run Full GTM error:', err)
      navigate('/agents')
    } finally {
      setIsRunningGtm(false)
    }
  }

  // Filter & sort contacts locally
  const filteredContacts = useMemo(() => {
    return contacts.filter(c => {
      // Search query filter
      const matchesSearch =
        !search ||
        c.first_name?.toLowerCase().includes(search.toLowerCase()) ||
        c.last_name?.toLowerCase().includes(search.toLowerCase()) ||
        c.email?.toLowerCase().includes(search.toLowerCase()) ||
        c.company?.toLowerCase().includes(search.toLowerCase()) ||
        c.title?.toLowerCase().includes(search.toLowerCase()) ||
        c.geography?.toLowerCase().includes(search.toLowerCase())

      // Score filter
      let matchesScore = true
      if (selectedScoreFilter === 'tier1') matchesScore = (c.icp_score || 0) >= 75
      else if (selectedScoreFilter === 'tier2') matchesScore = (c.icp_score || 0) >= 60 && (c.icp_score || 0) < 75
      else if (selectedScoreFilter === 'tier3') matchesScore = (c.icp_score || 0) < 60
      else if (selectedScoreFilter === 'signals') matchesScore = (c.signal_score != null && c.signal_score > 0) || Boolean(c.signal_type)

      // Industry filter
      let matchesIndustry = true
      if (industryFilter !== 'all') {
        matchesIndustry = c.industry?.toLowerCase().includes(industryFilter.toLowerCase())
      }

      return matchesSearch && matchesScore && matchesIndustry
    }).sort((a, b) => {
      if (selectedSort === 'name') {
        const nameA = `${a.first_name || ''} ${a.last_name || ''}`.trim().toLowerCase()
        const nameB = `${b.first_name || ''} ${b.last_name || ''}`.trim().toLowerCase()
        return nameA.localeCompare(nameB)
      }
      return 0
    })
  }, [contacts, search, selectedScoreFilter, selectedSort, industryFilter])

  // Extract unique industries for optional filter
  const industries = useMemo(() => {
    const set = new Set()
    contacts.forEach(c => { if (c.industry) set.add(c.industry) })
    return Array.from(set)
  }, [contacts])

  // Pagination calculations
  const totalItems = filteredContacts.length
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
  const paginatedContacts = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredContacts.slice(start, start + pageSize)
  }, [filteredContacts, currentPage, pageSize])

  return (
    <div className="w-full space-y-6 pb-12 selection:bg-[#5B4EFF]/15">
      
      {/* ── Page Header ────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-[26px] font-bold text-[#111827] tracking-tight">
            Prospect
          </h1>
          <p className="text-xs text-gray-400 font-medium mt-0.5">
            Prospect Intelligence Graph
          </p>
        </div>

        {/* Run Full GTM Button matching Figma */}
        <button
          type="button"
          onClick={handleRunFullGtm}
          disabled={isRunningGtm}
          className="self-start sm:self-auto py-2.5 px-5 sm:px-6 rounded-xl font-semibold text-sm text-white bg-[#5B4EFF] hover:bg-[#4E41E6] active:scale-[0.98] shadow-sm transition-all flex items-center justify-center gap-2.5 cursor-pointer disabled:opacity-60 whitespace-nowrap"
        >
          <Play size={14} className={isRunningGtm ? 'animate-spin' : 'fill-white text-white'} />
          <span>{isRunningGtm ? 'Running GTM...' : 'Run Full GTM'}</span>
        </button>
      </div>

      {/* ── Search & Filter Controls ─────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
        
        {/* Search contacts input */}
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setCurrentPage(1); }}
            placeholder="Search contacts..."
            className="w-full bg-white border border-gray-200/90 rounded-full py-2 pl-9 pr-4 text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] transition-all shadow-sm"
          />
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        </div>

        {/* Right Filter Controls */}
        <div className="flex items-center gap-3 self-end sm:self-auto flex-wrap">
          
          {/* Show: All scores dropdown */}
          <div className="relative">
            <select
              value={selectedScoreFilter}
              onChange={(e) => { setSelectedScoreFilter(e.target.value); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-2 pl-3 pr-8 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value="all">Show: All scores</option>
              <option value="tier1">Show: Tier 1 (75+)</option>
              <option value="tier2">Show: Tier 2 (60-74)</option>
              <option value="tier3">Show: Tier 3 (&lt;60)</option>
              <option value="signals">Show: With Signals</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Sort: Newest dropdown */}
          <div className="relative">
            <select
              value={selectedSort}
              onChange={(e) => { setSelectedSort(e.target.value); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-2 pl-3 pr-8 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value="newest">Sort: Newest</option>
              <option value="score">Sort: ICP Score</option>
              <option value="signal_score">Sort: Signal Score</option>
              <option value="name">Sort: Alphabetical</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Add Filter Button */}
          <button
            type="button"
            onClick={() => setShowFilterBar(prev => !prev)}
            className={`py-2 px-3.5 bg-white border rounded-xl text-xs font-medium transition-all shadow-sm flex items-center gap-1.5 cursor-pointer ${
              showFilterBar || industryFilter !== 'all'
                ? 'border-[#5B4EFF] text-[#5B4EFF] bg-[#ECE8FE]/30'
                : 'border-gray-200/90 text-gray-700 hover:border-gray-300'
            }`}
          >
            <Filter size={12} className={industryFilter !== 'all' ? 'text-[#5B4EFF]' : 'text-gray-500'} />
            <span>Add Filter</span>
          </button>
        </div>
      </div>

      {/* Expandable Industry / Advanced Filter Bar */}
      {showFilterBar && (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-gray-700">Industry:</span>
            <select
              value={industryFilter}
              onChange={(e) => { setIndustryFilter(e.target.value); setCurrentPage(1); }}
              className="bg-[#FBFBFE] border border-gray-200 rounded-lg py-1 px-2.5 text-xs text-gray-700"
            >
              <option value="all">All Industries</option>
              {industries.map(ind => (
                <option key={ind} value={ind}>{ind}</option>
              ))}
            </select>
          </div>
          {industryFilter !== 'all' && (
            <button
              onClick={() => { setIndustryFilter('all'); setCurrentPage(1); }}
              className="text-xs text-[#5B4EFF] hover:underline font-semibold"
            >
              Reset Filters
            </button>
          )}
        </div>
      )}

      {/* ── Main Contacts Table Card ─────────────────────────────────── */}
      <div className="bg-white rounded-3xl border border-gray-100 shadow-[0_2px_16px_rgba(30,27,75,0.03)] p-6 sm:p-7 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead>
              <tr className="border-b border-gray-100 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                <th className="pb-3.5 pl-2 font-semibold">Contact</th>
                <th className="pb-3.5 font-semibold">Company</th>
                <th className="pb-3.5 font-semibold text-center">ICP Score</th>
                <th className="pb-3.5 font-semibold text-center">Signal Score</th>
                <th className="pb-3.5 font-semibold">Readiness</th>
                <th className="pb-3.5 font-semibold">Signal</th>
                <th className="pb-3.5 pr-2 font-semibold text-right">Status</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-gray-100/70">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-xs text-gray-400">
                    Loading contacts…
                  </td>
                </tr>
              ) : paginatedContacts.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-xs text-gray-400">
                    No contacts found.
                  </td>
                </tr>
              ) : (
                paginatedContacts.map(c => {
                  const recency = formatSignalRecency(c.primary_signal_at || c.latest_signal_at)
                  const primarySig = c.primary_signal_type || (c.signal_type ? c.signal_type.split(',')[0] : null)
                  const allSigs = c.signal_type ? c.signal_type.split(',').filter(Boolean) : (primarySig ? [primarySig] : [])
                  const extraSigs = Math.max(0, allSigs.length - 1)
                  const badgeInfo = getSignalBadgeInfo(primarySig)

                  return (
                    <tr
                      key={c.id}
                      onClick={() => navigate(`/contacts/${c.id}`)}
                      className="hover:bg-gray-50/70 transition-colors cursor-pointer group"
                    >
                      {/* CONTACT */}
                      <td className="py-4 pl-2 pr-4 align-top">
                        <div className="space-y-0.5">
                          <div className="text-xs sm:text-[13px] font-bold text-gray-900 group-hover:text-[#5B4EFF] transition-colors leading-tight">
                            {c.first_name} {c.last_name}
                          </div>
                          <div className="text-[11px] text-gray-400 truncate max-w-[200px]">
                            {c.title || 'Executive'}
                          </div>
                          <div className="text-[11px] text-gray-400 flex items-center gap-1">
                            <span className="truncate max-w-[180px]">{c.email}</span>
                            {c.linkedin_url && (
                              <a
                                href={c.linkedin_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-gray-400 hover:text-[#5B4EFF] transition-colors shrink-0"
                                title="LinkedIn Profile"
                              >
                                <ExternalLink size={10} />
                              </a>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* COMPANY */}
                      <td className="py-4 px-4 align-top">
                        <div className="space-y-0.5">
                          <div className="text-xs sm:text-[13px] font-bold text-gray-900 leading-tight">
                            {c.company || 'Company'}
                          </div>
                          <div className="text-[11px] text-gray-400 flex items-center gap-1">
                            <span className="font-medium text-gray-400">HQ:</span>
                            <span className="truncate max-w-[200px]">
                              {c.geography || c.industry || 'United States'}
                            </span>
                          </div>
                        </div>
                      </td>

                      {/* ICP SCORE */}
                      <td className="py-4 px-3 align-top text-center">
                        <div className="inline-flex justify-center">
                          {c.icp_score != null ? (
                            <span
                              className={`w-9 h-7 rounded-lg flex items-center justify-center font-bold text-xs border ${
                                c.icp_score >= 80
                                  ? 'bg-[#DCFCE7] text-[#16A34A] border-[#BBF7D0]'
                                  : 'bg-[#EBF3FF] text-[#2563EB] border-[#BFDBFE]'
                              }`}
                            >
                              {Math.round(c.icp_score)}
                            </span>
                          ) : (
                            <span className="text-gray-400 text-xs">—</span>
                          )}
                        </div>
                      </td>

                      {/* SIGNAL SCORE */}
                      <td className="py-4 px-3 align-top text-center">
                        <div className="inline-flex justify-center">
                          {(c.primary_signal_score ?? c.signal_score) != null ? (
                            (() => {
                              const s = Math.round(c.primary_signal_score ?? c.signal_score)
                              return (
                                <span
                                  className={`w-9 h-7 rounded-lg flex items-center justify-center font-bold text-xs border ${
                                    s >= 70
                                      ? 'bg-[#EBF3FF] text-[#2563EB] border-[#BFDBFE]'
                                      : s >= 50
                                      ? 'bg-[#FEF3C7] text-[#D97706] border-[#FDE68A]'
                                      : 'bg-[#F1F5F9] text-[#64748B] border-[#E2E8F0]'
                                  }`}
                                >
                                  {s}
                                </span>
                              )
                            })()
                          ) : (
                            <span className="text-gray-400 text-xs">—</span>
                          )}
                        </div>
                      </td>

                      {/* READINESS */}
                      <td className="py-4 px-4 align-top">
                        <div className="flex items-center gap-2 pt-1.5">
                          <div className="w-14 sm:w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-[#5B4EFF] rounded-full transition-all"
                              style={{ width: `${Math.min(100, Math.max(0, c.readiness_score || 0))}%` }}
                            />
                          </div>
                          <span className="text-[11px] text-gray-400 font-medium">
                            {Math.round(c.readiness_score || 0)}%
                          </span>
                        </div>
                      </td>

                      {/* SIGNAL */}
                      <td className="py-4 px-4 align-top">
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-1 flex-wrap">
                            {badgeInfo ? (
                              <>
                                <span
                                  className={`px-2 py-0.5 rounded-md text-[10px] font-semibold border ${badgeInfo.bg} ${badgeInfo.text} ${badgeInfo.border}`}
                                >
                                  {badgeInfo.label}
                                </span>
                                {extraSigs > 0 && (
                                  <span className="bg-gray-100 text-gray-600 rounded-md px-1.5 py-0.5 text-[9px] font-medium border border-gray-200">
                                    +{extraSigs}
                                  </span>
                                )}
                              </>
                            ) : (
                              <span className="text-gray-400 text-xs">—</span>
                            )}
                          </div>
                          {recency && (
                            <div className="text-[10px] text-gray-400 font-medium">
                              {recency}
                            </div>
                          )}
                        </div>
                      </td>

                      {/* STATUS */}
                      <td className="py-4 pl-4 pr-2 align-top text-right">
                        <span className="inline-block bg-[#DCFCE7] text-[#16A34A] border border-[#BBF7D0] rounded-full px-2.5 py-0.5 text-[11px] font-medium">
                          Active
                        </span>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* ── Pagination Footer matching Figma ─────────────────────── */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 mt-4 border-t border-gray-100 text-xs text-gray-500">
          
          {/* Page Size Select */}
          <div className="relative">
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-1.5 pl-3 pr-7 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value={10}>10 Documents</option>
              <option value={20}>20 Documents</option>
              <option value={50}>50 Documents</option>
            </select>
            <ChevronDown size={13} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Pagination Navigation */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              className="px-2.5 py-1 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1"
            >
              <ChevronLeft size={13} />
              <span>Previous</span>
            </button>

            {Array.from({ length: Math.min(totalPages, 5) }).map((_, idx) => {
              const pNum = idx + 1
              return (
                <button
                  key={pNum}
                  type="button"
                  onClick={() => setCurrentPage(pNum)}
                  className={`w-7 h-7 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    currentPage === pNum
                      ? 'bg-[#5B4EFF] text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {pNum}
                </button>
              )
            })}

            {totalPages > 5 && (
              <>
                <span className="text-gray-400 px-1">…</span>
                <button
                  type="button"
                  onClick={() => setCurrentPage(totalPages)}
                  className={`w-7 h-7 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    currentPage === totalPages
                      ? 'bg-[#5B4EFF] text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {totalPages}
                </button>
              </>
            )}

            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              className="px-2.5 py-1 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight size={13} />
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}


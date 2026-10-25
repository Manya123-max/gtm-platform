// ── Contacts Page with ICP & Signal Tiering in Header Controls ──────────────
import { useQuery } from '@tanstack/react-query'
import { fetchContacts, fetchTierSummary } from '../api'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ArrowUpDown, Sparkles, ArrowDown, ArrowUp, Link } from 'lucide-react'
import { useSession } from '../context/SessionContext'

function ScorePill({ score }) {
  const color = score >= 80 ? 'badge-green' : score >= 60 ? 'badge-blue' : score >= 40 ? 'badge-amber' : 'badge-gray'
  return <span className={`badge ${color}`}>{score != null ? score.toFixed(0) : '—'}</span>
}

function SignalBadge({ type }) {
  if (!type) return <span className="text-gray-400 text-xs">—</span>
  const map = {
    tech_stack_change: ['badge-green', 'Tech Change'],
    new_hire:          ['badge-blue', 'New Hire'],
    funding_round:     ['badge-purple', 'Funding'],
    job_posting:       ['badge-amber', 'Hiring'],
    news_expansion:    ['badge-gray', 'News'],
    earnings_call:     ['badge-cyan', 'Earnings Call'],
    social_engagement: ['badge-blue', 'Social Buzz'],
    competitor_review: ['badge-amber', 'Competitor Review'],
  }
  const [cls, label] = map[type] || ['badge-gray', type]
  return <span className={`badge ${cls}`}>{label}</span>
}

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

function isNew(createdAt) {
  if (!createdAt) return false
  const created = new Date(createdAt)
  const now = new Date()
  const diffHours = (now - created) / (1000 * 60 * 60)
  return diffHours <= 24
}

export default function Contacts() {
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState('')
  const [sortBy, setSortBy] = useState('newest')
  const [sortOrder, setSortOrder] = useState('desc')
  const [selectedTier, setSelectedTier] = useState('all')
  const navigate = useNavigate()
  const { activeSessionId, ourCompanyName } = useSession()

  // Fetch full contacts list for the active session
  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts', minScore, sortBy, sortOrder, activeSessionId],
    queryFn: () => fetchContacts({
      min_score: minScore || undefined,
      limit: 100,
      sort_by: sortBy,
      sort_order: sortOrder,
      ...(activeSessionId != null ? { user_input_id: activeSessionId } : {}),
    }),
  })

  // Fetch authoritative tier summary counts
  const { data: tierSummary = {} } = useQuery({
    queryKey: ['contacts-tier-summary', activeSessionId],
    queryFn: () => fetchTierSummary(activeSessionId),
  })

  // Synchronized search and tier filtering
  const filtered = contacts.filter(c => {
    const matchesSearch = !search ||
      c.email?.toLowerCase().includes(search.toLowerCase()) ||
      c.company?.toLowerCase().includes(search.toLowerCase()) ||
      c.first_name?.toLowerCase().includes(search.toLowerCase()) ||
      c.last_name?.toLowerCase().includes(search.toLowerCase()) ||
      c.title?.toLowerCase().includes(search.toLowerCase())
    const matchesTier = selectedTier === 'all' || String(c.tier) === String(selectedTier)
    return matchesSearch && matchesTier
  })

  // Dynamic counts for toolbar buttons
  const countAll = tierSummary?.all ?? contacts.length
  const countTier1 = tierSummary?.tier_1 ?? contacts.filter(c => c.tier === 1).length
  const countTier2 = tierSummary?.tier_2 ?? contacts.filter(c => c.tier === 2).length
  const countTier3 = tierSummary?.tier_3 ?? contacts.filter(c => c.tier === 3).length

  const newCount = contacts.filter(c => isNew(c.created_at)).length

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      {/* ── Top Header & Controls (Matching Screenshot Layout) ──────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--c-text)]">
            Contacts {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-[var(--c-text2)] mt-0.5">
            Prospect Intelligence Graph — {filtered.length} contacts
            {newCount > 0 && (
              <span className="ml-2 inline-flex items-center gap-1 text-emerald-600 font-medium">
                <Sparkles size={11} />
                {newCount} new in last 24h
              </span>
            )}
          </p>
        </div>

        {/* Upper Region Controls: Search, Tier Filters, Score Filter, Sort */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Search Box */}
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              className="input pl-8 w-44 md:w-52 text-xs"
              placeholder="Search contacts…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          {/* Tier Filter Buttons Placed Next to Search Box */}
          <div className="inline-flex items-center p-0.5 rounded-lg border border-[var(--c-border)] bg-[var(--c-surface2)] shadow-2xs">
            {/* All */}
            <button
              type="button"
              onClick={() => setSelectedTier('all')}
              className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
                selectedTier === 'all'
                  ? 'bg-white text-[var(--c-blue)] shadow-xs'
                  : 'text-[var(--c-text2)] hover:text-[var(--c-text)] hover:bg-white/60'
              }`}
            >
              <span>All</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                selectedTier === 'all' ? 'bg-blue-100 text-[var(--c-blue)]' : 'bg-white/80 text-[var(--c-text3)]'
              }`}>
                {countAll}
              </span>
            </button>

            {/* Tier 1 */}
            <button
              type="button"
              onClick={() => setSelectedTier('1')}
              className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
                selectedTier === '1'
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'text-emerald-700 hover:text-emerald-800 hover:bg-emerald-50/80'
              }`}
              title="Tier 1: High priority accounts with strong ICP fit (≥70) and buying intent signals"
            >
              <span className={`w-1.5 h-1.5 rounded-full ${selectedTier === '1' ? 'bg-white' : 'bg-emerald-500 animate-pulse'}`} />
              <span>Tier 1</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                selectedTier === '1' ? 'bg-emerald-700 text-white' : 'bg-emerald-100 text-emerald-800'
              }`}>
                {countTier1}
              </span>
            </button>

            {/* Tier 2 */}
            <button
              type="button"
              onClick={() => setSelectedTier('2')}
              className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
                selectedTier === '2'
                  ? 'bg-[var(--c-blue)] text-white shadow-xs'
                  : 'text-blue-700 hover:text-blue-800 hover:bg-blue-50/80'
              }`}
              title="Tier 2: Medium priority accounts with promising ICP fit (≥50) or awaiting fresh signals"
            >
              <span>Tier 2</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                selectedTier === '2' ? 'bg-blue-700 text-white' : 'bg-blue-100 text-blue-800'
              }`}>
                {countTier2}
              </span>
            </button>

            {/* Tier 3 */}
            <button
              type="button"
              onClick={() => setSelectedTier('3')}
              className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 ${
                selectedTier === '3'
                  ? 'bg-gray-700 text-white shadow-xs'
                  : 'text-gray-600 hover:text-gray-800 hover:bg-white/60'
              }`}
              title="Tier 3: Lower ICP fit or nurture accounts"
            >
              <span>Tier 3</span>
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                selectedTier === '3' ? 'bg-gray-800 text-white' : 'bg-gray-200 text-gray-700'
              }`}>
                {countTier3}
              </span>
            </button>
          </div>

          {/* Scores Filter */}
          <select
            className="input w-32 text-xs"
            value={minScore}
            onChange={e => setMinScore(e.target.value)}
          >
            <option value="">All scores</option>
            <option value="40">Score ≥ 40</option>
            <option value="60">Score ≥ 60</option>
            <option value="70">Score ≥ 70</option>
            <option value="80">Score ≥ 80</option>
          </select>

          {/* Sort By */}
          <div className="relative">
            <select
              className="input pl-8 w-36 appearance-none text-xs cursor-pointer pr-7"
              value={sortBy}
              onChange={e => setSortBy(e.target.value)}
            >
              <option value="newest">Sort: Newest</option>
              <option value="score">Sort: ICP Score</option>
              <option value="signal_score">Sort: Signal Score</option>
            </select>
            <ArrowUpDown size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Sort Direction Toggle */}
          <button
            onClick={() => setSortOrder(o => o === 'desc' ? 'asc' : 'desc')}
            className="flex items-center justify-center p-2 rounded-lg border border-[var(--c-border)] bg-white hover:bg-[var(--c-surface2)] text-gray-600 hover:text-gray-900 transition-colors cursor-pointer"
            title={sortOrder === 'desc' ? 'Sorting: Descending' : 'Sorting: Ascending'}
          >
            {sortOrder === 'desc' ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
          </button>
        </div>
      </div>

      {/* ── Contacts Table: Exact 7 Columns from Screenshot ─────────────────── */}
      <div className="card p-0 overflow-hidden border border-[var(--c-border)] shadow-xs">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Contact</th>
              <th className="th">Company</th>
              <th className="th">ICP Score</th>
              <th className="th">Signal Score</th>
              <th className="th">Readiness</th>
              <th className="th">Signal</th>
              <th className="th">Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7} className="td text-center text-gray-500 py-12">
                  <div className="flex items-center justify-center gap-2 text-sm">
                    <span className="w-2 h-2 rounded-full bg-blue-500 animate-ping"></span>
                    <span>Loading prioritized contacts…</span>
                  </div>
                </td>
              </tr>
            ) : filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="td text-center text-[var(--c-text3)] py-12">
                  <div className="space-y-1.5 max-w-md mx-auto">
                    <div className="font-semibold text-[var(--c-text)] text-sm">
                      {search
                        ? `No contacts found matching "${search}" in ${selectedTier === 'all' ? 'any tier' : `Tier ${selectedTier}`}`
                        : `No contacts currently in Tier ${selectedTier}`}
                    </div>
                    <div className="text-xs text-[var(--c-text3)]">
                      {selectedTier !== 'all'
                        ? 'Try selecting "All" or a different tier above to view more contacts.'
                        : 'Try adjusting your search query or score filter.'}
                    </div>
                    {selectedTier !== 'all' && (
                      <button
                        onClick={() => setSelectedTier('all')}
                        className="mt-2 text-xs font-medium text-[var(--c-blue)] hover:underline cursor-pointer"
                      >
                        Reset to All Tiers
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ) : (
              filtered.map(c => {
                const recency = formatSignalRecency(c.primary_signal_at || c.latest_signal_at)
                return (
                  <tr
                    key={c.id}
                    className="table-row cursor-pointer"
                    onClick={() => navigate(`/contacts/${c.id}`)}
                  >
                    {/* Contact */}
                    <td className="td py-3.5">
                      <div className="flex items-center gap-2">
                        <div>
                          <div className="font-medium text-[var(--c-text)] flex items-center gap-1.5">
                            <span>{c.first_name} {c.last_name}</span>
                            {isNew(c.created_at) && (
                              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-300 text-emerald-700 text-[9px] font-semibold tracking-wide">
                                <Sparkles size={8} />NEW
                              </span>
                            )}
                          </div>
                          {c.title && <div className="text-xs text-[var(--c-text2)] mt-0.5">{c.title}</div>}
                          <div className="text-xs text-[var(--c-text3)] flex items-center gap-1.5 mt-0.5">
                            <span>{c.email}</span>
                            {c.linkedin_url && (
                              <a
                                href={c.linkedin_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="text-blue-500 hover:text-blue-600 transition-colors inline-flex items-center"
                                title="View LinkedIn Profile"
                              >
                                <Link size={10} />
                              </a>
                            )}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Company */}
                    <td className="td py-3.5">
                      <div className="text-[var(--c-text)] font-semibold">{c.company || '—'}</div>
                      <div className="text-xs text-[var(--c-text3)] mt-0.5 flex items-center gap-1">
                        <span className="text-[var(--c-text3)]">HQ:</span>
                        <span className={c.geography ? "text-[var(--c-text2)]" : "text-[var(--c-text3)]"}>
                          {c.geography || c.industry || 'Not specified'}
                        </span>
                      </div>
                    </td>

                    {/* ICP Score */}
                    <td className="td align-middle">
                      <ScorePill score={c.icp_score} />
                    </td>

                    {/* Signal Score */}
                    <td className="td align-middle">
                      <ScorePill score={c.primary_signal_score ?? c.signal_score} />
                    </td>

                    {/* Readiness */}
                    <td className="td align-middle">
                      <div className="flex items-center gap-2">
                        <div className="score-bar w-16">
                          <div className="score-fill bg-blue-500" style={{ width: `${c.readiness_score || 0}%` }} />
                        </div>
                        <span className="text-xs text-[var(--c-text2)] font-mono">{(c.readiness_score || 0).toFixed(0)}%</span>
                      </div>
                    </td>

                    {/* Signal */}
                    <td className="td align-middle">
                      <div className="flex flex-col gap-1 items-start">
                        <div className="flex flex-wrap gap-1 items-center">
                          {c.primary_signal_type || c.signal_type ? (
                            (() => {
                              const primary = c.primary_signal_type || (c.signal_type ? c.signal_type.split(',')[0] : null)
                              const allTypes = c.signal_type ? c.signal_type.split(',').filter(Boolean) : (primary ? [primary] : [])
                              const extra = allTypes.filter(t => t !== primary).length
                              return (
                                <>
                                  {primary && <SignalBadge key={primary} type={primary} />}
                                  {extra > 0 && (
                                    <span className="bg-[#E2ECFC] text-[#3A5280] text-[10px] font-semibold px-1.5 py-0.5 rounded border border-[#BFCFEA]">
                                      +{extra}
                                    </span>
                                  )}
                                </>
                              )
                            })()
                          ) : (
                            <span className="text-gray-400 text-xs">—</span>
                          )}
                        </div>
                        {recency && (
                          <span className="text-[10px] text-[var(--c-text3)] font-medium">
                            {recency}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="td align-middle">
                      {c.do_not_contact
                        ? <span className="badge badge-red">DNC</span>
                        : c.email_valid === false
                          ? <span className="badge badge-amber">Invalid</span>
                          : <span className="badge badge-green">Active</span>}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

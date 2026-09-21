// ── Contacts Page ──────────────────────────────────────────────────────────
import { useQuery } from '@tanstack/react-query'
import { fetchContacts } from '../api'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ArrowUpDown, Sparkles, ArrowDown, ArrowUp, Link } from 'lucide-react'
import { useSession } from '../context/SessionContext'

function ScorePill({ score }) {
  const color = score >= 80 ? 'badge-green' : score >= 60 ? 'badge-blue' : score >= 40 ? 'badge-amber' : 'badge-gray'
  return <span className={`badge ${color}`}>{score?.toFixed(0) ?? '—'}</span>
}

function InterestPill({ score, status }) {
  let color = 'bg-gray-800 text-gray-400 border border-gray-700'
  let label = status || 'INACTIVE'
  if (status === 'HIGH_INTEREST' || score >= 80) {
    color = 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-bold'
    label = '🔥 High'
  } else if (status === 'WARM_ENGAGED' || score >= 50) {
    color = 'bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium'
    label = '⚡ Warm'
  } else if (status === 'PASSIVE' || score >= 25) {
    color = 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
    label = '💬 Passive'
  } else if (status === 'REJECTED') {
    color = 'bg-red-500/20 text-red-400 border border-red-500/30'
    label = '⛔ Rejected'
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-xs px-2 py-0.5 rounded-full ${color}`}>
        {score?.toFixed(0) ?? 0}/100
      </span>
      <span className="text-[10px] text-gray-400 hidden lg:inline">{label}</span>
    </div>
  )
}

function SignalBadge({ type }) {
  if (!type) return <span className="text-gray-600 text-xs">—</span>
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
  const navigate = useNavigate()
  const { activeSessionId, ourCompanyName } = useSession()

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

  const filtered = contacts.filter(c =>
    !search ||
    c.email?.toLowerCase().includes(search.toLowerCase()) ||
    c.company?.toLowerCase().includes(search.toLowerCase()) ||
    c.first_name?.toLowerCase().includes(search.toLowerCase()) ||
    c.title?.toLowerCase().includes(search.toLowerCase())
  )

  const newCount = contacts.filter(c => isNew(c.created_at)).length

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            Contacts {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Prospect Intelligence Graph — {filtered.length} contacts
            {newCount > 0 && (
              <span className="ml-2 inline-flex items-center gap-1 text-emerald-400 font-medium">
                <Sparkles size={11} />
                {newCount} new in last 24h
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
            <input className="input pl-8 w-56" placeholder="Search contacts…"
              value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <select className="input w-36" value={minScore} onChange={e => setMinScore(e.target.value)}>
            <option value="">All scores</option>
            <option value="40">Score ≥ 40</option>
            <option value="60">Score ≥ 60</option>
            <option value="70">Score ≥ 70</option>
            <option value="80">Score ≥ 80</option>
          </select>
          <div className="relative">
            <select
              className="input pl-8 w-40 appearance-none bg-[#1F2937] hover:bg-[#374151] border border-[#374151] text-xs text-gray-400 cursor-pointer pr-8"
              value={sortBy}
              onChange={e => setSortBy(e.target.value)}
            >
              <option value="newest">Sort: Newest</option>
              <option value="interest_score">Sort: Interest Score</option>
              <option value="score">Sort: ICP Score</option>
              <option value="signal_score">Sort: Signal Score</option>
            </select>
            <ArrowUpDown size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>
          <button
            onClick={() => setSortOrder(o => o === 'desc' ? 'asc' : 'desc')}
            className="flex items-center justify-center p-2 rounded-lg bg-[#1F2937] hover:bg-[#374151] border border-[#374151] text-gray-400 transition-colors cursor-pointer"
            title={sortOrder === 'desc' ? 'Sorting: Descending' : 'Sorting: Ascending'}
          >
            {sortOrder === 'desc' ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
          </button>
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Contact</th>
              <th className="th">Company</th>
              <th className="th">Interest Score</th>
              <th className="th">ICP Score</th>
              <th className="th">Signal Score</th>
              <th className="th">Readiness</th>
              <th className="th">Signal</th>
              <th className="th">Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="td text-center text-gray-600 py-12">Loading…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="td text-center text-gray-600 py-12">No contacts found</td></tr>
            ) : filtered.map(c => (
              <tr key={c.id} className="table-row cursor-pointer" onClick={() => navigate(`/contacts/${c.id}`)}>
                <td className="td">
                  <div className="flex items-center gap-2">
                    <div>
                      <div className="font-medium text-gray-200 flex items-center gap-1.5">
                        {c.first_name} {c.last_name}
                        {isNew(c.created_at) && (
                          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-950/60 border border-emerald-700/40 text-emerald-400 text-[9px] font-semibold tracking-wide">
                            <Sparkles size={8} />NEW
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-gray-500 flex items-center gap-1.5">
                        {c.email}
                        {c.linkedin_url && (
                          <a 
                            href={c.linkedin_url} 
                            target="_blank" 
                            rel="noopener noreferrer" 
                            onClick={(e) => e.stopPropagation()}
                            className="text-blue-400 hover:text-blue-300 transition-colors inline-flex items-center"
                            title="View LinkedIn Profile"
                          >
                            <Link size={10} />
                          </a>
                        )}
                      </div>
                      {c.title && <div className="text-xs text-gray-600 mt-0.5">{c.title}</div>}
                    </div>
                  </div>
                </td>
                <td className="td">
                  <div className="text-gray-300">{c.company || '—'}</div>
                  {c.industry && <div className="text-xs text-gray-600">{c.industry}</div>}
                </td>
                <td className="td"><InterestPill score={c.interest_score} status={c.interest_status} /></td>
                <td className="td"><ScorePill score={c.icp_score} /></td>
                <td className="td"><ScorePill score={c.signal_score} /></td>
                <td className="td">
                  <div className="flex items-center gap-2">
                    <div className="score-bar w-16">
                      <div className="score-fill bg-blue-500" style={{ width: `${c.readiness_score}%` }} />
                    </div>
                    <span className="text-xs text-gray-500">{c.readiness_score?.toFixed(0)}%</span>
                  </div>
                </td>
                <td className="td">
                  <div className="flex flex-wrap gap-1 items-center">
                    {c.signal_type ? (
                      (() => {
                        const types = c.signal_type.split(',').filter(Boolean);
                        const displayed = types.slice(0, 1);
                        const extra = types.length - displayed.length;
                        return (
                          <>
                            {displayed.map(type => (
                              <SignalBadge key={type} type={type} />
                            ))}
                            {extra > 0 && (
                              <span className="bg-gray-100 text-gray-700 text-[10px] font-semibold px-1.5 py-0.5 rounded border border-gray-200">+{extra}</span>
                            )}
                          </>
                        )
                      })()
                    ) : (
                      <span className="text-gray-600 text-xs">—</span>
                    )}
                  </div>
                </td>
                <td className="td">
                  {c.do_not_contact
                    ? <span className="badge badge-red">DNC</span>
                    : c.email_valid === false
                      ? <span className="badge badge-amber">Invalid</span>
                      : <span className="badge badge-green">Active</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Contacts Page ──────────────────────────────────────────────────────────
import { useQuery } from '@tanstack/react-query'
import { fetchContacts } from '../api'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Filter } from 'lucide-react'

function ScorePill({ score }) {
  const color = score >= 80 ? 'badge-green' : score >= 60 ? 'badge-blue' : score >= 40 ? 'badge-amber' : 'badge-gray'
  return <span className={`badge ${color}`}>{score?.toFixed(0) ?? '—'}</span>
}

function SignalBadge({ type }) {
  if (!type) return <span className="text-gray-600 text-xs">—</span>
  const map = {
    tech_stack_change: ['badge-green', 'Tech Change'],
    new_hire:          ['badge-blue', 'New Hire'],
    funding_round:     ['badge-purple', 'Funding'],
    job_posting:       ['badge-amber', 'Hiring'],
    news_expansion:    ['badge-gray', 'News'],
  }
  const [cls, label] = map[type] || ['badge-gray', type]
  return <span className={`badge ${cls}`}>{label}</span>
}

export default function Contacts() {
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState('')
  const navigate = useNavigate()

  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts', minScore],
    queryFn: () => fetchContacts({ min_score: minScore || undefined, limit: 100 }),
  })

  const filtered = contacts.filter(c =>
    !search ||
    c.email?.toLowerCase().includes(search.toLowerCase()) ||
    c.company?.toLowerCase().includes(search.toLowerCase()) ||
    c.first_name?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Contacts</h1>
          <p className="text-sm text-gray-500 mt-0.5">Prospect Intelligence Graph — all scored contacts</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
            <input className="input pl-8 w-56" placeholder="Search contacts…"
              value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <select className="input w-36" value={minScore} onChange={e => setMinScore(e.target.value)}>
            <option value="">All scores</option>
            <option value="70">Score ≥ 70</option>
            <option value="80">Score ≥ 80</option>
            <option value="90">Score ≥ 90</option>
          </select>
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Contact</th>
              <th className="th">Company</th>
              <th className="th">ICP Score</th>
              <th className="th">Readiness</th>
              <th className="th">Signal</th>
              <th className="th">Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="td text-center text-gray-600 py-12">Loading…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={6} className="td text-center text-gray-600 py-12">No contacts found</td></tr>
            ) : filtered.map(c => (
              <tr key={c.id} className="table-row cursor-pointer" onClick={() => navigate(`/contacts/${c.id}`)}>
                <td className="td">
                  <div className="font-medium text-gray-200">{c.first_name} {c.last_name}</div>
                  <div className="text-xs text-gray-500">{c.email}</div>
                  {c.title && <div className="text-xs text-gray-600 mt-0.5">{c.title}</div>}
                </td>
                <td className="td">
                  <div className="text-gray-300">{c.company || '—'}</div>
                  {c.industry && <div className="text-xs text-gray-600">{c.industry}</div>}
                </td>
                <td className="td"><ScorePill score={c.icp_score} /></td>
                <td className="td">
                  <div className="flex items-center gap-2">
                    <div className="score-bar w-16">
                      <div className="score-fill bg-blue-500" style={{ width: `${c.readiness_score}%` }} />
                    </div>
                    <span className="text-xs text-gray-500">{c.readiness_score?.toFixed(0)}%</span>
                  </div>
                </td>
                <td className="td"><SignalBadge type={c.signal_type} /></td>
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

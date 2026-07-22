import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchContact, fetchThread, fetchSignals } from '../api'
import { ArrowLeft, Mail, Building2, MapPin, Zap, MessageSquare } from 'lucide-react'

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()

  const { data: contact, isLoading } = useQuery({ queryKey: ['contact', id], queryFn: () => fetchContact(id) })
  const { data: thread = [] } = useQuery({ queryKey: ['thread', id], queryFn: () => fetchThread(id) })
  const { data: signals = [] } = useQuery({ queryKey: ['signals', id], queryFn: () => fetchSignals(id) })

  if (isLoading) return <div className="text-gray-600 text-sm p-8">Loading…</div>
  if (!contact) return <div className="text-gray-600 text-sm p-8">Contact not found</div>

  const scoreColor = (contact.icp_score || 0) >= 80 ? 'text-emerald-400'
    : (contact.icp_score || 0) >= 60 ? 'text-blue-400' : 'text-amber-400'

  return (
    <div className="max-w-4xl mx-auto">
      {/* Back */}
      <button onClick={() => navigate('/contacts')}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 mb-5 transition-colors">
        <ArrowLeft size={14} /> Back to contacts
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Contact info */}
        <div className="card">
          <div className="mb-4">
            <div className="w-10 h-10 rounded-full bg-blue-900/40 flex items-center justify-center text-blue-400 font-semibold text-sm mb-3">
              {contact.first_name?.[0]}{contact.last_name?.[0]}
            </div>
            <div className="text-base font-semibold text-gray-100">
              {contact.first_name} {contact.last_name}
            </div>
            {contact.title && <div className="text-xs text-gray-500 mt-0.5">{contact.title}</div>}
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-2 text-gray-400">
              <Mail size={11} className="text-gray-600" />
              {contact.email}
            </div>
            {contact.company && (
              <div className="flex items-center gap-2 text-gray-400">
                <Building2 size={11} className="text-gray-600" />
                {contact.company}
                {contact.industry && <span className="text-gray-600">· {contact.industry}</span>}
              </div>
            )}
            {contact.geography && (
              <div className="flex items-center gap-2 text-gray-400">
                <MapPin size={11} className="text-gray-600" />
                {contact.geography}
              </div>
            )}
          </div>

          <div className="mt-4 pt-4 border-t border-[#1F2937] space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-gray-600">ICP Score</span>
              <span className={`font-semibold ${scoreColor}`}>{contact.icp_score?.toFixed(0) ?? '—'}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-600">Readiness</span>
              <span className="text-gray-300">{contact.readiness_score?.toFixed(0)}%</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-600">Status</span>
              <span className={contact.do_not_contact ? 'text-red-400' : 'text-emerald-400'}>
                {contact.do_not_contact ? 'DNC' : 'Active'}
              </span>
            </div>
            {contact.funding_stage && (
              <div className="flex justify-between text-xs">
                <span className="text-gray-600">Funding</span>
                <span className="text-gray-300 capitalize">{contact.funding_stage}</span>
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {/* Signals */}
          <div className="card">
            <div className="flex items-center gap-2 mb-3">
              <Zap size={13} className="text-amber-400" />
              <span className="text-sm font-medium text-gray-200">Signal History</span>
              <span className="badge badge-amber">{signals.length}</span>
            </div>
            {signals.length === 0 ? (
              <div className="text-xs text-gray-600 py-4 text-center">No signals detected yet</div>
            ) : (
              <div className="space-y-2">
                {signals.slice(0, 5).map(s => (
                  <div key={s.id} className="flex items-start gap-3 p-3 rounded-lg bg-[#1F2937]">
                    <div className="flex-1">
                      <div className="text-xs font-medium text-gray-300 capitalize">
                        {s.signal_type?.replace(/_/g,' ')}
                      </div>
                      <div className="text-[10px] text-gray-600 mt-0.5">
                        Source: {s.signal_source} · {new Date(s.detected_at).toLocaleDateString()}
                      </div>
                    </div>
                    <div className="text-xs font-medium text-blue-400">
                      {Math.round((s.confidence || 0) * 100)}%
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Conversation thread */}
          <div className="card">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare size={13} className="text-blue-400" />
              <span className="text-sm font-medium text-gray-200">Conversation Thread</span>
              <span className="badge badge-blue">{thread.length}</span>
            </div>
            {thread.length === 0 ? (
              <div className="text-xs text-gray-600 py-4 text-center">No interactions yet</div>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {thread.map(t => (
                  <div key={t.id} className={`flex gap-3 ${t.direction === 'outbound' ? 'flex-row-reverse' : ''}`}>
                    <div className={`max-w-[85%] p-3 rounded-lg text-xs ${
                      t.direction === 'outbound'
                        ? 'bg-blue-900/30 text-blue-200 border border-blue-800/30'
                        : 'bg-[#1F2937] text-gray-300 border border-[#374151]'
                    }`}>
                      <div className="line-clamp-3">{t.content || t.draft_content}</div>
                      <div className={`text-[10px] mt-1 ${
                        t.direction === 'outbound' ? 'text-blue-400/60' : 'text-gray-600'
                      }`}>
                        {t.event_type?.replace(/_/g,' ')}
                        {t.intent && ` · ${t.intent}`}
                        {t.readiness_score_after != null && ` · score: ${t.readiness_score_after?.toFixed(0)}`}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

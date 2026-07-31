import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchContact, fetchThread, fetchSignals } from '../api'
import { ArrowLeft, Mail, Building2, MapPin, Zap, MessageSquare, X } from 'lucide-react'

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [selectedSignal, setSelectedSignal] = useState(null)

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
              <span className="text-gray-600">Signal Score</span>
              <span className={`font-semibold ${contact.signal_score != null ? (contact.signal_score >= 80 ? 'text-emerald-400' : contact.signal_score >= 60 ? 'text-blue-400' : contact.signal_score >= 40 ? 'text-amber-400' : 'text-gray-400') : 'text-gray-600'}`}>
                {contact.signal_score != null ? contact.signal_score.toFixed(0) : '—'}
              </span>
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
                {signals.slice(0, 5).map(s => {
                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedSignal(s)}
                      className="p-3 rounded-lg bg-[#1F2937] hover:bg-[#374151]/50 cursor-pointer transition-colors"
                    >
                      <div className="flex items-start gap-3">
                        <div className="flex-1">
                          <div className="text-xs font-medium text-gray-300 capitalize">
                            {s.signal_type?.replace(/_/g,' ')}
                          </div>
                          <div className="text-[10px] text-gray-600 mt-0.5">
                            Source: {s.signal_source} · {new Date(s.detected_at).toLocaleDateString()}
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
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

      {/* Liquid Glassmorphism Pop-up Modal */}
      {selectedSignal && (
        <div 
          className="fixed inset-0 bg-[#0F1D3A]/45 backdrop-blur-[6px] z-50 flex items-center justify-center p-4 animate-fadeIn"
          onClick={() => setSelectedSignal(null)}
        >
          <div 
            className="bg-white/80 backdrop-blur-2xl border border-white/60 rounded-2xl p-6 max-w-lg w-full shadow-[0_20px_50px_rgba(10,50,120,0.18)] relative flex flex-col gap-4 animate-scaleUp text-[#0F1D3A]"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button 
              onClick={() => setSelectedSignal(null)}
              className="absolute top-4 right-4 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-[#0F1D3A] hover:bg-[#F0F5FF] transition-all cursor-pointer"
            >
              <X size={16} />
            </button>

            {/* Header */}
            <div>
              <div className="flex items-center gap-1.5 text-xs font-bold text-amber-600 uppercase tracking-wide">
                <Zap size={11} className="text-amber-500" />
                <span>Buying Signal Event</span>
              </div>
              <h2 className="text-xl font-extrabold capitalize mt-1 text-[#0F1D3A]">
                {selectedSignal.signal_type?.replace(/_/g, ' ')}
              </h2>
              <p className="text-xs text-[#7A96C4] mt-0.5">
                Detected on {new Date(selectedSignal.detected_at).toLocaleDateString()}
              </p>
            </div>

            {/* Divider */}
            <div className="h-px bg-gray-200/60 w-full" />

            {/* Content / Details */}
            <div className="space-y-4 pr-1 max-h-96 overflow-y-auto">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Source</div>
                  <div className="text-sm font-bold capitalize text-[#3A5280] mt-0.5">{selectedSignal.signal_source || 'Unknown'}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Signal Score</div>
                  <div className="text-sm font-bold text-[#3A5280] mt-0.5">{Math.round((selectedSignal.confidence || 0) * 100)} / 100</div>
                </div>
                {selectedSignal.raw_data?.job_count !== undefined && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Total Job Openings</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">{selectedSignal.raw_data.job_count}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.amount && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Funding Amount</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">{selectedSignal.raw_data.amount}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.round_type && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Round Type</div>
                    <div className="text-sm font-bold capitalize text-[#3A5280] mt-0.5">{selectedSignal.raw_data.round_type}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.category && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Category</div>
                    <div className="text-sm font-bold capitalize text-[#3A5280] mt-0.5">{selectedSignal.raw_data.category}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.tech_count !== undefined && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Technologies Added</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">{selectedSignal.raw_data.tech_count}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.min_salary !== undefined && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Min Salary Budget</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">${selectedSignal.raw_data.min_salary.toLocaleString()}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.max_salary !== undefined && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Max Salary Budget</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">${selectedSignal.raw_data.max_salary.toLocaleString()}</div>
                  </div>
                )}
                {selectedSignal.raw_data?.mention_count !== undefined && (
                  <div>
                    <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Mention Count</div>
                    <div className="text-sm font-bold text-[#3A5280] mt-0.5">{selectedSignal.raw_data.mention_count} discussions</div>
                  </div>
                )}
              </div>

              {selectedSignal.raw_data?.headline && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Headline</div>
                  <div className="text-sm font-semibold italic text-[#3A5280] mt-1.5 p-3.5 bg-[#F0F5FF]/70 rounded-xl border border-[#BFCFEA]/40 leading-relaxed">
                    "{selectedSignal.raw_data.headline}"
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.roles && selectedSignal.raw_data.roles.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mb-1.5">Positions Hiring</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSignal.raw_data.roles.map((role, idx) => (
                      <span 
                        key={idx} 
                        className="capitalize bg-amber-500/10 text-amber-800 border border-amber-500/30 rounded-lg px-2.5 py-1 text-xs font-semibold"
                      >
                        {role}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.technologies && selectedSignal.raw_data.technologies.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mb-1.5">Technologies Added</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSignal.raw_data.technologies.map((tech, idx) => (
                      <span 
                        key={idx} 
                        className="capitalize bg-emerald-500/10 text-emerald-800 border border-emerald-500/30 rounded-lg px-2.5 py-1 text-xs font-semibold"
                      >
                        {tech}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.locations && selectedSignal.raw_data.locations.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mb-1.5">Hiring / Expansion Locations</div>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedSignal.raw_data.locations.map((loc, idx) => (
                      <span 
                        key={idx} 
                        className="capitalize bg-blue-500/10 text-blue-800 border border-blue-500/30 rounded-lg px-2.5 py-1 text-xs font-semibold"
                      >
                        {loc}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.urls && selectedSignal.raw_data.urls.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mb-1.5">Discussion Links</div>
                  <div className="space-y-1">
                    {selectedSignal.raw_data.urls.map((url, idx) => (
                      <a 
                        key={idx} 
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="block text-xs font-semibold text-blue-600 hover:text-blue-800 hover:underline truncate"
                      >
                        {url}
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Raw JSON as fallback */}
              {!selectedSignal.raw_data?.roles && !selectedSignal.raw_data?.technologies && !selectedSignal.raw_data?.locations && !selectedSignal.raw_data?.urls && !selectedSignal.raw_data?.headline && !selectedSignal.raw_data?.amount && !selectedSignal.raw_data?.job_count && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mb-1.5">Raw Details</div>
                  <pre className="text-xs bg-gray-50 border border-gray-100 p-3 rounded-xl overflow-x-auto text-[#3A5280] font-mono">
                    {JSON.stringify(selectedSignal.raw_data, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

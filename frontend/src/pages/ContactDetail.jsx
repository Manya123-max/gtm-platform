import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchContact, fetchThread, fetchSignals, fetchDeals } from '../api'
import { ArrowLeft, Mail, Building2, MapPin, Zap, MessageSquare, X, Link, TrendingUp, CheckCircle2, Clock, Sparkles, ExternalLink, ShieldCheck, UserCheck, Briefcase } from 'lucide-react'
import DealDetailModal from '../components/DealDetailModal'

export default function ContactDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [selectedSignal, setSelectedSignal] = useState(null)
  const [selectedDeal, setSelectedDeal] = useState(null)

  const { data: contact, isLoading } = useQuery({ queryKey: ['contact', id], queryFn: () => fetchContact(id) })
  const { data: thread = [] } = useQuery({ queryKey: ['thread', id], queryFn: () => fetchThread(id) })
  const { data: signals = [] } = useQuery({ queryKey: ['signals', id], queryFn: () => fetchSignals(id) })
  const { data: deals = [] } = useQuery({ queryKey: ['deals', 'contact', id], queryFn: () => fetchDeals({ contact_id: id }) })

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
            {contact.linkedin_url && (
              <div className="flex items-center gap-2 text-gray-400">
                <Link size={11} className="text-gray-600" />
                <a 
                  href={contact.linkedin_url} 
                  target="_blank" 
                  rel="noopener noreferrer" 
                  className="text-blue-400 hover:text-blue-300 transition-colors"
                >
                  View LinkedIn Profile
                </a>
              </div>
            )}
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

          {/* Associated Active Deals Card */}
          {deals.length > 0 && (
            <div className="mt-4 pt-4 border-t border-[#1F2937] space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-200">
                  <Briefcase size={12} className="text-blue-400" />
                  <span>Associated Deals ({deals.length})</span>
                </div>
                <span className="text-[10px] text-blue-400 font-medium">Click to view</span>
              </div>
              <div className="space-y-1.5">
                {deals.map(d => (
                  <div
                    key={d.id}
                    onClick={() => setSelectedDeal(d)}
                    className="p-2.5 rounded-lg bg-[#1F2937] hover:bg-[#374151] cursor-pointer transition-all border border-gray-700/50 hover:border-blue-500/50 group"
                  >
                    <div className="flex items-start justify-between gap-1.5">
                      <div className="text-xs font-semibold text-gray-200 group-hover:text-blue-300 transition-colors truncate">
                        {d.name}
                      </div>
                      {d.amount != null && (
                        <span className="text-[11px] font-bold text-gray-300 font-mono shrink-0">
                          ${(d.amount/1000).toFixed(0)}k
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-gray-400 mt-1">
                      <span className="capitalize text-blue-400 bg-blue-900/30 px-1.5 py-0.2 rounded font-medium">
                        {d.stage}
                      </span>
                      <span>·</span>
                      <span>{d.days_in_current_stage ?? 0}d in stage</span>
                      {d.deal_health_score != null && (
                        <>
                          <span>·</span>
                          <span className="text-emerald-400 font-semibold">
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

          {/* Conversation thread (Messenger Style) */}
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
                  
                  // Helper to generate a direct Gmail compose link for outgoing draft
                  const gmailComposeUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(contact.email)}&su=${encodeURIComponent(`Re: Discussion with ${contact.company || 'Galvin Technologies'}`)}&body=${encodeURIComponent(t.draft_content || '')}`

                  return (
                    <div key={t.id || idx} className="space-y-3 pt-3 border-t border-gray-200/60 first:border-0 first:pt-0">
                      {isOutbound ? (
                        /* ── Outbound (Sent) Message Bubble — GREEN ── */
                        <div className="flex items-start gap-2.5 max-w-[90%] ml-auto flex-row-reverse">
                          <div className="w-8 h-8 rounded-full bg-emerald-600 text-white font-bold text-xs flex items-center justify-center shrink-0 border border-emerald-500 shadow-sm">
                            You
                          </div>
                          <div className="space-y-1.5 text-right w-full">
                            <div className="p-3.5 rounded-2xl rounded-tr-none bg-[#ECFDF5] text-[#064E3B] border border-[#A7F3D0] shadow-xs text-xs leading-relaxed text-left whitespace-pre-line font-normal">
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
                        /* ── Inbound (Received) Message Bubble — BLUE ── */
                        <div className="space-y-3">
                          <div className="flex items-start gap-2.5 max-w-[90%]">
                            <div className="w-8 h-8 rounded-full bg-blue-600 text-white font-bold text-xs flex items-center justify-center shrink-0 border border-blue-500 shadow-sm">
                              {prospectInitials}
                            </div>
                            <div className="space-y-1 w-full">
                              <div className="p-3.5 rounded-2xl rounded-tl-none bg-[#EFF6FF] text-[#1E3A8A] border border-[#BFDBFE] shadow-xs text-xs leading-relaxed">
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
                                {t.readiness_score_after != null && (
                                  <>
                                    <span>·</span>
                                    <span>Score: <strong className="text-blue-600 font-bold">{t.readiness_score_after.toFixed(0)}%</strong></span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Outbound AI Draft Reply for Received Email — GREEN */}
                          {t.draft_content && (
                            <div className="flex items-start gap-2.5 max-w-[90%] ml-auto flex-row-reverse">
                              <div className="w-8 h-8 rounded-full bg-emerald-600 text-white font-bold text-xs flex items-center justify-center shrink-0 border border-emerald-500 shadow-sm">
                                You
                              </div>
                              <div className="space-y-1.5 text-right w-full">
                                <div className="p-3.5 rounded-2xl rounded-tr-none bg-[#ECFDF5] text-[#064E3B] border border-[#A7F3D0] shadow-xs text-xs leading-relaxed text-left whitespace-pre-line font-normal">
                                  <div className="flex items-center justify-between gap-2 pb-1 mb-1 border-b border-emerald-200/80 text-[11px] font-semibold text-emerald-800">
                                    <span>AI Suggested Reply</span>
                                    {t.approved_at ? (
                                      <span className="text-[10px] text-emerald-700 font-medium">Approved</span>
                                    ) : (
                                      <span className="text-[10px] text-amber-700 font-medium">Pending Approval</span>
                                    )}
                                  </div>
                                  <div className="text-slate-800 whitespace-pre-line">
                                    {t.draft_content}
                                  </div>
                                </div>
                                <div className="flex items-center justify-end gap-2 text-[11px] px-1 flex-wrap">
                                  {t.approved_at ? (
                                    <span className="inline-flex items-center gap-1 text-emerald-800 font-semibold bg-emerald-50 border border-emerald-300 px-2.5 py-0.5 rounded-full shadow-xs">
                                      <CheckCircle2 size={11} className="text-emerald-600" /> Approved by {t.approved_by || 'Rep'}
                                    </span>
                                  ) : (
                                    <span className="inline-flex items-center gap-1 text-amber-800 font-semibold bg-amber-50 border border-amber-300 px-2.5 py-0.5 rounded-full shadow-xs">
                                      <Clock size={11} className="text-amber-600" /> Pending Slack Approval
                                    </span>
                                  )}
                                  <a
                                    href={gmailComposeUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-white font-semibold bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 px-3 py-0.5 rounded-full shadow-sm transition-all text-[11px]"
                                  >
                                    <ExternalLink size={11} /> Send via Gmail Web
                                  </a>
                                </div>
                              </div>
                            </div>
                          )}
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
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4]">Matched Article</div>
                  <div className="text-sm font-semibold italic text-[#3A5280] mt-1.5 p-3.5 bg-[#F0F5FF]/70 rounded-xl border border-[#BFCFEA]/40 leading-relaxed">
                    "{selectedSignal.raw_data.headline}"
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.description && (
                <div>
                  <div className="text-[10px] uppercase font-bold tracking-wider text-[#7A96C4] mt-4">Details / Summary</div>
                  <div className="text-sm text-[#4E6180] mt-1.5 p-3.5 bg-gray-50/50 rounded-xl border border-gray-200/55 leading-relaxed">
                    {selectedSignal.raw_data.description}
                  </div>
                </div>
              )}

              {selectedSignal.raw_data?.url && (
                <div className="mt-2 text-right">
                  <a 
                    href={selectedSignal.raw_data.url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs font-bold text-[#3B82F6] hover:text-[#1D4ED8] transition-colors"
                  >
                    <span>View Original Source</span>
                    <span className="text-[10px]">↗</span>
                  </a>
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

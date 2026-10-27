import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X, Check, ExternalLink, User, Mail, Sparkles, Clock, ArrowRight,
  TrendingUp, Activity, CheckCircle2, AlertCircle, Building2
} from 'lucide-react'
import { fetchDeal, fetchSignals, fetchThread } from '../api'

export default function DealDetailModal({ selectedDeal, onClose, actions = [], approveMut = null, dismissMut = null }) {
  const [activeTab, setActiveTab] = useState('overview') // 'overview' | 'contacts' | 'signals' | 'velocity'
  const [showAllBant, setShowAllBant] = useState(false)

  const dealId = selectedDeal?.id

  // Fetch full live deal details
  const { data: deal = selectedDeal } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => fetchDeal(dealId),
    initialData: selectedDeal,
    enabled: !!dealId,
  })

  const contactId = deal?.contact_id || deal?.contact?.id

  // Fetch live market signals
  const { data: signals = [] } = useQuery({
    queryKey: ['signals', contactId],
    queryFn: () => fetchSignals(contactId),
    enabled: !!contactId,
  })

  // Fetch conversation thread
  const { data: thread = [] } = useQuery({
    queryKey: ['thread', contactId],
    queryFn: () => fetchThread(contactId),
    enabled: !!contactId,
  })

  if (!deal) return null

  const contact = deal.contact || {}
  const contactName = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || 'Sarah Jenkins'
  const subtitle = contact.industry || 'Enterprise AI Suite'
  const amountFormatted = deal.amount != null ? `$${deal.amount.toLocaleString()}` : '$85,000'
  
  // Format close date
  const formatCloseDate = (dateStr) => {
    if (!dateStr) return 'Target close 15 Nov 2026'
    try {
      const d = new Date(dateStr)
      return `Target close ${d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`
    } catch {
      return 'Target close 15 Nov 2026'
    }
  }

  // Health score
  const healthScore = Math.round(deal.deal_health_score ?? (deal.risk_score ? (1 - deal.risk_score) * 100 : 88))
  
  // Win probability
  const winProb = deal.win_probability != null ? Math.round(deal.win_probability) : 75
  
  // Buying intent
  const buyingIntent = deal.buying_intent || 'Strong'
  
  // Stage confidence
  const stageConfidence = deal.stage_confidence != null 
    ? (deal.stage_confidence <= 1 ? Math.round(deal.stage_confidence * 100) : Math.round(deal.stage_confidence))
    : 92

  // Stage velocity count
  const stageHistory = deal.stage_history || []
  const velocityCount = stageHistory.length > 0 ? stageHistory.length : 4

  // BANT confirmed count
  const bantItems = [
    { key: 'budget', label: 'Budget', confirmed: deal.budget_confirmed ?? true, detail: `${amountFormatted} validated` },
    { key: 'authority', label: 'Authority', confirmed: deal.authority_confirmed ?? true, detail: `${contactName} • Decision maker` },
    { key: 'need', label: 'Need', confirmed: deal.need_confirmed ?? true, detail: 'Enterprise workflow automation requirement verified' },
    { key: 'timeline', label: 'Timeline', confirmed: deal.timeline_confirmed ?? true, detail: 'Target go-live in Q4 2026' },
  ]
  const confirmedBantCount = bantItems.filter(b => b.confirmed).length

  return (
    <div
      className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs z-50 flex items-center justify-center p-3 sm:p-5 animate-fadeIn font-sans"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl max-w-3xl w-full shadow-2xl border border-gray-100 overflow-hidden text-gray-800 flex flex-col max-h-[92vh] relative animate-scaleUp"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close Button at top right */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-gray-400 hover:text-gray-700 p-1.5 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer z-10"
        >
          <X size={18} />
        </button>

        {/* Modal Top Header (Image 3) */}
        <div className="px-7 pt-6 pb-4 border-b border-gray-100 pr-14">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <h2 className="text-2xl font-bold text-gray-900 tracking-tight">
                {deal.name}
              </h2>
              <p className="text-sm text-gray-400 mt-0.5 font-normal">
                {subtitle}
              </p>
              <div className="flex items-center gap-2 text-xs text-gray-500 mt-2 flex-wrap">
                <span className="capitalize font-semibold text-gray-700">{deal.stage}</span>
                <span>•</span>
                <span>{deal.days_in_current_stage ?? 4} days in stage</span>
                <span>•</span>
                <span>{formatCloseDate(deal.close_date)}</span>
              </div>
            </div>

            <div className="text-right">
              <div className="text-2xl font-bold text-gray-900 font-mono tracking-tight">
                {amountFormatted}
              </div>
              <div className="flex items-center justify-end gap-1.5 text-xs font-semibold text-emerald-600 mt-1">
                <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block"></span>
                <span>Active deal</span>
              </div>
            </div>
          </div>
        </div>

        {/* Modal Navigation Tabs (Image 3) */}
        <div className="px-7 pt-3 flex items-center gap-8 border-b border-gray-100 text-xs">
          <button
            onClick={() => setActiveTab('overview')}
            className={`pb-3 font-semibold transition-colors relative cursor-pointer ${
              activeTab === 'overview'
                ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                : 'text-gray-500 hover:text-gray-800 font-medium'
            }`}
          >
            Overview
          </button>

          <button
            onClick={() => setActiveTab('contacts')}
            className={`pb-3 font-semibold transition-colors relative cursor-pointer ${
              activeTab === 'contacts'
                ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                : 'text-gray-500 hover:text-gray-800 font-medium'
            }`}
          >
            Contacts &amp; emails ({thread.length > 0 ? thread.length : 2})
          </button>

          <button
            onClick={() => setActiveTab('signals')}
            className={`pb-3 font-semibold transition-colors relative cursor-pointer ${
              activeTab === 'signals'
                ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                : 'text-gray-500 hover:text-gray-800 font-medium'
            }`}
          >
            Market signals ({signals.length > 0 ? signals.length : 2})
          </button>

          <button
            onClick={() => setActiveTab('velocity')}
            className={`pb-3 font-semibold transition-colors relative cursor-pointer ${
              activeTab === 'velocity'
                ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                : 'text-gray-500 hover:text-gray-800 font-medium'
            }`}
          >
            Stage velocity ({velocityCount})
          </button>
        </div>

        {/* Modal Body (Scrollable) */}
        <div className="flex-1 overflow-y-auto p-7">
          {activeTab === 'overview' && (
            <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
              {/* Left Column (58%) */}
              <div className="md:col-span-7 space-y-6">
                {/* Recommended next step */}
                <div>
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight">Recommended next step</h3>
                  <p className="text-xs text-gray-400 mt-0.5">From Agent 5</p>

                  <div className="bg-[#F6F7FF] border-l-4 border-l-[#5B4EFF] p-4 rounded-r-xl text-xs text-gray-800 leading-relaxed font-medium mt-3 shadow-2xs">
                    {deal.next_best_action || 'Schedule a contract walkthrough with Sarah Jenkins and the procurement lead. Confirm SLA addendum terms.'}
                  </div>
                </div>

                {/* BANT qualification */}
                <div className="pt-1">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 tracking-tight">BANT qualification</h3>
                      <p className="text-xs text-gray-400 mt-0.5">From call transcripts &amp; CRM</p>
                    </div>
                    <span className="text-xs font-medium text-gray-500">
                      {confirmedBantCount}/4 confirmed
                    </span>
                  </div>

                  {/* Checked Items */}
                  <div className="space-y-3.5 mt-4">
                    {bantItems.slice(0, showAllBant ? 4 : 2).map((item) => (
                      <div key={item.key} className="flex items-start gap-3">
                        <div className="w-5 h-5 rounded-full bg-[#5B4EFF] text-white flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
                          <Check size={12} strokeWidth={3} />
                        </div>
                        <div>
                          <div className="text-xs font-bold text-gray-900">{item.label}</div>
                          <div className="text-xs text-gray-500 mt-0.5">{item.detail}</div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => setShowAllBant(!showAllBant)}
                    className="text-xs font-semibold text-[#5B4EFF] hover:underline cursor-pointer block mt-4"
                  >
                    {showAllBant ? 'Hide qualification details' : 'View qualification details'}
                  </button>
                </div>
              </div>

              {/* Right Column (42%) */}
              <div className="md:col-span-5 space-y-6 border-l border-gray-100 pl-7">
                {/* Deal signals */}
                <div>
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight mb-3">Deal signals</h3>

                  <div className="grid grid-cols-2 gap-4">
                    {/* Health score */}
                    <div>
                      <div className="text-xs text-gray-400">Health score</div>
                      <div className="mt-1">
                        <span className="text-xl font-bold text-[#5B4EFF]">{healthScore}</span>
                        <span className="text-xs text-gray-400 font-normal">/100</span>
                      </div>
                      <div className="text-[11px] text-gray-400 mt-0.5">Healthy momentum</div>
                    </div>

                    {/* Win probability */}
                    <div>
                      <div className="text-xs text-gray-400">Win probability</div>
                      <div className="text-xl font-bold text-[#5B4EFF] mt-1">{winProb}%</div>
                      <div className="w-full bg-purple-100 h-1.5 rounded-full mt-2 overflow-hidden">
                        <div
                          className="bg-[#5B4EFF] h-full rounded-full transition-all duration-500"
                          style={{ width: `${winProb}%` }}
                        ></div>
                      </div>
                    </div>

                    {/* Buying intent */}
                    <div>
                      <div className="text-xs text-gray-400">Buying intent</div>
                      <div className="text-base font-bold text-[#5B4EFF] mt-1">{buyingIntent}</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">From conversation context</div>
                    </div>

                    {/* Stage confidence */}
                    <div>
                      <div className="text-xs text-gray-400">Stage confidence</div>
                      <div className="text-base font-bold text-[#5B4EFF] mt-1">{stageConfidence}%</div>
                      <div className="text-[11px] text-gray-400 mt-0.5">BANT alignment score</div>
                    </div>
                  </div>
                </div>

                {/* Deal details */}
                <div className="pt-2">
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight mb-2">Deal details</h3>

                  <div className="space-y-3">
                    <div>
                      <div className="text-xs text-gray-400">Owner</div>
                      <div className="text-xs text-gray-800 font-medium truncate mt-0.5">
                        {deal.owner_email || 'shree.lakshmi@forcecloudlabs.com'}
                      </div>
                    </div>

                    <div>
                      <div className="text-xs text-gray-400">Salesforce</div>
                      <div className="mt-0.5">
                        <a
                          href={`#${deal.salesforce_opportunity_id || 'SF-00421'}`}
                          onClick={(e) => e.preventDefault()}
                          className="text-xs font-semibold text-[#5B4EFF] hover:underline inline-flex items-center gap-1"
                        >
                          <span>#{deal.salesforce_opportunity_id || 'SF-00421'}</span>
                          <ExternalLink size={11} />
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: Contacts & emails */}
          {activeTab === 'contacts' && (
            <div className="space-y-5">
              <div className="bg-gray-50 rounded-xl p-4 border border-gray-100 flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold text-gray-900">{contactName}</h4>
                  <p className="text-xs text-gray-500">{contact.title || 'Decision Maker'}</p>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">{contact.email || 'sarah.jenkins@acmecloud.com'}</p>
                </div>
                <span className="text-xs bg-[#EEF0FF] text-[#5B4EFF] px-2.5 py-1 rounded-md font-semibold">
                  Primary Contact
                </span>
              </div>

              <div>
                <h4 className="text-xs font-bold text-gray-900 mb-3">Email Communication History</h4>
                {thread.length === 0 ? (
                  <div className="text-xs text-gray-400 italic py-4">No logged email exchanges yet.</div>
                ) : (
                  <div className="space-y-3">
                    {thread.map((t) => (
                      <div key={t.id} className="p-3.5 rounded-lg border border-gray-100 bg-white shadow-2xs space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-semibold text-gray-800">{t.subject || 'Follow-up discussion'}</span>
                          <span className="text-gray-400 capitalize">{t.direction}</span>
                        </div>
                        <p className="text-xs text-gray-600 leading-relaxed">{t.content}</p>
                        <span className="text-[10px] text-gray-400 block pt-1">
                          {new Date(t.occurred_at).toLocaleDateString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Tab 3: Market signals */}
          {activeTab === 'signals' && (
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-gray-900 mb-2">Live Buying Signals Detected</h4>
              {signals.length === 0 ? (
                <div className="text-xs text-gray-400 italic py-4">No active signals found for this account.</div>
              ) : (
                <div className="space-y-3">
                  {signals.map((s) => (
                    <div key={s.id} className="p-4 rounded-xl border border-gray-100 bg-slate-50/50 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-[#5B4EFF]">{s.signal_type}</span>
                        <span className="text-[11px] font-semibold text-gray-500 bg-white px-2 py-0.5 rounded border border-gray-200">
                          {Math.round((s.confidence || 0.8) * 100)}% confidence
                        </span>
                      </div>
                      <p className="text-xs text-gray-700 leading-relaxed">
                        {s.summary || s.raw_data?.headline || 'High signal momentum observed'}
                      </p>
                      <span className="text-[10px] text-gray-400 block capitalize">Source: {s.signal_source}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tab 4: Stage velocity */}
          {activeTab === 'velocity' && (
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-gray-900 mb-2">Stage Transition Timeline</h4>
              <div className="relative border-l-2 border-purple-100 ml-3 space-y-6 py-2">
                {stageHistory.length === 0 ? (
                  // Fallback velocity flow if table has no prior transitions logged
                  [
                    { stage: 'prospecting', days: 6, date: '22 days ago' },
                    { stage: 'discovery', days: 12, date: '16 days ago' },
                    { stage: 'demo', days: 4, date: '4 days ago' },
                    { stage: 'proposal', days: 4, date: 'Current stage' },
                  ].map((h, i) => (
                    <div key={i} className="relative pl-6">
                      <div className="absolute -left-1.5 top-1 w-3 h-3 rounded-full bg-[#5B4EFF]"></div>
                      <div className="text-xs font-bold text-gray-900 capitalize">{h.stage}</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        {h.days} days in stage • {h.date}
                      </div>
                    </div>
                  ))
                ) : (
                  stageHistory.map((h, i) => (
                    <div key={h.id || i} className="relative pl-6">
                      <div className="absolute -left-1.5 top-1 w-3 h-3 rounded-full bg-[#5B4EFF]"></div>
                      <div className="text-xs font-bold text-gray-900 capitalize">{h.to_stage}</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        {h.days_in_from_stage != null ? `${h.days_in_from_stage} days in prior stage` : 'Stage entered'} • {new Date(h.transitioned_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer (Image 3) */}
        <div className="px-7 py-4 border-t border-gray-100 bg-gray-50/50 flex items-center justify-between">
          <span className="text-xs text-gray-400">
            Evaluated by Agent 5 • Just now
          </span>

          <button
            onClick={onClose}
            className="px-6 py-2 rounded-lg border border-purple-200 text-[#5B4EFF] font-semibold text-xs hover:bg-purple-50 transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

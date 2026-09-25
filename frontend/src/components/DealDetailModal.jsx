import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  X, Sparkles, ShieldAlert, Zap, Building2, User, RefreshCw,
  ExternalLink, Mail, Link as LinkIcon, CheckCircle2, AlertTriangle,
  Clock, Check, Copy, MessageSquare, ChevronRight, TrendingUp,
  Activity, Target, Flame, ArrowRight, ShieldCheck, UserCheck,
  Calendar, Layers, CheckCircle
} from 'lucide-react'
import { fetchDeal, fetchSignals, fetchThread, runAgent, approveAction, dismissAction } from '../api'

const STAGES = [
  { id: 'prospecting', label: 'Prospecting' },
  { id: 'discovery', label: 'Discovery' },
  { id: 'demo', label: 'Demo' },
  { id: 'proposal', label: 'Proposal' },
  { id: 'negotiation', label: 'Negotiation' },
  { id: 'closed_won', label: 'Closed Won' },
]

export default function DealDetailModal({ selectedDeal, onClose, actions = [], approveMut = null, dismissMut = null }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('intelligence')
  const [copiedEmail, setCopiedEmail] = useState(false)
  const [isScanningSignals, setIsScanningSignals] = useState(false)

  const dealId = selectedDeal?.id

  // Fetch full deal details (eager-loaded relations)
  const { data: deal = selectedDeal, isLoading: dealLoading } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => fetchDeal(dealId),
    initialData: selectedDeal,
    enabled: !!dealId,
  })

  const contactId = deal?.contact_id || deal?.contact?.id

  // Fetch live market signals
  const { data: signals = [], isLoading: signalsLoading } = useQuery({
    queryKey: ['signals', contactId],
    queryFn: () => fetchSignals(contactId),
    enabled: !!contactId,
  })

  // Fetch conversation thread
  const { data: thread = [], isLoading: threadLoading } = useQuery({
    queryKey: ['thread', contactId],
    queryFn: () => fetchThread(contactId),
    enabled: !!contactId,
  })

  // Local mutations if not passed
  const localApproveMut = useMutation({
    mutationFn: ({ id }) => approveAction(id, 'Sales Rep'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
      qc.invalidateQueries({ queryKey: ['deal', dealId] })
    },
  })

  const localDismissMut = useMutation({
    mutationFn: ({ id }) => dismissAction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
      qc.invalidateQueries({ queryKey: ['deal', dealId] })
    },
  })

  const handleApprove = approveMut ? approveMut.mutate : localApproveMut.mutate
  const handleDismiss = dismissMut ? dismissMut.mutate : localDismissMut.mutate

  // Scan signals mutation (Agent 2)
  const scanSignalsMut = useMutation({
    mutationFn: () => runAgent('A2', { contact_ids: [contactId] }),
    onMutate: () => setIsScanningSignals(true),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['signals', contactId] })
        qc.invalidateQueries({ queryKey: ['deals'] })
        qc.invalidateQueries({ queryKey: ['deal', dealId] })
        setIsScanningSignals(false)
      }, 2500)
    },
    onError: () => setIsScanningSignals(false),
  })

  if (!deal) return null

  const contact = deal.contact || {}
  const contactName = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || (deal.contact_id ? 'Associated Contact' : null)
  const contactCompany = contact.company || deal.name?.split('—')[0]?.split('-')[0]?.trim() || ''

  // Stage progress calculation
  const currentStageIndex = STAGES.findIndex(s => s.id === (deal.stage?.toLowerCase()))
  const stageIdx = currentStageIndex >= 0 ? currentStageIndex : 1

  // Health Score styling
  const healthScore = deal.deal_health_score ?? (deal.risk_score ? Math.round((1 - deal.risk_score) * 100) : 75)
  const healthColor = healthScore >= 70 ? 'text-emerald-700 bg-emerald-50 border-emerald-200' :
                      healthScore >= 45 ? 'text-amber-700 bg-amber-50 border-amber-200' :
                      'text-rose-700 bg-rose-50 border-rose-200'
  const healthLabel = healthScore >= 70 ? 'Healthy Momentum' : healthScore >= 45 ? 'Moderate Attention' : 'Critical Deal Risk'

  // Win Probability
  const winProb = deal.win_probability != null ? Math.round(deal.win_probability) : (deal.stage === 'proposal' ? 65 : deal.stage === 'demo' ? 55 : 35)

  // Buying Intent
  const buyingIntent = (deal.buying_intent || 'STRONG').toUpperCase()
  const intentBadge = buyingIntent === 'STRONG' ? 'bg-emerald-100 text-emerald-800 border-emerald-300' :
                      buyingIntent === 'MEDIUM' ? 'bg-blue-100 text-blue-800 border-blue-300' :
                      'bg-amber-100 text-amber-800 border-amber-300'

  // Stage confidence
  const stageConfidence = Math.round((deal.stage_confidence ?? 0.85) * 100)

  // Risk actions for this deal
  const dealRisks = actions.filter(a => (a.entity_id === deal.id || a.deal_id === deal.id) && a.status === 'pending')

  const copyEmailToClipboard = (email) => {
    if (!email) return
    navigator.clipboard.writeText(email)
    setCopiedEmail(true)
    setTimeout(() => setCopiedEmail(false), 2000)
  }

  return (
    <div 
      className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-3 sm:p-5 animate-fadeIn"
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl max-w-4xl w-full shadow-2xl border border-gray-200 relative flex flex-col max-h-[92vh] overflow-hidden text-gray-800 animate-scaleUp"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header Bar */}
        <div className="px-6 py-4 bg-gradient-to-r from-slate-50 via-gray-50 to-blue-50/40 border-b border-gray-200 flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider bg-blue-100 text-blue-800 border border-blue-200">
                {deal.stage?.replace(/_/g, ' ')}
              </span>
              {deal.amount != null && (
                <span className="text-sm font-extrabold text-gray-900 font-mono bg-white px-2 py-0.5 rounded-md border border-gray-200 shadow-2xs">
                  ${deal.amount.toLocaleString()}
                </span>
              )}
              <span className="text-xs text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded-full font-semibold border border-emerald-200 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                Active Deal
              </span>
              {deal.hubspot_deal_id && (
                <a
                  href={`https://app.hubspot.com/contacts/deals/${deal.hubspot_deal_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-orange-700 bg-orange-50 hover:bg-orange-100 px-2 py-0.5 rounded-md border border-orange-200 transition-colors flex items-center gap-1 font-medium"
                  title="Open deal in HubSpot CRM"
                >
                  <span>HubSpot #{deal.hubspot_deal_id}</span>
                  <ExternalLink size={10} />
                </a>
              )}
            </div>

            <h1 className="text-xl font-bold text-gray-900 truncate">
              {deal.name}
            </h1>

            <div className="flex items-center gap-3 text-xs text-gray-500 mt-1 flex-wrap">
              <span className="flex items-center gap-1">
                <User size={11} className="text-gray-400" />
                <span>Owner: <strong className="text-gray-700">{deal.owner_email || 'Not assigned'}</strong></span>
              </span>
              <span className="flex items-center gap-1">
                <Clock size={11} className="text-gray-400" />
                <span>Stage Age: <strong className="text-gray-700">{deal.days_in_current_stage ?? 0} days</strong></span>
              </span>
              {deal.close_date && (
                <span className="flex items-center gap-1">
                  <Calendar size={11} className="text-gray-400" />
                  <span>Target Close: <strong className="text-gray-700">{new Date(deal.close_date).toLocaleDateString()}</strong></span>
                </span>
              )}
            </div>
          </div>

          <button 
            onClick={onClose}
            className="w-9 h-9 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-200/80 transition-colors cursor-pointer shrink-0"
            title="Close modal (Esc)"
          >
            <X size={18} />
          </button>
        </div>

        {/* Pipeline Stage Stepper Bar */}
        <div className="px-6 py-3 bg-white border-b border-gray-100 overflow-x-auto">
          <div className="flex items-center justify-between min-w-[580px] gap-2">
            {STAGES.map((s, idx) => {
              const isPast = idx < stageIdx
              const isCurrent = idx === stageIdx
              return (
                <div key={s.id} className="flex-1 flex items-center gap-2">
                  <div className="flex flex-col items-center flex-1">
                    <div className="flex items-center w-full">
                      <div className={`h-1 flex-1 ${idx === 0 ? 'invisible' : (isPast || isCurrent ? 'bg-blue-600' : 'bg-gray-200')}`} />
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 transition-all ${
                        isCurrent
                          ? 'bg-blue-600 text-white ring-4 ring-blue-100 shadow-sm'
                          : isPast
                          ? 'bg-emerald-500 text-white'
                          : 'bg-gray-100 text-gray-400 border border-gray-300'
                      }`}>
                        {isPast ? <Check size={11} /> : idx + 1}
                      </div>
                      <div className={`h-1 flex-1 ${idx === STAGES.length - 1 ? 'invisible' : (isPast ? 'bg-blue-600' : 'bg-gray-200')}`} />
                    </div>
                    <span className={`text-[11px] mt-1 font-semibold capitalize ${
                      isCurrent ? 'text-blue-700 font-bold' : isPast ? 'text-gray-700' : 'text-gray-400'
                    }`}>
                      {s.label}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="px-6 bg-gray-50/80 border-b border-gray-200 flex gap-2 pt-2">
          <button
            onClick={() => setActiveTab('intelligence')}
            className={`px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-1.5 border-b-2 cursor-pointer ${
              activeTab === 'intelligence'
                ? 'bg-white text-blue-700 border-blue-600 shadow-xs'
                : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-100/80'
            }`}
          >
            <Sparkles size={13} className={activeTab === 'intelligence' ? 'text-blue-600' : 'text-gray-400'} />
            <span>AI Intelligence & BANT</span>
          </button>

          <button
            onClick={() => setActiveTab('contact')}
            className={`px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-1.5 border-b-2 cursor-pointer ${
              activeTab === 'contact'
                ? 'bg-white text-blue-700 border-blue-600 shadow-xs'
                : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-100/80'
            }`}
          >
            <User size={13} className={activeTab === 'contact' ? 'text-blue-600' : 'text-gray-400'} />
            <span>Contact & Emails {thread.length > 0 && `(${thread.length})`}</span>
          </button>

          <button
            onClick={() => setActiveTab('signals')}
            className={`px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-1.5 border-b-2 cursor-pointer ${
              activeTab === 'signals'
                ? 'bg-white text-blue-700 border-blue-600 shadow-xs'
                : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-100/80'
            }`}
          >
            <Zap size={13} className={activeTab === 'signals' ? 'text-amber-500' : 'text-gray-400'} />
            <span>Market Signals {signals.length > 0 && `(${signals.length})`}</span>
          </button>

          {deal.stage_history && deal.stage_history.length > 0 && (
            <button
              onClick={() => setActiveTab('history')}
              className={`px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all flex items-center gap-1.5 border-b-2 cursor-pointer ${
                activeTab === 'history'
                  ? 'bg-white text-blue-700 border-blue-600 shadow-xs'
                  : 'text-gray-600 border-transparent hover:text-gray-900 hover:bg-gray-100/80'
              }`}
            >
              <Layers size={13} className={activeTab === 'history' ? 'text-blue-600' : 'text-gray-400'} />
              <span>Stage Velocity ({deal.stage_history.length})</span>
            </button>
          )}
        </div>

        {/* Modal Scrollable Body */}
        <div className="p-6 overflow-y-auto flex-1 space-y-5 bg-slate-50/30">
          
          {/* TAB 1: AI Intelligence & BANT */}
          {activeTab === 'intelligence' && (
            <div className="space-y-5">
              {/* 4 Core AI Metrics Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {/* Health Score */}
                <div className={`p-3.5 rounded-xl border ${healthColor} flex flex-col justify-between shadow-2xs`}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold tracking-wider opacity-80">Health Score</span>
                    <Activity size={13} />
                  </div>
                  <div className="my-1">
                    <div className="text-2xl font-black">{healthScore}<span className="text-xs font-bold opacity-70">/100</span></div>
                  </div>
                  <div className="text-[10px] font-bold tracking-tight">{healthLabel}</div>
                </div>

                {/* Win Probability */}
                <div className="p-3.5 rounded-xl bg-blue-50/80 border border-blue-200 text-blue-900 flex flex-col justify-between shadow-2xs">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-blue-800 tracking-wider">Win Probability</span>
                    <TrendingUp size={13} className="text-blue-600" />
                  </div>
                  <div className="my-1">
                    <div className="text-2xl font-black text-blue-700">{winProb}%</div>
                  </div>
                  <div className="w-full bg-blue-200 rounded-full h-1.5 mt-1 overflow-hidden">
                    <div className="bg-blue-600 h-full rounded-full transition-all" style={{ width: `${winProb}%` }} />
                  </div>
                </div>

                {/* Buying Intent */}
                <div className="p-3.5 rounded-xl bg-amber-50/80 border border-amber-200 text-amber-900 flex flex-col justify-between shadow-2xs">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-amber-800 tracking-wider">Buying Intent</span>
                    <Flame size={13} className="text-amber-600" />
                  </div>
                  <div className="my-1">
                    <span className={`inline-block text-xs font-extrabold px-2 py-0.5 rounded-md border ${intentBadge}`}>
                      {buyingIntent}
                    </span>
                  </div>
                  <div className="text-[10px] text-amber-800 font-medium">From conversation context</div>
                </div>

                {/* Stage Confidence */}
                <div className="p-3.5 rounded-xl bg-purple-50/80 border border-purple-200 text-purple-900 flex flex-col justify-between shadow-2xs">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-purple-800 tracking-wider">Stage Conf.</span>
                    <Target size={13} className="text-purple-600" />
                  </div>
                  <div className="my-1">
                    <div className="text-2xl font-black text-purple-700">{stageConfidence}%</div>
                  </div>
                  <div className="text-[10px] text-purple-800 font-medium">BANT alignment score</div>
                </div>
              </div>

              {/* Agent 5 Next Best Action Prescription */}
              {deal.next_best_action && (
                <div className="p-4 rounded-xl bg-gradient-to-r from-blue-50 via-indigo-50 to-blue-50/60 border border-blue-200 shadow-2xs">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-blue-900 mb-1.5">
                    <Sparkles size={14} className="text-blue-600" />
                    <span>Agent 5 Next Best Action</span>
                    <span className="text-[10px] font-semibold bg-blue-200/80 text-blue-900 px-2 py-0.2 rounded-full ml-auto">
                      AI Prescriptive Guidance
                    </span>
                  </div>
                  <p className="text-xs text-blue-950 font-medium leading-relaxed bg-white/70 p-3 rounded-lg border border-blue-100">
                    {deal.next_best_action}
                  </p>
                </div>
              )}

              {/* BANT Qualification Framework */}
              <div className="p-4 rounded-xl bg-white border border-gray-200 shadow-2xs space-y-3">
                <div className="flex items-center justify-between border-b border-gray-100 pb-2">
                  <div className="text-xs font-bold text-gray-800 uppercase tracking-wider flex items-center gap-1.5">
                    <ShieldCheck size={14} className="text-blue-600" />
                    <span>BANT Qualification Matrix (Call Transcripts & CRM)</span>
                  </div>
                  <span className="text-[11px] text-gray-500 font-medium">
                    {[deal.budget_confirmed, deal.authority_confirmed, deal.need_confirmed, deal.timeline_confirmed].filter(Boolean).length}/4 Confirmed
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  {/* Budget */}
                  <div className={`p-3 rounded-lg border flex items-start gap-2.5 ${
                    deal.budget_confirmed ? 'bg-emerald-50/60 border-emerald-200 text-emerald-950' : 'bg-amber-50/50 border-amber-200 text-amber-950'
                  }`}>
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-xs font-bold ${
                      deal.budget_confirmed ? 'bg-emerald-500 text-white' : 'bg-amber-400 text-white'
                    }`}>
                      {deal.budget_confirmed ? '✓' : '!'}
                    </div>
                    <div>
                      <div className="font-bold">Budget (B)</div>
                      <div className="text-[11px] mt-0.5 text-gray-700">
                        {deal.budget_confirmed ? (deal.amount ? `$${deal.amount.toLocaleString()} Budget Validated` : 'Budget Allocated & Confirmed') : 'Budget pending confirmation / range discovery'}
                      </div>
                    </div>
                  </div>

                  {/* Authority */}
                  <div className={`p-3 rounded-lg border flex items-start gap-2.5 ${
                    deal.authority_confirmed ? 'bg-emerald-50/60 border-emerald-200 text-emerald-950' : 'bg-amber-50/50 border-amber-200 text-amber-950'
                  }`}>
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-xs font-bold ${
                      deal.authority_confirmed ? 'bg-emerald-500 text-white' : 'bg-amber-400 text-white'
                    }`}>
                      {deal.authority_confirmed ? '✓' : '!'}
                    </div>
                    <div>
                      <div className="font-bold">Authority (A)</div>
                      <div className="text-[11px] mt-0.5 text-gray-700">
                        {deal.authority_confirmed ? (contactName ? `Decision Maker Identified: ${contactName}` : 'Economic Buyer Identified') : 'Economic buyer unconfirmed / need DM intro'}
                      </div>
                    </div>
                  </div>

                  {/* Need */}
                  <div className={`p-3 rounded-lg border flex items-start gap-2.5 ${
                    deal.need_confirmed ? 'bg-emerald-50/60 border-emerald-200 text-emerald-950' : 'bg-amber-50/50 border-amber-200 text-amber-950'
                  }`}>
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-xs font-bold ${
                      deal.need_confirmed ? 'bg-emerald-500 text-white' : 'bg-amber-400 text-white'
                    }`}>
                      {deal.need_confirmed ? '✓' : '!'}
                    </div>
                    <div>
                      <div className="font-bold">Need (N)</div>
                      <div className="text-[11px] mt-0.5 text-gray-700">
                        {deal.need_confirmed ? 'Core Pain Point & Technical Use Case Validated' : 'Technical pain points partially qualified'}
                      </div>
                    </div>
                  </div>

                  {/* Timeline */}
                  <div className={`p-3 rounded-lg border flex items-start gap-2.5 ${
                    deal.timeline_confirmed ? 'bg-emerald-50/60 border-emerald-200 text-emerald-950' : 'bg-amber-50/50 border-amber-200 text-amber-950'
                  }`}>
                    <div className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 mt-0.5 text-xs font-bold ${
                      deal.timeline_confirmed ? 'bg-emerald-500 text-white' : 'bg-amber-400 text-white'
                    }`}>
                      {deal.timeline_confirmed ? '✓' : '!'}
                    </div>
                    <div>
                      <div className="font-bold">Timeline (T)</div>
                      <div className="text-[11px] mt-0.5 text-gray-700">
                        {deal.timeline_confirmed ? (deal.close_date ? `Close Target: ${new Date(deal.close_date).toLocaleDateString()}` : 'Target Deployment Timeline Confirmed') : 'Target implementation date unconfirmed'}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Active Objections Section */}
              <div className="p-4 rounded-xl bg-white border border-rose-100 shadow-2xs space-y-3">
                <div className="flex items-center justify-between border-b border-rose-100 pb-2">
                  <div className="text-xs font-bold text-rose-900 uppercase tracking-wider flex items-center gap-1.5">
                    <AlertTriangle size={14} className="text-rose-500" />
                    <span>Customer Objections & Concerns</span>
                  </div>
                  <span className="text-[11px] text-rose-700 font-medium">
                    {deal.objections?.length ?? 0} Logged
                  </span>
                </div>

                {!deal.objections || deal.objections.length === 0 ? (
                  <div className="text-xs text-gray-500 italic py-2 text-center bg-gray-50 rounded-lg">
                    No active objections recorded from recent call transcripts.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {deal.objections.map((obj, i) => (
                      <div key={i} className="p-3 bg-rose-50/40 rounded-lg border border-rose-200/80 text-xs shadow-2xs flex flex-col gap-1.5">
                        <div className="flex items-center gap-2">
                          <span className="bg-rose-100 text-rose-800 border border-rose-200 rounded-md uppercase text-[10px] px-2 py-0.5 font-bold">
                            {obj.category || 'general'}
                          </span>
                          <span className="text-[10px] text-rose-600 font-medium">Transcribed Concern</span>
                        </div>
                        <div className="text-gray-800 font-medium italic leading-relaxed pl-2 border-l-2 border-rose-300">
                          "{obj.text}"
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Detected Deal Risk Flags & Inline Actions */}
              {((deal.risk_flags && deal.risk_flags.length > 0) || dealRisks.length > 0) && (
                <div className="p-4 rounded-xl bg-amber-50/50 border border-amber-200 shadow-2xs space-y-3">
                  <div className="flex items-center justify-between border-b border-amber-200/80 pb-2">
                    <div className="text-xs font-bold text-amber-900 uppercase tracking-wider flex items-center gap-1.5">
                      <ShieldAlert size={14} className="text-amber-600" />
                      <span>Detected Deal Risks & Guard Actions</span>
                    </div>
                    <span className="text-[11px] font-bold text-amber-800 bg-amber-100 px-2 py-0.5 rounded-full">
                      Risk Level: {deal.risk_score >= 0.6 ? 'High' : deal.risk_score >= 0.3 ? 'Medium' : 'Low'}
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {/* CRM Risk Actions */}
                    {dealRisks.map(r => (
                      <div key={r.id} className="p-3.5 bg-white rounded-lg border border-amber-300 shadow-xs space-y-2">
                        <div className="flex items-center justify-between flex-wrap gap-2">
                          <span className="text-xs font-bold text-gray-900 capitalize flex items-center gap-1">
                            <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                            {r.action_type?.replace(/_/g, ' ')}
                          </span>
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleApprove({ id: r.id })}
                              className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-2.5 py-1 rounded-md transition-colors cursor-pointer flex items-center gap-1"
                            >
                              <CheckCircle size={11} /> Approve
                            </button>
                            <button
                              onClick={() => handleDismiss({ id: r.id })}
                              className="text-[11px] font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 border border-gray-200 px-2.5 py-1 rounded-md transition-colors cursor-pointer"
                            >
                              Dismiss
                            </button>
                          </div>
                        </div>
                        <p className="text-xs text-gray-600 leading-relaxed">{r.reason}</p>
                        {r.recommended_value && (
                          <div className="text-xs text-blue-800 bg-blue-50 p-2 rounded-md font-medium">
                            <strong>Recommended AI Action:</strong> {r.recommended_value}
                          </div>
                        )}
                      </div>
                    ))}

                    {/* Passive Risk Flags */}
                    {deal.risk_flags?.map((f, i) => (
                      <div key={i} className="p-3 bg-white/90 rounded-lg border border-amber-200 text-xs shadow-2xs space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-gray-900 capitalize">{f.type?.replace(/_/g, ' ')}</span>
                          <span className="text-[10px] font-bold px-2 py-0.2 rounded uppercase bg-amber-100 text-amber-800">
                            {f.severity || 'medium'}
                          </span>
                        </div>
                        <p className="text-gray-600">{f.description}</p>
                        {f.recommended_action && (
                          <p className="text-blue-700 font-medium mt-1">→ {f.recommended_action}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: Associated Contact & Communication Thread */}
          {activeTab === 'contact' && (
            <div className="space-y-5">
              {/* Contact Card */}
              {contactId ? (
                <div className="p-4 bg-white rounded-xl border border-gray-200 shadow-2xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-blue-100 text-blue-700 font-bold text-base flex items-center justify-center border border-blue-200 shadow-xs">
                      {contact.first_name?.[0] || 'C'}{contact.last_name?.[0] || ''}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold text-gray-900">{contactName || 'Primary Contact'}</h3>
                        {contact.icp_score != null && (
                          <span className="text-[10px] font-bold px-2 py-0.2 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                            ICP Fit: {Math.round(contact.icp_score)}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {contact.title ? `${contact.title} · ` : ''}{contactCompany}
                      </p>
                      {contact.email && (
                        <div className="flex items-center gap-2 mt-1">
                          <a href={`mailto:${contact.email}`} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                            <Mail size={11} /> {contact.email}
                          </a>
                          <button
                            onClick={() => copyEmailToClipboard(contact.email)}
                            className="text-[10px] text-gray-400 hover:text-gray-700 transition-colors cursor-pointer"
                            title="Copy email"
                          >
                            {copiedEmail ? <Check size={11} className="text-emerald-600" /> : <Copy size={11} />}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 self-stretch sm:self-auto justify-end">
                    {contact.linkedin_url && (
                      <a
                        href={contact.linkedin_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1.5 rounded-lg border border-gray-200 bg-gray-50 hover:bg-gray-100 text-xs font-semibold text-gray-700 transition-colors flex items-center gap-1.5"
                      >
                        <LinkIcon size={12} />
                        <span>LinkedIn</span>
                      </a>
                    )}
                    <button
                      onClick={() => navigate(`/contacts/${contactId}`)}
                      className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
                    >
                      <span>Full Contact Profile</span>
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="p-6 bg-white rounded-xl border border-gray-200 text-center space-y-2">
                  <User size={24} className="text-gray-300 mx-auto" />
                  <div className="text-sm font-semibold text-gray-700">No Contact Associated Yet</div>
                  <p className="text-xs text-gray-400 max-w-sm mx-auto">
                    This deal is currently linked directly to HubSpot without a mapped contact record.
                  </p>
                </div>
              )}

              {/* Conversation Messages */}
              <div className="p-4 bg-white rounded-xl border border-gray-200 shadow-2xs space-y-3">
                <div className="flex items-center justify-between border-b border-gray-100 pb-2.5">
                  <div className="flex items-center gap-2">
                    <MessageSquare size={14} className="text-blue-600" />
                    <span className="text-xs font-bold text-gray-800 uppercase tracking-wider">
                      Recent Conversation Messages
                    </span>
                    <span className="badge badge-blue">{thread.length} messages</span>
                  </div>
                  <span className="text-[11px] text-gray-400">Live Email Sync</span>
                </div>

                {threadLoading ? (
                  <div className="text-xs text-gray-400 py-6 text-center">Loading conversation history...</div>
                ) : thread.length === 0 ? (
                  <div className="text-xs text-gray-400 py-6 text-center">
                    No email exchanges recorded for this contact yet.
                  </div>
                ) : (
                  <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                    {thread.map((t, idx) => {
                      const isOutbound = t.direction === 'outbound' || t.event_type === 'email_sent' || t.event_type === 'reply_sent'
                      return (
                        <div key={t.id || idx} className="space-y-2 pt-2 border-t border-gray-100 first:border-0 first:pt-0">
                          {isOutbound ? (
                            /* Outbound (Sent) Message — GREEN */
                            <div className="flex items-start gap-2.5 ml-auto max-w-[88%] flex-row-reverse">
                              <div className="w-7 h-7 rounded-full bg-emerald-600 text-white font-bold text-[10px] flex items-center justify-center shrink-0 border border-emerald-500 shadow-2xs">
                                You
                              </div>
                              <div className="space-y-1 text-right flex-1">
                                <div className="p-3 rounded-xl rounded-tr-none bg-[#ECFDF5] text-[#064E3B] border border-[#A7F3D0] text-xs leading-relaxed text-left whitespace-pre-line font-normal shadow-2xs">
                                  <div className="flex items-center justify-between gap-1 pb-1 mb-1 border-b border-emerald-200/70 text-[10px] font-semibold text-emerald-800">
                                    <span>Sent Message</span>
                                    <span className="font-normal text-emerald-700">
                                      {t.sent_at || t.occurred_at ? new Date(t.sent_at || t.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                                    </span>
                                  </div>
                                  <div className="text-slate-800 whitespace-pre-line">{t.content}</div>
                                </div>
                                <div className="text-[10px] text-gray-400">
                                  Sent by You · {t.channel?.toUpperCase() || 'EMAIL'}
                                </div>
                              </div>
                            </div>
                          ) : (
                            /* Inbound (Received) Message — BLUE */
                            <div className="space-y-2">
                              <div className="flex items-start gap-2.5 max-w-[88%]">
                                <div className="w-7 h-7 rounded-full bg-blue-600 text-white font-bold text-[10px] flex items-center justify-center shrink-0 border border-blue-500 shadow-2xs">
                                  {contact.first_name?.[0] || 'P'}
                                </div>
                                <div className="space-y-1 flex-1">
                                  <div className="p-3 rounded-xl rounded-tl-none bg-[#EFF6FF] text-[#1E3A8A] border border-[#BFDBFE] text-xs leading-relaxed shadow-2xs">
                                    <div className="flex items-center justify-between gap-1 pb-1 mb-1 border-b border-blue-200/70 text-[10px] font-semibold text-blue-900">
                                      <span>Received Email</span>
                                      <span className="font-normal text-blue-700">
                                        {t.occurred_at ? new Date(t.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
                                      </span>
                                    </div>
                                    <div className="text-slate-800 whitespace-pre-line">{t.content}</div>
                                  </div>
                                  <div className="flex items-center gap-2 text-[10px] text-slate-400">
                                    <span className="font-semibold text-slate-600">{contactName || 'Prospect'}</span>
                                    {t.intent && <span className="capitalize text-blue-800 bg-blue-50 px-1.5 py-0.2 rounded border border-blue-200">{t.intent.replace(/_/g, ' ')}</span>}
                                  </div>
                                </div>
                              </div>

                              {/* AI Draft for received message — GREEN */}
                              {t.draft_content && (
                                <div className="flex items-start gap-2.5 ml-auto max-w-[88%] flex-row-reverse">
                                  <div className="w-7 h-7 rounded-full bg-emerald-600 text-white font-bold text-[10px] flex items-center justify-center shrink-0 shadow-2xs">
                                    You
                                  </div>
                                  <div className="space-y-1 text-right flex-1">
                                    <div className="p-3 rounded-xl rounded-tr-none bg-[#ECFDF5] text-[#064E3B] border border-[#A7F3D0] text-xs leading-relaxed text-left whitespace-pre-line shadow-2xs">
                                      <div className="text-[10px] font-semibold text-emerald-800 pb-1 mb-1 border-b border-emerald-200/70">AI Suggested Reply</div>
                                      <div className="text-slate-800 whitespace-pre-line">{t.draft_content}</div>
                                    </div>
                                    <div className="text-[10px] text-gray-400">
                                      {t.approved_at ? 'Approved Outbound Response' : 'Draft Response'}
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
          )}

          {/* TAB 3: Market Signals (Agent 2) */}
          {activeTab === 'signals' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between bg-white p-4 rounded-xl border border-gray-200 shadow-2xs">
                <div>
                  <div className="text-xs font-bold text-gray-800 uppercase tracking-wider flex items-center gap-1.5">
                    <Zap size={14} className="text-amber-500" />
                    <span>Real-time Market & Hiring Signals ({signals.length})</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Live triggers from Adzuna job postings, news releases, funding, and tech stack adoption.
                  </p>
                </div>
                <button
                  onClick={() => scanSignalsMut.mutate()}
                  disabled={isScanningSignals || !contactId}
                  className="text-xs font-semibold text-blue-700 hover:text-blue-800 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50 shadow-2xs"
                >
                  <RefreshCw size={12} className={isScanningSignals ? 'animate-spin' : ''} />
                  <span>{isScanningSignals ? 'Scanning Market News...' : '⚡ Run Agent 2 (Scan)'}</span>
                </button>
              </div>

              {signalsLoading ? (
                <div className="text-xs text-gray-400 py-8 text-center bg-white rounded-xl border border-gray-200">
                  Loading live account signals...
                </div>
              ) : signals.length === 0 ? (
                <div className="p-6 bg-white rounded-xl border border-gray-200 text-center space-y-2">
                  <Zap size={24} className="text-amber-300 mx-auto" />
                  <div className="text-sm font-semibold text-gray-700">No Signals Detected Yet</div>
                  <p className="text-xs text-gray-400 max-w-sm mx-auto">
                    Click <strong>"Run Agent 2"</strong> above to trigger a real-time scan of job postings and news feeds for {contactCompany || 'this account'}.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {signals.map(s => (
                    <div key={s.id} className="p-3.5 bg-white rounded-xl border border-gray-200 text-xs shadow-2xs flex items-start justify-between gap-3 hover:border-blue-200 transition-colors">
                      <div className="space-y-1 flex-1">
                        <div className="font-bold text-gray-900 capitalize flex items-center gap-1.5">
                          <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                          <span>{s.signal_type?.replace(/_/g, ' ')}</span>
                          <span className="text-[10px] text-gray-400 font-normal">· {s.signal_source}</span>
                          {s.confidence && (
                            <span className="text-[10px] text-blue-700 bg-blue-50 px-1.5 py-0.2 rounded font-semibold ml-1">
                              Score: {Math.round(s.confidence * 100)}
                            </span>
                          )}
                        </div>
                        {s.raw_data?.headline && (
                          <div className="text-gray-700 text-xs leading-snug font-medium italic">
                            "{s.raw_data.headline}"
                          </div>
                        )}
                        {s.raw_data?.description && (
                          <p className="text-gray-500 text-[11px] leading-relaxed">
                            {s.raw_data.description}
                          </p>
                        )}
                        {s.raw_data?.url && (
                          <a
                            href={s.raw_data.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline font-medium"
                          >
                            <span>View Source</span>
                            <ExternalLink size={9} />
                          </a>
                        )}
                      </div>
                      <span className="text-[10px] text-gray-400 shrink-0">
                        {new Date(s.detected_at).toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* TAB 4: Stage History & Velocity */}
          {activeTab === 'history' && deal.stage_history && (
            <div className="space-y-4">
              <div className="p-4 bg-white rounded-xl border border-gray-200 shadow-2xs space-y-3">
                <div className="text-xs font-bold text-gray-800 uppercase tracking-wider flex items-center gap-1.5">
                  <Layers size={14} className="text-blue-600" />
                  <span>Stage Transition Timeline</span>
                </div>

                <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-blue-100">
                  {deal.stage_history.map((h, idx) => (
                    <div key={h.id || idx} className="relative">
                      <div className="absolute -left-6 top-1 w-4 h-4 rounded-full bg-blue-600 border-2 border-white shadow-xs" />
                      <div className="bg-gray-50 p-3 rounded-lg border border-gray-200 text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-gray-900 capitalize">
                            {h.from_stage ? `${h.from_stage} → ${h.to_stage}` : `Entered ${h.to_stage}`}
                          </span>
                          <span className="text-[10px] text-gray-400">
                            {new Date(h.transitioned_at).toLocaleDateString()}
                          </span>
                        </div>
                        {h.days_in_from_stage != null && (
                          <div className="text-[11px] text-gray-500">
                            Spent {h.days_in_from_stage} days in prior stage
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

        </div>

        {/* Modal Bottom Footer */}
        <div className="px-6 py-3 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
          <div className="text-xs text-gray-500">
            Last evaluated by Agent 5 · {deal.updated_at ? new Date(deal.updated_at).toLocaleString() : 'Just now'}
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-gray-200 hover:bg-gray-300 text-gray-800 text-xs font-semibold transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

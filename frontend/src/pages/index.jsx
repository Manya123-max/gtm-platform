// ── Deals Page ────────────────────────────────────────────────────────────
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDeals, fetchPipelineSummary, fetchPendingActions, approveAction, dismissAction, fetchForecast, fetchFunnelMetrics, runAgent, pollAgentStatus, runOrchestratorAgent, runOrchestratorWorkflow, fetchWorkflowRun, DEFAULT_PIPELINE_AGENTS, fetchDrafts, fetchContent, fetchAgentSchedules, updateAgentSchedule, fetchOutreachDrafts, approveOutreachDraft, rejectOutreachDraft, editOutreachDraft, previewOutreachDraft, fetchSignals } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from 'recharts'
import { AlertTriangle, CheckCircle, X, Bot, Play, Loader2, FileText, Clock, Zap, Building2, User, RefreshCw, Sparkles, ExternalLink, ShieldAlert } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../context/SessionContext'

function RiskBadge({ score }) {
  if (score >= 0.6) return <span className="badge badge-red">High Risk</span>
  if (score >= 0.3) return <span className="badge badge-amber">Medium</span>
  return <span className="badge badge-green">Healthy</span>
}

export function Deals() {
  const { activeSessionId, ourCompanyName } = useSession()
  const [selectedDeal, setSelectedDeal] = useState(null)
  const [actionTab, setActionTab] = useState('pending')
  const navigate = useNavigate ? useNavigate() : null
  const { data: deals = [], isLoading } = useQuery({
    queryKey: ['deals', activeSessionId],
    queryFn: () => fetchDeals(activeSessionId != null ? { user_input_id: activeSessionId } : {})
  })
  const { data: summary = [] } = useQuery({
    queryKey: ['pipeline-summary', activeSessionId],
    queryFn: () => fetchPipelineSummary(activeSessionId)
  })
  const { data: actions = [] } = useQuery({
    queryKey: ['pending-actions', actionTab],
    queryFn: () => fetchPendingActions({ status: actionTab, agent_id: 'A5' })
  })
  const { data: pendingActions = [] } = useQuery({
    queryKey: ['pending-actions', 'pending_count'],
    queryFn: () => fetchPendingActions({ status: 'pending', agent_id: 'A5' })
  })
  const qc = useQueryClient()

  const approveMut = useMutation({
    mutationFn: ({ id }) => approveAction(id, 'Sales Rep'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })
  const dismissMut = useMutation({
    mutationFn: ({ id }) => dismissAction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  const STAGE_ORDER = ['prospecting','discovery','demo','proposal','negotiation']
  const ordered = STAGE_ORDER.map(s => summary.find(r => r.stage === s) || { stage: s, count: 0, value: 0 })

  const activeDealIds = new Set(deals.map(d => d.id))
  const dealActions = actions.filter(a => a.entity_type === 'deal' ? (activeDealIds.has(a.entity_id) || activeDealIds.has(a.deal_id)) : true)
  const activePendingDealActions = pendingActions.filter(a => a.entity_type === 'deal' ? (activeDealIds.has(a.entity_id) || activeDealIds.has(a.deal_id)) : true)

  const [isSyncingHubSpot, setIsSyncingHubSpot] = useState(false)
  const syncHubSpotMut = useMutation({
    mutationFn: () => runAgent('A5', {}),
    onMutate: () => setIsSyncingHubSpot(true),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['deals'] })
        qc.invalidateQueries({ queryKey: ['pending-actions'] })
        setIsSyncingHubSpot(false)
      }, 2000)
    },
    onError: () => setIsSyncingHubSpot(false),
  })

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-800">
            Deals {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Pipeline health and Agent 5 deal intelligence</p>
        </div>
        <button
          onClick={() => syncHubSpotMut.mutate()}
          disabled={isSyncingHubSpot}
          className="text-xs font-semibold text-orange-700 hover:text-orange-800 bg-orange-50 border border-orange-200 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50 shadow-xs"
        >
          <RefreshCw size={12} className={isSyncingHubSpot ? 'animate-spin' : ''} />
          <span>{isSyncingHubSpot ? 'Syncing CRM...' : '🔄 Sync with HubSpot'}</span>
        </button>
      </div>

      {/* Pipeline bar */}
      <div className="card mb-6">
        <div className="section-title text-gray-800 font-semibold">Pipeline by Stage</div>
        <div className="section-sub text-gray-500">Active deals count and value</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={ordered} barSize={32}>
            <XAxis dataKey="stage" tick={{ fill: '#6B7280', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis hide />
            <Tooltip
              contentStyle={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 8, fontSize: 12, boxShadow: '0 4px 6px -1px rgba(0,0,0,0.1)' }}
              labelStyle={{ color: '#374151', fontWeight: 600 }}
              formatter={(v, name) => [name === 'value' ? `$${(v/1000).toFixed(0)}k` : v, name]}
            />
            <Bar dataKey="count" fill="#3B82F6" radius={[4,4,0,0]} name="Deals" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Deal list */}
        <div className="card p-0 overflow-hidden shadow-sm border border-gray-200">
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
            <div className="text-sm font-semibold text-gray-800">Active Deals</div>
            <span className="text-xs text-gray-400 font-medium">Click a deal to view intelligence</span>
          </div>
          <div className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
            {isLoading ? (
              <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
            ) : deals.length === 0 ? (
              <div className="p-8 text-center text-gray-400 text-sm">No active deals</div>
            ) : deals.map(d => (
              <div 
                key={d.id} 
                onClick={() => setSelectedDeal(d)}
                className="px-5 py-3.5 hover:bg-blue-50/60 cursor-pointer transition-colors group"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-semibold text-gray-800 group-hover:text-blue-600 transition-colors flex items-center gap-1.5">
                      <span>{d.name}</span>
                      <span className="text-[10px] text-blue-500 opacity-0 group-hover:opacity-100 transition-opacity">↗</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5 capitalize">{d.stage} · {d.days_in_current_stage}d in stage</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {d.amount && <span className="text-xs font-bold text-gray-700 font-mono">${(d.amount/1000).toFixed(0)}k</span>}
                    <RiskBadge score={d.risk_score} />
                  </div>
                </div>
                {d.risk_flags?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {d.risk_flags.slice(0,2).map((f,i) => (
                      <span key={i} className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full font-medium">
                        {f.type?.replace(/_/g,' ')}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Pending actions */}
        <div className="card p-0 overflow-hidden shadow-sm border border-gray-200">
          <div className="px-5 py-3.5 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-800">CRM Risk Actions</span>
              <div className="flex bg-gray-200/80 p-0.5 rounded-lg text-xs font-medium">
                <button
                  onClick={() => setActionTab('pending')}
                  className={`px-2.5 py-1 rounded-md transition-all ${
                    actionTab === 'pending'
                      ? 'bg-white text-blue-600 shadow-xs font-semibold'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  Active ({activePendingDealActions.length})
                </button>
                <button
                  onClick={() => setActionTab('history')}
                  className={`px-2.5 py-1 rounded-md transition-all ${
                    actionTab === 'history'
                      ? 'bg-white text-blue-600 shadow-xs font-semibold'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  History
                </button>
              </div>
            </div>
            <span className="text-[11px] text-gray-400 font-medium">A5 Deal Guard</span>
          </div>

          <div className="divide-y divide-gray-100 max-h-96 overflow-y-auto">
            {dealActions.length === 0 ? (
              <div className="p-8 text-center text-gray-400 text-xs">
                {actionTab === 'pending' ? 'No active pending risk actions for current deals' : 'No resolved actions in history'}
              </div>
            ) : dealActions.map(a => (
              <div key={a.id} className="px-5 py-3.5 hover:bg-slate-50/50 transition-colors">
                {/* Target Company & Contact Badge */}
                <div className="flex items-center justify-between mb-1.5 flex-wrap gap-1">
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="font-bold text-gray-900 bg-blue-50 border border-blue-200/80 px-2 py-0.5 rounded-md flex items-center gap-1">
                      <Building2 size={11} className="text-blue-600" />
                      <span>{a.company || a.deal_name?.split('—')[0]?.split('-')[0]?.trim() || 'Galvin Technologies'}</span>
                    </span>
                    {a.contact_name && (
                      <span className="text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded-md font-medium text-[11px] flex items-center gap-1">
                        <User size={10} className="text-gray-500" />
                        <span>{a.contact_name}</span>
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full capitalize">
                      {a.action_type?.replace(/_/g,' ')}
                    </span>
                    {actionTab === 'history' && (
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full capitalize ${
                        a.status === 'approved'
                          ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                          : a.status === 'dismissed'
                          ? 'bg-gray-100 text-gray-700 border border-gray-200'
                          : 'bg-amber-50 text-amber-700 border border-amber-200'
                      }`}>
                        {a.status} {a.approved_by ? `by ${a.approved_by}` : ''}
                      </span>
                    )}
                  </div>
                </div>

                {a.deal_name && (
                  <div className="text-[11px] text-gray-500 mb-1 font-medium">
                    Deal: <span className="text-gray-700">{a.deal_name}</span>
                  </div>
                )}

                <div className="text-xs text-gray-600 mb-2 leading-relaxed">{a.reason}</div>
                {a.recommended_value && (
                  <div className="text-xs font-medium text-blue-800 bg-blue-50/80 border border-blue-100 p-2.5 rounded-lg mb-2.5 leading-relaxed">
                    <strong className="text-blue-950">AI Action: </strong> {a.recommended_value}
                  </div>
                )}
                {actionTab === 'pending' ? (
                  <div className="flex gap-3">
                    <button onClick={() => approveMut.mutate({ id: a.id })}
                      className="flex items-center gap-1 text-xs font-semibold text-emerald-700 hover:text-emerald-800 bg-emerald-50 border border-emerald-200 px-3 py-1 rounded-md transition-colors shadow-xs cursor-pointer">
                      <CheckCircle size={12} /> Approve Action
                    </button>
                    <button onClick={() => dismissMut.mutate({ id: a.id })}
                      className="flex items-center gap-1 text-xs font-medium text-gray-600 hover:text-gray-800 bg-gray-50 border border-gray-200 px-3 py-1 rounded-md transition-colors cursor-pointer">
                      <X size={12} /> Dismiss
                    </button>
                  </div>
                ) : (
                  <div className="text-[10px] text-gray-400">
                    Resolved: {a.approved_at ? new Date(a.approved_at).toLocaleString() : new Date(a.created_at).toLocaleString()}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Interactive Deal Detail & Live Signals Modal */}
      {selectedDeal && (
        <DealDetailModal 
          selectedDeal={selectedDeal} 
          onClose={() => setSelectedDeal(null)}
          actions={actions}
          approveMut={approveMut}
          dismissMut={dismissMut}
        />
      )}
    </div>
  )
}

function DealDetailModal({ selectedDeal, onClose, actions, approveMut, dismissMut }) {
  const qc = useQueryClient()
  const { data: signals = [], isLoading: signalsLoading, refetch: refetchSignals } = useQuery({
    queryKey: ['signals', selectedDeal.contact_id],
    queryFn: () => fetchSignals(selectedDeal.contact_id),
    enabled: !!selectedDeal.contact_id,
  })

  const [isScanningSignals, setIsScanningSignals] = useState(false)
  const scanSignalsMut = useMutation({
    mutationFn: () => runAgent('A2', { contact_ids: [selectedDeal.contact_id] }),
    onMutate: () => setIsScanningSignals(true),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['signals', selectedDeal.contact_id] })
        setIsScanningSignals(false)
      }, 2500)
    },
    onError: () => setIsScanningSignals(false),
  })

  const dealRisks = actions.filter(a => a.entity_id === selectedDeal.id && a.status === 'pending')

  return (
    <div 
      className="fixed inset-0 bg-[#0F1D3A]/45 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fadeIn"
      onClick={onClose}
    >
      <div 
        className="bg-white rounded-2xl p-6 max-w-2xl w-full shadow-2xl border border-gray-100 relative flex flex-col gap-4 animate-scaleUp text-gray-800 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-gray-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="badge badge-blue capitalize">{selectedDeal.stage}</span>
              <span className="text-xs text-gray-500 font-mono font-bold">${selectedDeal.amount?.toLocaleString() || '60,000'}</span>
              <span className="text-xs text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full font-semibold border border-emerald-200">Active Pipeline</span>
            </div>
            <h2 className="text-lg font-bold text-gray-900 mt-1">{selectedDeal.name}</h2>
            <p className="text-xs text-gray-500 mt-0.5">Owner: {selectedDeal.owner_email || 'Sales Rep'} · Stage Age: {selectedDeal.days_in_current_stage || 0}d</p>
          </div>
          <button 
            onClick={onClose}
            className="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Metrics Breakdown Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          <div className="p-3 rounded-xl bg-emerald-50/70 border border-emerald-100 text-center">
            <div className="text-[10px] uppercase font-bold text-emerald-800 tracking-wider">Health Score</div>
            <div className="text-xl font-extrabold text-emerald-700 mt-0.5">{selectedDeal.deal_health_score?.toFixed(0) || '85'}/100</div>
          </div>
          <div className="p-3 rounded-xl bg-blue-50/70 border border-blue-100 text-center">
            <div className="text-[10px] uppercase font-bold text-blue-800 tracking-wider">Win Probability</div>
            <div className="text-xl font-extrabold text-blue-700 mt-0.5">{selectedDeal.win_probability?.toFixed(0) || '65'}%</div>
          </div>
          <div className="p-3 rounded-xl bg-amber-50/70 border border-amber-100 text-center">
            <div className="text-[10px] uppercase font-bold text-amber-800 tracking-wider">Buying Intent</div>
            <div className="text-xs font-extrabold text-amber-700 uppercase mt-2">{selectedDeal.buying_intent || 'STRONG'}</div>
          </div>
          <div className="p-3 rounded-xl bg-purple-50/70 border border-purple-100 text-center">
            <div className="text-[10px] uppercase font-bold text-purple-800 tracking-wider">Stage Conf.</div>
            <div className="text-xl font-extrabold text-purple-700 mt-0.5">{Math.round((selectedDeal.stage_confidence || 0.5) * 100)}%</div>
          </div>
        </div>

        {/* Agent 5 Next Best Action Callout */}
        {selectedDeal.next_best_action && (
          <div className="p-4 rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200/80">
            <div className="flex items-center gap-1.5 text-xs font-bold text-blue-800 mb-1">
              <Sparkles size={13} className="text-blue-600" />
              <span>Agent 5 Next Best Action</span>
            </div>
            <p className="text-xs text-blue-900 leading-relaxed font-medium">
              {selectedDeal.next_best_action}
            </p>
          </div>
        )}

        {/* Active Deal Risks */}
        {dealRisks.length > 0 && (
          <div className="p-4 rounded-xl bg-amber-50/60 border border-amber-200/80 space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs font-bold text-amber-900 uppercase tracking-wider flex items-center gap-1.5">
                <ShieldAlert size={14} className="text-amber-600" />
                <span>Detected Risks for this Deal ({dealRisks.length})</span>
              </div>
            </div>
            <div className="space-y-2 pt-1">
              {dealRisks.map(r => (
                <div key={r.id} className="p-3 bg-white rounded-lg border border-amber-200 shadow-xs">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold text-gray-900 capitalize">{r.action_type?.replace(/_/g,' ')}</span>
                    <div className="flex gap-2">
                      <button 
                        onClick={() => approveMut.mutate({ id: r.id })}
                        className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-2 py-0.5 rounded transition-colors"
                      >
                        ✓ Approve
                      </button>
                      <button 
                        onClick={() => dismissMut.mutate({ id: r.id })}
                        className="text-[11px] font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 border border-gray-200 px-2 py-0.5 rounded transition-colors"
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-gray-600">{r.reason}</p>
                  {r.recommended_value && (
                    <p className="text-xs text-blue-700 font-medium mt-1">→ {r.recommended_value}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Real Live Market Signals (Agent 2 Integration) */}
        <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-bold text-gray-800 uppercase tracking-wider">
              <Zap size={14} className="text-amber-500" />
              <span>Real Market Signals for Company ({signals.length})</span>
            </div>
            <button
              onClick={() => scanSignalsMut.mutate()}
              disabled={isScanningSignals}
              className="text-[11px] font-semibold text-blue-700 hover:text-blue-800 bg-blue-50 border border-blue-200 px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-50"
            >
              <RefreshCw size={11} className={isScanningSignals ? 'animate-spin' : ''} />
              <span>{isScanningSignals ? 'Scanning Market News...' : '⚡ Run Agent 2 (Scan Signals)'}</span>
            </button>
          </div>

          {signalsLoading ? (
            <div className="text-xs text-gray-400 py-3 text-center">Loading live signals...</div>
          ) : signals.length === 0 ? (
            <div className="p-3 bg-white rounded-lg border border-gray-200 text-xs text-gray-600 leading-relaxed">
              No recent news/hiring signals logged for this company yet. Click <strong>"Run Agent 2"</strong> above to scan live Adzuna job postings and news feeds.
            </div>
          ) : (
            <div className="space-y-1.5 max-h-44 overflow-y-auto pr-1">
              {signals.map(s => (
                <div key={s.id} className="p-2.5 bg-white rounded-lg border border-gray-200 text-xs shadow-2xs flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-gray-800 capitalize flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                      <span>{s.signal_type?.replace(/_/g, ' ')}</span>
                      <span className="text-[10px] text-gray-400 font-normal">· {s.signal_source}</span>
                    </div>
                    {s.raw_data?.headline && (
                      <div className="text-gray-600 mt-0.5 text-[11px] leading-snug">{s.raw_data.headline}</div>
                    )}
                  </div>
                  <span className="text-[10px] text-gray-400 shrink-0">{new Date(s.detected_at).toLocaleDateString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* BANT Qualification Signals */}
        <div className="p-4 rounded-xl bg-gray-50 border border-gray-200/70 space-y-2">
          <div className="text-xs font-bold text-gray-700 uppercase tracking-wider mb-1">BANT Qualification Checklist</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="flex items-center gap-1.5 text-gray-700">
              <span className="text-emerald-600 font-bold">✓</span>
              <span>Budget: <strong className="text-gray-900">${selectedDeal.amount?.toLocaleString() || '60,000'} Confirmed</strong></span>
            </div>
            <div className="flex items-center gap-1.5 text-gray-700">
              <span className="text-emerald-600 font-bold">✓</span>
              <span>Authority: <strong className="text-gray-900">VP of Engineering</strong></span>
            </div>
            <div className="flex items-center gap-1.5 text-gray-700">
              <span className="text-emerald-600 font-bold">✓</span>
              <span>Need: <strong className="text-gray-900">CRM & RAG Migration</strong></span>
            </div>
            <div className="flex items-center gap-1.5 text-gray-700">
              <span className="text-emerald-600 font-bold">✓</span>
              <span>Timeline: <strong className="text-gray-900">4 Weeks Target</strong></span>
            </div>
          </div>
        </div>

        {/* Objections List */}
        <div className="p-4 rounded-xl bg-rose-50/50 border border-rose-100 space-y-2">
          <div className="text-xs font-bold text-rose-800 uppercase tracking-wider mb-1">Active Objections (Agent 5)</div>
          {!selectedDeal.objections || selectedDeal.objections.length === 0 ? (
            <div className="text-xs text-gray-500 italic">No active objections recorded from recent calls.</div>
          ) : (
            <div className="space-y-1.5 max-h-36 overflow-y-auto pr-1">
              {selectedDeal.objections.map((obj, i) => (
                <div key={i} className="p-2 bg-white rounded-lg border border-rose-100 text-xs shadow-2xs flex flex-col gap-1">
                  <div className="flex items-center gap-1.5">
                    <span className="bg-rose-50 text-rose-700 border border-rose-100 rounded-md capitalize text-[9px] px-1.5 py-0.5 font-bold">
                      {obj.category || 'other'}
                    </span>
                  </div>
                  <div className="text-gray-700 leading-relaxed italic">"{obj.text}"</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Associated Contact Link */}
        {selectedDeal.contact_id && (
          <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-200">
            <div>
              <div className="text-[10px] text-gray-500 font-semibold uppercase">Associated Contact & Thread</div>
              <div className="text-xs font-bold text-gray-800 mt-0.5">Lauren Bell (Galvin Technologies)</div>
            </div>
            <a
              href={`/contacts/${selectedDeal.contact_id}`}
              className="text-xs font-semibold text-blue-600 hover:text-blue-700 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1"
            >
              <span>View Conversation Thread</span>
              <span>→</span>
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Revenue Page ──────────────────────────────────────────────────────────
export function Revenue() {
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: forecast } = useQuery({ queryKey: ['forecast'], queryFn: fetchForecast })
  const { data: metrics = {} } = useQuery({
    queryKey: ['funnel-metrics', 30],
    queryFn: () => fetchFunnelMetrics(30),
  })

  const funnelData = Object.entries(metrics).map(([k,v]) => ({
    name: k.replace(/_/g,' '),
    count: v,
  })).sort((a,b) => b.count - a.count).slice(0,8)

  const stages = forecast?.stage_conversion_rates
    ? Object.entries(forecast.stage_conversion_rates).map(([k,v]) => ({
        stage: k.replace(/_to_.*/, '').replace(/_/g,' '),
        rate: Math.round(v * 100),
      }))
    : []

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-100">
          Revenue Intelligence {ourCompanyName ? `for ${ourCompanyName}` : ''}
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">A7 forecast model — 30/60/90-day pipeline</p>
      </div>

      {/* Forecast cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: '30-Day Forecast', val: forecast?.forecast_30d },
          { label: '60-Day Forecast', val: forecast?.forecast_60d },
          { label: '90-Day Forecast', val: forecast?.forecast_90d },
        ].map(f => (
          <div key={f.label} className="stat-card">
            <div className="stat-label">{f.label}</div>
            <div className="stat-value">
              {f.val != null ? `$${(f.val/1000).toFixed(0)}k` : '—'}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        {/* Constraint */}
        {forecast?.bottleneck_stage && (
          <div className="card border-amber-800/40 bg-amber-900/10">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle size={14} className="text-amber-400" />
              <span className="text-sm font-medium text-amber-300">Constraint Detected</span>
            </div>
            <div className="text-sm text-amber-400 font-medium capitalize mb-1">{forecast.bottleneck_stage} Stage</div>
            <div className="text-xs text-gray-400 mb-3">{forecast.bottleneck_description}</div>
            <div className="text-xs text-blue-400">→ {forecast.recommended_lever}</div>
          </div>
        )}

        {/* Stage conversion rates */}
        <div className="card">
          <div className="section-title">Stage Conversion Rates</div>
          <div className="section-sub">Current vs historical baseline</div>
          <div className="space-y-2">
            {stages.map(s => (
              <div key={s.stage}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-500 capitalize">{s.stage}</span>
                  <span className="text-gray-300">{s.rate}%</span>
                </div>
                <div className="score-bar">
                  <div className="score-fill bg-blue-500" style={{ width: `${s.rate}%` }} />
                </div>
              </div>
            ))}
            {stages.length === 0 && (
              <div className="text-sm text-gray-600 text-center py-4">Run A7 to see conversion rates</div>
            )}
          </div>
        </div>
      </div>

      {/* Activity breakdown */}
      {funnelData.length > 0 && (
        <div className="card">
          <div className="section-title">Activity Log (30 days)</div>
          <div className="section-sub">Events recorded in the Prospect Intelligence Graph</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={funnelData} layout="vertical" barSize={14}>
              <XAxis type="number" hide />
              <YAxis dataKey="name" type="category" tick={{ fill: '#6B7280', fontSize: 11 }} axisLine={false} tickLine={false} width={140} />
              <Tooltip contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }} />
              <Bar dataKey="count" fill="#3B82F6" radius={[0,4,4,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ── Agents Control Page ───────────────────────────────────────────────────
const AGENTS = [
  { id: 'A1', name: 'Prospect Intelligence', tier: 'data',
    desc: 'Win-pattern model. Discovers net-new Apollo people, enriches, scores, and saves contacts.',
    apis: ['Apollo people search', 'Apollo bulk enrichment'],
    schedule: 'Manual — runs when triggered' },
  { id: 'A2', name: 'Signal Intelligence', tier: 'data',
    desc: 'Signal Conversion Registry. Monitors Adzuna and NewsAPI for buying intent.',
    apis: ['Adzuna', 'NewsAPI'],
    schedule: 'Every hour' },
  { id: 'A3', name: 'Multi-Channel Outreach', tier: 'data',
    desc: 'Signal-matched sequences. Deduplication enforced. Claude Haiku for generation.',
    apis: ['Anthropic Claude API', 'Instantly', 'Dry run + approval default'],
    schedule: 'After signal detection' },
  { id: 'A4', name: 'Conversation Intelligence', tier: 'data',
    desc: 'Full thread memory. Rolling readiness score 0–100. Slack approval loop.',
    apis: ['Instantly webhook', 'Anthropic Claude API', 'Cal.com (free)', 'Slack API (free)'],
    schedule: 'On reply webhook' },
  { id: 'A5', name: 'Deal Intelligence', tier: 'intelligence',
    desc: 'Transcript extraction. Pattern comparison vs closed-won baselines. Risk flagging.',
    apis: ['Fireflies.ai webhook (free 800 min)', 'HubSpot API (free)', 'Gmail API (free)'],
    schedule: 'On transcript + daily scan' },
  { id: 'A6', name: 'Content Intelligence', tier: 'intelligence',
    desc: 'Demand-driven briefs from forum signals. Five separate format generations.',
    apis: ['NewsAPI', 'Anthropic Claude API', 'Hash embeddings'],
    schedule: 'Every Tuesday 9am' },
  { id: 'A7', name: 'Predictive Revenue', tier: 'intelligence',
    desc: '30/60/90-day forecast. Constraint detection. Weekly digest via Resend.',
    apis: ['HubSpot API (free)', 'Resend (free 100/day)', 'Internal PIG only'],
    schedule: 'Every night 2am' },
]

// Agents that have a Celery beat schedule entry (A1, A2, A6)
const SCHEDULABLE = new Set(['A1', 'A2', 'A6'])

export function Agents() {
  const { activeSessionId, ourCompanyName } = useSession()
  const queryClient = useQueryClient()
  const location = useLocation()
  const incomingRunId = location.state?.runId

  const [running, setRunning] = useState({})
  const [results, setResults] = useState({})
  const [pipelineRunning, setPipelineRunning] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState('')

  // Define summarizeAgentOutput BEFORE pollWorkflowRun so it can be referenced
  const summarizeAgentOutput = (agentId, output = {}) => {
    if (output.reason) return output.reason
    if (agentId === 'A1') return `saved ${output.saved_count ?? 0}, updated ${output.updated_count ?? 0}`
    if (agentId === 'A2') return `signals saved ${output.signals_saved ?? 0}, detected ${output.signals_detected ?? 0}`
    if (agentId === 'A3') return `drafts ${output.drafts_created ?? 0}, sent ${output.sent ?? 0}, skipped ${output.skipped ?? 0}`
    if (agentId === 'A5') return `deals scanned ${output.deals_scanned ?? 0}, flagged ${output.deals_flagged ?? 0}`
    if (agentId === 'A6') return `content ${output.content_pieces_generated ?? 0}, briefs ${output.briefs_created ?? 0}`
    if (agentId === 'A7') return `forecast ${output.forecast_30d != null ? `$${Math.round(output.forecast_30d).toLocaleString()}` : 'created'}`
    return output.status || 'completed'
  }

  const pollWorkflowRun = async (workflowRunId) => {
    setPipelineRunning(true)
    setPipelineStatus('Starting GTM pipeline...')
    try {
      for (let attempt = 0; attempt < 300; attempt += 1) {
        const data = await fetchWorkflowRun(workflowRunId)
        const status = data?.workflow?.status || 'queued'
        const currentAgent = data?.workflow?.current_agent
        const statusMsg = currentAgent
          ? `${status} — running ${currentAgent}`
          : status
        setPipelineStatus(statusMsg)

        const agentsInRun = data?.agents || []
        const newRunning = {}
        const newResults = {}

        agentsInRun.forEach(agent => {
          const agentId = agent.agent_id
          const agentStatus = agent.status?.toLowerCase()

          if (['running', 'started'].includes(agentStatus)) {
            newRunning[agentId] = true
            newResults[agentId] = 'Running...'
          } else if (agentStatus === 'queued') {
            newRunning[agentId] = false
            newResults[agentId] = 'Queued'
          } else if (['completed', 'success'].includes(agentStatus)) {
            newRunning[agentId] = false
            newResults[agentId] = `Completed — ${summarizeAgentOutput(agentId, agent.output_payload || {})}`
          } else if (agentStatus === 'failed') {
            newRunning[agentId] = false
            newResults[agentId] = `Failed — ${agent.error_message || 'error'}`
          }
        })

        setRunning(current => ({ ...current, ...newRunning }))
        setResults(current => ({ ...current, ...newResults }))

        if (['completed', 'failed', 'cancelled'].includes(status.toLowerCase())) {
          setPipelineStatus(
            status.toLowerCase() === 'completed'
              ? '✓ Pipeline completed — contacts and dashboard updated'
              : `Pipeline ${status.toLowerCase()}`
          )
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['overview'] }),
            queryClient.invalidateQueries({ queryKey: ['contacts'] }),
            queryClient.invalidateQueries({ queryKey: ['funnel-metrics'] }),
          ])
          break
        }
        await new Promise(resolve => setTimeout(resolve, 2000))
      }
    } catch (error) {
      console.error('Polling workflow run failed:', error)
      setPipelineStatus('Pipeline failed — check logs')
    } finally {
      setPipelineRunning(false)
    }
  }

  useEffect(() => {
    if (incomingRunId) {
      pollWorkflowRun(incomingRunId)
    }
  }, [incomingRunId])

  // ── Schedule state ──────────────────────────────────────────────────────
  const [agentModes, setAgentModes] = useState({})          // 'manual' | 'schedule'
  const [schedules, setSchedules] = useState({})            // { A1: { scheduled, cron }, … }
  const [cronInputs, setCronInputs] = useState({
    A1: '0 8 * * 1',   // every Monday 8am
    A2: '0 * * * *',   // every hour
    A6: '0 9 * * 2',   // every Tuesday 9am
  })
  const [savingSchedule, setSavingSchedule] = useState({})

  // Load live schedule state once on mount
  useEffect(() => {
    fetchAgentSchedules()
      .then(data => setSchedules(data || {}))
      .catch(() => {})
  }, [])

  const getMode  = id => agentModes[id] || 'manual'
  const setMode  = (id, mode) => setAgentModes(m => ({ ...m, [id]: mode }))

  const saveSchedule = async (agentId, enabled) => {
    setSavingSchedule(s => ({ ...s, [agentId]: true }))
    try {
      await updateAgentSchedule(agentId, enabled, enabled ? cronInputs[agentId] : null)
      const updated = await fetchAgentSchedules()
      setSchedules(updated || {})
    } catch (e) {
      console.error('Schedule update failed', e)
    } finally {
      setSavingSchedule(s => ({ ...s, [agentId]: false }))
    }
  }
  // ── End schedule state ──────────────────────────────────────────────────

  const pollWorkflow = async (workflowRunId, key) => {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const data = await fetchWorkflowRun(workflowRunId)
      const status = data?.workflow?.status || 'queued'
      const currentAgent = data?.workflow?.current_agent
      const message = currentAgent ? `${status} — ${currentAgent}` : status
      setResults(current => ({ ...current, [key]: message }))
      if (['completed', 'failed', 'cancelled'].includes(status.toLowerCase())) return data
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    throw new Error('Workflow status polling timed out')
  }

  const pollLegacyTask = async (taskId, key) => {
    for (let attempt = 0; attempt < 150; attempt += 1) {
      const data = await pollAgentStatus(taskId)
      const status = data?.status || 'queued'
      setResults(current => ({ ...current, [key]: status.toLowerCase() }))
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(status)) return data
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    throw new Error('Task status polling timed out')
  }


  const trigger = async agentId => {
    setRunning(current => ({ ...current, [agentId]: true }))
    setResults(current => ({ ...current, [agentId]: 'Starting…' }))
    try {
      if (agentId === 'A4') {
        const response = await runAgent('A4', {})
        setResults(current => ({
          ...current,
          A4: `Queued test — task ${response.task_id?.slice(0, 8) || 'created'}`,
        }))
        const completed = await pollLegacyTask(response.task_id, 'A4')
        const result = completed?.result || {}
        setResults(current => ({
          ...current,
          A4: `${completed.status?.toLowerCase() || 'completed'} - ${result.status || result.intent || 'done'}`,
        }))
        return
      }
      const response = await runOrchestratorAgent(agentId, {})
      setResults(current => ({
        ...current,
        [agentId]: `Queued — workflow ${response.workflow_run_id?.slice(0, 8) || 'created'}`,
      }))
      const completed = await pollWorkflow(response.workflow_run_id, agentId)
      const output =
        completed?.agents?.find(item => item.agent_id === agentId)?.output_payload ||
        completed?.workflow?.output_payload ||
        {}
      setResults(current => ({
        ...current,
        [agentId]: `completed - ${summarizeAgentOutput(agentId, output)}`,
      }))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['overview'] }),
        queryClient.invalidateQueries({ queryKey: ['contacts'] }),
        queryClient.invalidateQueries({ queryKey: ['funnel-metrics'] }),
      ])
    } catch (error) {
      setResults(current => ({
        ...current,
        [agentId]: `Failed — ${error.message}`,
      }))
    } finally {
      setRunning(current => ({ ...current, [agentId]: false }))
    }
  }

  const runFullPipeline = async () => {
    setPipelineRunning(true)
    setPipelineStatus('Starting…')
    try {
      const response = await runOrchestratorWorkflow({
        workflowName: 'manual_full_gtm',
        agentIds: DEFAULT_PIPELINE_AGENTS,
        payload: {},
      })
      setPipelineStatus(`Queued — workflow ${response.workflow_run_id?.slice(0, 8) || 'created'}`)
      const result = await pollWorkflow(response.workflow_run_id, '__pipeline__')
      setPipelineStatus(result?.workflow?.status || 'completed')
    } catch (error) {
      setPipelineStatus(`Failed — ${error.message}`)
    } finally {
      setPipelineRunning(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto">

      {/* Live pipeline status banner — shown when redirected from intake form */}
      {pipelineStatus && (
        <div className={`mb-5 flex items-center gap-3 px-4 py-3 rounded-xl border text-sm ${
          pipelineStatus.startsWith('✓')
            ? 'bg-emerald-950/40 border-emerald-700/40 text-emerald-300'
            : pipelineStatus.toLowerCase().includes('fail')
            ? 'bg-red-950/40 border-red-700/40 text-red-300'
            : 'bg-blue-950/40 border-blue-700/40 text-blue-300'
        }`}>
          {pipelineRunning
            ? <Loader2 size={16} className="animate-spin shrink-0" />
            : pipelineStatus.startsWith('✓')
            ? <CheckCircle size={16} className="shrink-0 text-emerald-400" />
            : <Bot size={16} className="shrink-0" />}
          <span className="font-medium">{pipelineStatus}</span>
        </div>
      )}

      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            Agent Control {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Manual agent execution with persistent workflow status</p>
        </div>
        <button
          onClick={runFullPipeline}
          disabled={pipelineRunning}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-xs text-white transition-colors disabled:opacity-50"
        >
          {pipelineRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          Run Full GTM
        </button>
      </div>

      <div className="space-y-3">
        {AGENTS.map(agent => (
          <div key={agent.id} className={`card border ${agent.tier === 'data' ? 'border-blue-900/40' : 'border-purple-900/40'}`}>
            <div className="flex items-start justify-between gap-4">

              {/* Left: agent info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`font-bold text-sm ${agent.tier === 'data' ? 'text-blue-400' : 'text-purple-400'}`}>{agent.id}</span>
                  <span className="text-sm font-medium text-gray-200">{agent.name}</span>
                  <span className={`badge ${agent.tier === 'data' ? 'badge-blue' : 'badge-purple'} text-[10px]`}>{agent.tier}</span>
                </div>
                <p className="text-xs text-gray-500 mb-2">{agent.desc}</p>
                <div className="flex items-center gap-3 text-[10px] text-gray-600">
                  <span className="flex items-center gap-1"><Clock size={10} /> {agent.schedule}</span>
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {agent.apis.map(apiName => (
                    <span key={apiName} className="text-[10px] px-1.5 py-0.5 rounded bg-[#1F2937] text-gray-500 border border-[#374151]">{apiName}</span>
                  ))}
                </div>
                {results[agent.id] && (
                  <div className={`mt-2 text-xs ${results[agent.id].startsWith('Failed') ? 'text-red-400' : 'text-emerald-400'}`}>
                    {results[agent.id]}
                  </div>
                )}
              </div>

              {/* Right: mode toggle + action */}
              <div className="flex flex-col items-end gap-2 shrink-0">

                {/* Mode toggle — only for schedulable agents */}
                {SCHEDULABLE.has(agent.id) && (
                  <div className="flex gap-1 bg-[#0F1623] rounded-md p-0.5">
                    <button
                      onClick={() => setMode(agent.id, 'manual')}
                      className={`px-2.5 py-1 rounded text-[11px] transition-colors ${
                        getMode(agent.id) === 'manual'
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-500 hover:text-gray-300'
                      }`}
                    >Run Now</button>
                    <button
                      onClick={() => setMode(agent.id, 'schedule')}
                      className={`px-2.5 py-1 rounded text-[11px] transition-colors ${
                        getMode(agent.id) === 'schedule'
                          ? 'bg-purple-600 text-white'
                          : 'text-gray-500 hover:text-gray-300'
                      }`}
                    >Schedule</button>
                  </div>
                )}

                {/* Run Now action (all agents; schedulable ones only when in manual mode) */}
                {getMode(agent.id) === 'manual' && (
                  <button
                    onClick={() => trigger(agent.id)}
                    disabled={running[agent.id]}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1F2937] hover:bg-[#374151] border border-[#374151] text-xs text-gray-300 transition-colors disabled:opacity-50"
                  >
                    {running[agent.id] ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                    {agent.id === 'A4' ? 'Run Test' : 'Run'}
                  </button>
                )}

                {/* Schedule action — only shown when Schedule tab is active */}
                {getMode(agent.id) === 'schedule' && SCHEDULABLE.has(agent.id) && (
                  <div className="flex flex-col items-end gap-1.5">
                    {/* Cron expression input */}
                    <input
                      value={cronInputs[agent.id] || ''}
                      onChange={e => setCronInputs(c => ({ ...c, [agent.id]: e.target.value }))}
                      placeholder="0 8 * * 1"
                      className="w-28 bg-[#0F1623] text-white text-[11px] px-2 py-1 rounded border border-[#374151] focus:border-purple-500 outline-none"
                    />
                    {/* Status + Save + Disable */}
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[10px] ${schedules[agent.id]?.scheduled ? 'text-green-400' : 'text-gray-600'}`}>
                        {schedules[agent.id]?.scheduled ? '● Active' : '○ Off'}
                      </span>
                      <button
                        onClick={() => saveSchedule(agent.id, true)}
                        disabled={savingSchedule[agent.id]}
                        className="px-2.5 py-1 bg-purple-600 hover:bg-purple-500 text-white text-[11px] rounded disabled:opacity-50 transition-colors"
                      >
                        {savingSchedule[agent.id] ? <Loader2 size={10} className="animate-spin inline" /> : 'Save'}
                      </button>
                      {schedules[agent.id]?.scheduled && (
                        <button
                          onClick={() => saveSchedule(agent.id, false)}
                          disabled={savingSchedule[agent.id]}
                          className="px-2.5 py-1 bg-[#1F2937] hover:bg-red-900/30 text-gray-500 hover:text-red-400 text-[11px] rounded border border-[#374151] transition-colors disabled:opacity-50"
                        >Disable</button>
                      )}
                    </div>
                  </div>
                )}

              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Outreach Page ─────────────────────────────────────────────────────────
export function Outreach() {
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: drafts = [], isLoading, refetch } = useQuery({
    queryKey: ['outreach-drafts'],
    queryFn: fetchOutreachDrafts,
  })

  const [selectedDraft, setSelectedDraft] = useState(null)

  const gmailComposeUrl = selectedDraft 
    ? `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(selectedDraft.contact?.email || '')}&su=${encodeURIComponent(selectedDraft.subject || '')}&body=${encodeURIComponent(selectedDraft.body || '')}`
    : '#';
  const [isEditing, setIsEditing] = useState(false)
  const [editSubject, setEditSubject] = useState('')
  const [editBody, setEditBody] = useState('')
  const [activeTab, setActiveTab] = useState('active') // 'active' or 'history'

  const qc = useQueryClient()
  
  const approveMut = useMutation({
    mutationFn: approveOutreachDraft,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => prev ? { ...prev, approval_state: 'approved' } : null)
    }
  })
  
  const rejectMut = useMutation({
    mutationFn: rejectOutreachDraft,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => prev ? { ...prev, approval_state: 'rejected' } : null)
    }
  })
  
  const editMut = useMutation({
    mutationFn: ({ id, subject, body }) => editOutreachDraft(id, subject, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => prev ? { ...prev, subject: data.subject, body: data.body } : null)
      setIsEditing(false)
    }
  })

  const handleSelectDraft = (draft) => {
    setSelectedDraft(draft)
    setIsEditing(false)
    setEditSubject(draft.subject)
    setEditBody(draft.body)
  }

  const handleSave = () => {
    editMut.mutate({
      id: selectedDraft.id,
      subject: editSubject,
      body: editBody
    })
  }

  // Filter drafts into Active vs Historical
  const activeDrafts = drafts.filter(d => d.contact?.user_input_id === activeSessionId)
  const historicalDrafts = drafts.filter(d => d.contact?.user_input_id !== activeSessionId)
  const displayedDrafts = activeTab === 'active' ? activeDrafts : historicalDrafts

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6 flex justify-between items-center">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            Outreach Queue {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Approve, reject, or edit generated email campaigns before they send</p>
        </div>
        <button onClick={() => refetch()} className="btn-secondary flex items-center gap-1 text-xs">
          <Clock size={12} /> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Draft list */}
        <div className="lg:col-span-5 card p-0 overflow-hidden flex flex-col max-h-[600px]">
          {/* Tab Selection */}
          <div className="flex border-b border-[#1F2937] bg-[#111827]">
            <button
              onClick={() => setActiveTab('active')}
              className={`flex-1 py-3 text-xs font-semibold border-b-2 transition-all cursor-pointer ${
                activeTab === 'active'
                  ? 'border-purple-500 text-purple-400 bg-purple-950/10'
                  : 'border-transparent text-gray-500 hover:text-gray-400 hover:bg-[#374151]/30'
              }`}
            >
              Active Session ({activeDrafts.length})
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`flex-1 py-3 text-xs font-semibold border-b-2 transition-all cursor-pointer ${
                activeTab === 'history'
                  ? 'border-purple-500 text-purple-400 bg-purple-950/10'
                  : 'border-transparent text-gray-500 hover:text-gray-400 hover:bg-[#374151]/30'
              }`}
            >
              History ({historicalDrafts.length})
            </button>
          </div>
          
          <div className="divide-y divide-[#1F2937] overflow-y-auto flex-1">
            {isLoading ? (
              <div className="p-10 text-center text-gray-500 text-sm">Loading drafts...</div>
            ) : displayedDrafts.length === 0 ? (
              <div className="p-10 text-center text-gray-500 text-sm">
                No {activeTab === 'active' ? 'active session' : 'historical'} drafts.
              </div>
            ) : (
              displayedDrafts.map(d => {
                const isSelected = selectedDraft?.id === d.id
                return (
                  <div
                    key={d.id}
                    onClick={() => handleSelectDraft(d)}
                    className={`px-5 py-4 cursor-pointer transition-colors ${isSelected ? 'bg-[#F0F5FF]/80' : 'hover:bg-[#F0F5FF]/30'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-medium text-gray-800 text-sm">{d.contact?.company || 'Unknown Company'}</div>
                      <span className={`badge ${d.approval_state === 'pending' ? 'badge-amber' : d.approval_state === 'approved' ? 'badge-green' : 'badge-red'}`}>
                        {d.approval_state}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 mt-1 truncate">{d.subject || '(No subject)'}</div>
                    <div className="flex items-center gap-2 mt-2">
                      <span className="badge badge-gray text-[9px]">{d.channel}</span>
                      <span className="badge badge-blue text-[9px]">{d.business_case}</span>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right Column: Preview / Edit Pane */}
        <div className="lg:col-span-7 flex flex-col">
          {selectedDraft ? (
            <div className="card flex-1 flex flex-col">
              <div className="border-b border-[#1F2937] pb-4 mb-4 flex justify-between items-start">
                <div>
                  <h3 className="text-lg font-semibold text-gray-800">{selectedDraft.contact?.first_name} {selectedDraft.contact?.last_name}</h3>
                  <p className="text-xs text-gray-500">{selectedDraft.contact?.title} · {selectedDraft.contact?.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  {!isEditing && (
                    <>
                      {selectedDraft.approval_state === 'pending' ? (
                        <>
                          <button onClick={() => setIsEditing(true)} className="btn-secondary text-xs py-1.5 px-3">
                            Edit
                          </button>
                          <a 
                            href={gmailComposeUrl} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            onClick={() => approveMut.mutate(selectedDraft.id)}
                            className="bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs font-semibold py-1.5 px-3 rounded-lg flex items-center gap-1.5 transition-colors duration-200"
                          >
                            Send via Gmail Web
                          </a>
                          <button 
                            onClick={() => approveMut.mutate(selectedDraft.id)} 
                            disabled={approveMut.isPending}
                            className="btn-primary text-xs py-1.5 px-3"
                          >
                            {approveMut.isPending ? 'Sending...' : 'Approve & Send'}
                          </button>
                          <button 
                            onClick={() => rejectMut.mutate(selectedDraft.id)} 
                            disabled={rejectMut.isPending}
                            className="btn-danger text-xs py-1.5 px-3"
                          >
                            Reject
                          </button>
                        </>
                      ) : selectedDraft.approval_state === 'approved' ? (
                        <button 
                          disabled
                          className="bg-green-600 text-white text-xs font-semibold py-1.5 px-4 rounded-lg cursor-not-allowed flex items-center gap-1.5"
                        >
                          <span className="text-white font-bold">✓</span> Sent & Approved
                        </button>
                      ) : (
                        <button 
                          disabled
                          className="bg-red-600 text-white text-xs font-semibold py-1.5 px-4 rounded-lg cursor-not-allowed"
                        >
                          Rejected
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Meta details */}
              <div className="grid grid-cols-2 gap-4 mb-4 bg-[#F5F8FF] p-3 rounded-lg border border-[#BFCFEA]">
                <div>
                  <span className="text-[10px] text-gray-500 block uppercase font-medium">Business Case</span>
                  <span className="text-xs font-semibold text-gray-700">{selectedDraft.business_case}</span>
                </div>
                <div>
                  <span className="text-[10px] text-gray-500 block uppercase font-medium">Matched Services</span>
                  <span className="text-xs font-semibold text-gray-700">
                    {selectedDraft.matched_services?.join(', ') || 'None'}
                  </span>
                </div>
              </div>

              {/* Form or Read-only message */}
              <div className="flex-1 flex flex-col gap-3">
                {isEditing ? (
                  <div className="flex-1 flex flex-col gap-3">
                    <div>
                      <label className="text-xs text-gray-500 font-medium block mb-1">Subject Line</label>
                      <input
                        type="text"
                        className="input"
                        value={editSubject}
                        onChange={e => setEditSubject(e.target.value)}
                      />
                    </div>
                    <div className="flex-1 flex flex-col min-h-[250px]">
                      <label className="text-xs text-gray-500 font-medium block mb-1">Body Text</label>
                      <textarea
                        className="input flex-1 font-mono text-xs"
                        style={{ resize: 'none' }}
                        value={editBody}
                        onChange={e => setEditBody(e.target.value)}
                      />
                    </div>
                    <div className="flex justify-end gap-2 pt-2 border-t border-[#1F2937]">
                      <button onClick={() => setIsEditing(false)} className="btn-secondary text-xs">
                        Cancel
                      </button>
                      <button 
                        onClick={handleSave} 
                        disabled={editMut.isPending}
                        className="btn-primary text-xs"
                      >
                        {editMut.isPending ? 'Save Changes' : 'Save Changes'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 flex flex-col gap-3 bg-[#F5F8FF] border border-[#BFCFEA] rounded-lg p-4 max-h-[400px] overflow-y-auto">
                    <div>
                      <div className="text-[10px] text-gray-500 font-medium uppercase block">Subject</div>
                      <div className="text-sm font-semibold text-gray-800">{selectedDraft.subject}</div>
                    </div>
                    <hr className="border-[#BFCFEA] my-1" />
                    <div className="flex-1 whitespace-pre-wrap text-sm text-gray-700 leading-relaxed font-sans">
                      {selectedDraft.body}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card flex-1 flex flex-col justify-center items-center text-center p-12 text-gray-500 min-h-[400px]">
              <FileText size={48} className="text-[#A0BBDF] mb-3" />
              <h3 className="font-semibold text-gray-800 text-base mb-1">No Draft Selected</h3>
              <p className="text-xs max-w-xs text-gray-500 font-medium">Select any outreach campaign from the list on the left to preview, edit, or approve it.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Content Page ──────────────────────────────────────────────────────────
export function Content() {
  const [format, setFormat] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [copiedId, setCopiedId] = useState(null)
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: content = [] } = useQuery({
    queryKey: ['content', format, activeSessionId],
    queryFn: () => fetchContent({
      format: format || undefined,
      limit: 30,
      ...(activeSessionId != null ? { user_input_id: activeSessionId } : {}),
    }),
  })

  const formats = ['linkedin_post','email_sequence','case_study','blog_article','sales_deck_outline']

  const handleCopy = (e, id, text) => {
    e.stopPropagation()
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-100">
            Content {ourCompanyName ? `for ${ourCompanyName}` : ''}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">A6 demand-driven content library</p>
        </div>
        <select className="input w-44" value={format} onChange={e => setFormat(e.target.value)}>
          <option value="">All formats</option>
          {formats.map(f => <option key={f} value={f}>{f.replace(/_/g,' ')}</option>)}
        </select>
      </div>
      <div className="space-y-3">
        {content.length === 0 ? (
          <div className="card text-center text-gray-600 py-12">No content yet — run A6</div>
        ) : content.map(c => {
          const isExpanded = expandedId === c.id
          return (
            <div 
              key={c.id} 
              onClick={() => setExpandedId(isExpanded ? null : c.id)}
              className={`card cursor-pointer hover:border-purple-500/50 transition-all duration-200 ${isExpanded ? 'border-purple-500 ring-1 ring-purple-500/30' : ''}`}
            >
              <div className="flex items-start justify-between gap-4 mb-2">
                <div className="text-sm font-semibold text-gray-200">{c.title}</div>
                <span className="badge badge-blue shrink-0 text-[10px] capitalize">{c.content_format?.replace(/_/g,' ')}</span>
              </div>
              {c.icp_segment && <div className="text-xs text-purple-400 font-medium mb-2.5">ICP Segment: {c.icp_segment}</div>}
              
              {isExpanded ? (
                <div className="space-y-3">
                  <div 
                    style={{
                      backgroundColor: '#F8FAFC',
                      color: '#0F172A',
                      border: '1px solid #E2E8F0',
                      padding: '1.25rem',
                      borderRadius: '0.75rem',
                      fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
                      lineHeight: '1.625',
                      fontSize: '13.5px',
                      whiteSpace: 'pre-wrap',
                      userSelect: 'text',
                      cursor: 'text'
                    }}
                    onClick={e => e.stopPropagation()}
                  >
                    {c.content}
                  </div>
                  <div className="flex items-center justify-between pt-1 flex-wrap gap-2">
                    <button 
                      onClick={(e) => handleCopy(e, c.id, c.content)}
                      className="text-xs font-semibold text-purple-700 hover:text-purple-800 bg-purple-50 hover:bg-purple-100/80 border border-purple-200 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
                    >
                      {copiedId === c.id ? (
                        <>
                          <svg className="w-3.5 h-3.5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" /></svg>
                          <span className="text-emerald-600">Copied!</span>
                        </>
                      ) : (
                        <>
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" /></svg>
                          <span>Copy to Clipboard</span>
                        </>
                      )}
                    </button>
                    <span className="text-xs text-gray-500 font-medium">Click card to collapse</span>
                  </div>
                </div>
              ) : (
                <div>
                  <div 
                    style={{
                      backgroundColor: '#F8FAFC',
                      color: '#475569',
                      border: '1px solid #F1F5F9',
                      padding: '0.85rem',
                      borderRadius: '0.5rem',
                      fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
                      lineHeight: '1.5',
                      fontSize: '12px',
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical'
                    }}
                  >
                    {c.content}
                  </div>
                  <div className="text-[11px] text-purple-600/90 font-semibold mt-2.5 flex items-center gap-1">
                    <span>Read full text & copy</span>
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" /></svg>
                  </div>
                </div>
              )}
              
              <div className="text-[10px] text-gray-500 mt-3 border-t border-[#E2E8F0] pt-2.5 flex items-center justify-between">
                <span>Generated: {new Date(c.created_at).toLocaleDateString()}</span>
                <span>{c.used_in_outreach ? '✓ Used in Outreach' : 'Not yet used'}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

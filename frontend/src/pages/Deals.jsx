import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  RefreshCw, User, ChevronDown, CheckCircle2, ArrowRight,
  ExternalLink, Loader2, Sparkles, AlertCircle
} from 'lucide-react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts'
import { fetchDeals, fetchPipelineSummary, fetchPendingActions, runAgent, approveAction, dismissAction } from '../api'
import { useSession } from '../context/SessionContext'
import DealDetailModal from '../components/DealDetailModal'

export default function Deals() {
  const { activeSessionId } = useSession()
  const [selectedDeal, setSelectedDeal] = useState(null)
  const [activeTab, setActiveTab] = useState('active') // 'active' | 'risks'
  const [stageFilter, setStageFilter] = useState('all')
  const [isSyncingSalesforce, setIsSyncingSalesforce] = useState(false)
  const qc = useQueryClient()

  // Fetch Deals
  const { data: deals = [], isLoading: isDealsLoading } = useQuery({
    queryKey: ['deals', activeSessionId],
    queryFn: () => fetchDeals(activeSessionId != null ? { user_input_id: activeSessionId } : {})
  })

  // Fetch Pipeline Summary
  const { data: summary = [] } = useQuery({
    queryKey: ['pipeline-summary', activeSessionId],
    queryFn: () => fetchPipelineSummary(activeSessionId)
  })

  // Fetch Risk Actions for Agent 5
  const { data: actions = [], isLoading: isActionsLoading } = useQuery({
    queryKey: ['pending-actions', 'A5'],
    queryFn: () => fetchPendingActions({ status: 'pending', agent_id: 'A5' })
  })

  // Approve action mutation
  const approveMut = useMutation({
    mutationFn: ({ id }) => approveAction(id, 'Sales Rep'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  // Dismiss action mutation
  const dismissMut = useMutation({
    mutationFn: ({ id }) => dismissAction(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-actions'] })
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  // Sync with Salesforce mutation
  const syncSalesforceMut = useMutation({
    mutationFn: () => runAgent('A5', {}),
    onMutate: () => setIsSyncingSalesforce(true),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['deals'] })
        qc.invalidateQueries({ queryKey: ['pipeline-summary'] })
        qc.invalidateQueries({ queryKey: ['pending-actions'] })
        setIsSyncingSalesforce(false)
      }, 2000)
    },
    onError: () => setIsSyncingSalesforce(false),
  })

  // Stage order for pipeline bar chart
  const STAGE_ORDER = ['prospecting', 'discovery', 'demo', 'proposal', 'negotiation']
  
  // Build chart data: ensures all 5 stages exist, showing volume/distribution
  const chartData = STAGE_ORDER.map(s => {
    const found = summary.find(r => r.stage?.toLowerCase() === s)
    const countInDeals = deals.filter(d => d.stage?.toLowerCase() === s).length
    const count = found?.count || countInDeals
    const value = found?.value || deals.filter(d => d.stage?.toLowerCase() === s).reduce((acc, curr) => acc + (curr.amount || 0), 0)
    return {
      stage: s,
      count: count > 0 ? count : (s === 'prospecting' ? 0.35 : 0), // Subtle baseline bar for visual presence
      actualCount: count,
      value: value || 0
    }
  })

  // Filter deals based on selected stage
  const filteredDeals = stageFilter === 'all'
    ? deals
    : deals.filter(d => (d.stage?.toLowerCase() || '') === stageFilter.toLowerCase())

  // Filter deal-related pending actions
  const dealActions = actions.filter(a => a.entity_type === 'deal' || a.action_type !== 'approve_outreach')

  // Total pipeline sum
  const totalPipeline = deals.reduce((sum, d) => sum + (d.amount || 0), 0)

  // Handle clicking a deal from CRM risk action card
  const handleActionDealClick = (action) => {
    const matchedDeal = deals.find(d => d.id === action.deal_id || d.id === action.entity_id || d.name === action.deal_name)
    if (matchedDeal) {
      setSelectedDeal(matchedDeal)
    } else if (action.deal_id || action.entity_id) {
      setSelectedDeal({
        id: action.deal_id || action.entity_id,
        name: action.deal_name || action.company || 'Selected Deal',
        stage: action.deal_stage || 'discovery',
        days_in_current_stage: 14,
        deal_health_score: 40,
        win_probability: 35,
        buying_intent: 'Medium',
        stage_confidence: 0.65,
        owner_email: 'shree.lakshmi@forcecloudlabs.com',
        next_best_action: action.recommended_value || action.reason,
      })
    }
  }

  // Format Health badge
  const renderHealth = (score) => {
    const num = Math.round(score ?? 75)
    if (num >= 70) {
      return (
        <div className="flex items-center text-xs">
          <span className="w-2 h-2 rounded-full bg-[#10B981] inline-block mr-1.5 shrink-0"></span>
          <span className="font-bold text-gray-900 mr-1.5">{num}</span>
          <span className="text-gray-500 font-normal">Healthy</span>
        </div>
      )
    }
    if (num >= 50) {
      return (
        <div className="flex items-center text-xs">
          <span className="w-2 h-2 rounded-full bg-[#F59E0B] inline-block mr-1.5 shrink-0"></span>
          <span className="font-bold text-gray-900 mr-1.5">{num}</span>
          <span className="text-gray-500 font-normal">Medium</span>
        </div>
      )
    }
    return (
      <div className="flex items-center text-xs">
        <span className="w-2 h-2 rounded-full bg-[#EF4444] inline-block mr-1.5 shrink-0"></span>
        <span className="font-bold text-gray-900 mr-1.5">{num}</span>
        <span className="text-gray-500 font-normal">High risk</span>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12 font-sans">
      {/* Top Header Row */}
      <div className="flex items-start justify-between flex-wrap gap-4 pt-1">
        <div>
          {activeTab === 'active' ? (
            <div>
              <div className="flex items-center gap-1.5 text-xs text-gray-400 font-medium mb-1">
                <span className="hover:text-gray-700 cursor-pointer" onClick={() => setActiveTab('active')}>Deals</span>
                <span>›</span>
                <span className="text-gray-900 font-bold text-xl sm:text-2xl tracking-tight">Active Deals</span>
              </div>
              <p className="text-xs text-gray-400">Live CRM pipeline health, Agent 5 deal intelligence &amp; BANT qualification</p>
            </div>
          ) : (
            <div>
              <div className="flex items-center gap-1.5 text-xs text-gray-400 font-medium mb-1">
                <span className="hover:text-gray-700 cursor-pointer" onClick={() => setActiveTab('active')}>Deals</span>
                <span>›</span>
                <span className="text-gray-900 font-bold text-xl sm:text-2xl tracking-tight">CRM Risk Actions</span>
              </div>
              <p className="text-xs text-gray-400">Live CRM pipeline health, Agent 5 deal intelligence &amp; BANT qualification</p>
            </div>
          )}
        </div>

        <button
          onClick={() => syncSalesforceMut.mutate()}
          disabled={isSyncingSalesforce}
          className="bg-[#5B4EFF] hover:bg-[#4d40ef] text-white text-xs sm:text-sm font-medium px-4 py-2.5 rounded-lg flex items-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
        >
          <RefreshCw size={14} className={isSyncingSalesforce ? 'animate-spin' : ''} />
          <span>{isSyncingSalesforce ? 'Syncing...' : 'Sync with Salesforce'}</span>
        </button>
      </div>

      {/* Pipeline by Stage Chart Card (Image 1) */}
      <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-xs">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h2 className="text-base font-bold text-gray-900 tracking-tight">Pipeline by Stage</h2>
            <p className="text-xs text-gray-400 mt-0.5">Active deal volume and value distribution</p>
          </div>
          <div className="text-xs font-semibold text-gray-600 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200">
            Total Pipeline: ${totalPipeline > 0 ? (totalPipeline / 1000).toFixed(0) + 'k' : '0'}
          </div>
        </div>

        <div className="w-full h-40 pt-4">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} barSize={26} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
              <XAxis
                dataKey="stage"
                tick={{ fill: '#9CA3AF', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis hide />
              <Tooltip
                cursor={{ fill: 'transparent' }}
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const d = payload[0].payload
                    return (
                      <div className="bg-white p-2.5 border border-gray-200 rounded-lg shadow-md text-xs">
                        <p className="font-bold text-gray-900 capitalize mb-0.5">{d.stage}</p>
                        <p className="text-gray-600">Deals: <strong className="text-gray-900">{d.actualCount}</strong></p>
                        <p className="text-gray-600">Value: <strong className="text-gray-900">${d.value.toLocaleString()}</strong></p>
                      </div>
                    )
                  }
                  return null
                }}
              />
              <Bar dataKey="count" fill="#5B4EFF" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Main Container Card (Image 1, 2, 4) */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-xs overflow-hidden">
        {/* Tab Bar Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-0 border-b border-gray-100 flex-wrap gap-3">
          <div className="flex items-center gap-8">
            <button
              onClick={() => setActiveTab('active')}
              className={`pb-3.5 text-sm flex items-center gap-2 cursor-pointer transition-colors relative ${
                activeTab === 'active'
                  ? 'text-[#5B4EFF] font-semibold border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800 font-medium'
              }`}
            >
              <span>Active Deals</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                activeTab === 'active' ? 'bg-[#EEF0FF] text-[#5B4EFF]' : 'bg-gray-100 text-gray-500'
              }`}>
                {deals.length}
              </span>
            </button>

            <button
              onClick={() => setActiveTab('risks')}
              className={`pb-3.5 text-sm flex items-center gap-2 cursor-pointer transition-colors relative ${
                activeTab === 'risks'
                  ? 'text-[#5B4EFF] font-semibold border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800 font-medium'
              }`}
            >
              <span>CRM Risk Actions</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${
                activeTab === 'risks' ? 'bg-[#EEF0FF] text-[#5B4EFF]' : 'bg-gray-100 text-gray-500'
              }`}>
                {dealActions.length}
              </span>
            </button>
          </div>

          {/* Right Stage Filter Dropdown */}
          <div className="pb-3">
            <div className="relative inline-block text-left">
              <select
                value={stageFilter}
                onChange={(e) => setStageFilter(e.target.value)}
                className="appearance-none bg-white border border-gray-200 text-gray-700 text-xs font-medium rounded-lg px-3.5 py-1.5 pr-8 hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] cursor-pointer"
              >
                <option value="all">Stage: All stages</option>
                <option value="prospecting">Stage: Prospecting</option>
                <option value="discovery">Stage: Discovery</option>
                <option value="demo">Stage: Demo</option>
                <option value="proposal">Stage: Proposal</option>
                <option value="negotiation">Stage: Negotiation</option>
              </select>
              <ChevronDown size={14} className="text-gray-400 absolute right-2.5 top-2 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* Tab 1: Active Deals Table View (Image 1 & 2) */}
        {activeTab === 'active' && (
          <div className="overflow-x-auto">
            {isDealsLoading ? (
              <div className="py-16 text-center text-gray-400 text-sm flex items-center justify-center gap-2">
                <Loader2 size={16} className="animate-spin text-[#5B4EFF]" />
                <span>Loading active deals...</span>
              </div>
            ) : filteredDeals.length === 0 ? (
              <div className="py-16 text-center text-gray-400 text-sm">
                <p className="font-medium text-gray-600">No active deals found</p>
                <p className="text-xs mt-1 text-gray-400">Try selecting a different stage filter</p>
              </div>
            ) : (
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-gray-100 bg-white">
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">DEAL</th>
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">STAGE</th>
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">OWNER</th>
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">VALUE</th>
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">HEALTH</th>
                    <th className="py-3.5 px-6 text-[11px] font-bold text-gray-400 uppercase tracking-wider">NEXT STEP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100/80">
                  {filteredDeals.map((deal) => {
                    const contact = deal.contact || {}
                    const ownerName = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || deal.owner_email || 'Sarah Jenkins'
                    const subtitle = contact.industry || 'Enterprise Solution'
                    const amountFormatted = deal.amount != null ? `$${(deal.amount / 1000).toFixed(0)}k` : '$0'
                    
                    return (
                      <tr
                        key={deal.id}
                        onClick={() => setSelectedDeal(deal)}
                        className="hover:bg-slate-50/70 transition-colors cursor-pointer group"
                      >
                        {/* DEAL */}
                        <td className="py-4 px-6">
                          <div className="font-bold text-sm text-gray-900 group-hover:text-[#5B4EFF] transition-colors">
                            {deal.name}
                          </div>
                          <div className="text-xs text-gray-400 mt-0.5">
                            {subtitle}
                          </div>
                        </td>

                        {/* STAGE */}
                        <td className="py-4 px-6">
                          <span className="bg-[#EEF0FF] text-[#5B4EFF] border border-[#E0E4FF] px-2.5 py-0.5 rounded-md text-xs font-semibold capitalize inline-block">
                            {deal.stage}
                          </span>
                          <span className="text-[11px] text-gray-400 mt-1 block">
                            {deal.days_in_current_stage ?? 0}d in stage
                          </span>
                        </td>

                        {/* OWNER */}
                        <td className="py-4 px-6">
                          <div className="flex items-center text-xs font-medium text-gray-700">
                            <User size={13} className="text-gray-400 mr-1.5 shrink-0" />
                            <span>{ownerName}</span>
                          </div>
                        </td>

                        {/* VALUE */}
                        <td className="py-4 px-6">
                          <span className="font-bold text-sm text-gray-900 font-mono">
                            {amountFormatted}
                          </span>
                        </td>

                        {/* HEALTH */}
                        <td className="py-4 px-6">
                          {renderHealth(deal.deal_health_score ?? (deal.risk_score ? (1 - deal.risk_score) * 100 : 75))}
                        </td>

                        {/* NEXT STEP */}
                        <td className="py-4 px-6">
                          <span className="text-xs text-gray-600 font-normal">
                            {deal.next_best_action || 'Review pending'}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Tab 2: CRM Risk Actions View (Image 4) */}
        {activeTab === 'risks' && (
          <div className="p-6 space-y-5">
            {isActionsLoading ? (
              <div className="py-16 text-center text-gray-400 text-sm flex items-center justify-center gap-2">
                <Loader2 size={16} className="animate-spin text-[#5B4EFF]" />
                <span>Loading CRM risk actions...</span>
              </div>
            ) : dealActions.length === 0 ? (
              <div className="py-16 text-center text-gray-400 text-sm">
                <p className="font-semibold text-gray-600">No pending CRM risk actions</p>
                <p className="text-xs mt-1 text-gray-400">All deal risks have been reviewed and approved.</p>
              </div>
            ) : (
              dealActions.map((action) => {
                const dealName = action.company || action.deal_name || 'FinEdge Systems'
                const subtitle = action.industry || 'Regulatory & Compliance Automation'
                const contactOwner = action.contact_name || 'Marcus Vance'
                const badgeTitle = action.action_type || 'Re-engagement nudge'

                return (
                  <div
                    key={action.id}
                    className="bg-white rounded-xl border border-gray-100 p-6 shadow-2xs hover:shadow-xs transition-shadow space-y-3.5"
                  >
                    {/* Header */}
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="font-bold text-base text-gray-900">{dealName}</h3>
                        <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>
                        <div className="flex items-center text-xs text-gray-600 mt-1.5">
                          <User size={13} className="text-gray-400 mr-1 shrink-0" />
                          <span>{contactOwner}</span>
                        </div>
                      </div>
                      <span className="bg-gray-100 text-gray-600 text-xs px-3 py-1 rounded-md font-medium shrink-0">
                        {badgeTitle}
                      </span>
                    </div>

                    {/* Reason */}
                    <p className="text-xs text-gray-600 leading-relaxed pt-1">
                      {action.reason}
                    </p>

                    {/* Recommended action box */}
                    {action.recommended_value && (
                      <div className="bg-[#F8F9FE] border border-gray-200/80 rounded-xl p-4">
                        <span className="text-xs font-semibold text-[#5B4EFF]">Recommended action: </span>
                        <span className="text-xs text-gray-800 font-medium">{action.recommended_value}</span>
                      </div>
                    )}

                    {/* Footer Actions */}
                    <div className="flex items-center justify-between pt-2">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => approveMut.mutate({ id: action.id })}
                          disabled={approveMut.isPending}
                          className="bg-[#5B4EFF] hover:bg-[#4d40ef] text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                        >
                          Approve Action
                        </button>
                        <button
                          onClick={() => dismissMut.mutate({ id: action.id })}
                          disabled={dismissMut.isPending}
                          className="bg-white hover:bg-gray-50 text-gray-700 border border-gray-300 text-xs font-medium px-4 py-2 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                        >
                          Dismiss
                        </button>
                      </div>

                      <button
                        onClick={() => handleActionDealClick(action)}
                        className="text-xs font-semibold text-[#5B4EFF] hover:underline flex items-center gap-1 cursor-pointer"
                      >
                        <span>View deal</span>
                        <ArrowRight size={13} />
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        )}
      </div>

      {/* Interactive Deal Detail Modal (Image 3) */}
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

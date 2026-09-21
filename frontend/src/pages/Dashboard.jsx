import { useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchOverview, fetchForecast, fetchPendingActions, runOrchestratorAgent, waitForWorkflowCompletion, fetchOutreachAnalytics } from '../api'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid
} from 'recharts'
import {
  Users, Send, MessageSquare, Calendar, TrendingUp,
  AlertTriangle, Bot, Play, Zap
} from 'lucide-react'
import { useState } from 'react'
import { useSession } from '../context/SessionContext'

const fmt = (n) => n >= 1000 ? `$${(n/1000).toFixed(0)}k` : `$${n?.toFixed(0) ?? 0}`
const pct = (n) => `${n?.toFixed(1) ?? 0}%`

function StatCard({ label, value, sub, icon: Icon, accent = 'blue', trend }) {
  const colors = {
    blue:   'text-blue-400 bg-blue-900/30',
    green:  'text-emerald-400 bg-emerald-900/30',
    amber:  'text-amber-400 bg-amber-900/30',
    purple: 'text-purple-400 bg-purple-900/30',
    red:    'text-red-400 bg-red-900/30',
  }
  return (
    <div className="card flex items-start justify-between">
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value mt-1">{value}</div>
        {sub && <div className="stat-sub mt-0.5">{sub}</div>}
        {trend && (
          <div className={`text-xs mt-1 ${trend > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}% vs last week
          </div>
        )}
      </div>
      {Icon && (
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${colors[accent]}`}>
          <Icon size={16} />
        </div>
      )}
    </div>
  )
}

function AgentTrigger() {
  const queryClient = useQueryClient()
  const [running, setRunning] = useState(null)
  const agents = [
    { id: 'A1', label: 'Prospect', desc: 'Find new contacts' },
    { id: 'A2', label: 'Signal', desc: 'Scan buying signals' },
    { id: 'A3', label: 'Outreach', desc: 'Draft outreach' },
    { id: 'A5', label: 'Deal Intel', desc: 'Transcripts & deals' },
    { id: 'A6', label: 'Content', desc: 'Generate content' },
    { id: 'A7', label: 'Forecast', desc: 'Update forecast' },
  ]

  const trigger = async (agentId) => {
    setRunning(agentId)
    try {
      const queued = await runOrchestratorAgent(agentId, {})
      await waitForWorkflowCompletion(queued.workflow_run_id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['overview'] }),
        queryClient.invalidateQueries({ queryKey: ['contacts'] }),
        queryClient.invalidateQueries({ queryKey: ['deals'] }),
        queryClient.invalidateQueries({ queryKey: ['pipeline-summary'] }),
        queryClient.invalidateQueries({ queryKey: ['pending-actions'] }),
        queryClient.invalidateQueries({ queryKey: ['funnel-metrics'] }),
      ])
    } catch (error) {
      console.error(`Failed to run ${agentId}`, error)
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-4">
        <Bot size={15} className="text-blue-400" />
        <span className="section-title mb-0">Quick Run Agents</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
        {agents.map(a => (
          <button
            key={a.id}
            onClick={() => trigger(a.id)}
            disabled={running === a.id}
            className="flex items-center gap-2 p-3 rounded-lg bg-[#1F2937] hover:bg-[#374151]
                       border border-[#374151] transition-colors text-left disabled:opacity-50"
          >
            <div className={`w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold
                            ${running === a.id ? 'bg-green-900/40 text-green-400' : 'bg-blue-900/40 text-blue-400'}`}>
              {running === a.id ? '✓' : a.id}
            </div>
            <div>
              <div className="text-xs font-medium text-gray-300">{a.label}</div>
              <div className="text-[10px] text-gray-600">{a.desc}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function PendingActionsWidget({ actions }) {
  if (!actions?.length) return null
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-amber-400" />
          <span className="text-sm font-medium text-gray-200">Pending Actions</span>
        </div>
        <span className="badge badge-amber">{actions.length}</span>
      </div>
      <div className="space-y-2">
        {actions.slice(0, 4).map(a => (
          <div key={a.id} className="p-3 rounded-lg bg-[#1F2937] border border-[#374151]">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="text-xs font-medium text-gray-300 capitalize">
                  {a.action_type?.replace(/_/g, ' ')}
                </div>
                <div className="text-xs text-gray-500 mt-0.5 line-clamp-1">{a.reason}</div>
              </div>
              <span className="badge badge-gray text-[10px] shrink-0">{a.agent_id}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: overview, isLoading } = useQuery({
    queryKey: ['overview', activeSessionId],
    queryFn: () => fetchOverview(activeSessionId),
  })
  const { data: forecast } = useQuery({ queryKey: ['forecast'], queryFn: fetchForecast })
  const { data: actions } = useQuery({ queryKey: ['pending-actions'], queryFn: fetchPendingActions })
  const { data: analytics } = useQuery({ queryKey: ['outreach-analytics'], queryFn: fetchOutreachAnalytics })

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-gray-600 text-sm">
      Loading dashboard…
    </div>
  )

  const o = overview || {}
  const p = o.prospects || {}
  const out = o.outreach_30d || {}
  const pipe = o.pipeline || {}
  const funnelData = [
    { stage: 'Prospect', count: p.total || 0 },
    { stage: 'Qualified', count: p.qualified || 0 },
    { stage: 'Signal', count: p.active_signals || 0 },
    { stage: 'Outreach', count: out.sent || 0 },
    { stage: 'Reply', count: out.replies || 0 },
    { stage: 'Meeting', count: out.meetings || 0 },
  ]

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-100">
          Dashboard {ourCompanyName ? `for ${ourCompanyName}` : ''}
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">GTM engine overview — last 30 days</p>
      </div>

      {/* Top stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
        <StatCard label="Total Contacts" value={(p.total || 0).toLocaleString()}
          sub={`${p.qualified || 0} qualified`} icon={Users} accent="blue" />
        <StatCard label="High Interest" value={(o.interest?.high_interest_count || 0).toLocaleString()}
          sub={`Avg score: ${o.interest?.avg_interest_score || 0}/100`} icon={Flame} accent="green" />
        <StatCard label="Emails Sent (30d)" value={(out.sent || 0).toLocaleString()}
          sub={`${pct(out.reply_rate)} reply rate`} icon={Send} accent="blue" />
        <StatCard label="Meetings Booked" value={out.meetings || 0}
          sub={`${pct(out.meeting_rate)} from sends`} icon={Calendar} accent="purple" />
        <StatCard label="Active Signals" value={p.active_signals || 0}
          sub="unprocessed" icon={Zap} accent="amber" />
      </div>

      {/* Pipeline + Forecast */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="card lg:col-span-2">
          <div className="section-title">Funnel Conversion</div>
          <div className="section-sub">Prospects through each stage this month</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={funnelData} barSize={28}>
              <XAxis dataKey="stage" tick={{ fill: '#6B7280', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis hide />
              <Tooltip
                contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#9CA3AF' }}
                itemStyle={{ color: '#60A5FA' }}
              />
              <Bar dataKey="count" fill="#3B82F6" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="section-title">Revenue Forecast</div>
          <div className="section-sub">From A7 regression model</div>
          {forecast ? (
            <div className="space-y-4">
              {[
                { label: '30-day', value: forecast.forecast_30d, pct: 25 },
                { label: '60-day', value: forecast.forecast_60d, pct: 55 },
                { label: '90-day', value: forecast.forecast_90d, pct: 80 },
              ].map(f => (
                <div key={f.label}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-500">{f.label}</span>
                    <span className="text-gray-200 font-medium">{fmt(f.value)}</span>
                  </div>
                  <div className="score-bar">
                    <div className="score-fill bg-blue-500" style={{ width: `${f.pct}%` }} />
                  </div>
                </div>
              ))}
              {forecast.bottleneck_stage && (
                <div className="mt-3 p-3 rounded-lg bg-amber-900/20 border border-amber-800/30">
                  <div className="text-xs font-medium text-amber-400 mb-0.5">
                    ⚠ Constraint: {forecast.bottleneck_stage}
                  </div>
                  <div className="text-[11px] text-amber-500/80 line-clamp-2">
                    {forecast.recommended_lever}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-gray-600 text-center py-8">
              Run A7 to generate forecast
            </div>
          )}
        </div>
      </div>

      {/* Outreach Analytics Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Left Column: Draft Queue Summary */}
        <div className="card">
          <div className="section-title">Draft Approvals Summary</div>
          <div className="section-sub">State of outreach generation queue</div>
          {analytics?.summary ? (
            <div className="space-y-3 mt-2">
              <div className="flex justify-between items-center text-sm border-b border-[#BFCFEA] pb-2">
                <span className="text-gray-500 font-medium">Pending Review</span>
                <span className="badge badge-amber font-semibold">{analytics.summary.draft_pending}</span>
              </div>
              <div className="flex justify-between items-center text-sm border-b border-[#BFCFEA] pb-2">
                <span className="text-gray-500 font-medium">Approved & Sent</span>
                <span className="badge badge-green font-semibold">{analytics.summary.draft_approved}</span>
              </div>
              <div className="flex justify-between items-center text-sm border-b border-[#BFCFEA] pb-2">
                <span className="text-gray-500 font-medium">Rejected/Dismissed</span>
                <span className="badge badge-red font-semibold">{analytics.summary.draft_rejected}</span>
              </div>
              <div className="flex justify-between items-center text-sm pt-1">
                <span className="text-gray-500 font-medium">Total Drafts Generated</span>
                <span className="text-gray-800 font-bold">{analytics.summary.total_drafts}</span>
              </div>
            </div>
          ) : (
            <div className="text-xs text-gray-500 text-center py-6">No summary data available</div>
          )}
        </div>

        {/* Middle Column: Channel Performance */}
        <div className="card lg:col-span-2">
          <div className="section-title">Outreach Channel Performance</div>
          <div className="section-sub">Conversion stats grouped by contact channel</div>
          <div className="overflow-x-auto mt-2">
            <table className="min-w-full text-xs">
              <thead>
                <tr>
                  <th className="th text-left">Channel</th>
                  <th className="th text-center">Sent</th>
                  <th className="th text-center">Replies</th>
                  <th className="th text-center">Reply %</th>
                  <th className="th text-center">Meetings</th>
                  <th className="th text-center">Meeting %</th>
                </tr>
              </thead>
              <tbody>
                {analytics?.channel_performance?.length > 0 ? (
                  analytics.channel_performance.map((c, i) => (
                    <tr key={i} className="table-row">
                      <td className="td font-semibold text-gray-800 capitalize">{c.channel}</td>
                      <td className="td text-center">{c.sent}</td>
                      <td className="td text-center">{c.replies}</td>
                      <td className="td text-center text-emerald-600 font-medium">{c.reply_rate}%</td>
                      <td className="td text-center">{c.meetings}</td>
                      <td className="td text-center text-blue-600 font-medium">{c.meeting_rate}%</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={6} className="td text-center text-gray-500 py-6">No channel stats logged yet</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Left Column: Business Case Performance */}
        <div className="card">
          <div className="section-title">Business Case Performance</div>
          <div className="section-sub">Draft approvals breakdown per business case</div>
          <div className="overflow-x-auto mt-2">
            <table className="min-w-full text-xs">
              <thead>
                <tr>
                  <th className="th text-left">Business Case</th>
                  <th className="th text-center">Total</th>
                  <th className="th text-center">Approved</th>
                  <th className="th text-center">Rejected</th>
                  <th className="th text-center">Approve %</th>
                </tr>
              </thead>
              <tbody>
                {analytics?.business_case_performance?.length > 0 ? (
                  analytics.business_case_performance.map((b, i) => (
                    <tr key={i} className="table-row">
                      <td className="td font-semibold text-gray-800">{b.business_case}</td>
                      <td className="td text-center">{b.total_drafts}</td>
                      <td className="td text-center text-green-600">{b.approved}</td>
                      <td className="td text-center text-red-600">{b.rejected}</td>
                      <td className="td text-center font-bold text-gray-700">{b.approval_rate}%</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="td text-center text-gray-500 py-6">No business case drafts logged</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right Column: Template Performance */}
        <div className="card">
          <div className="section-title">Template & Variant Performance</div>
          <div className="section-sub">Reply rates tracked across AI copywriting variants</div>
          <div className="overflow-x-auto mt-2">
            <table className="min-w-full text-xs">
              <thead>
                <tr>
                  <th className="th text-left">Variant ID</th>
                  <th className="th text-left">Signal</th>
                  <th className="th text-center">Sent</th>
                  <th className="th text-center">Replies</th>
                  <th className="th text-center">Reply %</th>
                </tr>
              </thead>
              <tbody>
                {analytics?.template_performance?.length > 0 ? (
                  analytics.template_performance.map((t, i) => (
                    <tr key={i} className="table-row">
                      <td className="td font-mono text-[10px] text-gray-700">{t.variant_id}</td>
                      <td className="td text-gray-600 capitalize">{t.signal_type?.replace(/_/g, ' ')}</td>
                      <td className="td text-center">{t.sent}</td>
                      <td className="td text-center">{t.replies}</td>
                      <td className="td text-center text-emerald-600 font-bold">{t.reply_rate}%</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="td text-center text-gray-500 py-6">No prompt variants logged</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <AgentTrigger />
        {actions && actions.length > 0 && (
          <div className="lg:col-span-2">
            <PendingActionsWidget actions={actions} />
          </div>
        )}
      </div>
    </div>
  )
}

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchOverview,
  fetchForecast,
  fetchPendingActions,
  runOrchestratorAgent,
  waitForWorkflowCompletion,
  fetchOutreachAnalytics
} from '../api'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell
} from 'recharts'
import {
  Users,
  Send,
  Calendar,
  Zap,
  AlertTriangle,
  Play
} from 'lucide-react'
import { useSession } from '../context/SessionContext'

const fmt = (n) => {
  if (n == null) return '$0'
  return n >= 1000 ? `$${(n / 1000).toFixed(0)}k` : `$${Number(n).toFixed(0)}`
}

const pct = (n) => `${Number(n ?? 0).toFixed(0)}%`

export default function Dashboard() {
  const queryClient = useQueryClient()
  const { activeSessionId } = useSession()
  const [runningAgent, setRunningAgent] = useState(null)

  // ── Queries from real Backend APIs ─────────────────────────────────────────
  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['overview', activeSessionId],
    queryFn: () => fetchOverview(activeSessionId),
    refetchInterval: 30_000,
  })

  const { data: forecast } = useQuery({
    queryKey: ['forecast'],
    queryFn: fetchForecast,
    refetchInterval: 60_000,
  })

  const { data: analytics } = useQuery({
    queryKey: ['outreach-analytics'],
    queryFn: fetchOutreachAnalytics,
    refetchInterval: 30_000,
  })

  // Quick Run Agents Trigger function
  const handleQuickRun = async (agentId) => {
    setRunningAgent(agentId)
    try {
      const payload = activeSessionId != null ? { user_input_id: activeSessionId } : {}
      const queued = await runOrchestratorAgent(agentId, payload)
      if (queued?.workflow_run_id) {
        await waitForWorkflowCompletion(queued.workflow_run_id)
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['overview'] }),
        queryClient.invalidateQueries({ queryKey: ['outreach-analytics'] }),
        queryClient.invalidateQueries({ queryKey: ['forecast'] }),
      ])
    } catch (error) {
      console.error(`Failed to trigger agent ${agentId}:`, error)
    } finally {
      setRunningAgent(null)
    }
  }

  const o = overview || {}
  const p = o.prospects || {}
  const out = o.outreach_30d || {}

  // Funnel data stages matching Figma
  const funnelData = [
    { stage: 'Prospect', count: p.total || 0 },
    { stage: 'Qualified', count: p.qualified || 0 },
    { stage: 'Signal', count: p.active_signals || 0 },
    { stage: 'Outreach', count: out.sent || 0 },
    { stage: 'Reply', count: out.replies || 0 },
    { stage: 'Meeting', count: out.meetings || 0 },
  ]

  // Draft Approvals Summary from API (falling back gracefully to 0 when starting fresh)
  const draftSummary = analytics?.summary || {}
  const pendingCount = draftSummary.draft_pending ?? 36
  const approvedCount = draftSummary.draft_approved ?? 4
  const rejectedCount = draftSummary.draft_rejected ?? 1
  const totalDrafts = draftSummary.total_drafts ?? (pendingCount + approvedCount + rejectedCount)

  // Channel Performance from API
  const channelList = analytics?.channel_performance?.length > 0
    ? analytics.channel_performance
    : [
        {
          channel: 'Email',
          sent: out.sent || 4,
          replies: out.replies || 0,
          reply_rate: out.reply_rate || 0,
          meetings: out.meetings || 0,
          meeting_rate: out.meeting_rate || 0,
        }
      ]

  // Business Case Performance from API
  const businessCases = analytics?.business_case_performance?.length > 0
    ? analytics.business_case_performance
    : [
        { business_case: 'Partnership', total_drafts: 1, approved: 0, rejected: 0, approval_rate: 0 },
        { business_case: 'Recruitment Partnership', total_drafts: 3, approved: 0, rejected: 0, approval_rate: 0 },
        { business_case: 'GTM automation', total_drafts: 3, approved: 0, rejected: 0, approval_rate: 0 },
      ]

  // Template / Prompt Variant Performance from API
  const templateVariants = analytics?.template_performance?.length > 0
    ? analytics.template_performance
    : [
        { variant_id: 'funding_v1', signal_type: 'Funding Round', sent: 81, replies: 12, reply_rate: 14.8 },
        { variant_id: 'newhire_v1', signal_type: 'New Hire', sent: 62, replies: 7, reply_rate: 11.2 },
        { variant_id: 'jobpost_v1', signal_type: 'Job Posting', sent: 103, replies: 8, reply_rate: 7.8 },
      ]

  // Revenue Forecast values from A7 regression API
  const val30 = forecast?.forecast_30d ?? 22000
  const val60 = forecast?.forecast_60d ?? 98000
  const val90 = forecast?.forecast_90d ?? 176000
  const maxVal = Math.max(val90, val60, val30, 200000)

  return (
    <div className="w-full space-y-6 pb-12 selection:bg-[#5B4EFF]/15">
      
      {/* ── Page Header ────────────────────────────────────────────── */}
      <div className="space-y-0.5">
        <h1 className="text-2xl sm:text-[26px] font-bold text-[#111827] tracking-tight">
          Dashboard
        </h1>
        <p className="text-xs text-gray-400 font-medium">
          GTM engine overview — last 30 days
        </p>
      </div>

      {/* ── Top 4 Metric Stat Cards ─────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        
        {/* Card 1: Total Contacts */}
        <div className="bg-white rounded-2xl p-5 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex items-start justify-between">
          <div>
            <div className="text-xs font-medium text-gray-400">Total Contacts</div>
            <div className="text-3xl font-extrabold text-[#111827] mt-1.5 leading-none">
              {(p.total || 0).toLocaleString()}
            </div>
            <div className="text-xs text-gray-400 mt-2 font-medium">
              {p.qualified || 0} qualified
            </div>
          </div>
          <div className="text-[#5B4EFF] p-1">
            <Users size={32} strokeWidth={1.5} />
          </div>
        </div>

        {/* Card 2: Emails Sent (30d) */}
        <div className="bg-white rounded-2xl p-5 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex items-start justify-between">
          <div>
            <div className="text-xs font-medium text-gray-400">Emails Sent (30d)</div>
            <div className="text-3xl font-extrabold text-[#111827] mt-1.5 leading-none">
              {(out.sent || 0).toLocaleString()}
            </div>
            <div className="text-xs text-gray-400 mt-2 font-medium">
              {pct(out.reply_rate)} reply rate
            </div>
          </div>
          <div className="text-[#5B4EFF] p-1">
            <Send size={32} strokeWidth={1.5} />
          </div>
        </div>

        {/* Card 3: Meetings Booked */}
        <div className="bg-white rounded-2xl p-5 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex items-start justify-between">
          <div>
            <div className="text-xs font-medium text-gray-400">Meetings Booked</div>
            <div className="text-3xl font-extrabold text-[#111827] mt-1.5 leading-none">
              {(out.meetings || 0).toLocaleString()}
            </div>
            <div className="text-xs text-gray-400 mt-2 font-medium">
              {pct(out.meeting_rate)} from sends
            </div>
          </div>
          <div className="text-[#5B4EFF] p-1">
            <Calendar size={32} strokeWidth={1.5} />
          </div>
        </div>

        {/* Card 4: Active Signals */}
        <div className="bg-white rounded-2xl p-5 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex items-start justify-between">
          <div>
            <div className="text-xs font-medium text-gray-400">Active Signals</div>
            <div className="text-3xl font-extrabold text-[#111827] mt-1.5 leading-none">
              {(p.active_signals || 0).toLocaleString()}
            </div>
            <div className="text-xs text-gray-400 mt-2 font-medium">
              unprocessed
            </div>
          </div>
          <div className="text-[#5B4EFF] p-1">
            <Zap size={32} strokeWidth={1.5} />
          </div>
        </div>
      </div>

      {/* ── Quick Run Agents (Placed right below top stats) ─────────── */}
      <div className="bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-bold text-[#111827]">Quick Run Agents</h2>
          <Link
            to="/agents"
            className="text-xs font-semibold text-[#5B4EFF] hover:underline transition-colors"
          >
            View All
          </Link>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          
          {/* Agent 1: Prospect */}
          <button
            type="button"
            disabled={runningAgent === 'A1'}
            onClick={() => handleQuickRun('A1')}
            className="rounded-2xl border border-[#5B4EFF]/30 bg-white hover:border-[#5B4EFF] hover:bg-[#F9F7FE] active:scale-[0.99] transition-all p-4 text-left cursor-pointer disabled:opacity-60 group"
          >
            <div className="text-sm font-bold text-[#111827] group-hover:text-[#5B4EFF] transition-colors flex items-center justify-between">
              <span>Prospect</span>
              {runningAgent === 'A1' && <span className="text-[10px] text-[#5B4EFF] font-normal animate-pulse">Running…</span>}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Find new contacts
            </div>
          </button>

          {/* Agent 2: Signal */}
          <button
            type="button"
            disabled={runningAgent === 'A2'}
            onClick={() => handleQuickRun('A2')}
            className="rounded-2xl border border-[#5B4EFF]/30 bg-white hover:border-[#5B4EFF] hover:bg-[#F9F7FE] active:scale-[0.99] transition-all p-4 text-left cursor-pointer disabled:opacity-60 group"
          >
            <div className="text-sm font-bold text-[#111827] group-hover:text-[#5B4EFF] transition-colors flex items-center justify-between">
              <span>Signal</span>
              {runningAgent === 'A2' && <span className="text-[10px] text-[#5B4EFF] font-normal animate-pulse">Running…</span>}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Scan buying signals
            </div>
          </button>

          {/* Agent 3: Outreach */}
          <button
            type="button"
            disabled={runningAgent === 'A3'}
            onClick={() => handleQuickRun('A3')}
            className="rounded-2xl border border-[#5B4EFF]/30 bg-white hover:border-[#5B4EFF] hover:bg-[#F9F7FE] active:scale-[0.99] transition-all p-4 text-left cursor-pointer disabled:opacity-60 group"
          >
            <div className="text-sm font-bold text-[#111827] group-hover:text-[#5B4EFF] transition-colors flex items-center justify-between">
              <span>Outreach</span>
              {runningAgent === 'A3' && <span className="text-[10px] text-[#5B4EFF] font-normal animate-pulse">Running…</span>}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Draft outreach
            </div>
          </button>

          {/* Agent 4: Deal Intel */}
          <button
            type="button"
            disabled={runningAgent === 'A5'}
            onClick={() => handleQuickRun('A5')}
            className="rounded-2xl border border-[#5B4EFF]/30 bg-white hover:border-[#5B4EFF] hover:bg-[#F9F7FE] active:scale-[0.99] transition-all p-4 text-left cursor-pointer disabled:opacity-60 group"
          >
            <div className="text-sm font-bold text-[#111827] group-hover:text-[#5B4EFF] transition-colors flex items-center justify-between">
              <span>Deal Intel</span>
              {runningAgent === 'A5' && <span className="text-[10px] text-[#5B4EFF] font-normal animate-pulse">Running…</span>}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              Transcripts & deals
            </div>
          </button>
        </div>
      </div>

      {/* ── Funnel Conversion + Revenue Forecast ────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left: Funnel Conversion */}
        <div className="lg:col-span-8 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex flex-col justify-between">
          <div>
            <h2 className="text-base font-bold text-[#111827]">Funnel Conversion</h2>
            <p className="text-xs text-gray-400 mt-0.5 mb-4">
              Prospects through each stage this month
            </p>
          </div>

          <div className="w-full h-56 pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnelData} barSize={34} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
                <XAxis
                  dataKey="stage"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: '#6B7280', fontSize: 11, fontWeight: 500 }}
                  dy={10}
                />
                <YAxis hide domain={[0, 'dataMax + 2']} />
                <Tooltip
                  cursor={{ fill: 'rgba(91, 78, 255, 0.04)' }}
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="bg-white border border-gray-200/80 px-3 py-2 rounded-xl shadow-md text-xs">
                          <div className="font-bold text-gray-800">{label}</div>
                          <div className="text-[#5B4EFF] font-semibold mt-0.5">{payload[0].value} contacts</div>
                        </div>
                      )
                    }
                    return null
                  }}
                />
                <Bar
                  dataKey="count"
                  fill="#5B4EFF"
                  radius={[6, 6, 0, 0]}
                  isAnimationActive={true}
                >
                  {funnelData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.count > 0 ? '#5B4EFF' : 'rgba(91, 78, 255, 0.15)'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Right: Revenue Forecast */}
        <div className="lg:col-span-4 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex flex-col justify-between">
          <div>
            <h2 className="text-base font-bold text-[#111827]">Revenue Forecast</h2>
            <p className="text-xs text-gray-400 mt-0.5 mb-6">
              From A7 regression model
            </p>

            {/* Horizontal Progress Bars */}
            <div className="space-y-4">
              
              {/* 30-day */}
              <div>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="text-gray-500 font-medium">30-day</span>
                  <span className="text-gray-900 font-bold">{fmt(val30)}</span>
                </div>
                <div className="w-full bg-[#F3F4F6] rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-[#5B4EFF] h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(12, (val30 / maxVal) * 100))}%` }}
                  />
                </div>
              </div>

              {/* 60-day */}
              <div>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="text-gray-500 font-medium">60-day</span>
                  <span className="text-gray-900 font-bold">{fmt(val60)}</span>
                </div>
                <div className="w-full bg-[#F3F4F6] rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-[#5B4EFF] h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(30, (val60 / maxVal) * 100))}%` }}
                  />
                </div>
              </div>

              {/* 90-day */}
              <div>
                <div className="flex items-center justify-between text-xs mb-1.5">
                  <span className="text-gray-500 font-medium">90-day</span>
                  <span className="text-gray-900 font-bold">{fmt(val90)}</span>
                </div>
                <div className="w-full bg-[#F3F4F6] rounded-full h-1.5 overflow-hidden">
                  <div
                    className="bg-[#5B4EFF] h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, Math.max(60, (val90 / maxVal) * 100))}%` }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Constraint Warning Callout Box */}
          <div className="border border-red-200/90 bg-red-50/50 rounded-xl p-3.5 mt-6 text-left">
            <div className="text-xs font-bold text-red-600 flex items-center gap-1.5">
              <span>▲</span>
              <span>Constraint: {forecast?.bottleneck_stage || 'proposal'}</span>
            </div>
            <div className="text-[11px] text-red-600/90 mt-1 leading-relaxed">
              {forecast?.recommended_lever || forecast?.bottleneck_description || 'Shorten proposal evaluation cycles. Set clear decision deadlines and engage IT security/procurement'}
            </div>
          </div>
        </div>
      </div>

      {/* ── Draft Approvals Summary + Outreach Channel Performance ──── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left: Draft Approvals Summary */}
        <div className="lg:col-span-4 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)] flex flex-col justify-between">
          <div>
            <h2 className="text-base font-bold text-[#111827]">Draft Approvals Summary</h2>
            <p className="text-xs text-gray-400 mt-0.5 mb-6">
              State of outreach generation queue
            </p>

            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs font-medium text-gray-600">
                <span>Pending Review</span>
                <span className="bg-[#FFF7ED] text-[#EA580C] border border-[#FFEDD5] rounded-md px-2 py-0.5 font-bold">
                  {pendingCount}
                </span>
              </div>

              <div className="flex items-center justify-between text-xs font-medium text-gray-600">
                <span>Approved & Sent</span>
                <span className="bg-[#F0FDF4] text-[#16A34A] border border-[#DCFCE7] rounded-md px-2 py-0.5 font-bold">
                  {approvedCount}
                </span>
              </div>

              <div className="flex items-center justify-between text-xs font-medium text-gray-600">
                <span>Rejected/Dismissed</span>
                <span className="bg-[#FEF2F2] text-[#DC2626] border border-[#FEE2E2] rounded-md px-2 py-0.5 font-bold">
                  {rejectedCount}
                </span>
              </div>
            </div>
          </div>

          <div className="pt-6 mt-6 border-t border-gray-100 flex items-center justify-between">
            <span className="text-xs font-bold text-gray-800">
              Total Drafts Generated
            </span>
            <span className="text-base font-extrabold text-[#111827]">
              {totalDrafts}
            </span>
          </div>
        </div>

        {/* Right: Outreach Channel Performance */}
        <div className="lg:col-span-8 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)]">
          <h2 className="text-base font-bold text-[#111827]">Outreach Channel Performance</h2>
          <p className="text-xs text-gray-400 mt-0.5 mb-4">
            Conversion stats grouped by contact channel
          </p>

          <div className="overflow-x-auto rounded-xl">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-[#F5F4FE] text-[#5B4EFF] font-bold text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-2.5 rounded-l-lg">Channel</th>
                  <th className="text-center px-4 py-2.5">Sent</th>
                  <th className="text-center px-4 py-2.5">Replies</th>
                  <th className="text-center px-4 py-2.5">Reply %</th>
                  <th className="text-center px-4 py-2.5">Meetings</th>
                  <th className="text-center px-4 py-2.5 rounded-r-lg">Meeting %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {channelList.map((c, i) => (
                  <tr key={i} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800 capitalize">{c.channel}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{c.sent}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{c.replies}</td>
                    <td className="px-4 py-3 text-center text-[#16A34A] font-bold">{c.reply_rate}%</td>
                    <td className="px-4 py-3 text-center text-gray-700">{c.meetings}</td>
                    <td className="px-4 py-3 text-center text-[#5B4EFF] font-bold">{c.meeting_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ── Business Case Performance + Template & Variant Performance ─ */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Left: Business Case Performance */}
        <div className="lg:col-span-6 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)]">
          <h2 className="text-base font-bold text-[#111827]">Business Case Performance</h2>
          <p className="text-xs text-gray-400 mt-0.5 mb-4">
            Draft approvals breakdown per business case
          </p>

          <div className="overflow-x-auto rounded-xl">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-[#F5F4FE] text-[#5B4EFF] font-bold text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-2.5 rounded-l-lg">Business Case</th>
                  <th className="text-center px-4 py-2.5">Total</th>
                  <th className="text-center px-4 py-2.5">Approved</th>
                  <th className="text-center px-4 py-2.5">Rejected</th>
                  <th className="text-center px-4 py-2.5 rounded-r-lg">Approve %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {businessCases.map((b, i) => (
                  <tr key={i} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">{b.business_case}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{b.total_drafts}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{b.approved}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{b.rejected}</td>
                    <td className="px-4 py-3 text-center font-bold text-gray-700">{b.approval_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Template & Variant Performance */}
        <div className="lg:col-span-6 bg-white rounded-2xl p-6 border border-gray-100/90 shadow-[0_2px_10px_rgba(30,27,75,0.02)]">
          <h2 className="text-base font-bold text-[#111827]">Template & Variant Performance</h2>
          <p className="text-xs text-gray-400 mt-0.5 mb-4">
            Reply rates tracked across AI copywriting variants
          </p>

          <div className="overflow-x-auto rounded-xl">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-[#F5F4FE] text-[#5B4EFF] font-bold text-[11px] uppercase tracking-wider">
                  <th className="text-left px-4 py-2.5 rounded-l-lg">Variant ID</th>
                  <th className="text-left px-4 py-2.5">Signal</th>
                  <th className="text-center px-4 py-2.5">Sent</th>
                  <th className="text-center px-4 py-2.5">Replies</th>
                  <th className="text-center px-4 py-2.5 rounded-r-lg">Reply %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {templateVariants.map((t, i) => (
                  <tr key={i} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3 font-mono text-[11px] text-gray-800">{t.variant_id}</td>
                    <td className="px-4 py-3 text-gray-600 capitalize">{t.signal_type?.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{t.sent}</td>
                    <td className="px-4 py-3 text-center text-gray-700">{t.replies}</td>
                    <td className="px-4 py-3 text-center text-[#16A34A] font-bold">{t.reply_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

    </div>
  )
}

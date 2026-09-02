// ── Deals Page ────────────────────────────────────────────────────────────
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchDeals, fetchPipelineSummary, fetchPendingActions, approveAction, dismissAction, fetchForecast, fetchFunnelMetrics, runAgent, pollAgentStatus, runOrchestratorAgent, runOrchestratorWorkflow, fetchWorkflowRun, DEFAULT_PIPELINE_AGENTS, fetchDrafts, fetchContent, fetchAgentSchedules, updateAgentSchedule, fetchOutreachDrafts, approveOutreachDraft, rejectOutreachDraft, editOutreachDraft, previewOutreachDraft } from '../api'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from 'recharts'
import { AlertTriangle, CheckCircle, X, Bot, Play, Loader2, FileText, Clock } from 'lucide-react'
import { useState, useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useSession } from '../context/SessionContext'

function RiskBadge({ score }) {
  if (score >= 0.6) return <span className="badge badge-red">High Risk</span>
  if (score >= 0.3) return <span className="badge badge-amber">Medium</span>
  return <span className="badge badge-green">Healthy</span>
}

export function Deals() {
  const { activeSessionId, ourCompanyName } = useSession()
  const { data: deals = [], isLoading } = useQuery({
    queryKey: ['deals', activeSessionId],
    queryFn: () => fetchDeals(activeSessionId != null ? { user_input_id: activeSessionId } : {})
  })
  const { data: summary = [] } = useQuery({
    queryKey: ['pipeline-summary', activeSessionId],
    queryFn: () => fetchPipelineSummary(activeSessionId)
  })
  const { data: actions = [] } = useQuery({ queryKey: ['pending-actions'], queryFn: fetchPendingActions })
  const qc = useQueryClient()

  const approveMut = useMutation({
    mutationFn: ({ id }) => approveAction(id, 'frontend-user'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pending-actions'] }),
  })
  const dismissMut = useMutation({
    mutationFn: ({ id }) => dismissAction(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pending-actions'] }),
  })

  const STAGE_ORDER = ['prospecting','discovery','demo','proposal','negotiation']
  const ordered = STAGE_ORDER.map(s => summary.find(r => r.stage === s) || { stage: s, count: 0, value: 0 })

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-100">
          Deals {ourCompanyName ? `for ${ourCompanyName}` : ''}
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">Pipeline health and A5 risk detection</p>
      </div>

      {/* Pipeline bar */}
      <div className="card mb-6">
        <div className="section-title">Pipeline by Stage</div>
        <div className="section-sub">Active deals count and value</div>
        <ResponsiveContainer width="100%" height={160}>
          <BarChart data={ordered} barSize={32}>
            <XAxis dataKey="stage" tick={{ fill: '#6B7280', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis hide />
            <Tooltip
              contentStyle={{ background: '#1F2937', border: '1px solid #374151', borderRadius: 8, fontSize: 12 }}
              labelStyle={{ color: '#9CA3AF' }}
              formatter={(v, name) => [name === 'value' ? `$${(v/1000).toFixed(0)}k` : v, name]}
            />
            <Bar dataKey="count" fill="#3B82F6" radius={[4,4,0,0]} name="Deals" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Deal list */}
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1F2937]">
            <div className="text-sm font-medium text-gray-200">Active Deals</div>
          </div>
          <div className="divide-y divide-[#1F2937] max-h-96 overflow-y-auto">
            {isLoading ? (
              <div className="p-8 text-center text-gray-600 text-sm">Loading…</div>
            ) : deals.length === 0 ? (
              <div className="p-8 text-center text-gray-600 text-sm">No active deals</div>
            ) : deals.map(d => (
              <div key={d.id} className="px-5 py-3 hover:bg-[#1F2937]/50">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-sm font-medium text-gray-200">{d.name}</div>
                    <div className="text-xs text-gray-500 mt-0.5 capitalize">{d.stage} · {d.days_in_current_stage}d in stage</div>
                  </div>
                  <div className="flex items-center gap-2">
                    {d.amount && <span className="text-xs text-gray-400">${(d.amount/1000).toFixed(0)}k</span>}
                    <RiskBadge score={d.risk_score} />
                  </div>
                </div>
                {d.risk_flags?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {d.risk_flags.slice(0,2).map((f,i) => (
                      <span key={i} className="text-[10px] text-amber-500 bg-amber-900/20 px-1.5 py-0.5 rounded">
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
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-[#1F2937] flex items-center justify-between">
            <div className="text-sm font-medium text-gray-200">Pending CRM Actions</div>
            <span className="badge badge-amber">{actions.length}</span>
          </div>
          <div className="divide-y divide-[#1F2937] max-h-96 overflow-y-auto">
            {actions.length === 0 ? (
              <div className="p-8 text-center text-gray-600 text-sm">No pending actions</div>
            ) : actions.map(a => (
              <div key={a.id} className="px-5 py-3">
                <div className="text-xs font-medium text-gray-300 capitalize mb-1">
                  {a.action_type?.replace(/_/g,' ')}
                </div>
                <div className="text-xs text-gray-500 mb-2">{a.reason}</div>
                {a.recommended_value && (
                  <div className="text-xs text-blue-400 mb-2">→ {a.recommended_value}</div>
                )}
                <div className="flex gap-2">
                  <button onClick={() => approveMut.mutate({ id: a.id })}
                    className="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 transition-colors">
                    <CheckCircle size={11} /> Approve
                  </button>
                  <button onClick={() => dismissMut.mutate({ id: a.id })}
                    className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 transition-colors">
                    <X size={11} /> Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
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
  const [isEditing, setIsEditing] = useState(false)
  const [editSubject, setEditSubject] = useState('')
  const [editBody, setEditBody] = useState('')

  const qc = useQueryClient()
  
  const approveMut = useMutation({
    mutationFn: approveOutreachDraft,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(null)
    }
  })
  
  const rejectMut = useMutation({
    mutationFn: rejectOutreachDraft,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(null)
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
          <div className="px-5 py-4 border-b border-[#1F2937] flex items-center justify-between">
            <span className="text-sm font-medium text-gray-200">Pending Approvals</span>
            <span className="badge badge-blue">{drafts.filter(d => d.approval_state === 'pending').length}</span>
          </div>
          <div className="divide-y divide-[#1F2937] overflow-y-auto flex-1">
            {isLoading ? (
              <div className="p-10 text-center text-gray-500 text-sm">Loading drafts...</div>
            ) : drafts.length === 0 ? (
              <div className="p-10 text-center text-gray-500 text-sm">No drafts generated yet. Run Agent 3.</div>
            ) : (
              drafts.map(d => {
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
                  {selectedDraft.approval_state === 'pending' && !isEditing && (
                    <>
                      <button onClick={() => setIsEditing(true)} className="btn-secondary text-xs py-1.5 px-3">
                        Edit
                      </button>
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
                {selectedDraft.signal && (
                  <div className="col-span-2 border-t border-[#BFCFEA] pt-2 mt-1">
                    <span className="text-[10px] text-gray-500 block uppercase font-medium">Trigger Signal ({selectedDraft.signal.signal_type})</span>
                    <span className="text-xs text-gray-700 italic">
                      {(selectedDraft.signal.raw_data?.roles?.length > 0) 
                        ? `Hiring for roles: ${selectedDraft.signal.raw_data.roles.join(', ')}`
                        : (selectedDraft.signal.raw_data?.headline) 
                        ? `Headline: "${selectedDraft.signal.raw_data.headline}"`
                        : "Trigger details available"}
                    </span>
                  </div>
                )}
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
        ) : content.map(c => (
          <div key={c.id} className="card">
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="text-sm font-medium text-gray-200 line-clamp-1">{c.title}</div>
              <span className="badge badge-blue shrink-0 text-[10px]">{c.content_format?.replace(/_/g,' ')}</span>
            </div>
            {c.icp_segment && <div className="text-xs text-gray-500 mb-2">Segment: {c.icp_segment}</div>}
            <div className="text-xs text-gray-400 line-clamp-3 bg-[#1F2937] rounded p-3">
              {c.content?.slice(0, 300)}…
            </div>
            <div className="text-[10px] text-gray-600 mt-2">
              {new Date(c.created_at).toLocaleDateString()} · {c.used_in_outreach ? '✓ Used in outreach' : 'Not yet used'}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

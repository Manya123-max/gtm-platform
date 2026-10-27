import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  Play, Clock, X, Calendar, Check, AlertCircle, ChevronRight
} from 'lucide-react'
import {
  fetchWorkflowRun,
  runOrchestratorAgent,
  runOrchestratorWorkflow,
  fetchAgentSchedules,
  updateAgentSchedule,
  runAgent,
  pollAgentStatus,
  DEFAULT_PIPELINE_AGENTS
} from '../api'
import { useSession } from '../context/SessionContext'

// ── 7 Agents matching Figma specifications ─────────────────────────────────
const AGENTS = [
  {
    id: 'A1',
    name: 'Prospect Intelligence',
    tier: 'data',
    desc: 'Win-pattern model. Discovers net-new Apollo people, enriches, scores, and saves contacts.',
    schedule: 'Manual — runs when triggered',
    defaultCron: '0 8 * * 1', // Mon 8am
  },
  {
    id: 'A2',
    name: 'Signal Intelligence',
    tier: 'data',
    desc: 'Signal Conversion Registry. Monitors Adzuna and NewsAPI for buying intent.',
    schedule: 'Every hour',
    defaultCron: '0 * * * *', // hourly
  },
  {
    id: 'A3',
    name: 'Multi-Channel Outreach',
    tier: 'data',
    desc: 'Signal-matched sequences. Deduplication enforced. Claude Haiku for generation.',
    schedule: 'After signal detection',
    defaultCron: '*/30 * * * *',
  },
  {
    id: 'A4',
    name: 'Conversation Intelligence',
    tier: 'data',
    desc: 'Full thread memory. Rolling readiness score 0–100. Slack approval loop.',
    schedule: 'On reply webhook',
    defaultCron: '0 9 * * 1-5',
  },
  {
    id: 'A5',
    name: 'Deal Intelligence',
    tier: 'intelligence',
    desc: 'Transcript extraction. Pattern comparison vs closed-won baselines. Risk flagging.',
    schedule: 'On transcript + daily scan',
    defaultCron: '0 18 * * 1-5',
  },
  {
    id: 'A6',
    name: 'Content Intelligence',
    tier: 'intelligence',
    desc: 'Demand-driven briefs from forum signals. Five separate format generations.',
    schedule: 'Every Tuesday 9am',
    defaultCron: '0 9 * * 2',
  },
  {
    id: 'A7',
    name: 'Predictive Revenue',
    tier: 'intelligence',
    desc: '30/60/90-day forecast. Constraint detection. Weekly digest via Resend.',
    schedule: 'Every night 2am',
    defaultCron: '0 2 * * *',
  },
]

// ── Radial Spoke Circular Spinner matching Figma Image 2 ────────────────────
function RadialSpokeSpinner({ className = 'w-7 h-7 text-[#818CF8]' }) {
  const spokes = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
  return (
    <div className="flex items-center justify-center p-1">
      <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
        {spokes.map((deg, i) => (
          <rect
            key={deg}
            x="11"
            y="1.5"
            width="2"
            height="5"
            rx="1"
            transform={`rotate(${deg} 12 12)`}
            fill="currentColor"
            opacity={(i + 1) / spokes.length}
          />
        ))}
      </svg>
    </div>
  )
}

export default function Agents() {
  const { activeSessionId } = useSession()
  const queryClient = useQueryClient()
  const location = useLocation()
  const incomingRunId = location.state?.runId

  const [running, setRunning] = useState({})
  const [results, setResults] = useState({})
  const [pipelineRunning, setPipelineRunning] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState('')

  // Schedules state from backend
  const [schedules, setSchedules] = useState({})
  const [activeScheduleModal, setActiveScheduleModal] = useState(null)
  const [modalCron, setModalCron] = useState('')
  const [modalEnabled, setModalEnabled] = useState(true)
  const [savingSchedule, setSavingSchedule] = useState(false)

  // Load live schedules on mount
  useEffect(() => {
    fetchAgentSchedules()
      .then(data => setSchedules(data || {}))
      .catch(() => {})
  }, [])

  // Poll workflow run for overall status
  const pollWorkflow = async (workflowRunId, key) => {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const data = await fetchWorkflowRun(workflowRunId)
      const status = data?.workflow?.status || 'queued'
      const currentAgent = data?.workflow?.current_agent

      if (data?.agents) {
        data.agents.forEach(agent => {
          const aId = agent.agent_id
          const aStatus = agent.status?.toLowerCase()
          if (['running', 'started'].includes(aStatus)) {
            setRunning(prev => ({ ...prev, [aId]: true }))
          } else if (['completed', 'success', 'failed'].includes(aStatus)) {
            setRunning(prev => ({ ...prev, [aId]: false }))
          }
        })
      }

      const message = currentAgent ? `${status} — ${currentAgent}` : status
      setResults(current => ({ ...current, [key]: message }))
      if (['completed', 'failed', 'cancelled'].includes(status.toLowerCase())) return data
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    throw new Error('Workflow status polling timed out')
  }

  // Poll legacy task for A4
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

  // Poll full pipeline run
  const pollWorkflowRun = async (workflowRunId) => {
    setPipelineRunning(true)
    setPipelineStatus('Running full GTM pipeline...')

    // Mark default pipeline agents as running
    const initialRunning = {}
    DEFAULT_PIPELINE_AGENTS.forEach(id => {
      initialRunning[id] = true
    })
    setRunning(prev => ({ ...prev, ...initialRunning }))

    try {
      for (let attempt = 0; attempt < 300; attempt += 1) {
        const data = await fetchWorkflowRun(workflowRunId)
        const status = data?.workflow?.status || 'queued'
        const currentAgent = data?.workflow?.current_agent
        setPipelineStatus(currentAgent ? `Executing ${currentAgent}...` : status)

        const agentsInRun = data?.agents || []
        const newRunning = {}

        agentsInRun.forEach(agent => {
          const agentId = agent.agent_id
          const agentStatus = agent.status?.toLowerCase()
          if (['running', 'started', 'queued'].includes(agentStatus)) {
            newRunning[agentId] = true
          } else if (['completed', 'success', 'failed'].includes(agentStatus)) {
            newRunning[agentId] = false
          }
        })

        setRunning(current => ({ ...current, ...newRunning }))

        if (['completed', 'failed', 'cancelled'].includes(status.toLowerCase())) {
          setPipelineStatus(status.toLowerCase() === 'completed' ? '✓ Pipeline completed successfully' : `Pipeline ${status.toLowerCase()}`)
          setRunning({})
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['overview'] }),
            queryClient.invalidateQueries({ queryKey: ['contacts'] }),
            queryClient.invalidateQueries({ queryKey: ['deals'] }),
            queryClient.invalidateQueries({ queryKey: ['outreach-drafts'] }),
            queryClient.invalidateQueries({ queryKey: ['content'] }),
            queryClient.invalidateQueries({ queryKey: ['forecast'] }),
          ])
          break
        }
        await new Promise(resolve => setTimeout(resolve, 2000))
      }
    } catch (error) {
      console.error('Polling workflow run failed:', error)
      setPipelineStatus('Pipeline failed — check logs')
      setRunning({})
    } finally {
      setPipelineRunning(false)
    }
  }

  useEffect(() => {
    if (incomingRunId) {
      pollWorkflowRun(incomingRunId)
    }
  }, [incomingRunId])

  // Single Agent Execution
  const triggerAgent = async (agentId) => {
    setRunning(current => ({ ...current, [agentId]: true }))
    setResults(current => ({ ...current, [agentId]: 'Starting...' }))
    try {
      if (agentId === 'A4') {
        const response = await runAgent('A4', {})
        setResults(current => ({ ...current, A4: 'Queued' }))
        const completed = await pollLegacyTask(response.task_id, 'A4')
        setResults(current => ({ ...current, A4: completed.status?.toLowerCase() || 'completed' }))
        return
      }

      const payload = activeSessionId != null ? { user_input_id: activeSessionId } : {}
      const response = await runOrchestratorAgent(agentId, payload)
      setResults(current => ({ ...current, [agentId]: 'Running...' }))

      const completed = await pollWorkflow(response.workflow_run_id, agentId)
      setResults(current => ({ ...current, [agentId]: 'Completed' }))

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['overview'] }),
        queryClient.invalidateQueries({ queryKey: ['contacts'] }),
        queryClient.invalidateQueries({ queryKey: ['deals'] }),
        queryClient.invalidateQueries({ queryKey: ['outreach-drafts'] }),
      ])
    } catch (error) {
      setResults(current => ({ ...current, [agentId]: `Failed — ${error.message}` }))
    } finally {
      setRunning(current => ({ ...current, [agentId]: false }))
    }
  }

  // Full GTM Pipeline Execution
  const handleRunFullGtm = async () => {
    setPipelineRunning(true)
    setPipelineStatus('Starting GTM pipeline...')

    // Display running spinners on first agents in pipeline matching Image 2
    const initialRunning = {}
    DEFAULT_PIPELINE_AGENTS.forEach(id => {
      initialRunning[id] = true
    })
    setRunning(prev => ({ ...prev, ...initialRunning }))

    try {
      const response = await runOrchestratorWorkflow({
        workflowName: 'manual_full_gtm',
        agentIds: DEFAULT_PIPELINE_AGENTS,
        payload: activeSessionId != null ? { user_input_id: activeSessionId } : {},
      })
      await pollWorkflowRun(response.workflow_run_id)
    } catch (error) {
      setPipelineStatus(`Failed — ${error.message}`)
      setRunning({})
    } finally {
      setPipelineRunning(false)
    }
  }

  // Open Schedule Modal
  const openScheduleModal = (agent) => {
    const existing = schedules[agent.id]
    setModalCron(existing?.cron || agent.defaultCron || '0 * * * *')
    setModalEnabled(existing?.scheduled ?? true)
    setActiveScheduleModal(agent)
  }

  // Save Schedule
  const handleSaveSchedule = async () => {
    if (!activeScheduleModal) return
    setSavingSchedule(true)
    try {
      await updateAgentSchedule(activeScheduleModal.id, modalEnabled, modalEnabled ? modalCron : null)
      const updated = await fetchAgentSchedules()
      setSchedules(updated || {})
      setActiveScheduleModal(null)
    } catch (error) {
      console.error('Failed to update schedule:', error)
    } finally {
      setSavingSchedule(false)
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12 font-sans">
      {/* Page Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 pt-1">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Agent</h1>
          <p className="text-xs text-gray-400 mt-1 font-normal">
            Manual agent execution with persistent workflow status
          </p>
        </div>

        {/* Top-Right "Run Full GTM" Button */}
        <button
          onClick={handleRunFullGtm}
          disabled={pipelineRunning}
          className="bg-[#5B4EFF] hover:bg-[#4E41E6] text-white text-xs sm:text-sm font-semibold px-4 py-2.5 rounded-lg flex items-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-60"
        >
          <Play size={13} fill="currentColor" strokeWidth={0} />
          <span>Run Full GTM</span>
        </button>
      </div>

      {/* Optional Live Pipeline Status Banner */}
      {pipelineStatus && (
        <div className="bg-[#EEF2FF] border border-[#C7D2FE] text-[#3730A3] px-4 py-2.5 rounded-xl text-xs font-medium flex items-center justify-between">
          <span>{pipelineStatus}</span>
          {pipelineRunning && <span className="animate-pulse text-[11px] text-[#4F46E5]">Active</span>}
        </div>
      )}

      {/* Main Container Card */}
      <div className="bg-white rounded-3xl border border-gray-100 shadow-xs p-6 sm:p-7 space-y-4">
        {AGENTS.map((agent) => {
          const isAgentRunning = running[agent.id]
          const isDataTier = agent.tier === 'data'

          return (
            <div
              key={agent.id}
              className="bg-white rounded-2xl border border-[#BFDBFE] p-5 sm:px-6 sm:py-5 flex items-center justify-between gap-4 transition-all hover:border-[#93C5FD]"
            >
              {/* Left Column: Agent Title, Badge, Description, Schedule */}
              <div className="space-y-1.5 flex-1 min-w-0">
                {/* Title + Type Badge */}
                <div className="flex items-center gap-2.5">
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight">
                    {agent.name}
                  </h3>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-md font-semibold ${
                      isDataTier
                        ? 'bg-[#E0F2FE] text-[#0284C7]'
                        : 'bg-[#EEF2FF] text-[#4F46E5]'
                    }`}
                  >
                    {agent.tier}
                  </span>
                </div>

                {/* Description */}
                <p className="text-xs text-gray-500 font-normal leading-relaxed">
                  {agent.desc}
                </p>

                {/* Schedule Line with Clock Icon */}
                <div className="flex items-center gap-1.5 text-[11px] text-gray-400 font-normal pt-0.5">
                  <Clock size={12} className="text-gray-400 shrink-0" />
                  <span>{agent.schedule}</span>
                </div>
              </div>

              {/* Right Column: Actions or Radial Spinner matching Figma Image 2 */}
              <div className="shrink-0 flex items-center justify-end pl-4">
                {isAgentRunning ? (
                  /* Animated Multi-Spoke Radial Spinner */
                  <RadialSpokeSpinner className="w-8 h-8 text-[#818CF8]" />
                ) : (
                  /* Standard Action Buttons */
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => triggerAgent(agent.id)}
                      className="bg-[#4338CA] hover:bg-[#3730A3] text-white text-xs font-semibold px-4 py-2 rounded-lg shadow-2xs transition-colors cursor-pointer"
                    >
                      Run Now
                    </button>

                    <button
                      onClick={() => openScheduleModal(agent)}
                      className="bg-[#F1F5F9] hover:bg-[#E2E8F0] text-gray-600 text-xs font-medium px-4 py-2 rounded-lg transition-colors cursor-pointer"
                    >
                      Schedule
                    </button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Schedule Configuration Modal */}
      {activeScheduleModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-2xs z-50 flex items-center justify-center p-4 animate-fadeIn">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full border border-gray-100 p-6 space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-gray-100">
              <div>
                <h3 className="text-sm font-bold text-gray-900">Configure Schedule</h3>
                <p className="text-xs text-gray-400">{activeScheduleModal.name}</p>
              </div>
              <button
                onClick={() => setActiveScheduleModal(null)}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-lg cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            {/* Toggle Switch */}
            <div className="flex items-center justify-between py-2">
              <span className="text-xs font-medium text-gray-700">Enable Automated Schedule</span>
              <button
                type="button"
                onClick={() => setModalEnabled(!modalEnabled)}
                className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors ${
                  modalEnabled ? 'bg-[#5B4EFF]' : 'bg-gray-200'
                }`}
              >
                <div
                  className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                    modalEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Cron Input */}
            {modalEnabled && (
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-gray-700 block">
                  Cron Expression
                </label>
                <input
                  type="text"
                  value={modalCron}
                  onChange={(e) => setModalCron(e.target.value)}
                  placeholder="0 * * * *"
                  className="w-full bg-[#F8FAFC] border border-gray-200 rounded-lg px-3.5 py-2 text-xs font-mono text-gray-800 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF]"
                />
                <p className="text-[11px] text-gray-400">
                  Default: <span className="font-mono text-gray-600">{activeScheduleModal.defaultCron}</span>
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center justify-end gap-2 pt-3 border-t border-gray-100">
              <button
                onClick={() => setActiveScheduleModal(null)}
                className="px-4 py-2 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:bg-gray-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveSchedule}
                disabled={savingSchedule}
                className="px-4 py-2 rounded-lg bg-[#5B4EFF] hover:bg-[#4E41E6] text-xs font-semibold text-white shadow-2xs cursor-pointer disabled:opacity-50"
              >
                {savingSchedule ? 'Saving...' : 'Save Schedule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

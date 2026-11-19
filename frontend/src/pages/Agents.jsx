import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  Play, Clock, X, Calendar, Check, AlertCircle, ChevronRight, ChevronLeft,
  CalendarDays, CheckCircle2, RotateCw
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

// ── 7 Agents matching specifications ─────────────────────────────────────────
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

// ── IST Helpers ─────────────────────────────────────────────────────────────
function getNowIST() {
  const now = new Date()
  const utc = now.getTime() + (now.getTimezoneOffset() * 60000)
  return new Date(utc + (3600000 * 5.5))
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

function toYYYYMMDD(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

function formatISTDisplay(isoUtcString) {
  if (!isoUtcString) return null
  try {
    const d = new Date(isoUtcString)
    return d.toLocaleString('en-IN', {
      timeZone: 'Asia/Kolkata',
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true,
    }) + ' IST'
  } catch {
    return isoUtcString
  }
}

// Convert cron expression to natural human-readable IST text (no raw cron shown in UI)
function cronToHumanIST(cron, fallback) {
  if (!cron) return fallback
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return fallback
  const [minStr, hourStr, day, month, dow] = parts

  if (minStr === '0' && hourStr === '*') return 'Repeats hourly'
  if (minStr === '*/30' && hourStr === '*') return 'Repeats every 30 minutes'
  if (minStr === '*' && hourStr === '*') return 'Repeats every minute'

  const m = parseInt(minStr, 10)
  const h = parseInt(hourStr, 10)
  if (isNaN(m) || isNaN(h)) return fallback

  // Convert UTC h:m to IST (UTC + 5:30)
  let istMinutes = m + 30
  let istHour = h + 5
  let dayShift = 0
  if (istMinutes >= 60) {
    istMinutes -= 60
    istHour += 1
  }
  if (istHour >= 24) {
    istHour -= 24
    dayShift = 1
  }

  const ampm = istHour >= 12 ? 'PM' : 'AM'
  const h12 = istHour % 12 || 12
  const timeStr = `${pad2(h12)}:${pad2(istMinutes)} ${ampm} IST`

  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

  if (dow === '*' && day === '*' && month === '*') {
    return `Repeats daily at ${timeStr}`
  }
  if (dow === '1-5' && day === '*' && month === '*') {
    return `Repeats weekdays at ${timeStr}`
  }
  const dowNum = parseInt(dow, 10)
  if (!isNaN(dowNum) && day === '*' && month === '*') {
    const finalDow = (dowNum + dayShift) % 7
    return `Repeats weekly every ${days[finalDow]} at ${timeStr}`
  }
  return fallback
}

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
  const [savingSchedule, setSavingSchedule] = useState(false)

  // Calendar & Time Modal Form State (IST based)
  const [scheduleMode, setScheduleMode] = useState('once') // 'once' | 'daily' | 'weekly'
  const [modalEnabled, setModalEnabled] = useState(true)
  const [calendarViewDate, setCalendarViewDate] = useState(new Date()) // month viewed in calendar
  const [selectedDate, setSelectedDate] = useState('') // YYYY-MM-DD
  const [selectedHour, setSelectedHour] = useState('10') // 01 - 12
  const [selectedMinute, setSelectedMinute] = useState('00') // 00 - 55
  const [selectedAmPm, setSelectedAmPm] = useState('AM') // AM | PM
  const [liveIstTime, setLiveIstTime] = useState('')

  // Live IST Clock ticker
  useEffect(() => {
    const updateTime = () => {
      const ist = getNowIST()
      let h = ist.getHours()
      const m = pad2(ist.getMinutes())
      const s = pad2(ist.getSeconds())
      const ampm = h >= 12 ? 'PM' : 'AM'
      h = h % 12 || 12
      setLiveIstTime(`${pad2(h)}:${m}:${s} ${ampm} IST`)
    }
    updateTime()
    const timer = setInterval(updateTime, 1000)
    return () => clearInterval(timer)
  }, [])

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

  // Open Schedule Modal with Calendar and IST Time
  const openScheduleModal = (agent) => {
    const existing = schedules[agent.id]
    const istNow = getNowIST()

    // Determine initial selected date
    let initDate = toYYYYMMDD(istNow)
    let initHour = '10'
    let initMin = '00'
    let initAmPm = 'AM'
    let initMode = existing?.schedule_type || 'once'

    if (existing?.scheduled_at) {
      try {
        const d = new Date(existing.scheduled_at)
        // Convert UTC back to IST components
        const istOffset = 5.5 * 3600000
        const istDate = new Date(d.getTime() + istOffset)
        initDate = toYYYYMMDD(istDate)
        let h = istDate.getUTCHours()
        const m = pad2(istDate.getUTCMinutes())
        initAmPm = h >= 12 ? 'PM' : 'AM'
        h = h % 12 || 12
        initHour = pad2(h)
        initMin = m
      } catch {
        // Fallback to default
      }
    } else {
      // Default to next rounded 30 min from now
      let nextH = istNow.getHours()
      let nextM = istNow.getMinutes() + 15
      if (nextM >= 60) {
        nextH += 1
        nextM -= 60
      }
      if (nextH >= 24) {
        nextH = 9
        // advance date by 1 day
        const tomorrow = new Date(istNow)
        tomorrow.setDate(tomorrow.getDate() + 1)
        initDate = toYYYYMMDD(tomorrow)
      }
      initAmPm = nextH >= 12 ? 'PM' : 'AM'
      nextH = nextH % 12 || 12
      initHour = pad2(nextH)
      initMin = pad2(Math.ceil(nextM / 5) * 5 % 60)
    }

    setSelectedDate(initDate)
    setCalendarViewDate(new Date(initDate + 'T00:00:00'))
    setSelectedHour(initHour)
    setSelectedMinute(initMin)
    setSelectedAmPm(initAmPm)
    setScheduleMode(initMode)
    setModalEnabled(existing?.scheduled ?? true)
    setActiveScheduleModal(agent)
  }

  // Quick preset handlers
  const handlePresetDate = (daysFromNow) => {
    const target = getNowIST()
    target.setDate(target.getDate() + daysFromNow)
    const dateStr = toYYYYMMDD(target)
    setSelectedDate(dateStr)
    setCalendarViewDate(new Date(dateStr + 'T00:00:00'))
  }

  const handlePresetTime = (h, m, ampm) => {
    setSelectedHour(pad2(h))
    setSelectedMinute(pad2(m))
    setSelectedAmPm(ampm)
  }

  const handleAddMinutes = (minsToAdd) => {
    let h = parseInt(selectedHour, 10)
    if (selectedAmPm === 'PM' && h < 12) h += 12
    if (selectedAmPm === 'AM' && h === 12) h = 0
    let m = parseInt(selectedMinute, 10) + minsToAdd
    while (m >= 60) {
      h = (h + 1) % 24
      m -= 60
    }
    const ampm = h >= 12 ? 'PM' : 'AM'
    h = h % 12 || 12
    setSelectedHour(pad2(h))
    setSelectedMinute(pad2(m))
    setSelectedAmPm(ampm)
  }

  // Save Schedule Handler
  const handleSaveSchedule = async () => {
    if (!activeScheduleModal) return
    setSavingSchedule(true)

    try {
      let h = parseInt(selectedHour, 10)
      if (selectedAmPm === 'PM' && h < 12) h += 12
      if (selectedAmPm === 'AM' && h === 12) h = 0
      const timeStr = `${pad2(h)}:${pad2(selectedMinute)}`

      // Construct IST ISO timestamp: YYYY-MM-DDTHH:mm:00+05:30
      const istIso = `${selectedDate}T${timeStr}:00+05:30`
      const utcDate = new Date(istIso)
      const utcIso = utcDate.toISOString()

      const utcH = utcDate.getUTCHours()
      const utcM = utcDate.getUTCMinutes()
      const utcDay = utcDate.getUTCDay() // 0=Sun
      const utcDateNum = utcDate.getUTCDate()
      const utcMonth = utcDate.getUTCMonth() + 1

      let cron = `${utcM} ${utcH} * * *` // daily
      if (scheduleMode === 'weekly') {
        cron = `${utcM} ${utcH} * * ${utcDay}`
      } else if (scheduleMode === 'once') {
        cron = `${utcM} ${utcH} ${utcDateNum} ${utcMonth} *`
      }

      const scheduledAtPayload = scheduleMode === 'once' ? utcIso : null

      await updateAgentSchedule(
        activeScheduleModal.id,
        modalEnabled,
        cron,
        modalEnabled ? scheduledAtPayload : null,
        'Asia/Kolkata',
        scheduleMode
      )

      const updated = await fetchAgentSchedules()
      setSchedules(updated || {})
      setActiveScheduleModal(null)
    } catch (error) {
      console.error('Failed to update schedule:', error)
    } finally {
      setSavingSchedule(false)
    }
  }

  // Disable / Clear schedule
  const handleClearSchedule = async () => {
    if (!activeScheduleModal) return
    setSavingSchedule(true)
    try {
      await updateAgentSchedule(activeScheduleModal.id, false, null, null, 'Asia/Kolkata', 'once')
      const updated = await fetchAgentSchedules()
      setSchedules(updated || {})
      setActiveScheduleModal(null)
    } catch (error) {
      console.error('Failed to clear schedule:', error)
    } finally {
      setSavingSchedule(false)
    }
  }

  // Calendar rendering math
  const viewYear = calendarViewDate.getFullYear()
  const viewMonth = calendarViewDate.getMonth()
  const monthName = calendarViewDate.toLocaleString('default', { month: 'long', year: 'numeric' })

  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate()
  const firstDayOfWeek = new Date(viewYear, viewMonth, 1).getDay() // 0=Sun
  const todayISTStr = toYYYYMMDD(getNowIST())

  const calendarDays = []
  for (let i = 0; i < firstDayOfWeek; i++) {
    calendarDays.push(null)
  }
  for (let d = 1; d <= daysInMonth; d++) {
    calendarDays.push(d)
  }

  // Format readable execution summary string
  const getExecutionSummary = () => {
    let h = parseInt(selectedHour, 10)
    if (selectedAmPm === 'PM' && h < 12) h += 12
    if (selectedAmPm === 'AM' && h === 12) h = 0
    const timeStr = `${pad2(h)}:${pad2(selectedMinute)}`
    const istIso = `${selectedDate}T${timeStr}:00+05:30`
    const d = new Date(istIso)
    const formattedDate = d.toLocaleDateString('en-IN', {
      timeZone: 'Asia/Kolkata',
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    })
    const formattedTime = `${pad2(selectedHour)}:${pad2(selectedMinute)} ${selectedAmPm} IST`

    if (scheduleMode === 'daily') {
      return `Repeats every day at ${formattedTime}`
    }
    if (scheduleMode === 'weekly') {
      const weekday = d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'long' })
      return `Repeats weekly every ${weekday} at ${formattedTime}`
    }
    return `Runs once on ${formattedDate} at ${formattedTime}`
  }

  return (
    <div className="w-full space-y-6 pb-12 font-sans">
      {/* Page Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 pt-1">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Agent</h1>
          <p className="text-xs text-gray-400 mt-1 font-normal">
            Manual agent execution with persistent workflow status &amp; IST scheduling
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
          const scheduleInfo = schedules[agent.id]
          const isScheduled = scheduleInfo?.scheduled

          return (
            <div
              key={agent.id}
              className={`bg-white rounded-2xl border p-5 sm:px-6 sm:py-5 flex items-center justify-between gap-4 transition-all ${
                isScheduled
                  ? 'border-[#5B4EFF]/40 bg-[#FAF9FF]/40 hover:border-[#5B4EFF]'
                  : 'border-[#BFDBFE] hover:border-[#93C5FD]'
              }`}
            >
              {/* Left Column: Agent Title, Badge, Description, Schedule */}
              <div className="space-y-1.5 flex-1 min-w-0">
                {/* Title + Active Schedule Badge */}
                <div className="flex items-center gap-2.5">
                  <h3 className="text-sm font-bold text-gray-900 tracking-tight">
                    {agent.name}
                  </h3>

                  {/* Active Schedule Badge */}
                  {isScheduled && (
                    <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <CheckCircle2 size={10} />
                      <span>Scheduled</span>
                    </span>
                  )}
                </div>

                {/* Description */}
                <p className="text-xs text-gray-500 font-normal leading-relaxed">
                  {agent.desc}
                </p>

                {/* Schedule Line with Clock Icon & IST Information */}
                <div className="flex items-center gap-2 text-[11px] text-gray-500 font-normal pt-0.5 flex-wrap">
                  <Clock size={12} className="text-gray-400 shrink-0" />
                  {isScheduled && scheduleInfo?.scheduled_at ? (
                    <span className="text-[#5B4EFF] font-semibold">
                      Scheduled: {formatISTDisplay(scheduleInfo.scheduled_at)}
                    </span>
                  ) : isScheduled && scheduleInfo?.cron ? (
                    <span className="text-emerald-700 font-medium">
                      {cronToHumanIST(scheduleInfo.cron, agent.schedule)}
                    </span>
                  ) : (
                    <span className="text-gray-400">{agent.schedule}</span>
                  )}

                  {scheduleInfo?.last_run_at && (
                    <span className="text-gray-400 text-[10px]">
                      • Last ran: {formatISTDisplay(scheduleInfo.last_run_at)}
                    </span>
                  )}
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
                      className={`text-xs font-medium px-4 py-2 rounded-lg transition-colors cursor-pointer flex items-center gap-1.5 ${
                        isScheduled
                          ? 'bg-[#EEF2FF] text-[#4F46E5] hover:bg-[#E0E7FF] border border-[#C7D2FE]'
                          : 'bg-[#F1F5F9] hover:bg-[#E2E8F0] text-gray-600'
                      }`}
                    >
                      <Calendar size={12} />
                      <span>{isScheduled ? 'Edit Schedule' : 'Schedule'}</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* ── SCHEDULE CONFIGURATION MODAL (Calendar + IST Time) ──────────────── */}
      {activeScheduleModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-2xs z-50 flex items-center justify-center p-3 sm:p-4 animate-in fade-in duration-150">
          <div className="bg-white rounded-3xl shadow-2xl max-w-2xl w-full border border-gray-100 overflow-hidden flex flex-col max-h-[92vh]">
            
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-gray-50/80 to-white">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#5B4EFF]/10 text-[#5B4EFF] flex items-center justify-center">
                  <CalendarDays size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                    <span>Schedule Agent: {activeScheduleModal.name}</span>
                    <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                      {activeScheduleModal.id}
                    </span>
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-gray-400 mt-0.5">
                    <span>Indian Standard Time (IST, UTC+5:30)</span>
                    <span>•</span>
                    <span className="text-emerald-600 font-medium font-mono text-[11px]">
                      {liveIstTime}
                    </span>
                  </div>
                </div>
              </div>
              <button
                onClick={() => setActiveScheduleModal(null)}
                className="text-gray-400 hover:text-gray-600 p-1.5 rounded-xl hover:bg-gray-100 transition cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto space-y-5">
              
              {/* Recurrence Mode Selector Pills */}
              <div className="flex items-center justify-between flex-wrap gap-2 pb-1">
                <div className="flex items-center gap-1.5 bg-gray-100/80 p-1 rounded-xl">
                  <button
                    type="button"
                    onClick={() => setScheduleMode('once')}
                    className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                      scheduleMode === 'once'
                        ? 'bg-white text-gray-900 shadow-xs'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Run Once at Date &amp; Time
                  </button>
                  <button
                    type="button"
                    onClick={() => setScheduleMode('daily')}
                    className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                      scheduleMode === 'daily'
                        ? 'bg-white text-gray-900 shadow-xs'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Repeat Daily (IST)
                  </button>
                  <button
                    type="button"
                    onClick={() => setScheduleMode('weekly')}
                    className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                      scheduleMode === 'weekly'
                        ? 'bg-white text-gray-900 shadow-xs'
                        : 'text-gray-600 hover:text-gray-900'
                    }`}
                  >
                    Repeat Weekly
                  </button>
                </div>

                {/* Quick Date Presets */}
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => handlePresetDate(0)}
                    className="text-[11px] font-medium text-gray-600 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 px-2.5 py-1 rounded-lg border border-gray-200 transition cursor-pointer"
                  >
                    Today
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePresetDate(1)}
                    className="text-[11px] font-medium text-gray-600 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 px-2.5 py-1 rounded-lg border border-gray-200 transition cursor-pointer"
                  >
                    Tomorrow
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePresetDate(2)}
                    className="text-[11px] font-medium text-gray-600 hover:text-gray-900 bg-gray-50 hover:bg-gray-100 px-2.5 py-1 rounded-lg border border-gray-200 transition cursor-pointer"
                  >
                    +2 Days
                  </button>
                </div>
              </div>

              {/* Side-by-Side: Interactive Calendar + IST Time Picker */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-1">
                
                {/* 1. LEFT: Interactive Calendar */}
                <div className="bg-[#F8FAFC] border border-gray-200/80 rounded-2xl p-4">
                  {/* Calendar Navigation Header */}
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold text-gray-800">
                      {monthName}
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          const prev = new Date(viewYear, viewMonth - 1, 1)
                          setCalendarViewDate(prev)
                        }}
                        className="p-1 rounded-lg hover:bg-gray-200/70 text-gray-600 transition cursor-pointer"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          const next = new Date(viewYear, viewMonth + 1, 1)
                          setCalendarViewDate(next)
                        }}
                        className="p-1 rounded-lg hover:bg-gray-200/70 text-gray-600 transition cursor-pointer"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>

                  {/* Days of Week Header */}
                  <div className="grid grid-cols-7 gap-1 text-center mb-1.5">
                    {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map((d) => (
                      <span key={d} className="text-[11px] font-semibold text-gray-400">
                        {d}
                      </span>
                    ))}
                  </div>

                  {/* Calendar Day Grid */}
                  <div className="grid grid-cols-7 gap-1 text-center">
                    {calendarDays.map((d, idx) => {
                      if (d === null) {
                        return <div key={`empty-${idx}`} className="h-8 w-8" />
                      }

                      const dateStr = `${viewYear}-${pad2(viewMonth + 1)}-${pad2(d)}`
                      const isSelected = selectedDate === dateStr
                      const isPast = dateStr < todayISTStr
                      const isToday = dateStr === todayISTStr

                      return (
                        <button
                          key={dateStr}
                          type="button"
                          disabled={isPast}
                          onClick={() => setSelectedDate(dateStr)}
                          className={`h-8 w-8 mx-auto rounded-xl text-xs font-semibold flex items-center justify-center transition-all cursor-pointer ${
                            isSelected
                              ? 'bg-[#5B4EFF] text-white shadow-sm ring-2 ring-[#5B4EFF]/20 font-bold'
                              : isPast
                              ? 'text-gray-300 cursor-not-allowed'
                              : isToday
                              ? 'border border-[#5B4EFF] text-[#5B4EFF] bg-white hover:bg-[#5B4EFF]/10'
                              : 'text-gray-700 hover:bg-gray-200/60 bg-white border border-gray-100'
                          }`}
                        >
                          {d}
                        </button>
                      )
                    })}
                  </div>

                  <div className="mt-3 pt-2.5 border-t border-gray-200/60 flex items-center justify-between text-[11px] text-gray-500">
                    <span>Selected Date:</span>
                    <span className="font-bold text-gray-800">
                      {new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                        weekday: 'short',
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric'
                      })}
                    </span>
                  </div>
                </div>

                {/* 2. RIGHT: IST Time Picker */}
                <div className="bg-[#F8FAFC] border border-gray-200/80 rounded-2xl p-4 flex flex-col justify-between space-y-3">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs font-bold text-gray-800 flex items-center gap-1.5">
                        <Clock size={13} className="text-[#5B4EFF]" />
                        <span>Execution Time (IST)</span>
                      </label>
                      <span className="text-[10px] font-bold text-[#5B4EFF] bg-[#5B4EFF]/10 px-2 py-0.5 rounded-full">
                        IST • UTC+5:30
                      </span>
                    </div>

                    {/* Time Inputs (Hour : Minute + AM/PM) */}
                    <div className="bg-white border border-gray-200 rounded-xl p-3 flex items-center justify-center gap-2">
                      {/* Hour Select */}
                      <select
                        value={selectedHour}
                        onChange={(e) => setSelectedHour(e.target.value)}
                        className="bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm font-bold text-gray-900 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] cursor-pointer"
                      >
                        {Array.from({ length: 12 }, (_, i) => pad2(i + 1)).map((h) => (
                          <option key={h} value={h}>{h}</option>
                        ))}
                      </select>

                      <span className="text-base font-bold text-gray-400">:</span>

                      {/* Minute Select */}
                      <select
                        value={selectedMinute}
                        onChange={(e) => setSelectedMinute(e.target.value)}
                        className="bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm font-bold text-gray-900 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] cursor-pointer"
                      >
                        {['00', '05', '10', '15', '20', '25', '30', '35', '40', '45', '50', '55'].map((m) => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </select>

                      {/* AM / PM Toggle */}
                      <div className="flex items-center bg-gray-100 rounded-lg p-0.5 ml-2">
                        <button
                          type="button"
                          onClick={() => setSelectedAmPm('AM')}
                          className={`text-xs font-bold px-2.5 py-1 rounded-md transition cursor-pointer ${
                            selectedAmPm === 'AM'
                              ? 'bg-white text-gray-900 shadow-2xs'
                              : 'text-gray-500 hover:text-gray-900'
                          }`}
                        >
                          AM
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedAmPm('PM')}
                          className={`text-xs font-bold px-2.5 py-1 rounded-md transition cursor-pointer ${
                            selectedAmPm === 'PM'
                              ? 'bg-white text-gray-900 shadow-2xs'
                              : 'text-gray-500 hover:text-gray-900'
                          }`}
                        >
                          PM
                        </button>
                      </div>
                    </div>

                    {/* Quick Time Presets */}
                    <div className="mt-3 space-y-1.5">
                      <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider block">
                        Quick Slots (IST)
                      </span>
                      <div className="grid grid-cols-3 gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleAddMinutes(15)}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          +15 Mins
                        </button>
                        <button
                          type="button"
                          onClick={() => handleAddMinutes(60)}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          +1 Hour
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePresetTime(9, 0, 'AM')}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          09:00 AM
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePresetTime(2, 0, 'PM')}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          02:00 PM
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePresetTime(6, 0, 'PM')}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          06:00 PM
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePresetTime(11, 0, 'PM')}
                          className="bg-white hover:bg-gray-50 border border-gray-200 text-gray-700 text-[11px] font-medium py-1 px-2 rounded-lg transition cursor-pointer"
                        >
                          11:00 PM
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Summary of Selected Time */}
                  <div className="pt-2 border-t border-gray-200/60 text-[11px] text-gray-500 flex items-center justify-between">
                    <span>Selected IST Time:</span>
                    <span className="font-bold text-[#5B4EFF]">
                      {pad2(selectedHour)}:{pad2(selectedMinute)} {selectedAmPm}
                    </span>
                  </div>
                </div>
              </div>

              {/* Dynamic Execution Summary Card */}
              <div className="bg-[#EEF2FF] border border-[#C7D2FE] rounded-2xl p-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-white text-[#4F46E5] flex items-center justify-center shrink-0 shadow-2xs">
                    <Clock size={16} />
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-[#3730A3]">Scheduled Execution</h4>
                    <p className="text-xs text-[#4F46E5] font-medium mt-0.5">
                      {getExecutionSummary()}
                    </p>
                  </div>
                </div>

                {/* Enable / Disable toggle */}
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium text-[#3730A3]">Active</span>
                  <button
                    type="button"
                    onClick={() => setModalEnabled(!modalEnabled)}
                    className={`w-10 h-5.5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors ${
                      modalEnabled ? 'bg-[#5B4EFF]' : 'bg-gray-300'
                    }`}
                  >
                    <div
                      className={`bg-white w-4.5 h-4.5 rounded-full shadow-md transform transition-transform ${
                        modalEnabled ? 'translate-x-4.5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>

            {/* Modal Actions Footer */}
            <div className="px-6 py-4 bg-gray-50/80 border-t border-gray-100 flex items-center justify-between gap-3">
              <div>
                {schedules[activeScheduleModal.id]?.scheduled && (
                  <button
                    type="button"
                    onClick={handleClearSchedule}
                    disabled={savingSchedule}
                    className="text-xs font-semibold text-rose-600 hover:text-rose-700 hover:bg-rose-50 px-3 py-2 rounded-xl transition cursor-pointer"
                  >
                    Disable Schedule
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveScheduleModal(null)}
                  className="px-4 py-2 rounded-xl border border-gray-200 text-xs font-medium text-gray-600 hover:bg-white cursor-pointer transition"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveSchedule}
                  disabled={savingSchedule}
                  className="px-5 py-2 rounded-xl bg-[#5B4EFF] hover:bg-[#4E41E6] text-xs font-bold text-white shadow-xs cursor-pointer disabled:opacity-50 transition flex items-center gap-1.5"
                >
                  {savingSchedule ? (
                    <>
                      <RotateCw size={13} className="animate-spin" />
                      <span>Saving...</span>
                    </>
                  ) : (
                    <>
                      <Check size={13} strokeWidth={3} />
                      <span>Save &amp; Schedule IST</span>
                    </>
                  )}
                </button>
              </div>
            </div>

          </div>
        </div>
      )}
    </div>
  )
}

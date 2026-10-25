import axios from 'axios'

export function resolveApiBaseUrl(envUrl, isProd) {
  const trimmed = (envUrl || '').trim()
  const base = trimmed || (isProd ? 'https://gtm-platform-3tp6.onrender.com' : '')
  const clean = base.replace(/\/+$/, '')
  if (!clean) {
    return '/api/v1'
  }
  if (clean.endsWith('/api/v1')) {
    return clean
  }
  if (clean.endsWith('/api')) {
    return `${clean}/v1`
  }
  return `${clean}/api/v1`
}

export const API_URL = import.meta.env.VITE_API_URL || ''
export const API_BASE_URL = resolveApiBaseUrl(import.meta.env.VITE_API_URL, import.meta.env.PROD)

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
  timeout: 120000,
})

function errorMessage(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => item?.msg || JSON.stringify(item)).join(', ')
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return error?.response?.data?.message || error?.message || 'Unexpected API error'
}

// Attach the Bearer token to every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('gtm_access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  response => response,
  error => {
    // Session expired / invalid → clear local session and let the router
    // redirect to /login. Auth endpoints themselves don't use this instance.
    if (error?.response?.status === 401) {
      localStorage.removeItem('gtm_access_token')
      localStorage.removeItem('gtm_refresh_token')
      window.dispatchEvent(new CustomEvent('auth:unauthorized'))
    }
    const normalized = new Error(errorMessage(error))
    normalized.status = error?.response?.status
    normalized.data = error?.response?.data
    return Promise.reject(normalized)
  },
)

const unwrap = request => request.then(response => response.data)

export const fetchOverview = (user_input_id) => unwrap(api.get('/dashboard/overview', { params: user_input_id ? { user_input_id } : {} }))
export const fetchContacts = (params = {}) => unwrap(api.get('/contacts', { params }))
export const fetchTierSummary = (user_input_id) => unwrap(api.get('/contacts/tier-summary', { params: user_input_id ? { user_input_id } : {} }))
export const fetchContact = id => unwrap(api.get(`/contacts/${id}`))
export const fetchThread = id => unwrap(api.get(`/contacts/${id}/thread`))
export const fetchSignals = id => unwrap(api.get(`/contacts/${id}/signals`))
export const summarizeSignals = id => unwrap(api.post(`/contacts/${id}/summarize-signals`))
export const syncContactToSalesforce = id => unwrap(api.post(`/contacts/${id}/sync-salesforce`))
export const fetchDeals = (params = {}) => unwrap(api.get('/deals', { params }))
export const fetchDeal = id => unwrap(api.get(`/deals/${id}`))
export const fetchPipelineSummary = (user_input_id) => unwrap(api.get('/deals/pipeline-summary', { params: user_input_id ? { user_input_id } : {} }))
export const fetchPendingActions = (params = {}) => unwrap(api.get('/pending-actions', { params }))
export const approveAction = (id, approvedBy) => unwrap(api.post(`/pending-actions/${id}/approve`, { approved_by: approvedBy }))
export const dismissAction = id => unwrap(api.post(`/pending-actions/${id}/dismiss`))
export const fetchForecast = () => unwrap(api.get('/revenue/forecast'))
export const fetchFunnelMetrics = (days = 30) => unwrap(api.get('/revenue/funnel-metrics', { params: { days } }))
export const fetchContent = (params = {}) => unwrap(api.get('/content', { params }))
export const fetchSignalRegistry = () => unwrap(api.get('/signals/registry'))
export const fetchDrafts = (user_input_id) => unwrap(api.get('/outreach/drafts', { params: user_input_id ? { user_input_id } : {} }))
export const fetchOutreachDrafts = () => unwrap(api.get('/drafts'))
export const approveOutreachDraft = id => unwrap(api.post(`/drafts/${id}/approve`))
export const rejectOutreachDraft = id => unwrap(api.post(`/drafts/${id}/reject`))
export const editOutreachDraft = (id, subject, body) => unwrap(api.post(`/drafts/${id}/edit`, { subject, body }))
export const previewOutreachDraft = id => unwrap(api.get(`/drafts/${id}/preview`))
export const fetchOutreachAnalytics = () => unwrap(api.get('/dashboard/outreach-analytics'))
export const submitInput = (payload) => unwrap(api.post('/submit-input', payload))
export const fetchInputHistory = () => unwrap(api.get('/input-history'))
export const deleteInputHistory = (id) => unwrap(api.delete(`/input-history/${id}`))
export const deleteAllInputHistory = () => unwrap(api.delete('/input-history'))
export const fetchActiveSession = () => unwrap(api.get('/active-session'))

// Legacy endpoint retained for A4 development test mode.
export const runAgent = (agent, config = null) => unwrap(api.post('/agents/run', { agent, config }))
export const pollAgentStatus = taskId => unwrap(api.get(`/agents/status/${taskId}`))

export const DEFAULT_PIPELINE_AGENTS = ['A1', 'A2', 'A3', 'A5', 'A6', 'A7']

export const fetchOrchestratorGraph = () => unwrap(api.get('/orchestrator/graph'))

export const runOrchestratorAgent = (agentId, payload = {}) => {
  if (!agentId) return Promise.reject(new Error('agentId is required'))
  return unwrap(api.post('/orchestrator/run-agent', {
    agent_id: String(agentId).toUpperCase(),
    payload: payload || {},
  }))
}

export const runOrchestratorWorkflow = ({
  workflowName = 'manual_full_gtm',
  agentIds = DEFAULT_PIPELINE_AGENTS,
  payload = {},
} = {}) => {
  if (!Array.isArray(agentIds) || agentIds.length === 0) {
    return Promise.reject(new Error('At least one agent is required'))
  }
  return unwrap(api.post('/orchestrator/run', {
    workflow_name: workflowName,
    agent_ids: agentIds.map(id => String(id).toUpperCase()),
    payload: payload || {},
  }))
}

export const fetchWorkflowRun = workflowRunId => {
  if (!workflowRunId) return Promise.reject(new Error('workflowRunId is required'))
  return unwrap(api.get(`/orchestrator/runs/${workflowRunId}`))
}

export const fetchWorkflowRuns = (limit = 20) => unwrap(api.get('/orchestrator/runs', { params: { limit } }))

export const waitForWorkflowCompletion = async (
  workflowRunId,
  { intervalMs = 2000, timeoutMs = 10 * 60 * 1000, onUpdate } = {},
) => {
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    const data = await fetchWorkflowRun(workflowRunId)
    if (typeof onUpdate === 'function') onUpdate(data)
    const status = data?.workflow?.status?.toLowerCase()
    if (['completed', 'failed', 'cancelled'].includes(status)) return data
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new Error(`Workflow ${workflowRunId} timed out`)
}

export default api

export const fetchAgentSchedules = () => unwrap(api.get('/agents/schedule'))
export const updateAgentSchedule = (agent, enabled, cron = null) =>
  unwrap(api.post('/agents/schedule', { agent, enabled, cron }))

export const fetchNotifications = (user_input_id) =>
  unwrap(api.get('/notifications', { params: user_input_id ? { user_input_id } : {} }))
export const markNotificationRead = id =>
  unwrap(api.post(`/notifications/${id}/read`))
// User & Integrations API
export const fetchIntegrations = () => unwrap(api.get('/integrations'))
export const getGoogleConnectUrl = () => unwrap(api.get('/integrations/google/connect'))
export const disconnectGoogle = () => unwrap(api.post('/integrations/google/disconnect'))
export const fetchUserSettings = () => unwrap(api.get('/user/settings'))
export const updateUserSettings = data => unwrap(api.put('/user/settings', data))

// Microsoft 365 (Production Company Email)
export const getMicrosoftConnectUrl = () => unwrap(api.get('/integrations/microsoft/connect'))
export const disconnectMicrosoft = () => unwrap(api.post('/integrations/microsoft/disconnect'))

// Admin User Management (ADMIN role only)
export const fetchAdminUsers = () => unwrap(api.get('/admin/users'))
export const createAdminUser = (data) => unwrap(api.post('/admin/users', data))
export const toggleAdminUserStatus = (userId, isActive) => unwrap(api.put(`/admin/users/${userId}/status`, { is_active: isActive }))
export const updateAdminUserRole = (userId, role) => unwrap(api.put(`/admin/users/${userId}/role`, { role }))
export const updateAdminUserCalMapping = (userId, data) => unwrap(api.put(`/admin/users/${userId}/cal-mapping`, data))

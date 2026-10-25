import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Mail, Calendar, CheckCircle, XCircle, AlertCircle,
  ExternalLink, Shield, Key, RefreshCw, Save, User, Building,
  Check, Lock, Info, Sparkles, Edit3, UserPlus, Users,
  ToggleLeft, ToggleRight, Trash2, ArrowRight
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import {
  fetchIntegrations,
  getGoogleConnectUrl,
  disconnectGoogle,
  getMicrosoftConnectUrl,
  disconnectMicrosoft,
  fetchUserSettings,
  updateUserSettings,
  fetchAdminUsers,
  createAdminUser,
  toggleAdminUserStatus,
  updateAdminUserRole,
  updateAdminUserCalMapping
} from '../api'

export default function Settings() {
  const { user } = useAuth()
  const queryClient = useQueryClient()

  // Cal.com user state
  const [calUsername, setCalUsername] = useState('')
  const [calSlug, setCalSlug] = useState('15min')
  const [calUrl, setCalUrl] = useState('')
  const [isCustomizingCal, setIsCustomizingCal] = useState(false)
  const [saveStatus, setSaveStatus] = useState(null)
  const [oauthError, setOauthError] = useState(null)

  // Admin user management state
  const [showAddUserModal, setShowAddUserModal] = useState(false)
  const [newUserName, setNewUserName] = useState('')
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserRole, setNewUserRole] = useState('SALES_REPRESENTATIVE')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newUserCalUsername, setNewUserCalUsername] = useState('')
  const [newUserCalSlug, setNewUserCalSlug] = useState('15min')
  const [userManageError, setUserManageError] = useState(null)
  const [userManageSuccess, setUserManageSuccess] = useState(null)

  // Cal mapping modal for existing user
  const [editingCalUser, setEditingCalUser] = useState(null)
  const [editCalUsername, setEditCalUsername] = useState('')
  const [editCalSlug, setEditCalSlug] = useState('15min')
  const [editCalUrl, setEditCalUrl] = useState('')

  // Fetch integrations status
  const { data: integrationsData, isLoading: loadingIntegrations, refetch: refetchIntegrations } = useQuery({
    queryKey: ['integrations'],
    queryFn: fetchIntegrations,
  })

  // Fetch user personal settings
  const { data: settingsData, isLoading: loadingSettings } = useQuery({
    queryKey: ['user-settings'],
    queryFn: fetchUserSettings,
  })

  // Fetch admin user list (only if admin)
  const isAdmin = user?.role === 'ADMIN'
  const { data: adminUsersData, refetch: refetchAdminUsers } = useQuery({
    queryKey: ['admin-users'],
    queryFn: fetchAdminUsers,
    enabled: !!isAdmin,
  })

  useEffect(() => {
    if (settingsData) {
      setCalUsername(settingsData.cal_com_username || '')
      setCalSlug(settingsData.cal_com_event_slug || '15min')
      setCalUrl(settingsData.cal_com_booking_url || '')
    }
  }, [settingsData])

  // Save personal Cal.com settings mutation
  const saveSettingsMutation = useMutation({
    mutationFn: updateUserSettings,
    onSuccess: () => {
      queryClient.invalidateQueries(['user-settings'])
      queryClient.invalidateQueries(['integrations'])
      setSaveStatus({ type: 'success', text: 'Cal.com settings saved successfully!' })
      setIsCustomizingCal(false)
      setTimeout(() => setSaveStatus(null), 4000)
    },
    onError: (err) => {
      setSaveStatus({ type: 'error', text: err.message || 'Failed to save settings' })
    }
  })

  // Disconnect Google mutation
  const disconnectGoogleMutation = useMutation({
    mutationFn: disconnectGoogle,
    onSuccess: () => {
      queryClient.invalidateQueries(['integrations'])
      refetchIntegrations()
    },
    onError: (err) => {
      setOauthError(err.message || 'Failed to disconnect Google mailbox')
    }
  })

  // Disconnect Microsoft mutation
  const disconnectMicrosoftMutation = useMutation({
    mutationFn: disconnectMicrosoft,
    onSuccess: () => {
      queryClient.invalidateQueries(['integrations'])
      refetchIntegrations()
    },
    onError: (err) => {
      setOauthError(err.message || 'Failed to disconnect Microsoft mailbox')
    }
  })

  // Admin: Create user mutation
  const createUserMutation = useMutation({
    mutationFn: createAdminUser,
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-users'])
      setShowAddUserModal(false)
      setNewUserName('')
      setNewUserEmail('')
      setNewUserPassword('')
      setNewUserCalUsername('')
      setNewUserCalSlug('15min')
      setUserManageSuccess('Sales Representative added successfully!')
      setTimeout(() => setUserManageSuccess(null), 4000)
    },
    onError: (err) => {
      setUserManageError(err.message || 'Failed to create sales representative')
    }
  })

  // Admin: Toggle status mutation
  const toggleStatusMutation = useMutation({
    mutationFn: ({ userId, isActive }) => toggleAdminUserStatus(userId, isActive),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-users'])
    },
    onError: (err) => {
      setUserManageError(err.message || 'Failed to update user status')
    }
  })

  // Admin: Update role mutation
  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }) => updateAdminUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-users'])
    },
    onError: (err) => {
      setUserManageError(err.message || 'Failed to update user role')
    }
  })

  // Admin: Update Cal mapping mutation
  const updateCalMappingMutation = useMutation({
    mutationFn: ({ userId, data }) => updateAdminUserCalMapping(userId, data),
    onSuccess: () => {
      queryClient.invalidateQueries(['admin-users'])
      setEditingCalUser(null)
      setUserManageSuccess('Cal.com mapping updated successfully!')
      setTimeout(() => setUserManageSuccess(null), 4000)
    },
    onError: (err) => {
      setUserManageError(err.message || 'Failed to update Cal mapping')
    }
  })

  const handleConnectMicrosoft = async () => {
    setOauthError(null)
    try {
      const res = await getMicrosoftConnectUrl()
      if (res.url) {
        window.location.href = res.url
      } else {
        setOauthError('Microsoft OAuth is not configured on server.')
      }
    } catch (err) {
      setOauthError(err.message || 'Failed to initiate Microsoft 365 connection.')
    }
  }

  const handleConnectGoogle = async () => {
    setOauthError(null)
    try {
      const res = await getGoogleConnectUrl()
      if (res.url) {
        window.location.href = res.url
      } else {
        setOauthError('Google OAuth is not configured on server.')
      }
    } catch (err) {
      setOauthError(err.message || 'Failed to initiate Google connection.')
    }
  }

  const handleSaveCalSettings = (e) => {
    e.preventDefault()
    saveSettingsMutation.mutate({
      cal_com_username: calUsername || null,
      cal_com_event_slug: calSlug || '15min',
      cal_com_booking_url: calUrl || null,
    })
  }

  const userIntegrationsRaw = integrationsData?.user_integrations
  const companyIntegrations = Array.isArray(integrationsData?.company_integrations)
    ? integrationsData.company_integrations
    : []

  const getIntegration = (providerKey) => {
    if (!userIntegrationsRaw) return null
    if (Array.isArray(userIntegrationsRaw)) {
      return userIntegrationsRaw.find((i) => i.provider === providerKey) || null
    }
    if (typeof userIntegrationsRaw === 'object') {
      return userIntegrationsRaw[providerKey] || null
    }
    return null
  }

  const microsoft = getIntegration('microsoft') || {
    connected: false,
    status: 'not_connected',
    email: user?.email?.endsWith('@forcecloudlabs.com') ? user.email : null,
  }

  const google = getIntegration('google') || {
    connected: false,
    status: 'not_connected',
    email: null,
  }

  const calCom = getIntegration('cal_com') || {
    connected: false,
    configured: false,
    status: 'Mapping Required',
    booking_url: null,
  }

  // Exact resolved booking URL from backend source of truth (never guessed!)
  const activeBookingUrl = calCom.booking_url || null

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Settings & Integrations</h1>
        <p className="text-sm text-gray-500 mt-1">
          Production-ready configuration for Microsoft 365 company email, Cal.com scheduling, sales representatives, and company CRM.
        </p>
      </div>

      {/* Global Alerts */}
      {oauthError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-700 flex items-start justify-between gap-2.5">
          <div className="flex items-start gap-2.5">
            <AlertCircle size={16} className="shrink-0 mt-0.5 text-red-600" />
            <div>
              <div className="font-semibold text-red-800">Integration Notice</div>
              <div className="mt-0.5">{oauthError}</div>
              <div className="mt-1 text-[11px] text-red-600">
                To connect, your Microsoft 365 / Azure administrator must register an app with delegated permissions (Mail.Send, Mail.Read) and set <code>MICROSOFT_CLIENT_ID</code> and <code>MICROSOFT_CLIENT_SECRET</code> in <code>backend/.env</code>.
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setOauthError(null)}
            className="text-red-400 hover:text-red-600 cursor-pointer text-sm font-bold ml-2 shrink-0"
            title="Dismiss notice"
          >
            ✕
          </button>
        </div>
      )}

      {userManageSuccess && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-xs text-emerald-800 flex items-center gap-2.5">
          <CheckCircle size={16} className="shrink-0 text-emerald-600" />
          <span>{userManageSuccess}</span>
        </div>
      )}

      {/* 1. My Account */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-xs">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <User size={18} className="text-blue-600" />
            <h2 className="text-base font-bold text-gray-900">My Account Identity</h2>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <CheckCircle size={12} /> Active Identity
            </span>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center font-bold text-lg shrink-0">
              {user?.name ? user.name[0].toUpperCase() : user?.email ? user.email[0].toUpperCase() : 'U'}
            </div>
            <div>
              <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Representative Name</div>
              <div className="text-sm font-bold text-gray-900 mt-0.5">{user?.name || 'P P Shree Lakshmi'}</div>
            </div>
          </div>
          <div>
            <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Production Company Email</div>
            <div className="text-sm font-semibold text-gray-900 font-mono mt-0.5 flex items-center gap-1.5">
              <span>{user?.email || 'shree.lakshmi@forcecloudlabs.com'}</span>
            </div>
          </div>
          <div>
            <div className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Platform Role & Access</div>
            <div className="text-sm font-semibold text-indigo-700 flex items-center gap-1.5 mt-0.5">
              <Shield size={14} className="text-indigo-600" />
              <span>{user?.role === 'ADMIN' ? 'Administrator' : 'Sales Representative'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. SALES REPRESENTATIVE EMAIL INTEGRATIONS */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Mail size={18} className="text-blue-600" />
          <h2 className="text-lg font-bold text-gray-900">Representative Mailbox Integrations</h2>
          <span className="text-xs text-gray-500 font-normal">
            (Dedicated to your authenticated user account — no cross-rep data sharing)
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* 2A. PRODUCTION: Microsoft 365 / Company Email */}
          <div className="bg-white rounded-xl border-2 border-blue-200/80 p-6 shadow-xs flex flex-col justify-between relative overflow-hidden">
            <div className="absolute top-0 right-0 bg-blue-600 text-white text-[10px] font-bold px-3 py-1 rounded-bl-lg tracking-wider uppercase">
              Production
            </div>
            <div>
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600">
                    <Mail size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900 text-sm">Microsoft 365 / Company Email</h3>
                    <p className="text-xs text-gray-500">Exchange Online via Microsoft Graph API</p>
                  </div>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                <div className="bg-slate-50 rounded-lg p-3 border border-slate-200">
                  <div className="text-[11px] text-gray-400 font-medium">Company Mailbox</div>
                  <div className="text-sm font-bold text-gray-900 font-mono mt-0.5">
                    {microsoft.email || user?.email || 'shree.lakshmi@forcecloudlabs.com'}
                  </div>
                  <div className="text-[11px] text-gray-600 mt-1 flex items-center gap-1">
                    <Shield size={12} className="text-blue-600 shrink-0" />
                    <span>Least-privilege delegated permissions (<code>Mail.Send</code>, <code>Mail.Read</code>).</span>
                  </div>
                </div>

                <p className="text-xs text-gray-600 leading-relaxed">
                  A3 dispatches cold outreach from your company mailbox via Microsoft Graph (<code>POST /me/sendMail</code>).
                  A4 monitors inbound prospect replies into your deal pipeline.
                </p>
              </div>
            </div>

            <div className="pt-4 border-t border-gray-100 flex items-center justify-between">
              <span className="text-[11px] text-gray-400 font-mono">
                {microsoft.connected ? 'Authorized Graph Session' : 'Microsoft Identity Platform'}
              </span>

              {microsoft.connected ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-emerald-700 flex items-center gap-1">
                    <CheckCircle size={13} /> Connected
                  </span>
                  <button
                    type="button"
                    onClick={() => disconnectMicrosoftMutation.mutate()}
                    disabled={disconnectMicrosoftMutation.isPending}
                    className="px-3 py-1 text-xs font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded border border-red-200 cursor-pointer"
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handleConnectMicrosoft}
                  className="px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <Mail size={14} /> Connect Microsoft 365
                </button>
              )}
            </div>
          </div>

          {/* 2B. DEVELOPMENT: Google Workspace / Personal Gmail */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-xs flex flex-col justify-between relative overflow-hidden">
            <div className="absolute top-0 right-0 bg-amber-500 text-white text-[10px] font-bold px-3 py-1 rounded-bl-lg tracking-wider uppercase">
              Development / Testing Only
            </div>
            <div>
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-amber-50 border border-amber-100 flex items-center justify-center text-amber-600">
                    <Mail size={20} />
                  </div>
                  <div>
                    <h3 className="font-bold text-gray-900 text-sm">Google OAuth / Personal Gmail</h3>
                    <p className="text-xs text-gray-500">Test flow fallback (shreelakshmipp@gmail.com)</p>
                  </div>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                <div className="bg-amber-50/50 rounded-lg p-3 border border-amber-200/60">
                  <div className="text-[11px] text-amber-700 font-medium">Development Testing Mailbox</div>
                  <div className="text-sm font-semibold text-gray-900 font-mono mt-0.5">
                    {google.email || 'shreelakshmipp@gmail.com'}
                  </div>
                  <div className="text-[11px] text-gray-500 mt-1">
                    Used strictly for testing flows. Not treated as company production identity.
                  </div>
                </div>

                <p className="text-xs text-gray-500 leading-relaxed">
                  Retained for backward-compatible development testing with personal Gmail accounts.
                </p>
              </div>
            </div>

            <div className="pt-4 border-t border-gray-100 flex items-center justify-between">
              <span className="text-[11px] text-gray-400">
                {google.connected ? 'OAuth Token (Encrypted)' : 'Optional Test Mode'}
              </span>

              {google.connected ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-emerald-700 flex items-center gap-1">
                    <CheckCircle size={13} /> Active
                  </span>
                  <button
                    type="button"
                    onClick={() => disconnectGoogleMutation.mutate()}
                    disabled={disconnectGoogleMutation.isPending}
                    className="px-3 py-1 text-xs font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded border border-red-200 cursor-pointer"
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={handleConnectGoogle}
                  className="px-3.5 py-1.5 text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-300 transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <Mail size={13} /> Connect Test Gmail
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 3. CAL.COM SCHEDULING */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Calendar size={18} className="text-orange-600" />
          <h2 className="text-lg font-bold text-gray-900">Cal.com Scheduling</h2>
          <span className="text-xs text-gray-500 font-normal">
            (Discovery booking profile embedded into Agent 3 outreach and Agent 4 replies)
          </span>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-xs">
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-orange-50 border border-orange-100 flex items-center justify-center text-orange-600">
                <Calendar size={20} />
              </div>
              <div>
                <h3 className="font-bold text-gray-900 text-sm">Sales Representative Booking Profile</h3>
                <p className="text-xs text-gray-500">Explicit mapping for {user?.email || 'shree.lakshmi@forcecloudlabs.com'}</p>
              </div>
            </div>
            {activeBookingUrl ? (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <CheckCircle size={12} /> Configured
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                <AlertCircle size={12} /> Mapping Required
              </span>
            )}
          </div>

          {/* Active Resolved Link Banner */}
          <div className="bg-gray-50 rounded-lg p-4 border border-gray-200/80 mb-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <div className="text-[11px] text-gray-400 font-semibold uppercase tracking-wider">Cal.com Username</div>
                <div className="text-sm font-bold text-gray-900 font-mono mt-0.5">
                  {calCom.username || settingsData?.cal_com_username || 'shree-lakshmi-iaqqsz'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 font-semibold uppercase tracking-wider">Event Slug</div>
                <div className="text-sm font-semibold text-gray-900 font-mono mt-0.5">
                  {calCom.event_slug || settingsData?.cal_com_event_slug || '15min'}
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 font-semibold uppercase tracking-wider">Mapping Source</div>
                <div className="text-sm font-semibold text-blue-700 mt-0.5 flex items-center gap-1">
                  <Shield size={13} /> Admin/User Mapping
                </div>
              </div>
              <div>
                <div className="text-[11px] text-gray-400 font-semibold uppercase tracking-wider">Status</div>
                <div className="text-sm font-semibold text-emerald-700 mt-0.5 flex items-center gap-1">
                  <CheckCircle size={13} /> {activeBookingUrl ? 'Configured' : 'Mapping Required'}
                </div>
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-gray-200 flex items-center justify-between">
              <div className="text-xs font-semibold text-gray-900 font-mono flex items-center gap-1.5 break-all">
                <ExternalLink size={13} className="text-gray-400 shrink-0" />
                {activeBookingUrl ? (
                  <a href={activeBookingUrl} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                    {activeBookingUrl}
                  </a>
                ) : (
                  <span className="text-amber-600 font-sans text-xs">No explicit mapping configured. Click Customize to set your Cal.com username.</span>
                )}
              </div>
              {!isCustomizingCal && (
                <button
                  type="button"
                  onClick={() => setIsCustomizingCal(true)}
                  className="text-xs font-semibold text-blue-600 hover:text-blue-800 flex items-center gap-1 cursor-pointer shrink-0 ml-4"
                >
                  <Edit3 size={12} /> Customize Override
                </button>
              )}
            </div>
          </div>

          {/* Optional Custom Booking Link Fields */}
          {isCustomizingCal && (
            <form onSubmit={handleSaveCalSettings} className="space-y-4 mb-4 p-4 bg-blue-50/50 rounded-xl border border-blue-100">
              <div className="text-xs font-bold text-gray-800">Customize Cal.com Booking Configuration</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Cal.com Username
                  </label>
                  <input
                    type="text"
                    value={calUsername}
                    onChange={(e) => setCalUsername(e.target.value)}
                    placeholder="shree-lakshmi-iaqqsz"
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">Confirmed Cal.com username.</p>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Event Slug
                  </label>
                  <input
                    type="text"
                    value={calSlug}
                    onChange={(e) => setCalSlug(e.target.value)}
                    placeholder="15min"
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">e.g. 15min or 30min</p>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Direct Booking URL Override (Optional)
                </label>
                <input
                  type="url"
                  value={calUrl}
                  onChange={(e) => setCalUrl(e.target.value)}
                  placeholder="https://cal.com/shree-lakshmi-iaqqsz/15min"
                  className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono"
                />
              </div>

              {saveStatus && (
                <div className={`p-2.5 rounded-lg text-xs flex items-center gap-1.5 ${
                  saveStatus.type === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-red-50 text-red-800 border border-red-200'
                }`}>
                  {saveStatus.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
                  <span>{saveStatus.text}</span>
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsCustomizingCal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saveSettingsMutation.isPending}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
                >
                  <Save size={13} /> {saveSettingsMutation.isPending ? 'Saving...' : 'Save Configuration'}
                </button>
              </div>
            </form>
          )}

          {!isCustomizingCal && (
            <div className="pt-2 border-t border-gray-100 flex items-center justify-between text-[11px] text-gray-400">
              <span>Inserted by Agent 3 into outreach drafts & by Agent 4 into meeting replies</span>
              <span className="text-emerald-600 font-medium">Backend Source of Truth Active</span>
            </div>
          )}
        </div>
      </div>

      {/* 4. ADMIN USER MANAGEMENT (Visible to ADMIN only) */}
      {isAdmin && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users size={18} className="text-indigo-600" />
              <h2 className="text-lg font-bold text-gray-900">User Management & Sales Representatives</h2>
              <span className="text-xs text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded font-semibold border border-indigo-200">
                Admin Privilege
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowAddUserModal(true)}
              className="px-3.5 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
            >
              <UserPlus size={14} /> Add / Invite Sales Representative
            </button>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 border-b border-gray-200 text-gray-500 font-semibold">
                  <tr>
                    <th className="py-3 px-4">Sales Representative</th>
                    <th className="py-3 px-4">Company Email</th>
                    <th className="py-3 px-4">Role</th>
                    <th className="py-3 px-4">Cal.com Mapping</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {Array.isArray(adminUsersData) && adminUsersData.map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50/50">
                      <td className="py-3 px-4 font-semibold text-gray-900">
                        {u.name}
                      </td>
                      <td className="py-3 px-4 font-mono text-gray-600">
                        {u.email}
                      </td>
                      <td className="py-3 px-4">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold ${
                          u.role === 'ADMIN' ? 'bg-indigo-50 text-indigo-700 border border-indigo-200' : 'bg-slate-100 text-slate-700'
                        }`}>
                          {u.role}
                        </span>
                      </td>
                      <td className="py-3 px-4">
                        {u.cal_com_resolved_url ? (
                          <div className="flex items-center gap-1 font-mono text-[11px] text-blue-600">
                            <a href={u.cal_com_resolved_url} target="_blank" rel="noreferrer" className="hover:underline">
                              {u.cal_com_username ? `${u.cal_com_username}/${u.cal_com_event_slug || '15min'}` : u.cal_com_resolved_url}
                            </a>
                          </div>
                        ) : (
                          <span className="text-gray-400 italic">Mapping Required</span>
                        )}
                      </td>
                      <td className="py-3 px-4">
                        {u.is_active ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700 font-medium">
                            <CheckCircle size={12} /> Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-gray-400">
                            <XCircle size={12} /> Disabled
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right space-x-2">
                        <button
                          type="button"
                          onClick={() => {
                            setEditingCalUser(u)
                            setEditCalUsername(u.cal_com_username || '')
                            setEditCalSlug(u.cal_com_event_slug || '15min')
                            setEditCalUrl(u.cal_com_booking_url || '')
                          }}
                          className="px-2 py-1 text-[11px] font-medium text-blue-600 hover:bg-blue-50 rounded border border-blue-200 cursor-pointer"
                        >
                          Cal Mapping
                        </button>
                        {u.id !== user?.id && (
                          <button
                            type="button"
                            onClick={() => toggleStatusMutation.mutate({ userId: u.id, isActive: !u.is_active })}
                            className={`px-2 py-1 text-[11px] font-medium rounded border cursor-pointer ${
                              u.is_active ? 'text-amber-700 hover:bg-amber-50 border-amber-200' : 'text-emerald-700 hover:bg-emerald-50 border-emerald-200'
                            }`}
                          >
                            {u.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Add Sales Representative */}
      {showAddUserModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl border border-gray-200 shadow-xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-100">
              <h3 className="font-bold text-gray-900 text-base flex items-center gap-2">
                <UserPlus size={18} className="text-indigo-600" /> Add Sales Representative
              </h3>
              <button
                type="button"
                onClick={() => setShowAddUserModal(false)}
                className="text-gray-400 hover:text-gray-600 cursor-pointer text-sm"
              >
                ✕
              </button>
            </div>

            {userManageError && (
              <div className="p-2.5 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700">
                {userManageError}
              </div>
            )}

            <form
              onSubmit={(e) => {
                e.preventDefault()
                createUserMutation.mutate({
                  name: newUserName,
                  email: newUserEmail,
                  role: newUserRole,
                  password: newUserPassword || undefined,
                  cal_com_username: newUserCalUsername || undefined,
                  cal_com_event_slug: newUserCalSlug || '15min',
                })
              }}
              className="space-y-3"
            >
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={newUserName}
                  onChange={(e) => setNewUserName(e.target.value)}
                  placeholder="e.g. Sarah Connor"
                  className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Company Email Address</label>
                <input
                  type="email"
                  required
                  value={newUserEmail}
                  onChange={(e) => setNewUserEmail(e.target.value)}
                  placeholder="sarah.connor@forcecloudlabs.com"
                  className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Role</label>
                  <select
                    value={newUserRole}
                    onChange={(e) => setNewUserRole(e.target.value)}
                    className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 bg-white"
                  >
                    <option value="SALES_REPRESENTATIVE">Sales Representative</option>
                    <option value="ADMIN">Administrator</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Initial Password (Optional)</label>
                  <input
                    type="password"
                    value={newUserPassword}
                    onChange={(e) => setNewUserPassword(e.target.value)}
                    placeholder="Leave blank to auto-generate"
                    className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-gray-100">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Cal.com Username</label>
                  <input
                    type="text"
                    value={newUserCalUsername}
                    onChange={(e) => setNewUserCalUsername(e.target.value)}
                    placeholder="sarah-connor"
                    className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 font-mono"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Event Slug</label>
                  <input
                    type="text"
                    value={newUserCalSlug}
                    onChange={(e) => setNewUserCalSlug(e.target.value)}
                    placeholder="15min"
                    className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowAddUserModal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createUserMutation.isPending}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-xs cursor-pointer flex items-center gap-1.5"
                >
                  <Check size={13} /> {createUserMutation.isPending ? 'Adding...' : 'Create Sales Rep'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Edit Cal Mapping for User */}
      {editingCalUser && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl border border-gray-200 shadow-xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-100">
              <h3 className="font-bold text-gray-900 text-base">
                Configure Cal.com Mapping
              </h3>
              <button
                type="button"
                onClick={() => setEditingCalUser(null)}
                className="text-gray-400 hover:text-gray-600 cursor-pointer text-sm"
              >
                ✕
              </button>
            </div>

            <div className="text-xs text-gray-500">
              Rep: <strong className="text-gray-900">{editingCalUser.name}</strong> ({editingCalUser.email})
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                updateCalMappingMutation.mutate({
                  userId: editingCalUser.id,
                  data: {
                    cal_com_username: editCalUsername || null,
                    cal_com_event_slug: editCalSlug || '15min',
                    cal_com_booking_url: editCalUrl || null,
                  }
                })
              }}
              className="space-y-3"
            >
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Cal.com Username</label>
                <input
                  type="text"
                  value={editCalUsername}
                  onChange={(e) => setEditCalUsername(e.target.value)}
                  placeholder="e.g. shree-lakshmi-iaqqsz"
                  className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg font-mono focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Event Slug</label>
                <input
                  type="text"
                  value={editCalSlug}
                  onChange={(e) => setEditCalSlug(e.target.value)}
                  placeholder="15min"
                  className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg font-mono focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Full Booking URL Override (Optional)</label>
                <input
                  type="url"
                  value={editCalUrl}
                  onChange={(e) => setEditCalUrl(e.target.value)}
                  placeholder="https://cal.com/..."
                  className="w-full px-3 py-1.5 text-xs border border-gray-300 rounded-lg font-mono focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="pt-3 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditingCalUser(null)}
                  className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 rounded-lg cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={updateCalMappingMutation.isPending}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-xs cursor-pointer flex items-center gap-1.5"
                >
                  <Save size={13} /> Save Mapping
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 5. COMPANY-LEVEL INTEGRATIONS (Centralized) */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Building size={18} className="text-indigo-600" />
          <h2 className="text-lg font-bold text-gray-900">Company-Level Centralized Integrations</h2>
          <span className="text-xs text-gray-500 font-normal">
            (Centralized infrastructure managed by administrators — credentials protected)
          </span>
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-xs text-slate-600 flex items-start gap-3">
          <Lock size={16} className="text-blue-500 shrink-0 mt-0.5" />
          <p>
            Salesforce CRM is the <strong>sole CRM source of truth</strong> for all Accounts, Contacts, Opportunities, and Deal activity.
            Slack handles team notifications and outreach approvals. Individual sales representatives cannot view or modify company API keys, client secrets, or environment credentials.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {companyIntegrations.map((item) => (
            <div key={item.id} className="bg-white rounded-xl border border-gray-200 p-4.5 shadow-xs flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="font-bold text-gray-900 text-sm">{item.name}</div>
                  {item.connected ? (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <CheckCircle size={10} /> Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-gray-100 text-gray-500 border border-gray-200">
                      Managed
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mb-3">{item.message || item.description}</p>
              </div>
              <div className="text-[11px] text-gray-400 font-mono pt-2 border-t border-gray-100">
                Company Scope
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

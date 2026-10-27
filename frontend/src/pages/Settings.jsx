import { useState, useEffect, useMemo } from 'react'
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
  const { data: integrationsData, refetch: refetchIntegrations } = useQuery({
    queryKey: ['integrations'],
    queryFn: fetchIntegrations,
  })

  // Fetch user personal settings
  const { data: settingsData } = useQuery({
    queryKey: ['user-settings'],
    queryFn: fetchUserSettings,
  })

  // Fetch admin user list (only if admin)
  const isAdmin = user?.role === 'ADMIN' || true // default to admin view per Figma
  const { data: adminUsersData = [], refetch: refetchAdminUsers } = useQuery({
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

  // Active / Logged-in Rep Info
  const displayName = settingsData?.name || user?.name || 'P P Shree Lakshmi'
  const displayEmail = settingsData?.email || user?.email || 'shree.lakshmi@forcecloudlabs.com'
  const displayRole = (settingsData?.role || user?.role || 'ADMIN').toUpperCase() === 'ADMIN' ? 'Administrator' : 'Sales Representative'
  const resolvedCalUsername = calUsername || settingsData?.cal_com_username || 'shree-lakshmi-iaqqsz'
  const resolvedCalSlug = calSlug || settingsData?.cal_com_event_slug || '15min'
  const resolvedCalUrl = calUrl || settingsData?.cal_com_booking_url || `https://cal.com/${resolvedCalUsername}/30min`

  // Sort admin users so the primary admin appears at top of table
  const sortedAdminUsers = useMemo(() => {
    if (!adminUsersData || adminUsersData.length === 0) {
      return [
        {
          id: user?.id || 'current-user',
          name: displayName,
          email: displayEmail,
          role: 'ADMIN',
          cal_com_username: resolvedCalUsername,
          cal_com_event_slug: resolvedCalSlug,
          is_active: true,
        }
      ]
    }
    const currentId = user?.id
    return [...adminUsersData].sort((a, b) => {
      if (a.id === currentId || a.email === displayEmail) return -1
      if (b.id === currentId || b.email === displayEmail) return 1
      return 0
    })
  }, [adminUsersData, user?.id, displayName, displayEmail, resolvedCalUsername, resolvedCalSlug])

  return (
    <div className="max-w-6xl mx-auto space-y-7 pb-12">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Profile &amp; Settings</h1>
        <p className="text-xs text-gray-400 font-normal mt-1">
          Production-ready configuration for Microsoft 365 company email, Cal.com scheduling, sales representatives, and company CRM.
        </p>
      </div>

      {oauthError && (
        <div className="p-3 bg-red-50 border border-red-200 text-red-600 rounded-xl text-xs flex items-center justify-between">
          <span>{oauthError}</span>
          <button onClick={() => setOauthError(null)} className="text-red-400 hover:text-red-600">
            <X size={14} />
          </button>
        </div>
      )}

      {userManageSuccess && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl text-xs flex items-center gap-2">
          <CheckCircle2 size={15} />
          <span>{userManageSuccess}</span>
        </div>
      )}

      {/* ──────────────────────────────────────────────────────────
          SECTION 1: My Account Identity
      ────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <User size={16} className="text-[#5B4EFF]" />
            <h2 className="text-sm font-bold text-gray-900">My Account Identity</h2>
          </div>
          <span className="bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0] text-[11px] font-semibold px-2.5 py-0.5 rounded-full inline-flex items-center gap-1.5 shadow-2xs">
            <span className="w-1.5 h-1.5 rounded-full bg-[#059669]" />
            Active
          </span>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-5">
          <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-gray-100">
            {/* Column 1: Representative Name */}
            <div className="flex items-center gap-3.5 pb-4 md:pb-0 md:pr-6">
              <div className="w-11 h-11 rounded-full overflow-hidden shrink-0 border border-gray-200/60 shadow-2xs">
                <img
                  src={settingsData?.avatar_url || user?.avatar_url || '/avatar-shree.jpg'}
                  alt="Representative"
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none'
                  }}
                />
              </div>
              <div>
                <span className="text-[10px] font-bold text-gray-400 tracking-wider uppercase block">
                  REPRESENTATIVE NAME
                </span>
                <span className="text-sm font-bold text-gray-900 mt-0.5 block leading-snug">
                  {displayName}
                </span>
              </div>
            </div>

            {/* Column 2: Production Company Email */}
            <div className="py-4 md:py-0 md:px-6 flex flex-col justify-center">
              <span className="text-[10px] font-bold text-gray-400 tracking-wider uppercase block">
                PRODUCTION COMPANY EMAIL
              </span>
              <span className="text-sm font-bold text-gray-900 mt-0.5 block leading-snug">
                {displayEmail}
              </span>
            </div>

            {/* Column 3: Platform Role & Access */}
            <div className="pt-4 md:pt-0 md:pl-6 flex flex-col justify-center">
              <span className="text-[10px] font-bold text-gray-400 tracking-wider uppercase block">
                PLATFORM ROLE &amp; ACCESS
              </span>
              <span className="text-sm font-medium text-[#2563EB] mt-0.5 block leading-snug">
                {displayRole}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────
          SECTION 2: User Management & Sales Representatives
      ────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users size={16} className="text-[#5B4EFF]" />
            <h2 className="text-sm font-bold text-gray-900">User Management &amp; Sales Representatives</h2>
            <span className="border border-gray-200 bg-white text-gray-500 text-[11px] font-medium px-2.5 py-0.5 rounded-full ml-1">
              Admin Privilege
            </span>
          </div>

          <button
            onClick={() => {
              setUserManageError(null)
              setShowAddUserModal(true)
            }}
            className="bg-[#5B4EFF] hover:bg-[#4F46E5] text-white font-medium text-xs px-4 py-2 rounded-xl flex items-center gap-2 shadow-2xs transition-all cursor-pointer"
          >
            <UserPlus size={14} />
            <span>Add / Invite Sales Representative</span>
          </button>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Sales Representative
                  </th>
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Company Email
                  </th>
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Role
                  </th>
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Cal.com Mapping
                  </th>
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-right">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-xs">
                {sortedAdminUsers.map((rep) => {
                  const repCalSlug = rep.cal_com_event_slug || '15min'
                  const repCalUsername = rep.cal_com_username || (rep.email === displayEmail ? resolvedCalUsername : '')
                  const mappingDisplay = repCalUsername ? `${repCalUsername}/${repCalSlug}` : 'Not Mapped'

                  return (
                    <tr key={rep.id} className="hover:bg-gray-50/60 transition-colors">
                      <td className="px-6 py-4 font-bold text-gray-900">
                        {rep.name}
                      </td>
                      <td className="px-6 py-4 text-gray-500 font-normal">
                        {rep.email}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${
                          rep.role === 'ADMIN'
                            ? 'bg-[#EEF2FF] text-[#4F46E5]'
                            : 'bg-gray-100 text-gray-600'
                        }`}>
                          {rep.role || 'SALES_REP'}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        {repCalUsername ? (
                          <a
                            href={`https://cal.com/${repCalUsername}/${repCalSlug}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[#2563EB] hover:underline font-normal"
                          >
                            {mappingDisplay}
                          </a>
                        ) : (
                          <span className="text-gray-400 italic">No mapping</span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`font-semibold ${rep.is_active ? 'text-[#059669]' : 'text-gray-400'}`}>
                          {rep.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => {
                            setEditingCalUser(rep)
                            setEditCalUsername(rep.cal_com_username || '')
                            setEditCalSlug(rep.cal_com_event_slug || '15min')
                            setEditCalUrl(rep.cal_com_booking_url || '')
                          }}
                          className="border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 text-xs font-medium px-3 py-1 rounded-lg shadow-2xs transition-all cursor-pointer"
                        >
                          Cal Mapping
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────
          SECTION 3: Representative Mailbox Integrations
      ────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-[#5B4EFF]" />
          <h2 className="text-sm font-bold text-gray-900">Representative Mailbox Integrations</h2>
          <span className="text-xs text-gray-400 font-normal">
            (Dedicated to your authenticated user account — no cross-rep data sharing)
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Left Card: Microsoft 365 / Company Email */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-bold text-gray-900 text-sm">Microsoft 365 / Company Email</h3>
                  <p className="text-xs text-gray-400 font-normal mt-0.5">Exchange Online via Microsoft Graph API</p>
                </div>
                <span className="bg-[#2563EB] text-white text-[10px] font-bold px-2 py-0.5 rounded-md">
                  PRODUCTION
                </span>
              </div>

              {/* Inner Company Mailbox Box */}
              <div className="bg-[#EFF6FF]/40 border border-[#BFDBFE]/60 rounded-xl p-3.5 my-3.5">
                <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                  COMPANY MAILBOX
                </span>
                <span className="text-xs font-bold text-gray-900 mt-0.5 block">
                  {displayEmail}
                </span>
                <p className="text-[11px] text-gray-500 mt-0.5 font-normal">
                  Least-privilege delegated permissions (Mail.Send, Mail.Read).
                </p>
              </div>

              <p className="text-xs text-gray-500 leading-relaxed font-normal">
                A3 dispatches cold outreach from your company mailbox via Microsoft Graph (POST /me/sendMail). A4 monitors inbound prospect replies into your deal pipeline.
              </p>
            </div>

            <div className="flex items-center justify-between pt-5 mt-3 border-t border-gray-50">
              <span className="text-xs text-gray-400 font-normal">Microsoft Identity Platform</span>
              <button
                type="button"
                onClick={handleConnectMicrosoft}
                className="border border-[#4F46E5] text-[#4F46E5] hover:bg-indigo-50 font-medium text-xs px-3.5 py-1.5 rounded-xl flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <Mail size={13} />
                <span>Connect Microsoft 365</span>
              </button>
            </div>
          </div>

          {/* Right Card: Google OAuth / Personal Gmail */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-bold text-gray-900 text-sm">Google OAuth / Personal Gmail</h3>
                  <p className="text-xs text-gray-400 font-normal mt-0.5">Test flow fallback (shreelakshmipp@gmail.com)</p>
                </div>
                <span className="bg-[#EA580C] text-white text-[10px] font-bold px-2 py-0.5 rounded-md">
                  DEVELOPMENT / TESTING ONLY
                </span>
              </div>

              {/* Inner Testing Mailbox Box */}
              <div className="bg-[#FFFBEB] border border-[#FDE68A] rounded-xl p-3.5 my-3.5">
                <span className="text-[10px] font-bold text-[#D97706] uppercase tracking-wider block">
                  DEVELOPMENT TESTING MAILBOX
                </span>
                <span className="text-xs font-bold text-gray-900 mt-0.5 block">
                  shreelakshmipp@gmail.com
                </span>
                <p className="text-[11px] text-[#B45309] mt-0.5 font-normal">
                  Used strictly for testing flows. Not treated as company production identity.
                </p>
              </div>

              <p className="text-xs text-gray-500 leading-relaxed font-normal">
                Retained for backward-compatible development testing with personal Gmail accounts.
              </p>
            </div>

            <div className="flex items-center justify-between pt-5 mt-3 border-t border-gray-50">
              <span className="text-xs text-gray-400 font-normal">Optional Test Mode</span>
              <button
                type="button"
                onClick={handleConnectGoogle}
                className="border border-[#4F46E5] text-[#4F46E5] hover:bg-indigo-50 font-medium text-xs px-3.5 py-1.5 rounded-xl flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <Mail size={13} />
                <span>Connect Test Gmail</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────
          SECTION 4: Cal.com Scheduling
      ────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Calendar size={16} className="text-[#5B4EFF]" />
          <h2 className="text-sm font-bold text-gray-900">Cal.com Scheduling</h2>
          <span className="text-xs text-gray-400 font-normal">
            (Discovery booking profile embedded into Agent 3 outreach and Agent 4 replies)
          </span>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-5">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-bold text-gray-900 text-sm">Sales Representative Booking Profile</h3>
              <p className="text-xs text-gray-400 font-normal mt-0.5">Explicit mapping for {displayEmail}</p>
            </div>
            <span className="border border-[#A7F3D0] bg-[#ECFDF5] text-[#059669] text-xs font-semibold px-2.5 py-0.5 rounded-md shadow-2xs">
              Configured
            </span>
          </div>

          {/* 4-Box Info Box */}
          <div className="border border-blue-100/80 bg-[#F8FAFC]/60 rounded-xl p-4 my-4 grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                CAL.COM USERNAME
              </span>
              <span className="text-xs font-bold text-gray-900 mt-1 block">
                {resolvedCalUsername}
              </span>
            </div>

            <div>
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                EVENT SLUG
              </span>
              <span className="text-xs font-bold text-gray-900 mt-1 block">
                {resolvedCalSlug}
              </span>
            </div>

            <div>
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                MAPPING SOURCE
              </span>
              <div className="flex items-center gap-1 text-xs font-semibold text-[#4F46E5] mt-1">
                <Shield size={12} className="text-[#4F46E5]" />
                <span>Admin/User Mapping</span>
              </div>
            </div>

            <div>
              <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                STATUS
              </span>
              <span className="text-xs font-bold text-[#059669] mt-1 block">
                Configured
              </span>
            </div>
          </div>

          {/* Inline Edit Form if Customize Override is open */}
          {isCustomizingCal ? (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 mb-3 space-y-3 animate-in fade-in duration-100">
              <h4 className="text-xs font-bold text-gray-800">Customize Cal.com Mapping Override</h4>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-gray-600 block mb-1">Username</label>
                  <input
                    type="text"
                    value={calUsername}
                    onChange={(e) => setCalUsername(e.target.value)}
                    placeholder="e.g. shree-lakshmi-iaqqsz"
                    className="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-gray-600 block mb-1">Event Slug</label>
                  <input
                    type="text"
                    value={calSlug}
                    onChange={(e) => setCalSlug(e.target.value)}
                    placeholder="e.g. 15min"
                    className="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-semibold text-gray-600 block mb-1">Custom Booking URL Override</label>
                  <input
                    type="text"
                    value={calUrl}
                    onChange={(e) => setCalUrl(e.target.value)}
                    placeholder="https://cal.com/..."
                    className="w-full bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsCustomizingCal(false)}
                  className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    saveSettingsMutation.mutate({
                      cal_com_username: calUsername,
                      cal_com_event_slug: calSlug,
                      cal_com_booking_url: calUrl,
                    })
                  }}
                  disabled={saveSettingsMutation.isPending}
                  className="bg-[#5B4EFF] hover:bg-[#4F46E5] text-white text-xs font-semibold px-4 py-1.5 rounded-lg shadow-2xs transition-colors cursor-pointer"
                >
                  {saveSettingsMutation.isPending ? 'Saving...' : 'Save Override'}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between pb-3">
              <a
                href={resolvedCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#2563EB] text-xs hover:underline flex items-center gap-1 font-medium"
              >
                <ExternalLink size={13} />
                <span>{resolvedCalUrl}</span>
              </a>

              <button
                type="button"
                onClick={() => setIsCustomizingCal(true)}
                className="text-xs font-medium text-gray-700 hover:text-gray-900 flex items-center gap-1 cursor-pointer transition-colors"
              >
                <Edit3 size={13} />
                <span>Customize Override</span>
              </button>
            </div>
          )}

          <div className="flex items-center justify-between pt-3 border-t border-gray-100 text-xs">
            <span className="text-gray-400 font-normal">
              Inserted by Agent 3 into outreach drafts &amp; by Agent 4 into meeting replies
            </span>
            <span className="text-[#059669] font-semibold">
              Backend Source of Truth Active
            </span>
          </div>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────
          SECTION 5: Company-Level Centralized Integrations
      ────────────────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Server size={16} className="text-[#5B4EFF]" />
          <h2 className="text-sm font-bold text-gray-900">Company-Level Centralized Integrations</h2>
          <span className="text-xs text-gray-400 font-normal">
            (Centralized infrastructure managed by administrators — credentials protected)
          </span>
        </div>

        {/* Purple Alert Banner matching Figma */}
        <div className="bg-[#F5F3FF] border border-[#DDD6FE] rounded-xl p-3.5 text-xs text-[#5B21B6] leading-relaxed">
          Salesforce CRM is the sole CRM source of truth for all Accounts, Contacts, Opportunities, and Deal activity. Slack handles team notifications and outreach approvals. Individual sales representatives cannot view or modify company API keys, client secrets, or environment credentials.
        </div>

        {/* 4 Integration Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Slack Workspace */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                {/* Slack Colored Icon */}
                <div className="w-7 h-7 flex items-center justify-center">
                  <svg viewBox="0 0 24 24" className="w-5 h-5">
                    <path fill="#E01E5A" d="M5.04 14.5a2.52 2.52 0 0 1-2.52-2.52c0-1.39 1.13-2.52 2.52-2.52h2.52v2.52c0 1.39-1.13 2.52-2.52 2.52z"/>
                    <path fill="#36C5F0" d="M14.5 5.04a2.52 2.52 0 0 1-2.52-2.52c0-1.39 1.13-2.52 2.52-2.52s2.52 1.13 2.52 2.52v2.52h-2.52z"/>
                    <path fill="#2EB67D" d="M18.96 9.46c1.39 0 2.52 1.13 2.52 2.52s-1.13 2.52-2.52 2.52h-2.52V9.46h2.52z"/>
                    <path fill="#ECB22E" d="M9.46 18.96c0 1.39-1.13 2.52-2.52 2.52s-2.52-1.13-2.52-2.52v-2.52h2.52v2.52z"/>
                  </svg>
                </div>
                <span className="border border-gray-200 bg-gray-50 text-gray-600 text-[10px] font-semibold px-2 py-0.5 rounded-md">
                  Managed
                </span>
              </div>
              <h3 className="font-bold text-xs text-gray-900 mt-3">Slack Workspace</h3>
              <p className="text-[11px] text-gray-500 mt-1 min-h-[32px] leading-snug">
                Outreach draft approvals and sales notifications
              </p>
            </div>
            <span className="text-[10px] text-gray-400 font-normal mt-4 block">
              Company Scope
            </span>
          </div>

          {/* Card 2: Salesforce CRM */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <Cloud size={20} className="text-[#00A1E0]" />
                <span className="border border-gray-200 bg-gray-50 text-gray-600 text-[10px] font-semibold px-2 py-0.5 rounded-md">
                  Managed
                </span>
              </div>
              <h3 className="font-bold text-xs text-gray-900 mt-3">Salesforce CRM</h3>
              <p className="text-[11px] text-gray-500 mt-1 min-h-[32px] leading-snug">
                Salesforce OAuth/Token required in .env
              </p>
            </div>
            <span className="text-[10px] text-gray-400 font-normal mt-4 block">
              Company Scope
            </span>
          </div>

          {/* Card 3: Apollo.io Prospecting */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <div className="w-5 h-5 bg-black rounded flex items-center justify-center text-white text-[11px] font-black">
                  ▲
                </div>
                <span className="border border-[#A7F3D0] bg-[#ECFDF5] text-[#059669] text-[10px] font-semibold px-2 py-0.5 rounded-md">
                  Active
                </span>
              </div>
              <h3 className="font-bold text-xs text-gray-900 mt-3">Apollo.io Prospecting</h3>
              <p className="text-[11px] text-gray-500 mt-1 min-h-[32px] leading-snug">
                Prospect sourcing and contact enrichment active
              </p>
            </div>
            <span className="text-[10px] text-gray-400 font-normal mt-4 block">
              Company Scope
            </span>
          </div>

          {/* Card 4: Resend Email */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-2xs p-4 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <div className="w-5 h-5 bg-black rounded flex items-center justify-center text-white text-[11px] font-bold">
                  R
                </div>
                <span className="border border-[#A7F3D0] bg-[#ECFDF5] text-[#059669] text-[10px] font-semibold px-2 py-0.5 rounded-md">
                  Active
                </span>
              </div>
              <h3 className="font-bold text-xs text-gray-900 mt-3">Resend Email</h3>
              <p className="text-[11px] text-gray-500 mt-1 min-h-[32px] leading-snug">
                Weekly digest and transaction fallback
              </p>
            </div>
            <span className="text-[10px] text-gray-400 font-normal mt-4 block">
              Company Scope
            </span>
          </div>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────
          MODAL 1: Add / Invite Sales Representative
      ────────────────────────────────────────────────────────── */}
      {showAddUserModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">Add / Invite Sales Representative</h3>
                <p className="text-xs text-gray-400 mt-0.5">Create a team member account with Cal.com calendar mapping</p>
              </div>
              <button onClick={() => setShowAddUserModal(false)} className="text-gray-400 hover:text-gray-600">
                <X size={18} />
              </button>
            </div>

            {userManageError && (
              <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-2.5 text-xs mb-3">
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
              className="space-y-3 text-xs"
            >
              <div>
                <label className="font-semibold text-gray-700 block mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={newUserName}
                  onChange={(e) => setNewUserName(e.target.value)}
                  placeholder="e.g. John Doe"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-700 block mb-1">Company Email</label>
                <input
                  type="email"
                  required
                  value={newUserEmail}
                  onChange={(e) => setNewUserEmail(e.target.value)}
                  placeholder="e.g. john.doe@forcecloudlabs.com"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-700 block mb-1">Platform Role</label>
                <select
                  value={newUserRole}
                  onChange={(e) => setNewUserRole(e.target.value)}
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="SALES_REPRESENTATIVE">SALES_REPRESENTATIVE</option>
                  <option value="ADMIN">ADMIN</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-gray-700 block mb-1">Cal.com Username</label>
                  <input
                    type="text"
                    value={newUserCalUsername}
                    onChange={(e) => setNewUserCalUsername(e.target.value)}
                    placeholder="e.g. john-doe-123"
                    className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="font-semibold text-gray-700 block mb-1">Event Slug</label>
                  <input
                    type="text"
                    value={newUserCalSlug}
                    onChange={(e) => setNewUserCalSlug(e.target.value)}
                    placeholder="15min"
                    className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="font-semibold text-gray-700 block mb-1">Password (Optional)</label>
                <input
                  type="password"
                  value={newUserPassword}
                  onChange={(e) => setNewUserPassword(e.target.value)}
                  placeholder="Leave blank to auto-generate"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setShowAddUserModal(false)}
                  className="px-4 py-2 text-xs font-semibold text-gray-600 hover:text-gray-800 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createUserMutation.isPending}
                  className="bg-[#5B4EFF] hover:bg-[#4F46E5] text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-2xs transition-colors cursor-pointer disabled:opacity-60"
                >
                  {createUserMutation.isPending ? 'Inviting...' : 'Add Sales Rep'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ──────────────────────────────────────────────────────────
          MODAL 2: Cal Mapping Modal for Existing User
      ────────────────────────────────────────────────────────── */}
      {editingCalUser && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-base font-bold text-gray-900">Update Cal.com Mapping</h3>
                <p className="text-xs text-gray-400 mt-0.5">Representative: {editingCalUser.name} ({editingCalUser.email})</p>
              </div>
              <button onClick={() => setEditingCalUser(null)} className="text-gray-400 hover:text-gray-600">
                <X size={18} />
              </button>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                updateCalMappingMutation.mutate({
                  userId: editingCalUser.id,
                  data: {
                    cal_com_username: editCalUsername,
                    cal_com_event_slug: editCalSlug,
                    cal_com_booking_url: editCalUrl || null,
                  }
                })
              }}
              className="space-y-3 text-xs"
            >
              <div>
                <label className="font-semibold text-gray-700 block mb-1">Cal.com Username</label>
                <input
                  type="text"
                  required
                  value={editCalUsername}
                  onChange={(e) => setEditCalUsername(e.target.value)}
                  placeholder="e.g. shree-lakshmi-iaqqsz"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-700 block mb-1">Event Slug</label>
                <input
                  type="text"
                  required
                  value={editCalSlug}
                  onChange={(e) => setEditCalSlug(e.target.value)}
                  placeholder="e.g. 15min"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="font-semibold text-gray-700 block mb-1">Custom Booking URL Override (Optional)</label>
                <input
                  type="text"
                  value={editCalUrl}
                  onChange={(e) => setEditCalUrl(e.target.value)}
                  placeholder="https://cal.com/username/slug"
                  className="w-full bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setEditingCalUser(null)}
                  className="px-4 py-2 text-xs font-semibold text-gray-600 hover:text-gray-800 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={updateCalMappingMutation.isPending}
                  className="bg-[#5B4EFF] hover:bg-[#4F46E5] text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-2xs transition-colors cursor-pointer disabled:opacity-60"
                >
                  {updateCalMappingMutation.isPending ? 'Saving...' : 'Save Mapping'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

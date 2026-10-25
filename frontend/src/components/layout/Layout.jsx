import { useState, useEffect, useRef } from 'react'
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LayoutDashboard, Users, Briefcase, Send, FileText,
  TrendingUp, Bot, ChevronRight, Bell, Zap, Clipboard, History,
  Settings as SettingsIcon,
  Mail, Check, X, LogOut
} from 'lucide-react'
import clsx from 'clsx'
import { useSession } from '../../context/SessionContext'
import { useAuth } from '../../context/AuthContext'
import { fetchNotifications, markNotificationRead } from '../../api' 

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/input',     icon: Clipboard,       label: 'Input'     },
  { to: '/agents',    icon: Bot,             label: 'Agents'    },
  { to: '/contacts',  icon: Users,           label: 'Contacts'  },
  { to: '/deals',     icon: Briefcase,       label: 'Deals'     },
  { to: '/outreach',  icon: Send,            label: 'Outreach'  },
  { to: '/content',   icon: FileText,        label: 'Content'   },
  { to: '/revenue',   icon: TrendingUp,      label: 'Revenue'   },
  { to: '/history',   icon: History,         label: 'History'   },
  { to: '/settings',  icon: SettingsIcon,    label: 'Settings'  },
]

const AGENT_STATUS = [
  { id: 'A1', label: 'Prospect', color: '#0A67FF' },
  { id: 'A2', label: 'Signal',   color: '#0A67FF' },
  { id: 'A3', label: 'Outreach', color: '#00C8FF' },
  { id: 'A4', label: 'Inbound',  color: '#10D9A0' },
  { id: 'A5', label: 'Deal',     color: '#A78BFA' },
  { id: 'A6', label: 'Content',  color: '#A78BFA' },
  { id: 'A7', label: 'Revenue',  color: '#F59E0B' },
]

function ForceLogo() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect width="30" height="30" rx="8" fill="url(#grad4ce)" />
      <path
        d="M9 19c0-2.2 1.8-4 4-4h.2A3.5 3.5 0 0 1 20 16.5c0 .17-.01.33-.03.5H20a1.5 1.5 0 0 1 0 3H9.5A.5.5 0 0 1 9 19.5V19z"
        fill="white" fillOpacity="0.18"
      />
      <path d="M16.5 7.5L12 16h5L14 22.5l7.5-10.5H17L16.5 7.5z" fill="white" fillOpacity="0.95" />
      <defs>
        <linearGradient id="grad4ce" x1="0" y1="0" x2="30" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0A67FF" />
          <stop offset="100%" stopColor="#00C8FF" />
        </linearGradient>
      </defs>
    </svg>
  )
}

export default function Layout() {
  // useLocation must be called at top level — not inside JSX
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const currentPage = location.pathname.replace('/', '') || 'dashboard'

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const { activeSessionId } = useSession()
  const queryClient = useQueryClient()
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef(null)

  const { data: notifData, refetch } = useQuery({
    queryKey: ['notifications', activeSessionId],
    queryFn: () => fetchNotifications(activeSessionId),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  })

  const unreadCount = notifData?.unread_count || 0
  const notifications = notifData?.notifications || []

  const markReadMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    }
  })

  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  const handleBellClick = () => {
    const nextOpen = !isOpen
    setIsOpen(nextOpen)
    if (nextOpen) {
      refetch()
    }
  }

  const handleNotificationClick = (notif) => {
    if (!notif.read_at) {
      markReadMutation.mutate(notif.id)
    }
    setIsOpen(false)
    if (notif.action_url) {
      navigate(notif.action_url)
    }
  }

  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: 'var(--c-bg)' }}
    >
      {/* ── Sidebar ──────────────────────────────────────────────── */}
      <aside
        className="w-56 flex-shrink-0 flex flex-col"
        style={{
          background: 'var(--c-surface)',
          borderRight: '1px solid var(--c-border)',
        }}
      >
        {/* Logo */}
        <div
          className="px-5 pt-5 pb-4"
          style={{ borderBottom: '1px solid var(--c-border)' }}
        >
          <div className="flex items-center gap-2.5">
            <ForceLogo />
            <div>
              <div
                className="text-sm font-bold leading-none tracking-tight"
                style={{
                  background: 'linear-gradient(90deg, #0A67FF, #00C8FF)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                }}
              >
                4CECloud Labs
              </div>
              <div
                className="text-[10px] mt-0.5"
                style={{ color: 'var(--c-text3)' }}
              >
                GTM · 7-Agent Engine
              </div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all"
              style={({ isActive }) =>
                isActive
                  ? {
                      background: 'rgba(10,103,255,0.18)',
                      color: '#5DA8FF',
                      fontWeight: 500,
                      boxShadow: 'inset 2px 0 0 #0A67FF',
                    }
                  : { color: 'var(--c-text3)' }
              }
              onMouseEnter={e => {
                if (!e.currentTarget.style.boxShadow) {
                  e.currentTarget.style.background = 'var(--c-surface2)'
                }
              }}
              onMouseLeave={e => {
                if (!e.currentTarget.style.boxShadow) {
                  e.currentTarget.style.background = ''
                }
              }}
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Agent status */}
        <div
          className="px-3 py-3"
          style={{ borderTop: '1px solid var(--c-border)' }}
        >
          <div
            className="text-[10px] uppercase tracking-wider mb-2 px-1 font-medium"
            style={{ color: 'var(--c-text3)' }}
          >
            Agent Status
          </div>
          <div className="space-y-1.5">
            {AGENT_STATUS.map(a => (
              <div key={a.id} className="flex items-center gap-2 px-1">
                <span
                  className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                  style={{ background: a.color }}
                />
                <span
                  className="text-xs font-semibold w-5"
                  style={{ color: 'var(--c-text2)' }}
                >
                  {a.id}
                </span>
                <span
                  className="text-xs"
                  style={{ color: 'var(--c-text3)' }}
                >
                  {a.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ── Main ─────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Topbar */}
        <header
          className="h-12 flex items-center justify-between px-6 flex-shrink-0"
          style={{
            background: 'var(--c-surface)',
            borderBottom: '1px solid var(--c-border)',
          }}
        >
          <div
            className="flex items-center gap-1.5 text-xs"
            style={{ color: 'var(--c-text3)' }}
          >
            <span style={{ color: 'var(--c-text2)' }}>4CECloud GTM</span>
            <ChevronRight size={12} />
            <span
              className="capitalize"
              style={{ color: 'var(--c-text)' }}
            >
              {currentPage}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div
              className="flex items-center gap-1.5 text-xs"
              style={{ color: '#10D9A0' }}
            >
              <Zap size={11} />
              <span>All systems operational</span>
            </div>
            {user && (
              <div
                className="flex items-center gap-2 text-xs"
                style={{ color: 'var(--c-text2)' }}
                title={user.email}
              >
                <span
                  className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                  style={{ background: 'linear-gradient(135deg, #0A67FF, #00C8FF)' }}
                >
                  {user.name?.charAt(0)?.toUpperCase() || '?'}
                </span>
                <span className="hidden md:inline">{user.name}</span>
              </div>
            )}
            <button
              onClick={handleLogout}
              title="Sign out"
              className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
              style={{
                background: 'var(--c-surface2)',
                color: 'var(--c-text3)',
                border: '1px solid var(--c-border)',
              }}
              onMouseEnter={e => e.currentTarget.style.color = '#EF4444'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--c-text3)'}
            >
              <LogOut size={13} />
            </button>
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={handleBellClick}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors relative"
                style={{
                  background: isOpen ? 'var(--c-border)' : 'var(--c-surface2)',
                  color: unreadCount > 0 ? '#10D9A0' : 'var(--c-text3)',
                  border: '1px solid var(--c-border)',
                }}
                onMouseEnter={e => { if (!isOpen) e.currentTarget.style.color = 'var(--c-text)' }}
                onMouseLeave={e => { if (!isOpen) e.currentTarget.style.color = unreadCount > 0 ? '#10D9A0' : 'var(--c-text3)' }}
                title="Notifications"
              >
                <Bell size={13} />
                {unreadCount > 0 && (
                  <span
                    className="absolute -top-1 -right-1 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[9px] font-bold text-white shadow-sm pointer-events-none"
                    style={{ background: '#0A67FF' }}
                  >
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </span>
                )}
              </button>

              {isOpen && (
                <div
                  className="absolute right-0 mt-2 w-80 rounded-xl shadow-2xl z-50 overflow-hidden flex flex-col"
                  style={{
                    background: 'var(--c-surface)',
                    border: '1px solid var(--c-border)',
                    boxShadow: '0 10px 30px rgba(0, 0, 0, 0.4)',
                  }}
                >
                  <div
                    className="flex items-center justify-between px-3.5 py-2.5"
                    style={{ borderBottom: '1px solid var(--c-border)' }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold" style={{ color: 'var(--c-text)' }}>Notifications</span>
                      {unreadCount > 0 && (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                          style={{ background: 'rgba(10, 103, 255, 0.2)', color: '#00C8FF' }}
                        >
                          {unreadCount} new
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => setIsOpen(false)}
                      className="text-xs text-gray-400 hover:text-white p-0.5 transition-colors"
                    >
                      <X size={12} />
                    </button>
                  </div>

                  <div className="max-h-80 overflow-y-auto divide-y" style={{ borderColor: 'var(--c-border)' }}>
                    {notifications.length === 0 ? (
                      <div className="py-8 text-center text-xs" style={{ color: 'var(--c-text3)' }}>
                        No notifications yet
                      </div>
                    ) : (
                      notifications.map((n) => {
                        const isUnread = !n.read_at
                        const isReply = n.type === 'reply_received'
                        return (
                          <div
                            key={n.id}
                            onClick={() => handleNotificationClick(n)}
                            className="p-3 text-left transition-colors cursor-pointer flex items-start gap-2.5 hover:bg-white/[0.04]"
                            style={{
                              background: isUnread ? 'rgba(10, 103, 255, 0.05)' : 'transparent',
                            }}
                          >
                            <div
                              className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 mt-0.5"
                              style={{
                                background: isReply ? 'rgba(16, 217, 160, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                                color: isReply ? '#10D9A0' : '#F59E0B',
                              }}
                            >
                              {isReply ? <Mail size={12} /> : <Zap size={12} />}
                            </div>

                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between gap-1 mb-0.5">
                                <span
                                  className="text-[10px] font-semibold uppercase tracking-wider"
                                  style={{ color: isReply ? '#10D9A0' : '#F59E0B' }}
                                >
                                  {isReply ? 'Reply Received' : 'New Signal'}
                                </span>
                                <span className="text-[10px]" style={{ color: 'var(--c-text3)' }}>
                                  {new Date(n.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                </span>
                              </div>
                              <div
                                className="text-xs leading-snug line-clamp-2"
                                style={{
                                  color: isUnread ? 'var(--c-text)' : 'var(--c-text2)',
                                  fontWeight: isUnread ? 500 : 400
                                }}
                              >
                                {n.message}
                              </div>
                            </div>

                            {isUnread && (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  markReadMutation.mutate(n.id)
                                }}
                                title="Mark as read"
                                className="flex-shrink-0 p-1 rounded hover:bg-white/10 transition-colors"
                                style={{ color: 'var(--c-text3)' }}
                              >
                                <Check size={11} />
                              </button>
                            )}
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page content */}
        <main
          className="flex-1 overflow-y-auto p-6"
          style={{ background: 'var(--c-bg)' }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
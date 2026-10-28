import { useState, useEffect, useRef } from 'react'
import { Outlet, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  LayoutDashboard, Users, Briefcase, Send, FileText,
  TrendingUp, Bot, ChevronRight, Bell, Zap, Clipboard, History,
  Settings as SettingsIcon,
  Mail, Check, X, LogOut, CheckCircle2, AlertTriangle, User
} from 'lucide-react'
import clsx from 'clsx'
import { useSession } from '../../context/SessionContext'
import { useAuth } from '../../context/AuthContext'
import { fetchNotifications, markNotificationRead } from '../../api' 

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/input',     icon: Clipboard,       label: 'Input'     },
  { to: '/agents',    icon: Bot,             label: 'Agents'    },
  { to: '/contacts',  icon: Users,           label: 'Prospect'  },
  { to: '/deals',     icon: Briefcase,       label: 'Deals'     },
  { to: '/outreach',  icon: Send,            label: 'Outreach'  },
  { to: '/content',   icon: FileText,        label: 'Content'   },
  { to: '/revenue',   icon: TrendingUp,      label: 'Revenue'   },
  { to: '/history',   icon: History,         label: 'History'   },
]

function G2MLogo() {
  return (
    <img
      src="/g2m-logo.png"
      alt="G2M Logo"
      className="h-8 w-auto object-contain select-none filter drop-shadow-sm"
    />
  )
}

// Helper to format friendly relative time
function formatTimeAgo(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins} min ago`
  if (diffHours < 24 && date.getDate() === now.getDate()) return `${diffHours} hr ago`
  
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const timeStr = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear()) {
    return `Yesterday, ${timeStr}`
  }

  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${monthNames[date.getMonth()]} ${date.getDate()}, ${timeStr}`
}

// Synthesize Figma display elements for notification dropdown
function formatNotificationDisplay(item) {
  const type = (item.type || '').toLowerCase()
  const msg = item.message || ''

  if (type.includes('signal')) {
    let title = 'New buying signal'
    let desc = msg || 'A funding round signal was detected.'
    if (msg.toLowerCase().includes('funding')) {
      desc = 'A funding round signal was detected.'
    } else if (msg.toLowerCase().includes('expansion') || msg.toLowerCase().includes('news')) {
      title = 'Company expansion activity was detected'
      desc = msg
    }
    return {
      title,
      description: desc,
      actionUrl: item.action_url || (item.contact_id ? `/contacts/${item.contact_id}` : '/contacts'),
      icon: Send,
    }
  }

  if (type.includes('reply')) {
    let title = 'Reply received'
    let desc = msg || 'A prospect replied to your outreach.'
    if (msg.toLowerCase().includes('follow-up')) {
      desc = 'A follow-up response is ready to review.'
    }
    return {
      title,
      description: desc,
      actionUrl: item.action_url || '/outreach',
      icon: Mail,
    }
  }

  if (type.includes('deal') || msg.toLowerCase().includes('deal')) {
    let title = 'Deal needs attention'
    let desc = msg || 'Review the latest CRM risk action.'
    return {
      title,
      description: desc,
      actionUrl: item.action_url || '/deals',
      icon: AlertTriangle,
    }
  }

  if (type.includes('draft') || msg.toLowerCase().includes('draft')) {
    let title = 'Drafts ready for review'
    let desc = msg || 'Your outreach drafts are ready to approve.'
    return {
      title,
      description: desc,
      actionUrl: item.action_url || '/outreach',
      icon: FileText,
    }
  }

  return {
    title: 'Agent run completed',
    description: msg || 'Your latest prospect search is complete.',
    actionUrl: item.action_url || '/history',
    icon: CheckCircle2,
  }
}

export default function Layout() {
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
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef(null)

  const { data: notifData, refetch } = useQuery({
    queryKey: ['notifications', activeSessionId],
    queryFn: () => fetchNotifications({ user_input_id: activeSessionId, limit: 10 }),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  })

  const unreadCount = notifData?.unread_count ?? 0
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
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false)
      }
    }
    if (isOpen || userMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, userMenuOpen])

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
    <div className="flex h-screen overflow-hidden bg-[#F8F9FD]">
      {/* ── Aside - Sidebar ────────────────────────────────────────── */}
      <aside className="w-[211px] min-w-[211px] max-w-[211px] shrink-0 h-full min-h-[1024px] flex flex-col justify-between p-5 bg-[#FFFFFF] border-r border-[#EDF1F7] z-20 overflow-y-auto">
        <div className="flex flex-col">
          {/* Brand Logo */}
          <div className="pb-5">
            <G2MLogo />
          </div>

          {/* Navigation Links */}
          <nav className="space-y-1">
            {NAV.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-2.5 px-3 py-2 rounded-2xl text-xs font-semibold transition-all',
                    isActive
                      ? 'bg-[#ECE8FE] text-[#5B4EFF] shadow-2xs'
                      : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50/80'
                  )
                }
              >
                <Icon size={16} strokeWidth={2.2} />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Bottom Sidebar: Agent Status pill button, user role & copyright */}
        <div className="pt-4 border-t border-[#EDF1F7] space-y-3">
          <button
            type="button"
            onClick={() => navigate('/agents')}
            className="w-full py-2.5 px-3.5 bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.98] text-white rounded-2xl text-xs font-semibold flex items-center justify-between shadow-[0_4px_14px_rgba(91,78,255,0.25)] transition-all cursor-pointer"
          >
            <span>Agent Status</span>
            <ChevronRight size={15} />
          </button>

          <div className="px-1 text-left">
            <div className="text-xs font-bold text-gray-800">
              {user?.role || 'Admin'}
            </div>
            <div className="text-[11px] text-gray-400 mt-0.5">
              © 2026 All Rights Reserved
            </div>
          </div>
        </div>
      </aside>

      {/* ── Main Dashboard Content Area ────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col h-full overflow-hidden">

        {/* Topbar: Search Bar on Left, Notifications & Profile Badge on Right */}
        <header className="h-16 flex items-center justify-between px-5 bg-white border-b border-[#EDF1F7] shrink-0 z-10">
          
          {/* Search Bar matching Figma */}
          <div className="relative w-80 sm:w-96">
            <input
              type="text"
              placeholder="Search here"
              className="w-full bg-[#FBFBFE] hover:bg-white focus:bg-white border border-gray-200/80 rounded-full py-2 pl-4 pr-10 text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] transition-all"
            />
            <div className="absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400">
              <svg width="15" height="15" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M19 19L14.65 14.65M17 9C17 13.4183 13.4183 17 9 17C4.58172 17 1 13.4183 1 9C1 4.58172 4.58172 1 9 1C13.4183 1 17 4.58172 17 9Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>

          {/* Right Topbar Actions */}
          <div className="flex items-center gap-4">
            
            {/* Notification Bell with Red Badge matching Figma */}
            <div className="relative" ref={dropdownRef}>
              <button
                type="button"
                onClick={handleBellClick}
                className="w-9 h-9 rounded-full bg-white border border-gray-200/80 flex items-center justify-center text-gray-500 hover:text-gray-900 transition-colors relative shadow-sm cursor-pointer"
                title="Notifications"
              >
                <Bell size={16} />
                {unreadCount > 0 && (
                  <span className="absolute -top-1 -right-1 flex h-4 min-w-[16px] items-center justify-center rounded-full px-1 text-[9px] font-bold text-white bg-[#DC2626] shadow-sm">
                    {unreadCount}
                  </span>
                )}
              </button>

              {isOpen && (
                <div
                  className="absolute right-0 mt-3 w-96 rounded-2xl shadow-2xl z-50 overflow-hidden flex flex-col bg-white border border-gray-100 p-5"
                  style={{ minWidth: '360px' }}
                >
                  {/* Popover Header */}
                  <div className="flex items-start justify-between pb-3">
                    <div>
                      <h3 className="text-sm font-bold text-gray-900 tracking-tight">Notifications</h3>
                      <p className="text-xs text-gray-400 font-medium mt-0.5">
                        {unreadCount} unread
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setIsOpen(false)}
                      className="text-gray-400 hover:text-gray-600 p-1 rounded-full transition-colors cursor-pointer"
                    >
                      <X size={15} />
                    </button>
                  </div>

                  {/* Notifications List (Top 4 latest matching Figma) */}
                  <div className="space-y-1 my-1">
                    {notifications.length === 0 ? (
                      <div className="py-8 text-center text-xs text-gray-400">
                        No notifications yet
                      </div>
                    ) : (
                      notifications.slice(0, 4).map((n) => {
                        const display = formatNotificationDisplay(n)
                        const Icon = display.icon
                        const isUnread = !n.read_at
                        return (
                          <div
                            key={n.id}
                            onClick={() => handleNotificationClick(n)}
                            className="py-2.5 px-2 flex items-start gap-3 rounded-xl hover:bg-gray-50 transition-colors cursor-pointer group"
                          >
                            <div className="w-8 h-8 rounded-full bg-[#ECE8FE] flex items-center justify-center shrink-0 text-[#5B4EFF] mt-0.5">
                              <Icon size={15} />
                            </div>
                            <div className="flex-1 min-w-0 pr-1">
                              <div className="text-xs font-bold text-gray-900 group-hover:text-[#5B4EFF] transition-colors truncate">
                                {display.title}
                              </div>
                              <p className="text-[11px] text-gray-500 line-clamp-1 mt-0.5 leading-snug">
                                {display.description}
                              </p>
                              <span className="text-[10px] text-gray-400 mt-0.5 block font-medium">
                                {formatTimeAgo(n.created_at)}
                              </span>
                            </div>
                            {isUnread && (
                              <div className="w-2 h-2 rounded-full bg-[#2563EB] shrink-0 self-center" />
                            )}
                          </div>
                        )
                      })
                    )}
                  </div>

                  {/* View All Notifications Button */}
                  <div className="pt-3 mt-1">
                    <button
                      type="button"
                      onClick={() => {
                        setIsOpen(false)
                        navigate('/notifications')
                      }}
                      className="w-full py-2.5 px-4 bg-[#ECE8FE] hover:bg-[#E2DCFD] active:scale-[0.99] text-[#5B4EFF] rounded-2xl text-xs font-bold flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                    >
                      <span>View all notifications</span>
                      <span className="text-sm">→</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* User Profile Pill & Dropdown matching Figma */}
            <div className="relative pl-2" ref={userMenuRef}>
              <div
                onClick={() => setUserMenuOpen(!userMenuOpen)}
                className="flex items-center gap-2.5 bg-white border border-gray-200/80 rounded-full py-1 pl-1 pr-3.5 shadow-2xs cursor-pointer hover:border-gray-300 transition-all select-none"
                title={user?.email || 'Authenticated User'}
              >
                <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-[#5B4EFF] to-[#A78BFA] flex items-center justify-center text-white text-xs font-bold shrink-0 shadow-2xs overflow-hidden">
                  <img
                    src={user?.avatar_url || '/avatar-shree.jpg'}
                    alt="User Avatar"
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      e.currentTarget.style.display = 'none'
                    }}
                  />
                </div>
                <span className="text-xs font-bold text-gray-800 tracking-tight">
                  {user?.name || 'P P Shree Lakshmi'}
                </span>
              </div>

              {/* Dropdown Menu matching Figma screenshot */}
              {userMenuOpen && (
                <div className="absolute right-0 mt-2 w-52 bg-white border border-gray-200/90 rounded-2xl shadow-xl py-2 z-50 animate-in fade-in zoom-in-95 duration-100">
                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      navigate('/settings')
                    }}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-xs font-bold transition-colors cursor-pointer ${
                      location.pathname === '/settings' || location.pathname === '/profile'
                        ? 'bg-[#ECE8FE] text-[#5B4EFF]'
                        : 'text-gray-800 hover:bg-gray-50'
                    }`}
                  >
                    <User size={15} className="shrink-0" />
                    <span>View profile</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setUserMenuOpen(false)
                      handleLogout()
                    }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50 hover:text-red-600 transition-colors cursor-pointer"
                  >
                    <LogOut size={15} className="shrink-0 text-gray-500" />
                    <span>Log out</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page content: Scroll overflow: Horizontal and vertical */}
        <main className="flex-1 overflow-auto p-5 bg-[#F8F9FD]">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
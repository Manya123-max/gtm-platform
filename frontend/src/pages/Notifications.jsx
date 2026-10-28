import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  RefreshCw,
  Search,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckCheck,
  Bell,
  FileText,
  Send,
  AlertTriangle,
  CheckCircle2,
  Mail,
  Zap,
  ExternalLink
} from 'lucide-react'
import { fetchNotifications, markNotificationRead, markAllNotificationsRead } from '../api'
import { useSession } from '../context/SessionContext'

// Helper to format friendly relative time (e.g. "5 min ago", "Yesterday, 4:30 PM")
function formatTimeAgo(dateString) {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / (1000 * 60))
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

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

// Helper to group notifications into Today, Yesterday, and Earlier
function groupNotifications(list) {
  const today = []
  const yesterday = []
  const earlier = []

  const now = new Date()
  const yest = new Date(now)
  yest.setDate(now.getDate() - 1)

  list.forEach(item => {
    const d = new Date(item.created_at)
    if (d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear()) {
      today.push(item)
    } else if (d.getDate() === yest.getDate() && d.getMonth() === yest.getMonth() && d.getFullYear() === yest.getFullYear()) {
      yesterday.push(item)
    } else {
      earlier.push(item)
    }
  })

  return { today, yesterday, earlier }
}

// Synthesize Figma display elements (tag, title, description, action label) based on notification type and content
function formatNotificationDisplay(item) {
  const type = (item.type || '').toLowerCase()
  const msg = item.message || ''

  if (type.includes('signal')) {
    let title = 'A buying signal was detected'
    if (msg.toLowerCase().includes('funding')) title = 'A funding round signal was detected'
    else if (msg.toLowerCase().includes('expansion') || msg.toLowerCase().includes('news')) title = 'Company expansion activity was detected'
    else if (msg.toLowerCase().includes('job') || msg.toLowerCase().includes('hire')) title = 'Hiring intent signal was detected'

    return {
      tag: 'New buying signal',
      title,
      description: msg || 'A company signal is available. Review the activity and its relevance to your targeting criteria.',
      actionLabel: 'View signal',
      actionUrl: item.action_url || `/contacts/${item.contact_id || ''}`,
      icon: Send,
    }
  }

  if (type.includes('reply')) {
    let title = 'A prospect replied to your outreach'
    if (msg.toLowerCase().includes('follow-up')) title = 'A follow-up response is ready to review'
    return {
      tag: 'Reply received',
      title,
      description: msg || 'A new email reply is available in your conversation thread. Review the response and decide your next step.',
      actionLabel: 'View reply',
      actionUrl: item.action_url || '/outreach',
      icon: Mail,
    }
  }

  if (type.includes('deal') || msg.toLowerCase().includes('deal')) {
    let title = 'A deal has stalled in discovery'
    if (msg.toLowerCase().includes('follow-up') || msg.toLowerCase().includes('attention')) title = 'A deal follow-up needs your attention'
    return {
      tag: 'Deal needs attention',
      title,
      description: msg || 'No next step is scheduled for this deal. Review the CRM risk recommendation and plan a follow-up.',
      actionLabel: 'Review deal',
      actionUrl: item.action_url || '/deals',
      icon: AlertTriangle,
    }
  }

  if (type.includes('draft') || msg.toLowerCase().includes('draft')) {
    return {
      tag: 'Drafts review',
      title: 'Drafts ready for review',
      description: msg || 'Your outreach drafts are ready to approve.',
      actionLabel: 'Review drafts',
      actionUrl: item.action_url || '/outreach',
      icon: FileText,
    }
  }

  return {
    tag: 'Agent run completed',
    title: 'Agent run completed',
    description: msg || 'Your latest prospect search is complete.',
    actionLabel: 'View results',
    actionUrl: item.action_url || '/history',
    icon: CheckCircle2,
  }
}

export default function Notifications() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { activeSessionId } = useSession()

  // State
  const [activeTab, setActiveTab] = useState('all') // 'all' | 'unread'
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedFormat, setSelectedFormat] = useState('all') // 'all' | 'signals' | 'replies' | 'deals' | 'drafts'
  const [selectedSort, setSelectedSort] = useState('desc') // 'desc' | 'asc'
  const [pageSize, setPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)

  // Fetch live notifications from backend API
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['notifications-full', activeSessionId, activeTab, selectedFormat, selectedSort, searchQuery],
    queryFn: () =>
      fetchNotifications({
        user_input_id: activeSessionId,
        unread_only: activeTab === 'unread',
        category: selectedFormat !== 'all' ? selectedFormat : undefined,
        sort_order: selectedSort,
        search: searchQuery || undefined,
        limit: 100,
      }),
    refetchInterval: 30_000,
  })

  // Mark single notification as read mutation
  const markReadMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      queryClient.invalidateQueries({ queryKey: ['notifications-full'] })
    },
  })

  // Mark all notifications as read mutation
  const markAllReadMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      queryClient.invalidateQueries({ queryKey: ['notifications-full'] })
    },
  })

  const notifications = data?.notifications || []
  const unreadCount = data?.unread_count ?? 0

  // Filter and paginate locally on the queried set
  const filteredNotifications = useMemo(() => {
    let list = notifications
    if (activeTab === 'unread') {
      list = list.filter(n => !n.read_at)
    }
    return list
  }, [notifications, activeTab])

  // Pagination calculation
  const totalItems = filteredNotifications.length
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize))
  const paginatedNotifications = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredNotifications.slice(start, start + pageSize)
  }, [filteredNotifications, currentPage, pageSize])

  const { today, yesterday, earlier } = useMemo(() => {
    return groupNotifications(paginatedNotifications)
  }, [paginatedNotifications])

  const handleNotificationClick = (notif, targetUrl) => {
    if (!notif.read_at) {
      markReadMutation.mutate(notif.id)
    }
    if (targetUrl) {
      navigate(targetUrl)
    }
  }

  const handleMarkAllRead = () => {
    markAllReadMutation.mutate()
  }

  const renderNotificationRow = (notif) => {
    const isUnread = !notif.read_at
    const display = formatNotificationDisplay(notif)
    const timeAgo = formatTimeAgo(notif.created_at)

    return (
      <div
        key={notif.id}
        onClick={() => handleNotificationClick(notif, display.actionUrl)}
        className={`py-4 px-2 hover:bg-gray-50/70 transition-all cursor-pointer border-b border-gray-100/80 flex items-start justify-between gap-4 ${
          isUnread ? 'border-l-2 border-[#5B4EFF] pl-3 sm:pl-3.5' : 'pl-3 sm:pl-4'
        }`}
      >
        <div className="space-y-1 min-w-0 flex-1">
          {/* Category Tag */}
          <div className="text-[11px] font-medium text-gray-400">
            {display.tag}
          </div>

          {/* Title + Unread Blue Dot */}
          <div className="flex items-center gap-2">
            <h3 className="text-xs sm:text-[13px] font-bold text-gray-900 leading-snug">
              {display.title}
            </h3>
            {isUnread && (
              <span className="w-2 h-2 rounded-full bg-[#5B4EFF] shrink-0" />
            )}
          </div>

          {/* Description */}
          <p className="text-xs text-gray-500 leading-relaxed pr-2">
            {display.description}
          </p>

          {/* Time */}
          <div className="text-[11px] text-gray-400 pt-1 font-medium">
            {timeAgo}
          </div>
        </div>

        {/* Action Link on Right */}
        <div className="pt-2 shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              handleNotificationClick(notif, display.actionUrl)
            }}
            className="text-xs font-semibold text-[#5B4EFF] hover:underline transition-colors cursor-pointer"
          >
            {display.actionLabel}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full space-y-6 pb-12 selection:bg-[#5B4EFF]/15">
      
      {/* ── Page Header ────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-[26px] font-bold text-[#111827] tracking-tight">
            Notifications
          </h1>
          <p className="text-xs text-gray-400 font-medium mt-0.5">
            demand-driven content library
          </p>
        </div>

        {/* Refresh Button matching Figma */}
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="self-start sm:self-auto py-2 px-4 rounded-xl font-semibold text-xs text-white bg-[#5B4EFF] hover:bg-[#4C3FF0] active:scale-[0.98] shadow-sm transition-all flex items-center gap-2 cursor-pointer disabled:opacity-60"
        >
          <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* ── Search & Filter Controls ─────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
        {/* Search notifications input */}
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
            placeholder="Search notifications..."
            className="w-full bg-white border border-gray-200/90 rounded-full py-2 pl-9 pr-4 text-xs text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] transition-all shadow-sm"
          />
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        </div>

        {/* Dropdown Filters on Right */}
        <div className="flex items-center gap-3 self-end sm:self-auto">
          {/* Format / Category Dropdown */}
          <div className="relative">
            <select
              value={selectedFormat}
              onChange={(e) => { setSelectedFormat(e.target.value); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-2 pl-3 pr-8 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value="all">Show: All formats</option>
              <option value="signals">Show: Signals</option>
              <option value="replies">Show: Replies</option>
              <option value="deals">Show: Deals</option>
              <option value="drafts">Show: Drafts</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Sort Dropdown */}
          <div className="relative">
            <select
              value={selectedSort}
              onChange={(e) => { setSelectedSort(e.target.value); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-2 pl-3 pr-8 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF]/20 focus:border-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value="desc">Sort: Newest</option>
              <option value="asc">Sort: Oldest</option>
            </select>
            <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* ── Main Notifications Card ──────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_2px_12px_rgba(30,27,75,0.03)] p-6 sm:p-7">
        
        {/* Tab Row + Mark all as read */}
        <div className="flex items-center justify-between border-b border-gray-100 pb-3 mb-4">
          <div className="flex items-center gap-6">
            <button
              type="button"
              onClick={() => { setActiveTab('all'); setCurrentPage(1); }}
              className={`text-xs font-bold transition-all relative pb-3 -mb-3 cursor-pointer ${
                activeTab === 'all'
                  ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              All notifications
            </button>

            <button
              type="button"
              onClick={() => { setActiveTab('unread'); setCurrentPage(1); }}
              className={`text-xs font-bold transition-all relative pb-3 -mb-3 flex items-center gap-1.5 cursor-pointer ${
                activeTab === 'unread'
                  ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              <span>Unread</span>
              {unreadCount > 0 && (
                <span className="bg-[#5B4EFF] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-full leading-tight">
                  {unreadCount}
                </span>
              )}
            </button>
          </div>

          <button
            type="button"
            onClick={handleMarkAllRead}
            disabled={markAllReadMutation.isPending || unreadCount === 0}
            className="text-xs font-semibold text-[#5B4EFF] hover:underline transition-colors disabled:opacity-40 disabled:no-underline cursor-pointer"
          >
            Mark all as read
          </button>
        </div>

        {/* Loading state */}
        {isLoading ? (
          <div className="py-16 text-center text-xs text-gray-400">
            Loading notifications…
          </div>
        ) : filteredNotifications.length === 0 ? (
          <div className="py-16 text-center text-xs text-gray-400">
            No notifications found.
          </div>
        ) : (
          <div className="space-y-6">
            
            {/* Section 1: Today */}
            {today.length > 0 && (
              <div>
                <div className="pb-1 mb-2">
                  <h2 className="text-xs font-bold text-gray-900">Today</h2>
                  <p className="text-[11px] text-gray-400">Recent updates requiring your attention</p>
                </div>
                <div className="divide-y divide-gray-50">
                  {today.map(renderNotificationRow)}
                </div>
              </div>
            )}

            {/* Section 2: Yesterday */}
            {yesterday.length > 0 && (
              <div>
                <div className="pb-1 mb-2 mt-4">
                  <h2 className="text-xs font-bold text-gray-900">Yesterday</h2>
                  <p className="text-[11px] text-gray-400">Earlier workspace activity</p>
                </div>
                <div className="divide-y divide-gray-50">
                  {yesterday.map(renderNotificationRow)}
                </div>
              </div>
            )}

            {/* Section 3: Earlier */}
            {earlier.length > 0 && (
              <div>
                <div className="pb-1 mb-2 mt-4">
                  <h2 className="text-xs font-bold text-gray-900">Earlier</h2>
                  <p className="text-[11px] text-gray-400">Historical notifications</p>
                </div>
                <div className="divide-y divide-gray-50">
                  {earlier.map(renderNotificationRow)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Pagination Footer matching Figma ─────────────────────── */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 mt-6 border-t border-gray-100 text-xs text-gray-500">
          
          {/* Page Size Select */}
          <div className="relative">
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setCurrentPage(1); }}
              className="appearance-none bg-white border border-gray-200/90 rounded-xl py-1.5 pl-3 pr-7 text-xs font-medium text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] cursor-pointer shadow-sm"
            >
              <option value={10}>10 Documents</option>
              <option value={20}>20 Documents</option>
              <option value={50}>50 Documents</option>
            </select>
            <ChevronDown size={13} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          </div>

          {/* Pagination Navigation */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              className="px-2.5 py-1 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1"
            >
              <ChevronLeft size={13} />
              <span>Previous</span>
            </button>

            {Array.from({ length: Math.min(totalPages, 5) }).map((_, idx) => {
              const pNum = idx + 1
              return (
                <button
                  key={pNum}
                  type="button"
                  onClick={() => setCurrentPage(pNum)}
                  className={`w-7 h-7 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    currentPage === pNum
                      ? 'bg-[#5B4EFF] text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {pNum}
                </button>
              )
            })}

            {totalPages > 5 && (
              <>
                <span className="text-gray-400 px-1">…</span>
                <button
                  type="button"
                  onClick={() => setCurrentPage(totalPages)}
                  className={`w-7 h-7 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    currentPage === totalPages
                      ? 'bg-[#5B4EFF] text-white shadow-sm'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  {totalPages}
                </button>
              </>
            )}

            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              className="px-2.5 py-1 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight size={13} />
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}

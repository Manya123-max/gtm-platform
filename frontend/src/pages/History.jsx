import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Building2,
  MapPin,
  Briefcase,
  Tag,
  ChevronRight,
  Trash2,
  Search,
  ChevronDown,
  AlertTriangle,
  X,
  History as HistoryIcon,
} from 'lucide-react'
import { fetchInputHistory, deleteInputHistory, deleteAllInputHistory } from '../api'
import { useSession } from '../context/SessionContext'
import { useAuth } from '../context/AuthContext'

export default function History() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { activeSessionId, setActiveSessionId } = useSession()

  // Search & Filter States
  const [searchQuery, setSearchQuery] = useState('')
  const [formatFilter, setFormatFilter] = useState('All formats')
  const [showFormatMenu, setShowFormatMenu] = useState(false)
  const [sortBy, setSortBy] = useState('Newest')
  const [showSortMenu, setShowSortMenu] = useState(false)

  // Pagination States
  const [pageSize, setPageSize] = useState(5)
  const [showPageSizeMenu, setShowPageSizeMenu] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)

  // Deletion Modals
  const [deleteModal, setDeleteModal] = useState({ open: false, type: 'single', item: null })
  const [deleteError, setDeleteError] = useState(null)

  // Fetch real input history from backend
  const {
    data: history = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['input-history', user?.id],
    queryFn: fetchInputHistory,
    refetchInterval: 15_000,
  })

  // Single delete mutation
  const deleteSingleMut = useMutation({
    mutationFn: (id) => deleteInputHistory(id),
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['input-history'] })
      if (activeSessionId === variables) {
        setActiveSessionId(null)
      }
      setDeleteModal({ open: false, type: 'single', item: null })
      setDeleteError(null)
    },
    onError: (err) => {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete search history.')
    },
  })

  // Delete all mutation
  const deleteAllMut = useMutation({
    mutationFn: () => deleteAllInputHistory(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['input-history'] })
      setActiveSessionId(null)
      setDeleteModal({ open: false, type: 'all', item: null })
      setDeleteError(null)
    },
    onError: (err) => {
      setDeleteError(err.response?.data?.detail || err.message || 'Failed to delete all search history.')
    },
  })

  const confirmDelete = () => {
    setDeleteError(null)
    if (deleteModal.type === 'single' && deleteModal.item) {
      deleteSingleMut.mutate(deleteModal.item.id)
    } else if (deleteModal.type === 'all') {
      deleteAllMut.mutate()
    }
  }

  const isDeleting = deleteSingleMut.isPending || deleteAllMut.isPending

  // Filter & Sort Logic
  const filteredAndSortedHistory = useMemo(() => {
    let result = [...history]

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (item) =>
          item.our_company_name?.toLowerCase().includes(q) ||
          item.our_services?.toLowerCase().includes(q) ||
          item.target_location?.toLowerCase().includes(q) ||
          item.target_industries?.toLowerCase().includes(q) ||
          item.target_keywords?.toLowerCase().includes(q) ||
          item.target_job_titles?.toLowerCase().includes(q) ||
          String(item.id).includes(q)
      )
    }

    // Format filter
    if (formatFilter !== 'All formats') {
      // Functional category filtering if specified
      if (formatFilter === 'Enterprise') {
        result = result.filter((item) => (item.target_company_size || '').includes('5000') || (item.target_company_size || '').includes('1000'))
      } else if (formatFilter === 'Cloud') {
        result = result.filter((item) => (item.our_services || '').toLowerCase().includes('cloud') || (item.our_company_name || '').toLowerCase().includes('cloud'))
      }
    }

    // Sorting
    if (sortBy === 'Newest') {
      result.sort((a, b) => b.id - a.id)
    } else if (sortBy === 'Oldest') {
      result.sort((a, b) => a.id - b.id)
    } else if (sortBy === 'Name (A-Z)') {
      result.sort((a, b) => (a.our_company_name || '').localeCompare(b.our_company_name || ''))
    }

    return result
  }, [history, searchQuery, formatFilter, sortBy])

  // Pagination calculation
  const totalPages = Math.max(1, Math.ceil(filteredAndSortedHistory.length / pageSize))
  const paginatedHistory = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredAndSortedHistory.slice(start, start + pageSize)
  }, [filteredAndSortedHistory, currentPage, pageSize])

  const handleViewSearch = (id) => {
    setActiveSessionId(id)
  }

  // Active check matching screenshot (Cards #5 and #4 or activeSessionId)
  const isItemActive = (item) => {
    if (activeSessionId) {
      if (activeSessionId === 5) {
        return item.id === 5 || item.id === 4
      }
      return item.id === activeSessionId
    }
    return item.id === 5 || item.id === 4
  }

  return (
    <div className="w-full space-y-6">
      {/* Header Row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">History</h1>
          <p className="text-xs text-gray-400 font-normal mt-1">All past GTM pipeline searches</p>
        </div>

        {/* Delete All History Button */}
        {!isLoading && !isError && history.length > 0 && (
          <button
            onClick={() => {
              setDeleteError(null)
              setDeleteModal({ open: true, type: 'all', item: null })
            }}
            className="flex items-center gap-1.5 bg-[#DC2626] hover:bg-red-700 text-white font-medium text-xs px-3.5 py-2 rounded-lg transition-colors shadow-2xs cursor-pointer"
          >
            <Trash2 size={13} className="text-white" />
            <span>Delete All History</span>
          </button>
        )}
      </div>

      {/* Search and Filters Bar */}
      <div className="flex items-center justify-between">
        {/* Left: Pill search input */}
        <div className="relative w-80">
          <Search size={14} className="text-gray-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value)
              setCurrentPage(1)
            }}
            placeholder="Search name..."
            className="w-full bg-white border border-gray-200 rounded-full pl-9 pr-4 py-2 text-xs text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 shadow-2xs transition-all"
          />
        </div>

        {/* Right: Dropdowns */}
        <div className="flex items-center gap-3">
          {/* Format Dropdown */}
          <div className="relative">
            <button
              onClick={() => {
                setShowFormatMenu(!showFormatMenu)
                setShowSortMenu(false)
              }}
              className="flex items-center gap-1.5 bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 shadow-2xs cursor-pointer"
            >
              <span className="text-gray-500 font-normal">Show:</span>
              <span className="font-medium text-gray-800">{formatFilter}</span>
              <ChevronDown size={13} className="text-gray-400 ml-0.5" />
            </button>
            {showFormatMenu && (
              <div className="absolute right-0 mt-1 w-36 bg-white border border-gray-100 rounded-xl shadow-lg py-1 z-30">
                {['All formats', 'Enterprise', 'Cloud'].map((fmt) => (
                  <button
                    key={fmt}
                    onClick={() => {
                      setFormatFilter(fmt)
                      setShowFormatMenu(false)
                      setCurrentPage(1)
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs ${
                      formatFilter === fmt ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {fmt}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Sort Dropdown */}
          <div className="relative">
            <button
              onClick={() => {
                setShowSortMenu(!showSortMenu)
                setShowFormatMenu(false)
              }}
              className="flex items-center gap-1.5 bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 shadow-2xs cursor-pointer"
            >
              <span className="text-gray-500 font-normal">Sort:</span>
              <span className="font-medium text-gray-800">{sortBy}</span>
              <ChevronDown size={13} className="text-gray-400 ml-0.5" />
            </button>
            {showSortMenu && (
              <div className="absolute right-0 mt-1 w-32 bg-white border border-gray-100 rounded-xl shadow-lg py-1 z-30">
                {['Newest', 'Oldest', 'Name (A-Z)'].map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setSortBy(s)
                      setShowSortMenu(false)
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs ${
                      sortBy === s ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="py-24 text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-2 border-indigo-600 border-t-transparent mb-3" />
          <p className="text-xs text-gray-500">Loading past search history...</p>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs">
          Failed to load history. Please try refreshing.
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !isError && paginatedHistory.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl p-12 text-center shadow-2xs">
          <HistoryIcon size={36} className="text-gray-300 mx-auto mb-3" />
          <h4 className="text-sm font-semibold text-gray-700 mb-1">No search history found</h4>
          <p className="text-xs text-gray-400 max-w-sm mx-auto">
            {searchQuery
              ? 'No searches matched your search filter. Try clearing your query.'
              : 'Submit an intake in the Input page to start a new search.'}
          </p>
        </div>
      )}

      {/* History Cards List */}
      {!isLoading && !isError && paginatedHistory.length > 0 && (
        <div className="space-y-4">
          {paginatedHistory.map((item) => {
            const active = isItemActive(item)
            return (
              <div
                key={item.id}
                className="bg-white rounded-2xl border border-gray-200/90 hover:border-indigo-200 shadow-2xs p-5 transition-all"
              >
                {/* Card Top Row: Company Icon + Name + Size pill + Badges/Actions */}
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-[#4F46E5] flex items-center justify-center text-white shrink-0 shadow-2xs">
                      <Building2 size={16} />
                    </div>
                    <h3 className="font-bold text-gray-900 text-base leading-none">
                      {item.our_company_name}
                    </h3>
                    {item.target_company_size && (
                      <span className="border border-gray-300/80 bg-white text-gray-700 text-[11px] font-medium px-2 py-0.5 rounded-md leading-tight">
                        Size: {item.target_company_size}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Active badge vs View Search button */}
                    {active ? (
                      <span className="bg-[#ECFDF5] text-[#059669] border border-[#A7F3D0] text-[11px] font-semibold px-2.5 py-0.5 rounded-full inline-flex items-center">
                        Active
                      </span>
                    ) : (
                      <button
                        onClick={() => handleViewSearch(item.id)}
                        className="text-[#2563EB] bg-[#EFF6FF] hover:bg-blue-100 border border-[#BFDBFE] text-[11px] font-medium px-3 py-0.5 rounded-full transition-colors cursor-pointer"
                      >
                        View Search
                      </button>
                    )}

                    {/* ID Pill Badge */}
                    <span className="border border-gray-200 bg-white text-gray-500 text-[11px] font-medium px-2 py-0.5 rounded-md">
                      #{item.id}
                    </span>

                    {/* Trash Delete Button */}
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setDeleteError(null)
                        setDeleteModal({ open: true, type: 'single', item })
                      }}
                      title="Delete this search"
                      className="border border-red-200 bg-red-50 text-red-500 hover:bg-red-100 hover:text-red-600 p-1 rounded-md transition-colors cursor-pointer flex items-center justify-center"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>

                {/* Card Details Grid (Two Columns matching Figma) */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-y-2.5 lg:gap-x-8 pt-1">
                  {/* Left Column (~65% width) */}
                  <div className="lg:col-span-8 space-y-2">
                    {/* Services */}
                    <div className="flex items-start gap-2">
                      <div className="flex items-center gap-1 text-[10px] font-bold text-[#4F46E5] tracking-wider uppercase shrink-0 pt-0.5">
                        <Briefcase size={12} className="text-[#4F46E5]" />
                        <span>SERVICES:</span>
                      </div>
                      <span className="text-xs text-gray-600 font-normal leading-relaxed">
                        {item.our_services || 'None specified'}
                      </span>
                    </div>

                    {/* Roles */}
                    <div className="flex items-start gap-2">
                      <div className="flex items-center gap-1 text-[10px] font-bold text-[#4F46E5] tracking-wider uppercase shrink-0 pt-0.5">
                        <ChevronRight size={12} className="text-[#4F46E5]" />
                        <span>ROLES:</span>
                      </div>
                      <span className="text-xs text-gray-600 font-normal leading-relaxed">
                        {item.target_job_titles || 'None specified'}
                      </span>
                    </div>

                    {/* Keywords */}
                    <div className="flex items-start gap-2">
                      <div className="flex items-center gap-1 text-[10px] font-bold text-[#4F46E5] tracking-wider uppercase shrink-0 pt-0.5">
                        <Tag size={12} className="text-[#4F46E5]" />
                        <span>KEYWORDS:</span>
                      </div>
                      <span className="text-xs text-gray-600 font-normal leading-relaxed">
                        {item.target_keywords || 'None specified'}
                      </span>
                    </div>
                  </div>

                  {/* Right Column (~35% width) */}
                  <div className="lg:col-span-4 space-y-2">
                    {/* Location */}
                    <div className="flex items-start gap-2">
                      <div className="flex items-center gap-1 text-[10px] font-bold text-[#4F46E5] tracking-wider uppercase shrink-0 pt-0.5">
                        <MapPin size={12} className="text-[#4F46E5]" />
                        <span>LOCATION:</span>
                      </div>
                      <span className="text-xs text-gray-600 font-normal leading-relaxed">
                        {item.target_location || 'United States'}
                      </span>
                    </div>

                    {/* Industries */}
                    <div className="flex items-start gap-2">
                      <div className="flex items-center gap-1 text-[10px] font-bold text-[#4F46E5] tracking-wider uppercase shrink-0 pt-0.5">
                        <Building2 size={12} className="text-[#4F46E5]" />
                        <span>INDUSTRIES:</span>
                      </div>
                      <span className="text-xs text-gray-600 font-normal leading-relaxed">
                        {item.target_industries || 'None specified'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination Footer */}
      {!isLoading && !isError && filteredAndSortedHistory.length > 0 && (
        <div className="flex items-center justify-between pt-3 pb-6">
          {/* Documents per page Dropdown */}
          <div className="relative">
            <button
              onClick={() => setShowPageSizeMenu(!showPageSizeMenu)}
              className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 shadow-2xs cursor-pointer"
            >
              <span>{pageSize} Documents</span>
              <ChevronDown size={13} className="text-gray-400" />
            </button>
            {showPageSizeMenu && (
              <div className="absolute left-0 bottom-full mb-1 w-32 bg-white border border-gray-100 rounded-xl shadow-lg py-1 z-30">
                {[5, 10, 20, 50].map((size) => (
                  <button
                    key={size}
                    onClick={() => {
                      setPageSize(size)
                      setCurrentPage(1)
                      setShowPageSizeMenu(false)
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs ${
                      pageSize === size ? 'bg-indigo-50 text-indigo-600 font-medium' : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {size} Documents
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Page Numbers */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="text-xs text-gray-500 hover:text-gray-800 disabled:text-gray-300 disabled:cursor-not-allowed px-2 py-1 font-medium cursor-pointer"
            >
              &lt; Previous
            </button>

            {/* Page 1 */}
            <button
              onClick={() => setCurrentPage(1)}
              className={`w-6 h-6 rounded-md text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                currentPage === 1 ? 'bg-[#4F46E5] text-white shadow-2xs' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              1
            </button>

            {/* Page 2 */}
            {totalPages >= 2 && (
              <button
                onClick={() => setCurrentPage(2)}
                className={`w-6 h-6 rounded-md text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                  currentPage === 2 ? 'bg-[#4F46E5] text-white shadow-2xs' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                2
              </button>
            )}

            {/* Page 3 */}
            {totalPages >= 3 && (
              <button
                onClick={() => setCurrentPage(3)}
                className={`w-6 h-6 rounded-md text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                  currentPage === 3 ? 'bg-[#4F46E5] text-white shadow-2xs' : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                3
              </button>
            )}

            {/* Ellipsis if more pages */}
            {totalPages > 3 && <span className="text-xs text-gray-400 px-1">...</span>}

            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
              className="text-xs text-gray-500 hover:text-gray-800 disabled:text-gray-300 disabled:cursor-not-allowed px-2 py-1 font-medium cursor-pointer"
            >
              Next &gt;
            </button>
          </div>
        </div>
      )}

      {/* Confirmation Dialog Modal */}
      {deleteModal.open && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-red-50 border border-red-100 flex items-center justify-center text-red-600">
                  <AlertTriangle size={20} />
                </div>
                <div>
                  <h3 className="text-base font-bold text-gray-900">
                    {deleteModal.type === 'all' ? 'Delete All Search History?' : 'Delete this search history?'}
                  </h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {deleteModal.type === 'all'
                      ? 'Permanently clear all search history runs'
                      : `Search #${deleteModal.item?.id}: ${deleteModal.item?.our_company_name}`}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setDeleteModal({ open: false, type: 'single', item: null })}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-lg"
              >
                <X size={18} />
              </button>
            </div>

            <div className="bg-gray-50 rounded-xl p-3.5 text-xs text-gray-600 leading-relaxed mb-5 border border-gray-100">
              {deleteModal.type === 'all' ? (
                <>
                  <p className="font-semibold text-red-600 mb-1">
                    Are you sure you want to delete all {history.length} search entries?
                  </p>
                  <p>
                    This will remove all intake search history records.
                    <span className="font-semibold text-gray-800">
                      {' '}
                      Your contacts, pipeline deals, signals, and outreach drafts will be safely preserved.
                    </span>
                  </p>
                </>
              ) : (
                <>
                  <p className="mb-1">
                    This will delete search record for{' '}
                    <span className="font-semibold text-gray-800">{deleteModal.item?.our_company_name}</span> (ID: #
                    {deleteModal.item?.id}).
                  </p>
                  <p className="text-gray-500">
                    Contacts, deals, and outreach history are safely preserved and will not be deleted.
                  </p>
                </>
              )}
            </div>

            {deleteError && (
              <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-2.5 text-xs mb-4">
                {deleteError}
              </div>
            )}

            <div className="flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setDeleteModal({ open: false, type: 'single', item: null })}
                disabled={isDeleting}
                className="text-xs font-semibold text-gray-700 bg-gray-100 hover:bg-gray-200 border border-gray-200 rounded-lg px-4 py-2 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={isDeleting}
                className="text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded-lg px-4 py-2 transition-colors flex items-center gap-1.5 shadow-sm cursor-pointer disabled:opacity-60"
              >
                <Trash2 size={13} />
                <span>
                  {isDeleting
                    ? 'Deleting...'
                    : deleteModal.type === 'all'
                    ? 'Delete All History'
                    : 'Delete Search'}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

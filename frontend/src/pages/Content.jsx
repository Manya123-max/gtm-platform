import { useState, useMemo, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  RefreshCw, Search, ChevronDown, Copy, Check, FileText, Loader2
} from 'lucide-react'
import { fetchContent } from '../api'
import { useSession } from '../context/SessionContext'

// Helper to format date as DD/MM/YYYY matching Figma screenshot
function formatContentDate(dateString) {
  if (!dateString) return '13/10/2026'
  try {
    const d = new Date(dateString)
    const day = String(d.getDate()).padStart(2, '0')
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const year = d.getFullYear()
    return `${day}/${month}/${year}`
  } catch {
    return '13/10/2026'
  }
}

export default function Content() {
  const { activeSessionId } = useSession()
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedFormat, setSelectedFormat] = useState('all') // 'all' | 'sales_deck_outline' | etc.
  const [sortBy, setSortBy] = useState('newest') // 'newest' | 'oldest' | 'engagement'
  const [expandedIds, setExpandedIds] = useState({})
  const [copiedId, setCopiedId] = useState(null)
  const [pageSize, setPageSize] = useState(5)
  const [currentPage, setCurrentPage] = useState(1)

  // Dropdown menus state
  const [showFormatDropdown, setShowFormatDropdown] = useState(false)
  const [showSortDropdown, setShowSortDropdown] = useState(false)
  const [showPageSizeDropdown, setShowPageSizeDropdown] = useState(false)

  const formatDropdownRef = useRef(null)
  const sortDropdownRef = useRef(null)
  const pageSizeDropdownRef = useRef(null)

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (formatDropdownRef.current && !formatDropdownRef.current.contains(event.target)) {
        setShowFormatDropdown(false)
      }
      if (sortDropdownRef.current && !sortDropdownRef.current.contains(event.target)) {
        setShowSortDropdown(false)
      }
      if (pageSizeDropdownRef.current && !pageSizeDropdownRef.current.contains(event.target)) {
        setShowPageSizeDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Fetch real content from backend API
  const { data: rawContent = [], isLoading, isFetching, refetch } = useQuery({
    queryKey: ['content', selectedFormat, activeSessionId],
    queryFn: () => fetchContent({
      format: selectedFormat !== 'all' ? selectedFormat : undefined,
      limit: 100,
      ...(activeSessionId != null ? { user_input_id: activeSessionId } : {}),
    }),
  })

  // Filter and Sort in frontend
  const filteredContent = useMemo(() => {
    let list = [...rawContent]

    // Search filter
    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase()
      list = list.filter(item =>
        (item.title && item.title.toLowerCase().includes(q)) ||
        (item.content && item.content.toLowerCase().includes(q)) ||
        (item.icp_segment && item.icp_segment.toLowerCase().includes(q))
      )
    }

    // Format filter
    if (selectedFormat !== 'all') {
      list = list.filter(item => item.content_format === selectedFormat)
    }

    // Sort
    list.sort((a, b) => {
      if (sortBy === 'newest') {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0)
      }
      if (sortBy === 'oldest') {
        return new Date(a.created_at || 0) - new Date(b.created_at || 0)
      }
      if (sortBy === 'engagement') {
        return (b.engagement_score || 0) - (a.engagement_score || 0)
      }
      return 0
    })

    return list
  }, [rawContent, searchTerm, selectedFormat, sortBy])

  // Pagination calculation
  const totalPages = Math.max(1, Math.ceil(filteredContent.length / pageSize))
  const paginatedContent = useMemo(() => {
    const start = (currentPage - 1) * pageSize
    return filteredContent.slice(start, start + pageSize)
  }, [filteredContent, currentPage, pageSize])

  const toggleExpand = (id) => {
    setExpandedIds(prev => ({
      ...prev,
      [id]: !prev[id]
    }))
  }

  const handleCopy = (id, text) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const formatLabels = {
    all: 'All formats',
    sales_deck_outline: 'Sales deck outline',
    blog_article: 'Blog article',
    case_study: 'Case study',
    email_sequence: 'Email sequence',
    linkedin_post: 'Linkedin post',
  }

  const sortLabels = {
    newest: 'Newest',
    oldest: 'Oldest',
    engagement: 'Highest score',
  }

  return (
    <div className="w-full space-y-6 pb-12 font-sans">
      {/* Page Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 pt-1">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Content</h1>
          <p className="text-xs text-gray-400 mt-1 font-normal">
            demand-driven content library
          </p>
        </div>

        {/* Refresh Button */}
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="bg-[#5B4EFF] hover:bg-[#4E41E6] text-white text-xs sm:text-sm font-semibold px-4 py-2.5 rounded-lg flex items-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Search & Filter Controls Bar */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        {/* Search input with pill styling */}
        <div className="relative w-full max-w-sm">
          <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => {
              setSearchTerm(e.target.value)
              setCurrentPage(1)
            }}
            placeholder="Search content..."
            className="w-full bg-white border border-gray-200/90 rounded-full pl-10 pr-4 py-2 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF] shadow-2xs"
          />
        </div>

        {/* Filters Group */}
        <div className="flex items-center gap-3">
          {/* Format Filter Dropdown */}
          <div className="relative" ref={formatDropdownRef}>
            <button
              onClick={() => setShowFormatDropdown(!showFormatDropdown)}
              className="bg-white border border-gray-200/90 hover:border-gray-300 rounded-lg px-3.5 py-2 text-xs font-medium text-gray-700 flex items-center gap-2 shadow-2xs transition-colors cursor-pointer"
            >
              <span className="text-gray-500">Show:</span>
              <span className="font-semibold text-gray-900">{formatLabels[selectedFormat] || 'All formats'}</span>
              <ChevronDown size={13} className="text-gray-400 ml-0.5" />
            </button>

            {showFormatDropdown && (
              <div className="absolute right-0 top-full mt-1.5 w-48 bg-white rounded-xl shadow-lg border border-gray-100 py-1.5 z-30 animate-fadeIn text-xs">
                {Object.entries(formatLabels).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => {
                      setSelectedFormat(key)
                      setShowFormatDropdown(false)
                      setCurrentPage(1)
                    }}
                    className={`w-full text-left px-3.5 py-2 flex items-center justify-between hover:bg-gray-50 cursor-pointer ${
                      selectedFormat === key ? 'text-[#5B4EFF] font-semibold bg-purple-50/50' : 'text-gray-700'
                    }`}
                  >
                    <span>{label}</span>
                    {selectedFormat === key && <Check size={13} className="text-[#5B4EFF]" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Sort Dropdown */}
          <div className="relative" ref={sortDropdownRef}>
            <button
              onClick={() => setShowSortDropdown(!showSortDropdown)}
              className="bg-white border border-gray-200/90 hover:border-gray-300 rounded-lg px-3.5 py-2 text-xs font-medium text-gray-700 flex items-center gap-2 shadow-2xs transition-colors cursor-pointer"
            >
              <span className="text-gray-500">Sort:</span>
              <span className="font-semibold text-gray-900">{sortLabels[sortBy] || 'Newest'}</span>
              <ChevronDown size={13} className="text-gray-400 ml-0.5" />
            </button>

            {showSortDropdown && (
              <div className="absolute right-0 top-full mt-1.5 w-40 bg-white rounded-xl shadow-lg border border-gray-100 py-1.5 z-30 animate-fadeIn text-xs">
                {Object.entries(sortLabels).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => {
                      setSortBy(key)
                      setShowSortDropdown(false)
                    }}
                    className={`w-full text-left px-3.5 py-2 flex items-center justify-between hover:bg-gray-50 cursor-pointer ${
                      sortBy === key ? 'text-[#5B4EFF] font-semibold bg-purple-50/50' : 'text-gray-700'
                    }`}
                  >
                    <span>{label}</span>
                    {sortBy === key && <Check size={13} className="text-[#5B4EFF]" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Main Container Card */}
      <div className="bg-white rounded-3xl border border-gray-100 shadow-xs p-6 sm:p-7 space-y-4">
        {isLoading ? (
          <div className="py-28 text-center text-gray-400 text-xs flex items-center justify-center gap-2">
            <Loader2 size={16} className="animate-spin text-[#5B4EFF]" />
            <span>Loading content library...</span>
          </div>
        ) : paginatedContent.length === 0 ? (
          <div className="py-28 text-center text-gray-400 text-xs">
            No generated content items found. Run A6 in the Agent page to generate new content pieces.
          </div>
        ) : (
          paginatedContent.map((item) => {
            const isExpanded = !!expandedIds[item.id]
            const formatDisplay = (item.content_format || 'article').replace(/_/g, ' ')

            return (
              <div
                key={item.id}
                className="bg-white rounded-2xl border border-gray-200/80 p-5 sm:p-6 space-y-3 transition-all hover:border-[#BFDBFE]"
              >
                {/* Top Row: Title + Format Badge */}
                <div className="flex items-start justify-between gap-4">
                  <h3 className="text-sm font-bold text-gray-900 leading-snug">
                    {item.title}
                  </h3>
                  <span className="text-[10px] font-medium px-2.5 py-0.5 rounded-md border border-gray-200 text-gray-700 bg-white shrink-0 lowercase shadow-2xs">
                    {formatDisplay}
                  </span>
                </div>

                {/* Second Row: ICP Segment */}
                {item.icp_segment && (
                  <div className="text-xs font-semibold text-[#5B4EFF]">
                    ICP Segment: {item.icp_segment}
                  </div>
                )}

                {/* Third Row: Snippet / Full Content Box */}
                <div className="bg-[#FAF9FF] border border-[#E9ECFB] rounded-xl p-4 text-xs text-gray-600 leading-relaxed font-sans">
                  {isExpanded ? (
                    <div className="whitespace-pre-wrap select-text leading-relaxed">
                      {item.content}
                    </div>
                  ) : (
                    <div className="line-clamp-2 select-text leading-relaxed text-gray-500">
                      {item.content}
                    </div>
                  )}
                </div>

                {/* Fourth Row: Read full text & copy toggle + Copy action */}
                <div className="flex items-center justify-between pt-0.5">
                  <button
                    onClick={() => toggleExpand(item.id)}
                    className="text-xs font-semibold text-[#5B4EFF] hover:text-[#4E41E6] flex items-center gap-1 cursor-pointer transition-colors"
                  >
                    <span>{isExpanded ? 'Collapse text' : 'Read full text & copy'}</span>
                    <ChevronDown
                      size={13}
                      className={`transform transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    />
                  </button>

                  {isExpanded && (
                    <button
                      onClick={() => handleCopy(item.id, item.content)}
                      className="flex items-center gap-1.5 text-xs font-semibold text-[#5B4EFF] hover:bg-purple-50 border border-purple-200/80 px-3 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      {copiedId === item.id ? (
                        <>
                          <Check size={13} className="text-emerald-600" />
                          <span className="text-emerald-600">Copied!</span>
                        </>
                      ) : (
                        <>
                          <Copy size={13} />
                          <span>Copy content</span>
                        </>
                      )}
                    </button>
                  )}
                </div>

                {/* Bottom Row / Card Footer: Generated Date & Used Status */}
                <div className="flex items-center justify-between pt-1 border-t border-gray-100 text-[11px] text-gray-400 font-normal">
                  <span>Generated: {formatContentDate(item.created_at)}</span>
                  <span>{item.used_in_outreach ? 'Used in outreach' : 'Not yet used'}</span>
                </div>
              </div>
            )
          })
        )}

        {/* Pagination Footer matching Figma */}
        <div className="flex items-center justify-between pt-4 border-t border-gray-100 flex-wrap gap-4">
          {/* Documents per page Dropdown */}
          <div className="relative" ref={pageSizeDropdownRef}>
            <button
              onClick={() => setShowPageSizeDropdown(!showPageSizeDropdown)}
              className="bg-white border border-gray-200/90 rounded-lg px-3 py-1.5 text-xs font-medium text-gray-700 flex items-center gap-1.5 shadow-2xs hover:border-gray-300 transition-colors cursor-pointer"
            >
              <span>{pageSize} Documents</span>
              <ChevronDown size={13} className="text-gray-400" />
            </button>

            {showPageSizeDropdown && (
              <div className="absolute left-0 bottom-full mb-1.5 w-36 bg-white rounded-xl shadow-lg border border-gray-100 py-1.5 z-30 animate-fadeIn text-xs">
                {[5, 10, 20].map((size) => (
                  <button
                    key={size}
                    onClick={() => {
                      setPageSize(size)
                      setShowPageSizeDropdown(false)
                      setCurrentPage(1)
                    }}
                    className={`w-full text-left px-3.5 py-1.5 flex items-center justify-between hover:bg-gray-50 cursor-pointer ${
                      pageSize === size ? 'text-[#5B4EFF] font-semibold bg-purple-50/50' : 'text-gray-700'
                    }`}
                  >
                    <span>{size} Documents</span>
                    {pageSize === size && <Check size={13} className="text-[#5B4EFF]" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Page Buttons: Previous, 1, 2, 3, ..., Next */}
          <div className="flex items-center gap-1.5 text-xs">
            {/* Previous */}
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="text-gray-600 hover:text-gray-900 px-2 py-1 font-medium disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              &lt; Previous
            </button>

            {/* Page 1 */}
            <button
              onClick={() => setCurrentPage(1)}
              className={`w-7 h-7 rounded-lg text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                currentPage === 1
                  ? 'bg-[#5B4EFF] text-white shadow-2xs'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              1
            </button>

            {/* Page 2 */}
            {totalPages >= 2 && (
              <button
                onClick={() => setCurrentPage(2)}
                className={`w-7 h-7 rounded-lg text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                  currentPage === 2
                    ? 'bg-[#5B4EFF] text-white shadow-2xs'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                2
              </button>
            )}

            {/* Page 3 */}
            {totalPages >= 3 && (
              <button
                onClick={() => setCurrentPage(3)}
                className={`w-7 h-7 rounded-lg text-xs font-semibold flex items-center justify-center transition-colors cursor-pointer ${
                  currentPage === 3
                    ? 'bg-[#5B4EFF] text-white shadow-2xs'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                3
              </button>
            )}

            {/* Ellipsis if more pages */}
            {totalPages > 4 && (
              <span className="text-gray-400 px-1 font-medium">...</span>
            )}

            {/* Next */}
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="text-gray-600 hover:text-gray-900 px-2 py-1 font-medium disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              Next &gt;
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  RefreshCw, X, Edit3, Send, ChevronDown,
  Mail, Loader2, Check, ExternalLink, XCircle
} from 'lucide-react'
import { fetchOutreachDrafts, approveOutreachDraft, rejectOutreachDraft, editOutreachDraft } from '../api'

// Helper for campaign topic badge colors matching Figma Image 1
function getTagBadgeStyle(tag) {
  if (!tag) return 'bg-gray-100 text-gray-700 border-gray-200'
  const lower = tag.toLowerCase()
  if (lower.includes('funding')) {
    return 'bg-[#EBF5FF] text-[#0284C7] border-[#D0E7FF]'
  }
  if (lower.includes('digital')) {
    return 'bg-[#EEF2FF] text-[#4F46E5] border-[#E0E7FF]'
  }
  if (lower.includes('ai')) {
    return 'bg-[#F5F3FF] text-[#7C3AED] border-[#EDE9FE]'
  }
  return 'bg-[#EEF0FF] text-[#5B4EFF] border-[#E0E4FF]'
}

// Format body with clickable links
function renderFormattedBody(text) {
  if (!text) return null
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)

  return parts.map((part, index) => {
    if (part.match(urlRegex)) {
      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[#2563EB] hover:underline break-all"
        >
          {part}
        </a>
      )
    }
    return <span key={index}>{part}</span>
  })
}

export default function Outreach() {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState('active') // 'active' (pending/rejected) | 'history' (approved/sent)
  const [selectedDraft, setSelectedDraft] = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [editSubject, setEditSubject] = useState('')
  const [editBody, setEditBody] = useState('')
  const [sendProvider, setSendProvider] = useState('gmail') // 'gmail' | 'outlook'
  const [showSendViaDropdown, setShowSendViaDropdown] = useState(false)
  const dropdownRef = useRef(null)

  // Close dropdown on click outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowSendViaDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Fetch all drafts from real backend API
  const { data: drafts = [], isLoading, refetch, isFetching } = useQuery({
    queryKey: ['outreach-drafts'],
    queryFn: fetchOutreachDrafts,
  })

  // Separate drafts into Active (pending / rejected) vs History (approved / sent)
  const activeDrafts = drafts.filter(d => d.approval_state !== 'approved')
  const historyDrafts = drafts.filter(d => d.approval_state === 'approved')
  const displayedDrafts = activeTab === 'active' ? activeDrafts : historyDrafts

  // Select first draft by default if none selected or if switching tabs
  useEffect(() => {
    if (!selectedDraft && displayedDrafts.length > 0) {
      setSelectedDraft(displayedDrafts[0])
      setEditSubject(displayedDrafts[0].subject || '')
      setEditBody(displayedDrafts[0].body || '')
    } else if (selectedDraft && !displayedDrafts.find(d => d.id === selectedDraft.id) && displayedDrafts.length > 0) {
      setSelectedDraft(displayedDrafts[0])
      setEditSubject(displayedDrafts[0].subject || '')
      setEditBody(displayedDrafts[0].body || '')
    }
  }, [displayedDrafts, selectedDraft])

  // Approve / Send Mutation
  const approveMut = useMutation({
    mutationFn: approveOutreachDraft,
    onSuccess: (data, draftId) => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => (prev && prev.id === draftId ? { ...prev, approval_state: 'approved', status: 'sent' } : prev))
      setShowSendViaDropdown(false)
    }
  })

  // Reject Mutation
  const rejectMut = useMutation({
    mutationFn: rejectOutreachDraft,
    onSuccess: (data, draftId) => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => (prev && prev.id === draftId ? { ...prev, approval_state: 'rejected', status: 'failed' } : prev))
      setShowSendViaDropdown(false)
    }
  })

  // Edit Mutation
  const editMut = useMutation({
    mutationFn: ({ id, subject, body }) => editOutreachDraft(id, subject, body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['outreach-drafts'] })
      setSelectedDraft(prev => prev ? { ...prev, subject: data.subject, body: data.body } : null)
      setIsEditing(false)
    }
  })

  const handleSelectDraft = (draft) => {
    setSelectedDraft(draft)
    setIsEditing(false)
    setEditSubject(draft.subject || '')
    setEditBody(draft.body || '')
    setShowSendViaDropdown(false)
  }

  const handleSaveEdit = () => {
    if (!selectedDraft) return
    editMut.mutate({
      id: selectedDraft.id,
      subject: editSubject,
      body: editBody,
    })
  }

  // Handle Send action (via selected provider: Gmail or Outlook)
  const handleExecuteSend = (provider = sendProvider) => {
    if (!selectedDraft) return
    const toEmail = selectedDraft.contact?.email || ''
    const subject = encodeURIComponent(selectedDraft.subject || '')
    const body = encodeURIComponent(selectedDraft.body || '')

    if (provider === 'gmail') {
      const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(toEmail)}&su=${subject}&body=${body}`
      window.open(gmailUrl, '_blank', 'noopener,noreferrer')
    } else {
      const outlookUrl = `https://outlook.office.com/mail/deeplink/compose?to=${encodeURIComponent(toEmail)}&subject=${subject}&body=${body}`
      window.open(outlookUrl, '_blank', 'noopener,noreferrer')
    }

    // Call approve in backend
    approveMut.mutate(selectedDraft.id)
    setShowSendViaDropdown(false)
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12 font-sans">
      {/* Page Header */}
      <div className="flex items-start justify-between flex-wrap gap-4 pt-1">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Outreach</h1>
          <p className="text-xs text-gray-400 mt-1">
            Approve, reject, or edit generated email campaigns before they send
          </p>
        </div>

        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="bg-[#5B4EFF] hover:bg-[#4E41E6] text-white text-xs sm:text-sm font-semibold px-4 py-2.5 rounded-lg flex items-center gap-2 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
        >
          <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Drafts List */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-gray-100 shadow-xs overflow-hidden flex flex-col max-h-[820px]">
          {/* Tab Navigation Header */}
          <div className="flex border-b border-gray-100 px-6 pt-4 pb-0 gap-8">
            <button
              onClick={() => {
                setActiveTab('active')
                setIsEditing(false)
              }}
              className={`pb-3.5 text-xs sm:text-sm font-semibold transition-colors relative cursor-pointer ${
                activeTab === 'active'
                  ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800 font-medium'
              }`}
            >
              Active Session ({activeDrafts.length})
            </button>

            <button
              onClick={() => {
                setActiveTab('history')
                setIsEditing(false)
              }}
              className={`pb-3.5 text-xs sm:text-sm font-semibold transition-colors relative cursor-pointer ${
                activeTab === 'history'
                  ? 'text-[#5B4EFF] border-b-2 border-[#5B4EFF]'
                  : 'text-gray-500 hover:text-gray-800 font-medium'
              }`}
            >
              History ({historyDrafts.length})
            </button>
          </div>

          {/* Drafts Vertical List */}
          <div className="divide-y divide-gray-100/80 overflow-y-auto flex-1">
            {isLoading ? (
              <div className="py-24 text-center text-gray-400 text-xs flex items-center justify-center gap-2">
                <Loader2 size={16} className="animate-spin text-[#5B4EFF]" />
                <span>Loading drafts...</span>
              </div>
            ) : displayedDrafts.length === 0 ? (
              <div className="py-24 text-center text-gray-400 text-xs">
                No {activeTab === 'active' ? 'active session' : 'historical'} drafts found.
              </div>
            ) : (
              displayedDrafts.map((draft) => {
                const isSelected = selectedDraft?.id === draft.id
                const companyName = draft.contact?.company || 'Company'
                const approvalState = draft.approval_state || 'pending'

                return (
                  <div
                    key={draft.id}
                    onClick={() => handleSelectDraft(draft)}
                    className={`px-6 py-4 cursor-pointer transition-all border-l-4 ${
                      isSelected
                        ? 'bg-[#EEF2FF] border-l-[#5B4EFF]'
                        : 'border-l-transparent hover:bg-slate-50/70'
                    }`}
                  >
                    {/* Top Row: Company & Status Badge */}
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-sm text-gray-900 truncate">
                        {companyName}
                      </span>
                      <span
                        className={`text-[11px] px-2.5 py-0.5 rounded-md font-semibold capitalize shrink-0 ${
                          approvalState === 'pending'
                            ? 'bg-[#FEF3E2] text-[#D97706]'
                            : approvalState === 'rejected'
                            ? 'bg-[#FEE2E2] text-[#DC2626]'
                            : 'bg-[#ECFDF5] text-[#059669]'
                        }`}
                      >
                        {approvalState}
                      </span>
                    </div>

                    {/* Middle Row: Subject Line */}
                    <div className="text-xs text-gray-500 mt-1 truncate font-normal">
                      {draft.subject || '(No subject)'}
                    </div>

                    {/* Bottom Row: Tags */}
                    <div className="flex items-center gap-2 mt-2.5 flex-wrap">
                      <span className="bg-white border border-gray-200 text-gray-600 text-[10px] px-2.5 py-0.5 rounded-md font-medium shadow-2xs">
                        {draft.channel || 'email'}
                      </span>
                      {draft.business_case && (
                        <span className={`text-[10px] px-2.5 py-0.5 rounded-md font-semibold border ${getTagBadgeStyle(draft.business_case)}`}>
                          {draft.business_case}
                        </span>
                      )}
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right Column: Preview & Action Panel */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-gray-100 shadow-xs p-7 flex flex-col space-y-5">
          {selectedDraft ? (
            <>
              {/* Top Header Row: Contact Info & Action Buttons */}
              <div className="flex items-start justify-between flex-wrap gap-4 pb-2 border-b border-gray-100">
                <div>
                  <h2 className="text-lg font-bold text-gray-900 tracking-tight">
                    {selectedDraft.contact?.first_name || 'Recipient'} {selectedDraft.contact?.last_name || ''}
                  </h2>
                  <p className="text-xs text-gray-400 mt-0.5 font-normal">
                    {selectedDraft.contact?.title || 'Decision Maker'}
                  </p>
                  <p className="text-xs text-gray-400 font-normal">
                    {selectedDraft.contact?.email || 'contact@example.com'}
                  </p>
                </div>

                {/* Actions Group */}
                <div className="flex items-center gap-2 relative" ref={dropdownRef}>
                  {/* Edit Button */}
                  <button
                    onClick={() => setIsEditing(!isEditing)}
                    className="bg-[#6B7280] hover:bg-[#4B5563] text-white text-xs font-semibold px-3.5 py-2 rounded-lg flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer"
                  >
                    <Edit3 size={13} />
                    <span>{isEditing ? 'Cancel' : 'Edit'}</span>
                  </button>

                  {/* Reject Button */}
                  <button
                    onClick={() => rejectMut.mutate(selectedDraft.id)}
                    disabled={rejectMut.isPending || selectedDraft.approval_state === 'rejected'}
                    className="bg-[#DC2626] hover:bg-[#B91C1C] text-white text-xs font-semibold px-3.5 py-2 rounded-lg flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <div className="w-3.5 h-3.5 rounded-full border border-white flex items-center justify-center">
                      <X size={9} strokeWidth={3} />
                    </div>
                    <span>Reject</span>
                  </button>

                  {/* Send via ▾ Dropdown Trigger */}
                  <div className="relative">
                    <button
                      onClick={() => setShowSendViaDropdown(!showSendViaDropdown)}
                      className="bg-[#5B4EFF] hover:bg-[#4E41E6] text-white text-xs font-semibold px-3.5 py-2 rounded-lg flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer"
                    >
                      <Mail size={13} />
                      <span>Send via</span>
                      <ChevronDown size={13} />
                    </button>

                    {/* Send via Popover Dropdown matching Figma Image 2 */}
                    {showSendViaDropdown && (
                      <div className="absolute right-0 top-full mt-3 w-80 bg-white rounded-2xl shadow-2xl border border-gray-100 p-3 z-50 space-y-1 animate-fadeIn">
                        {/* Triangle Tip pointing up at Send via button */}
                        <div className="absolute -top-2 right-8 w-4 h-4 bg-white border-t border-l border-gray-100 rotate-45 transform" />

                        {/* Option 1: Gmail */}
                        <div
                          onClick={() => {
                            setSendProvider('gmail')
                            handleExecuteSend('gmail')
                          }}
                          className={`p-3 rounded-xl flex items-center justify-between cursor-pointer transition-colors relative z-10 ${
                            sendProvider === 'gmail' ? 'bg-[#F4F5FF]' : 'hover:bg-gray-50'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            {/* Gmail Authentic Icon */}
                            <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0">
                              <svg className="w-7 h-7" viewBox="0 0 48 48">
                                <path fill="#4CAF50" d="M45,16.2l-5,2.75l-0.5,4.72L45,28V16.2z"/>
                                <path fill="#1E88E5" d="M3,16.2l5,2.75l0.5,4.72L3,28V16.2z"/>
                                <path fill="#E53935" d="M45,16.2l-14.77,8.12c-3.83,2.1-8.63,2.1-12.46,0L3,16.2V41c0,2.21,1.79,4,4,4h34c2.21,0,4-1.79,4-4V16.2z"/>
                                <path fill="#FBBC04" d="M41,3H7C4.79,3,3,4.79,3,7v9.2l21,11.55L45,16.2V7C45,4.79,43.21,3,41,3z"/>
                              </svg>
                            </div>
                            <div>
                              <div className="text-xs font-bold text-gray-900">Send via Gmail</div>
                              <div className="text-[11px] text-gray-400 mt-0.5 font-normal">Send the document via Gmail</div>
                            </div>
                          </div>
                          {/* Radio Button */}
                          <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                            sendProvider === 'gmail' ? 'border-[#5B4EFF]' : 'border-gray-300'
                          }`}>
                            {sendProvider === 'gmail' && <div className="w-2 h-2 rounded-full bg-[#5B4EFF]" />}
                          </div>
                        </div>

                        {/* Option 2: Outlook */}
                        <div
                          onClick={() => {
                            setSendProvider('outlook')
                            handleExecuteSend('outlook')
                          }}
                          className={`p-3 rounded-xl flex items-center justify-between cursor-pointer transition-colors relative z-10 ${
                            sendProvider === 'outlook' ? 'bg-[#F4F5FF]' : 'hover:bg-gray-50'
                          }`}
                        >
                          <div className="flex items-center gap-3">
                            {/* Outlook Authentic Icon */}
                            <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0">
                              <svg className="w-7 h-7" viewBox="0 0 48 48" fill="none">
                                <rect x="6" y="8" width="36" height="32" rx="4" fill="#0078D4"/>
                                <path d="M6 14L24 28L42 14" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                                <rect x="6" y="10" width="18" height="26" rx="3" fill="#106EBE"/>
                                <circle cx="15" cy="23" r="4.5" stroke="white" strokeWidth="2.5" fill="none"/>
                              </svg>
                            </div>
                            <div>
                              <div className="text-xs font-bold text-gray-900">Send via Outlook</div>
                              <div className="text-[11px] text-gray-400 mt-0.5 font-normal">Send the document via Outlook</div>
                            </div>
                          </div>
                          {/* Radio Button */}
                          <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
                            sendProvider === 'outlook' ? 'border-[#5B4EFF]' : 'border-gray-300'
                          }`}>
                            {sendProvider === 'outlook' && <div className="w-2 h-2 rounded-full bg-[#5B4EFF]" />}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Send Button */}
                  <button
                    onClick={() => handleExecuteSend(sendProvider)}
                    disabled={approveMut.isPending || selectedDraft.approval_state === 'approved'}
                    className="bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-semibold px-4 py-2 rounded-lg flex items-center gap-1.5 shadow-2xs transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <Send size={13} />
                    <span>Send</span>
                  </button>
                </div>
              </div>

              {/* Metadata Bar */}
              <div className="bg-[#F8FAFC] border border-gray-100 rounded-xl px-5 py-3.5 grid grid-cols-2 gap-6">
                <div>
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                    BUSINESS CASE
                  </span>
                  <span className="text-xs font-bold text-gray-900 mt-0.5 block">
                    {selectedDraft.business_case || 'General Sales Outreach'}
                  </span>
                </div>

                <div>
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                    MATCHED SERVICES
                  </span>
                  <span className="text-xs font-bold text-gray-900 mt-0.5 block truncate">
                    {selectedDraft.matched_services?.join(', ') || 'CRM consulting, GTM automation'}
                  </span>
                </div>
              </div>

              {/* Email Content Box */}
              <div className="bg-[#FAF9FF] border border-purple-100/80 rounded-xl p-6 flex flex-col space-y-4">
                {isEditing ? (
                  <div className="space-y-4">
                    <div>
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block mb-1">
                        SUBJECT
                      </label>
                      <input
                        type="text"
                        value={editSubject}
                        onChange={(e) => setEditSubject(e.target.value)}
                        className="w-full bg-white border border-gray-200 rounded-lg px-3.5 py-2 text-xs font-bold text-gray-900 focus:outline-none focus:ring-1 focus:ring-[#5B4EFF]"
                      />
                    </div>

                    <div>
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block mb-1">
                        BODY
                      </label>
                      <textarea
                        rows={12}
                        value={editBody}
                        onChange={(e) => setEditBody(e.target.value)}
                        className="w-full bg-white border border-gray-200 rounded-lg p-3.5 text-xs text-gray-700 leading-relaxed font-sans focus:outline-none focus:ring-1 focus:ring-[#5B4EFF]"
                      />
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-2">
                      <button
                        onClick={() => setIsEditing(false)}
                        className="px-4 py-1.5 rounded-lg border border-gray-200 text-xs font-semibold text-gray-600 hover:bg-gray-100 cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveEdit}
                        disabled={editMut.isPending}
                        className="px-4 py-1.5 rounded-lg bg-[#5B4EFF] hover:bg-[#4E41E6] text-xs font-semibold text-white shadow-2xs cursor-pointer disabled:opacity-50"
                      >
                        {editMut.isPending ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div>
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">
                      SUBJECT
                    </span>
                    <h3 className="text-sm font-bold text-gray-900 mt-0.5 mb-4">
                      {selectedDraft.subject}
                    </h3>

                    <div className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap font-sans">
                      {renderFormattedBody(selectedDraft.body)}
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="py-32 text-center text-gray-400 text-xs">
              Select any campaign draft from the left to preview and approve.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


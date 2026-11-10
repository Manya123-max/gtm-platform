import { useState, useMemo, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Calendar as CalendarIcon,
  Clock,
  Video,
  User,
  Mail,
  Building,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  ExternalLink,
  Globe,
  Sparkles,
  ArrowRight,
  ArrowLeft,
  Copy,
  Check,
  Download,
  AlertCircle
} from 'lucide-react'
import { fetchBookingInfo, fetchBookingSlots, scheduleBooking } from '../api'

const DAYS_OF_WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export default function PublicBooking() {
  const { username } = useParams()
  const identifier = username || 'shree-lakshmi'

  // User's detected timezone
  const userTimezone = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
      return 'UTC'
    }
  }, [])

  // Step state: 1: Pick Date & Time | 2: Details & Platform | 3: Confirmed
  const [step, setStep] = useState(1)
  const [selectedDuration, setSelectedDuration] = useState(30)
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [selectedDate, setSelectedDate] = useState(() => {
    // Default to tomorrow or next business day
    const d = new Date()
    d.setDate(d.getDate() + 1)
    if (d.getDay() === 0) d.setDate(d.getDate() + 1) // skip Sunday
    return d.toISOString().split('T')[0]
  })
  const [selectedSlot, setSelectedSlot] = useState('')

  // Form State
  const [attendeeName, setAttendeeName] = useState('')
  const [attendeeEmail, setAttendeeEmail] = useState('')
  const [attendeeCompany, setAttendeeCompany] = useState('')
  const [attendeeNotes, setAttendeeNotes] = useState('')
  const [selectedPlatform, setSelectedPlatform] = useState('zoom') // 'zoom' | 'google_meet' | 'teams'

  // Confirmation state
  const [confirmationData, setConfirmationData] = useState(null)
  const [copiedLink, setCopiedLink] = useState(false)

  // 1. Fetch Host Public Info
  const {
    data: hostInfo,
    isLoading: isLoadingInfo,
    isError: isInfoError,
  } = useQuery({
    queryKey: ['booking-info', identifier],
    queryFn: () => fetchBookingInfo(identifier),
    staleTime: 60_000,
  })

  // 2. Fetch Available Slots for selected date
  const {
    data: slotsData,
    isLoading: isLoadingSlots,
    refetch: refetchSlots,
  } = useQuery({
    queryKey: ['booking-slots', identifier, selectedDate, selectedDuration, userTimezone],
    queryFn: () => fetchBookingSlots(identifier, selectedDate, selectedDuration, userTimezone),
    enabled: !!selectedDate,
    staleTime: 10_000,
  })

  // 3. Schedule Meeting Mutation
  const scheduleMutation = useMutation({
    mutationFn: (payload) => scheduleBooking(identifier, payload),
    onSuccess: (data) => {
      setConfirmationData(data)
      setStep(3)
    },
  })

  // Calendar calculations
  const calendarDays = useMemo(() => {
    const year = currentMonth.getFullYear()
    const month = currentMonth.getMonth()
    const firstDayIndex = new Date(year, month, 1).getDay()
    // adjust so Monday is index 0
    const startOffset = firstDayIndex === 0 ? 6 : firstDayIndex - 1

    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const days = []

    // Empty lead slots
    for (let i = 0; i < startOffset; i++) {
      days.push(null)
    }

    const todayStr = new Date().toISOString().split('T')[0]

    // Actual month days
    for (let d = 1; d <= daysInMonth; d++) {
      const dateObj = new Date(year, month, d)
      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
      const isPast = dateStr < todayStr
      const isSunday = dateObj.getDay() === 0

      days.push({
        dayNumber: d,
        dateStr,
        disabled: isPast || isSunday,
        isToday: dateStr === todayStr,
      })
    }
    return days
  }, [currentMonth])

  const monthLabel = useMemo(() => {
    return currentMonth.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
  }, [currentMonth])

  const formattedSelectedDate = useMemo(() => {
    if (!selectedDate) return ''
    const parts = selectedDate.split('-').map(Number)
    const d = new Date(parts[0], parts[1] - 1, parts[2])
    return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
  }, [selectedDate])

  const handlePrevMonth = () => {
    setCurrentMonth(prev => new Date(prev.getFullYear(), prev.getMonth() - 1, 1))
  }

  const handleNextMonth = () => {
    setCurrentMonth(prev => new Date(prev.getFullYear(), prev.getMonth() + 1, 1))
  }

  const handleSlotSelect = (slot) => {
    setSelectedSlot(slot)
    setStep(2) // proceed to details
  }

  const handleSubmitBooking = (e) => {
    e.preventDefault()
    if (!attendeeName.trim() || !attendeeEmail.trim()) return

    scheduleMutation.mutate({
      date: selectedDate,
      time_slot: selectedSlot,
      timezone: userTimezone,
      duration_minutes: selectedDuration,
      platform: selectedPlatform,
      attendee_name: attendeeName.trim(),
      attendee_email: attendeeEmail.trim(),
      attendee_company: attendeeCompany.trim() || undefined,
      attendee_notes: attendeeNotes.trim() || undefined,
    })
  }

  const handleDownloadICS = () => {
    if (!confirmationData?.calendar_links?.ics_data) return
    const blob = new Blob([confirmationData.calendar_links.ics_data], { type: 'text/calendar;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `meeting-${confirmationData.meeting_id.slice(0, 8)}.ics`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  if (isLoadingInfo) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-4">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-3 border-[#5B4EFF] border-t-transparent rounded-full animate-spin" />
          <p className="text-xs font-semibold text-gray-500">Loading calendar...</p>
        </div>
      </div>
    )
  }

  if (isInfoError || !hostInfo?.host) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center p-4">
        <div className="bg-white border border-gray-200 rounded-2xl p-8 max-w-md w-full text-center shadow-sm">
          <AlertCircle size={40} className="text-rose-500 mx-auto mb-3" />
          <h2 className="text-base font-bold text-gray-900">Calendar Not Found</h2>
          <p className="text-xs text-gray-500 mt-1 mb-6">
            The scheduling page for representative &ldquo;{identifier}&rdquo; could not be located.
          </p>
          <Link
            to="/login"
            className="inline-block bg-[#5B4EFF] text-white text-xs font-semibold px-4 py-2 rounded-xl shadow-sm"
          >
            Return to GTM Platform
          </Link>
        </div>
      </div>
    )
  }

  const host = hostInfo.host
  const eventOptions = hostInfo.event_options || {}
  const platforms = hostInfo.supported_platforms || []

  return (
    <div className="min-h-screen bg-[#F8FAFC] py-8 px-4 sm:px-6 flex flex-col justify-between font-sans">
      <div className="max-w-4xl mx-auto w-full">
        {/* Main Card Container */}
        <div className="bg-white rounded-3xl border border-gray-100 shadow-xl overflow-hidden">
          
          {/* Top Brand Banner */}
          <div className="bg-gradient-to-r from-[#5B4EFF] to-[#4F46E5] px-6 py-4 flex items-center justify-between text-white">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-lg bg-white/20 flex items-center justify-center font-black text-xs">
                G
              </div>
              <span className="font-bold text-sm tracking-tight">GTM Platform</span>
              <span className="bg-white/20 text-[10px] font-semibold px-2 py-0.5 rounded-full ml-1">
                Verified Scheduler
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-white/90 font-medium">
              <Globe size={13} />
              <span>{userTimezone}</span>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 min-h-[580px]">
            
            {/* ── Left Sidebar: Host & Meeting Details (Cols: 4) ── */}
            <div className="lg:col-span-4 p-6 sm:p-7 border-b lg:border-b-0 lg:border-r border-gray-100 bg-[#FAFAFC] flex flex-col justify-between">
              <div>
                {/* Host Profile */}
                <div className="flex items-center gap-3 mb-5">
                  {host.avatar_url ? (
                    <img
                      src={host.avatar_url}
                      alt={host.name}
                      className="w-12 h-12 rounded-full object-cover ring-2 ring-[#5B4EFF]/20"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-full bg-[#5B4EFF] text-white flex items-center justify-center font-bold text-base shadow-sm">
                      {host.name?.charAt(0) || 'U'}
                    </div>
                  )}
                  <div>
                    <h3 className="text-sm font-bold text-gray-900 leading-tight">{host.name}</h3>
                    <p className="text-xs text-gray-500 font-medium mt-0.5">{host.role}</p>
                    <span className="text-[10px] text-[#5B4EFF] font-semibold block">{host.company}</span>
                  </div>
                </div>

                {/* Meeting Meta */}
                <div className="space-y-4 pt-3 border-t border-gray-200/60">
                  <div>
                    <h2 className="text-lg font-black text-gray-900 tracking-tight leading-snug">
                      {eventOptions.title || 'Strategy & Discovery Session'}
                    </h2>
                    <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                      {eventOptions.description}
                    </p>
                  </div>

                  {/* Duration Picker */}
                  <div>
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block mb-2">
                      Duration
                    </span>
                    <div className="flex gap-2">
                      {[15, 30, 45].map((dur) => (
                        <button
                          key={dur}
                          type="button"
                          onClick={() => {
                            setSelectedDuration(dur)
                            setSelectedSlot('')
                          }}
                          className={`flex-1 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer ${
                            selectedDuration === dur
                              ? 'bg-[#5B4EFF] text-white shadow-sm ring-2 ring-[#5B4EFF]/20'
                              : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                          }`}
                        >
                          {dur} min
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Meeting Details Summary Badge */}
                  {selectedDate && selectedSlot && step !== 3 && (
                    <div className="bg-[#EEF2FF] border border-[#C7D2FE] rounded-2xl p-3.5 space-y-1.5 animate-in fade-in duration-200">
                      <div className="flex items-center gap-2 text-xs font-bold text-[#4338CA]">
                        <CalendarIcon size={14} />
                        <span>{formattedSelectedDate}</span>
                      </div>
                      <div className="flex items-center gap-2 text-xs font-semibold text-[#4338CA]">
                        <Clock size={14} />
                        <span>{selectedSlot} ({selectedDuration} mins)</span>
                      </div>
                      <div className="flex items-center gap-2 text-xs font-semibold text-[#4338CA] pt-1">
                        <Video size={14} />
                        <span className="capitalize">
                          {selectedPlatform.replace('_', ' ')} Meeting
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Security Footnote */}
              <div className="pt-6 border-t border-gray-200/60 text-[11px] text-gray-400">
                🔒 Enterprise calendar encryption enabled. Timezone automatically synchronized.
              </div>
            </div>

            {/* ── Right Content Area: Wizard Steps (Cols: 8) ── */}
            <div className="lg:col-span-8 p-6 sm:p-8 flex flex-col justify-between">
              
              {/* STEP 1: Date & Time Picker */}
              {step === 1 && (
                <div className="space-y-6">
                  <div>
                    <h3 className="text-base font-bold text-gray-900 tracking-tight">Select a Date &amp; Time</h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      Available slots displayed in your local timezone ({userTimezone}).
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
                    {/* Interactive Calendar Month (Cols: 7) */}
                    <div className="md:col-span-7 bg-white rounded-2xl border border-gray-100 p-4 shadow-2xs">
                      {/* Month Header Nav */}
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-xs font-bold text-gray-900">{monthLabel}</h4>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={handlePrevMonth}
                            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-600 transition cursor-pointer"
                            aria-label="Previous Month"
                          >
                            <ChevronLeft size={16} />
                          </button>
                          <button
                            type="button"
                            onClick={handleNextMonth}
                            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-600 transition cursor-pointer"
                            aria-label="Next Month"
                          >
                            <ChevronRight size={16} />
                          </button>
                        </div>
                      </div>

                      {/* Day of Week Labels */}
                      <div className="grid grid-cols-7 gap-1 text-center mb-2">
                        {DAYS_OF_WEEK.map((d) => (
                          <span key={d} className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                            {d}
                          </span>
                        ))}
                      </div>

                      {/* Calendar Grid */}
                      <div className="grid grid-cols-7 gap-1.5 text-center">
                        {calendarDays.map((item, idx) => {
                          if (!item) {
                            return <div key={`empty-${idx}`} className="h-9" />
                          }
                          const isSelected = item.dateStr === selectedDate
                          return (
                            <button
                              key={item.dateStr}
                              type="button"
                              disabled={item.disabled}
                              onClick={() => {
                                setSelectedDate(item.dateStr)
                                setSelectedSlot('')
                              }}
                              className={`h-9 rounded-xl text-xs font-bold transition-all flex items-center justify-center cursor-pointer ${
                                isSelected
                                  ? 'bg-[#5B4EFF] text-white shadow-md shadow-[#5B4EFF]/20'
                                  : item.disabled
                                  ? 'text-gray-300 cursor-not-allowed'
                                  : 'text-gray-700 hover:bg-[#EEF2FF] hover:text-[#5B4EFF]'
                              }`}
                            >
                              {item.dayNumber}
                            </button>
                          )
                        })}
                      </div>
                    </div>

                    {/* Time Slots Column (Cols: 5) */}
                    <div className="md:col-span-5 flex flex-col">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-bold text-gray-900">
                          {formattedSelectedDate}
                        </span>
                        <span className="text-[10px] text-gray-400 font-medium">
                          {selectedDuration}m slots
                        </span>
                      </div>

                      {isLoadingSlots ? (
                        <div className="flex-1 flex flex-col items-center justify-center p-8 gap-2">
                          <div className="w-6 h-6 border-2 border-[#5B4EFF] border-t-transparent rounded-full animate-spin" />
                          <span className="text-[11px] text-gray-400">Loading open slots...</span>
                        </div>
                      ) : (slotsData?.available_slots || []).length > 0 ? (
                        <div className="space-y-1.5 max-h-[310px] overflow-y-auto pr-1">
                          {slotsData.available_slots.map((slot) => (
                            <button
                              key={slot}
                              type="button"
                              onClick={() => handleSlotSelect(slot)}
                              className="w-full text-left px-4 py-2.5 rounded-xl border border-gray-200 hover:border-[#5B4EFF] hover:bg-[#EEF2FF] hover:text-[#4338CA] text-xs font-bold text-gray-700 transition-all flex items-center justify-between group cursor-pointer shadow-2xs"
                            >
                              <span>{slot}</span>
                              <ArrowRight size={13} className="text-gray-300 group-hover:text-[#4338CA] transition" />
                            </button>
                          ))}
                        </div>
                      ) : (
                        <div className="bg-gray-50 rounded-2xl p-6 text-center border border-dashed border-gray-200">
                          <Clock size={20} className="text-gray-400 mx-auto mb-2" />
                          <p className="text-xs font-semibold text-gray-600">No open slots on this date</p>
                          <p className="text-[11px] text-gray-400 mt-1">Please select another weekday</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* STEP 2: Attendee Details & Platform Selection */}
              {step === 2 && (
                <form onSubmit={handleSubmitBooking} className="space-y-5 animate-in fade-in duration-200">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-bold text-gray-900 tracking-tight">Enter Your Details</h3>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Selected: <span className="font-bold text-gray-800">{formattedSelectedDate} at {selectedSlot}</span>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setStep(1)}
                      className="text-xs text-[#5B4EFF] font-semibold hover:underline flex items-center gap-1 cursor-pointer"
                    >
                      <ArrowLeft size={13} />
                      <span>Change Time</span>
                    </button>
                  </div>

                  {/* ── KEY FEATURE: Video Meeting Platform Choice ── */}
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-gray-900 block">
                      Choose How to Meet: <span className="text-[#5B4EFF] font-medium">(Select Platform)</span>
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                      
                      {/* 1. Zoom */}
                      <button
                        type="button"
                        onClick={() => setSelectedPlatform('zoom')}
                        className={`p-3.5 rounded-2xl border text-left transition-all relative flex flex-col justify-between cursor-pointer ${
                          selectedPlatform === 'zoom'
                            ? 'border-[#2D8CFF] bg-[#F0F7FF] ring-2 ring-[#2D8CFF]/20 shadow-xs'
                            : 'border-gray-200 bg-white hover:border-gray-300'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-3">
                          <img
                            src="/icons/zoom.png"
                            alt="Zoom"
                            className="w-8 h-8 rounded-lg object-contain"
                          />
                          <div className="flex items-center">
                            {selectedPlatform === 'zoom' ? (
                              <div className="w-4 h-4 rounded-full bg-[#2D8CFF] text-white flex items-center justify-center shadow-2xs">
                                <Check size={11} strokeWidth={3} />
                              </div>
                            ) : (
                              <div className="w-4 h-4 rounded-full border-2 border-gray-300 bg-white" />
                            )}
                          </div>
                        </div>
                        <h4 className="text-xs font-bold text-gray-900">Zoom Meeting</h4>
                      </button>

                      {/* 2. Google Meet */}
                      <button
                        type="button"
                        onClick={() => setSelectedPlatform('google_meet')}
                        className={`p-3.5 rounded-2xl border text-left transition-all relative flex flex-col justify-between cursor-pointer ${
                          selectedPlatform === 'google_meet'
                            ? 'border-[#00897B] bg-[#E6F4EA] ring-2 ring-[#00897B]/20 shadow-xs'
                            : 'border-gray-200 bg-white hover:border-gray-300'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-3">
                          <img
                            src="/icons/google-meet.png"
                            alt="Google Meet"
                            className="w-8 h-8 rounded-lg object-contain"
                          />
                          <div className="flex items-center">
                            {selectedPlatform === 'google_meet' ? (
                              <div className="w-4 h-4 rounded-full bg-[#00897B] text-white flex items-center justify-center shadow-2xs">
                                <Check size={11} strokeWidth={3} />
                              </div>
                            ) : (
                              <div className="w-4 h-4 rounded-full border-2 border-gray-300 bg-white" />
                            )}
                          </div>
                        </div>
                        <h4 className="text-xs font-bold text-gray-900">Google Meet</h4>
                      </button>

                      {/* 3. Microsoft Teams */}
                      <button
                        type="button"
                        onClick={() => setSelectedPlatform('teams')}
                        className={`p-3.5 rounded-2xl border text-left transition-all relative flex flex-col justify-between cursor-pointer ${
                          selectedPlatform === 'teams'
                            ? 'border-[#5059C9] bg-[#F2F3FB] ring-2 ring-[#5059C9]/20 shadow-xs'
                            : 'border-gray-200 bg-white hover:border-gray-300'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-3">
                          <img
                            src="/icons/ms-teams.png"
                            alt="Microsoft Teams"
                            className="w-8 h-8 rounded-lg object-contain"
                          />
                          <div className="flex items-center">
                            {selectedPlatform === 'teams' ? (
                              <div className="w-4 h-4 rounded-full bg-[#5059C9] text-white flex items-center justify-center shadow-2xs">
                                <Check size={11} strokeWidth={3} />
                              </div>
                            ) : (
                              <div className="w-4 h-4 rounded-full border-2 border-gray-300 bg-white" />
                            )}
                          </div>
                        </div>
                        <h4 className="text-xs font-bold text-gray-900">Microsoft Teams</h4>
                      </button>
                    </div>
                  </div>

                  {/* Form Input Fields */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                    <div>
                      <label className="text-[11px] font-bold text-gray-700 block mb-1">
                        Your Full Name <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="text"
                        required
                        value={attendeeName}
                        onChange={(e) => setAttendeeName(e.target.value)}
                        placeholder="e.g. Alex Morgan"
                        className="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF] focus:border-transparent transition"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-bold text-gray-700 block mb-1">
                        Business Email <span className="text-rose-500">*</span>
                      </label>
                      <input
                        type="email"
                        required
                        value={attendeeEmail}
                        onChange={(e) => setAttendeeEmail(e.target.value)}
                        placeholder="alex@company.com"
                        className="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF] focus:border-transparent transition"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-bold text-gray-700 block mb-1">
                        Company Name
                      </label>
                      <input
                        type="text"
                        value={attendeeCompany}
                        onChange={(e) => setAttendeeCompany(e.target.value)}
                        placeholder="e.g. Acme Corp"
                        className="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF] focus:border-transparent transition"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-bold text-gray-700 block mb-1">
                        Topics / Agenda (Optional)
                      </label>
                      <input
                        type="text"
                        value={attendeeNotes}
                        onChange={(e) => setAttendeeNotes(e.target.value)}
                        placeholder="e.g. Pipeline workflow & CRM integration"
                        className="w-full bg-white border border-gray-200 rounded-xl px-3.5 py-2 text-xs text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#5B4EFF] focus:border-transparent transition"
                      />
                    </div>
                  </div>

                  {scheduleMutation.isError && (
                    <div className="bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 rounded-xl flex items-center gap-2">
                      <AlertCircle size={14} />
                      <span>{scheduleMutation.error?.response?.data?.detail || 'Booking failed. Please try a different slot.'}</span>
                    </div>
                  )}

                  <div className="pt-2">
                    <button
                      type="submit"
                      disabled={scheduleMutation.isPending}
                      className="w-full bg-[#5B4EFF] hover:bg-[#4F46E5] text-white font-bold text-xs py-3 px-6 rounded-xl shadow-md shadow-[#5B4EFF]/20 transition-all cursor-pointer flex items-center justify-center gap-2 disabled:opacity-50"
                    >
                      {scheduleMutation.isPending ? (
                        <>
                          <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          <span>Generating Video Room &amp; Scheduling...</span>
                        </>
                      ) : (
                        <>
                          <span>Confirm &amp; Schedule {selectedPlatform.replace('_', ' ').toUpperCase()} Meeting</span>
                          <ArrowRight size={14} />
                        </>
                      )}
                    </button>
                  </div>
                </form>
              )}

              {/* STEP 3: Booking Confirmed Screen */}
              {step === 3 && confirmationData && (
                <div className="space-y-6 text-center animate-in zoom-in-95 duration-200 py-4">
                  <div className="w-16 h-16 bg-[#ECFDF5] text-[#059669] rounded-full flex items-center justify-center mx-auto shadow-sm ring-8 ring-[#ECFDF5]/50">
                    <CheckCircle2 size={36} />
                  </div>

                  <div>
                    <h3 className="text-xl font-black text-gray-900 tracking-tight">You&rsquo;re Scheduled!</h3>
                    <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
                      A calendar invitation and confirmation email have been sent to{' '}
                      <span className="font-bold text-gray-800">{confirmationData.attendee?.email}</span>.
                    </p>
                  </div>

                  {/* Summary Card */}
                  <div className="bg-[#F8FAFC] border border-gray-200/80 rounded-2xl p-5 max-w-md mx-auto text-left space-y-3">
                    <div className="flex items-start justify-between border-b border-gray-200/60 pb-3">
                      <div>
                        <h4 className="text-xs font-bold text-gray-900">{confirmationData.title}</h4>
                        <p className="text-[11px] text-gray-500">With {confirmationData.host?.name}</p>
                      </div>
                      <span className="text-[10px] font-bold bg-[#5B4EFF]/10 text-[#5B4EFF] px-2 py-0.5 rounded-full capitalize">
                        {confirmationData.platform_name}
                      </span>
                    </div>

                    <div className="space-y-1.5 text-xs text-gray-700">
                      <div className="flex items-center gap-2">
                        <CalendarIcon size={14} className="text-gray-400" />
                        <span className="font-semibold">{confirmationData.date}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Clock size={14} className="text-gray-400" />
                        <span className="font-semibold">{confirmationData.time_slot} ({confirmationData.duration_minutes} mins, {confirmationData.timezone})</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Video size={14} className="text-gray-400" />
                        <a
                          href={confirmationData.join_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[#2563EB] hover:underline font-semibold flex items-center gap-1"
                        >
                          <span>{confirmationData.join_url}</span>
                          <ExternalLink size={12} />
                        </a>
                      </div>
                      {confirmationData.passcode && (
                        <div className="text-[11px] text-gray-500 pl-5">
                          Passcode: <span className="font-mono font-bold text-gray-800">{confirmationData.passcode}</span>
                        </div>
                      )}
                    </div>

                    {/* Join Meeting Direct Button */}
                    <div className="pt-2">
                      <a
                        href={confirmationData.join_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-full bg-[#2563EB] hover:bg-[#1D4ED8] text-white text-xs font-bold py-2.5 rounded-xl shadow-xs transition flex items-center justify-center gap-1.5"
                      >
                        <Video size={14} />
                        <span>Open {confirmationData.platform_name} Room</span>
                      </a>
                    </div>
                  </div>

                  {/* Calendar 1-Click Buttons */}
                  <div className="space-y-2 max-w-md mx-auto">
                    <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider block">
                      Add to Calendar
                    </span>
                    <div className="grid grid-cols-3 gap-2">
                      <a
                        href={confirmationData.calendar_links?.google_calendar_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-xs font-semibold py-2 px-3 rounded-xl transition flex items-center justify-center gap-1.5 shadow-2xs"
                      >
                        <span>Google</span>
                        <ExternalLink size={11} className="text-gray-400" />
                      </a>
                      <a
                        href={confirmationData.calendar_links?.outlook_calendar_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-xs font-semibold py-2 px-3 rounded-xl transition flex items-center justify-center gap-1.5 shadow-2xs"
                      >
                        <span>Outlook</span>
                        <ExternalLink size={11} className="text-gray-400" />
                      </a>
                      <button
                        type="button"
                        onClick={handleDownloadICS}
                        className="bg-white border border-gray-200 hover:bg-gray-50 text-gray-700 text-xs font-semibold py-2 px-3 rounded-xl transition flex items-center justify-center gap-1.5 shadow-2xs cursor-pointer"
                      >
                        <Download size={12} className="text-gray-500" />
                        <span>.ICS File</span>
                      </button>
                    </div>
                  </div>

                  <div className="pt-3">
                    <button
                      type="button"
                      onClick={() => {
                        setStep(1)
                        setSelectedSlot('')
                        setConfirmationData(null)
                      }}
                      className="text-xs text-gray-500 hover:text-gray-800 font-semibold underline cursor-pointer"
                    >
                      Book Another Meeting
                    </button>
                  </div>
                </div>
              )}

              {/* Progress Step Dots */}
              {step !== 3 && (
                <div className="pt-4 border-t border-gray-100 flex items-center justify-between text-xs text-gray-400">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${step === 1 ? 'bg-[#5B4EFF]' : 'bg-gray-300'}`} />
                    <span className={step === 1 ? 'font-bold text-gray-800' : ''}>1. Date &amp; Time</span>
                    <span className="text-gray-300">&bull;</span>
                    <span className={`w-2 h-2 rounded-full ${step === 2 ? 'bg-[#5B4EFF]' : 'bg-gray-300'}`} />
                    <span className={step === 2 ? 'font-bold text-gray-800' : ''}>2. Attendee &amp; Platform</span>
                  </div>
                  <span>Step {step} of 2</span>
                </div>
              )}
            </div>

          </div>
        </div>
      </div>
      
      {/* Footer */}
      <footer className="mt-8 text-center text-xs text-gray-400">
        Powered by <span className="font-bold text-gray-600">GTM Platform AI Scheduler</span> &bull; Zoom, Google Meet &amp; Teams Multi-Platform Integration
      </footer>
    </div>
  )
}


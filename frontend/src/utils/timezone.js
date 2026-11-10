/**
 * timezone.js — Shared IST (Asia/Kolkata, UTC+05:30) date & time utilities.
 * 
 * Rules:
 * 1. Backend stores timestamps in UTC.
 * 2. All frontend displays use Asia/Kolkata (IST).
 * 3. Never manually add 5 hours 30 minutes; use standard Intl.DateTimeFormat with timeZone: 'Asia/Kolkata'.
 * 4. Correctly parse ISO 8601 strings (including trailing 'Z', naive timestamps, and explicit offsets).
 */

const IST_TIMEZONE = 'Asia/Kolkata'

/**
 * Safely parse any date input (string, Date, number) into a valid Date object.
 * Naive ISO strings like "2026-11-10T05:30:00" are treated as UTC by appending 'Z'.
 */
export function parseToDate(dateInput) {
  if (!dateInput) return null
  if (dateInput instanceof Date) {
    return isNaN(dateInput.getTime()) ? null : dateInput
  }
  if (typeof dateInput === 'number') {
    const d = new Date(dateInput)
    return isNaN(d.getTime()) ? null : d
  }
  try {
    const s = String(dateInput).trim()
    if (!s) return null
    // If it's a naive ISO timestamp (no Z and no +/- offset at end), treat as UTC
    const isIsoNaive = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(s)
    const normalizedStr = isIsoNaive ? `${s}Z` : s
    const d = new Date(normalizedStr)
    return isNaN(d.getTime()) ? null : d
  } catch {
    return null
  }
}

/**
 * Formats a timestamp into standard IST Date & Time.
 * Example output: "10 Nov 2026, 11:00 AM IST"
 */
export function formatISTDateTime(dateInput, options = {}) {
  const d = parseToDate(dateInput)
  if (!d) return options.fallback || ''

  try {
    const formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone: IST_TIMEZONE,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      ...options,
    })

    const parts = formatter.formatToParts(d)
    const partMap = {}
    parts.forEach(p => { partMap[p.type] = p.value })

    const day = partMap.day || ''
    const month = partMap.month || ''
    const year = partMap.year || ''
    const hour = partMap.hour || ''
    const minute = partMap.minute || ''
    const dayPeriod = (partMap.dayPeriod || '').toUpperCase()

    const datePart = `${day} ${month} ${year}`.trim()
    const timePart = `${hour}:${minute} ${dayPeriod}`.trim()

    if (options.dateOnly) return datePart
    if (options.timeOnly) return `${timePart} IST`

    return `${datePart}, ${timePart} IST`
  } catch {
    return options.fallback || ''
  }
}

/**
 * Formats a timestamp into standard IST Date.
 * Example output: "10 Nov 2026"
 */
export function formatISTDate(dateInput, fallback = '') {
  return formatISTDateTime(dateInput, { dateOnly: true, fallback })
}

/**
 * Formats a timestamp into standard IST Time.
 * Example output: "11:00 AM IST"
 */
export function formatISTTime(dateInput, fallback = '') {
  return formatISTDateTime(dateInput, { timeOnly: true, fallback })
}

/**
 * Formats friendly relative time with IST fallback.
 * Examples:
 * - "Just now" (< 1 min)
 * - "5 min ago" (< 1 hr)
 * - "2 hr ago" (earlier today in IST)
 * - "Yesterday, 11:00 AM IST" (yesterday in IST)
 * - "10 Nov 2026, 11:00 AM IST" (older)
 */
export function formatISTRelativeTime(dateInput) {
  const date = parseToDate(dateInput)
  if (!date) return ''

  const now = new Date()
  const diffMs = now - date

  // Future timestamp guard
  if (diffMs < 0) {
    return 'Just now'
  }

  const diffMins = Math.floor(diffMs / (1000 * 60))
  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins} min ago`

  // Format date and now in IST for day comparisons
  const dateISTParts = getISTDateParts(date)
  const nowISTParts = getISTDateParts(now)

  const isToday =
    dateISTParts.year === nowISTParts.year &&
    dateISTParts.month === nowISTParts.month &&
    dateISTParts.day === nowISTParts.day

  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  if (isToday) {
    if (diffHours < 24) return `${diffHours} hr ago`
  }

  // Check if yesterday in IST
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  const yesterdayISTParts = getISTDateParts(yesterday)
  const isYesterday =
    dateISTParts.year === yesterdayISTParts.year &&
    dateISTParts.month === yesterdayISTParts.month &&
    dateISTParts.day === yesterdayISTParts.day

  const timeStr = formatISTTime(date)
  if (isYesterday) {
    return `Yesterday, ${timeStr}`
  }

  return `${dateISTParts.day} ${dateISTParts.month} ${dateISTParts.year}, ${timeStr}`
}

/**
 * Extracts year, month, and day parts in IST.
 */
function getISTDateParts(date) {
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone: IST_TIMEZONE,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
  const parts = formatter.formatToParts(date)
  const map = {}
  parts.forEach(p => { map[p.type] = p.value })
  return {
    day: map.day || '',
    month: map.month || '',
    year: map.year || '',
  }
}

/**
 * Groups items into "today", "yesterday", and "earlier" using IST calendar day boundaries.
 */
export function groupItemsByISTDay(items, getDateFn = item => item.created_at) {
  const today = []
  const yesterday = []
  const earlier = []

  const now = new Date()
  const nowIST = getISTDateParts(now)
  const yest = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  const yestIST = getISTDateParts(yest)

  items.forEach(item => {
    const d = parseToDate(getDateFn(item))
    if (!d) {
      earlier.push(item)
      return
    }
    const itemIST = getISTDateParts(d)
    if (
      itemIST.year === nowIST.year &&
      itemIST.month === nowIST.month &&
      itemIST.day === nowIST.day
    ) {
      today.push(item)
    } else if (
      itemIST.year === yestIST.year &&
      itemIST.month === yestIST.month &&
      itemIST.day === yestIST.day
    ) {
      yesterday.push(item)
    } else {
      earlier.push(item)
    }
  })

  return { today, yesterday, earlier }
}


const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

export function formatAbsolute(iso: string): string {
  const date = new Date(iso)
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

export function formatRelative(iso: string): string {
  const date = new Date(iso)
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffSec = Math.round(diffMs / 1000)
  if (diffSec < 60) return rtf.format(-diffSec, "second")
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return rtf.format(-diffMin, "minute")
  const diffHour = Math.round(diffMin / 60)
  if (diffHour < 24) return rtf.format(-diffHour, "hour")
  const diffDay = Math.round(diffHour / 24)
  if (diffDay < 30) return rtf.format(-diffDay, "day")
  const diffMonth = Math.round(diffDay / 30)
  if (diffMonth < 12) return rtf.format(-diffMonth, "month")
  const diffYear = Math.round(diffMonth / 12)
  return rtf.format(-diffYear, "year")
}

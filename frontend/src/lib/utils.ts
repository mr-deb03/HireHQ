import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

import type { ApplicationStatus, AtsRecommendation } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ------------------------------------------------------------------ formatting
export function formatCurrency(
  amount: number | null | undefined,
  currency = 'INR',
  { compact = true }: { compact?: boolean } = {},
): string {
  if (amount === null || amount === undefined) return '—'
  const locale = currency === 'INR' ? 'en-IN' : 'en-US'
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
    // Compact notation keeps salary bands readable in tight table cells.
    notation: compact && amount >= 100_000 ? 'compact' : 'standard',
  }).format(amount)
}

export function formatSalaryRange(
  min: number | null | undefined,
  max: number | null | undefined,
  currency = 'INR',
): string {
  if (min == null && max == null) return 'Not disclosed'
  if (min != null && max != null) {
    return `${formatCurrency(min, currency)} – ${formatCurrency(max, currency)}`
  }
  return formatCurrency(min ?? max, currency)
}

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** "3 days ago" / "in 2 hours". Falls back to an absolute date beyond a month. */
export function formatRelative(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'

  const diffSeconds = (date.getTime() - Date.now()) / 1000
  const absolute = Math.abs(diffSeconds)
  if (absolute > 60 * 60 * 24 * 30) return formatDate(date)

  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['year', 60 * 60 * 24 * 365],
    ['month', 60 * 60 * 24 * 30],
    ['day', 60 * 60 * 24],
    ['hour', 60 * 60],
    ['minute', 60],
  ]
  for (const [unit, seconds] of units) {
    if (absolute >= seconds) return formatter.format(Math.round(diffSeconds / seconds), unit)
  }
  return 'just now'
}

export function formatExperience(years: number | null | undefined): string {
  if (years == null) return '—'
  if (years === 0) return 'Fresher'
  if (years < 1) return '<1 yr'
  return `${Number.isInteger(years) ? years : years.toFixed(1)} yr${years === 1 ? '' : 's'}`
}

export function formatNoticePeriod(days: number | null | undefined): string {
  if (days == null) return '—'
  if (days === 0) return 'Immediate'
  if (days % 30 === 0) return `${days / 30} month${days === 30 ? '' : 's'}`
  return `${days} days`
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

// -------------------------------------------------------------------- colours
/**
 * Status colours. Defined once so a status looks identical on the Kanban board, the
 * candidate page and the applications table.
 */
export const STATUS_STYLES: Record<ApplicationStatus, { badge: string; dot: string; label: string }> =
  {
    APPLIED: { badge: 'bg-ink-100 text-ink-700 ring-ink-200', dot: 'bg-ink-400', label: 'Applied' },
    UNDER_REVIEW: {
      badge: 'bg-info-50 text-info-700 ring-info-100',
      dot: 'bg-info-500',
      label: 'Under review',
    },
    SCREENING: {
      badge: 'bg-info-50 text-info-700 ring-info-100',
      dot: 'bg-info-500',
      label: 'Screening',
    },
    SHORTLISTED: {
      badge: 'bg-brand-50 text-brand-700 ring-brand-100',
      dot: 'bg-brand-500',
      label: 'Shortlisted',
    },
    ASSESSMENT: {
      badge: 'bg-warning-50 text-warning-700 ring-warning-100',
      dot: 'bg-warning-500',
      label: 'Assessment',
    },
    INTERVIEW: {
      badge: 'bg-brand-50 text-brand-700 ring-brand-100',
      dot: 'bg-brand-600',
      label: 'Interview',
    },
    INTERVIEW_PASSED: {
      badge: 'bg-success-50 text-success-700 ring-success-100',
      dot: 'bg-success-500',
      label: 'Interview passed',
    },
    INTERVIEW_FAILED: {
      badge: 'bg-danger-50 text-danger-700 ring-danger-100',
      dot: 'bg-danger-500',
      label: 'Interview failed',
    },
    OFFER: {
      badge: 'bg-success-50 text-success-700 ring-success-100',
      dot: 'bg-success-500',
      label: 'Offer',
    },
    OFFER_ACCEPTED: {
      badge: 'bg-success-100 text-success-700 ring-success-500/20',
      dot: 'bg-success-600',
      label: 'Offer accepted',
    },
    OFFER_REJECTED: {
      badge: 'bg-danger-50 text-danger-700 ring-danger-100',
      dot: 'bg-danger-500',
      label: 'Offer declined',
    },
    HIRED: {
      badge: 'bg-success-100 text-success-700 ring-success-500/20',
      dot: 'bg-success-600',
      label: 'Hired',
    },
    REJECTED: {
      badge: 'bg-danger-50 text-danger-700 ring-danger-100',
      dot: 'bg-danger-500',
      label: 'Rejected',
    },
    ON_HOLD: {
      badge: 'bg-warning-50 text-warning-700 ring-warning-100',
      dot: 'bg-warning-500',
      label: 'On hold',
    },
    WITHDRAWN: {
      badge: 'bg-ink-100 text-ink-600 ring-ink-200',
      dot: 'bg-ink-400',
      label: 'Withdrawn',
    },
  }

export const RECOMMENDATION_STYLES: Record<AtsRecommendation, { badge: string; label: string }> = {
  STRONG_MATCH: { badge: 'bg-success-50 text-success-700 ring-success-100', label: 'Strong match' },
  GOOD_MATCH: { badge: 'bg-brand-50 text-brand-700 ring-brand-100', label: 'Good match' },
  PARTIAL_MATCH: {
    badge: 'bg-warning-50 text-warning-700 ring-warning-100',
    label: 'Partial match',
  },
  WEAK_MATCH: { badge: 'bg-ink-100 text-ink-600 ring-ink-200', label: 'Weak match' },
}

/** Score colour bands, matching the recommendation thresholds. */
export function scoreColour(score: number | null | undefined): string {
  if (score == null) return 'text-ink-400'
  if (score >= 85) return 'text-success-600'
  if (score >= 70) return 'text-brand-600'
  if (score >= 50) return 'text-warning-600'
  return 'text-ink-500'
}

export function scoreRingColour(score: number | null | undefined): string {
  if (score == null) return 'stroke-ink-200'
  if (score >= 85) return 'stroke-success-500'
  if (score >= 70) return 'stroke-brand-500'
  if (score >= 50) return 'stroke-warning-500'
  return 'stroke-ink-300'
}

export const WORK_MODE_LABELS: Record<string, string> = {
  REMOTE: 'Remote',
  HYBRID: 'Hybrid',
  ONSITE: 'On-site',
}

export const EMPLOYMENT_TYPE_LABELS: Record<string, string> = {
  FULL_TIME: 'Full-time',
  PART_TIME: 'Part-time',
  CONTRACT: 'Contract',
  INTERNSHIP: 'Internship',
  TEMPORARY: 'Temporary',
  FRESHER: 'Fresher',
}

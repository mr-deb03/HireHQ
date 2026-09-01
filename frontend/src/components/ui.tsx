'use client'

/**
 * The shared UI primitives. Kept in one module so the visual language stays consistent -
 * a button, badge or card looks identical everywhere because there is only one of each.
 */

import { Loader2, X } from 'lucide-react'
import Link from 'next/link'
import { forwardRef, useEffect } from 'react'

import { cn } from '@/lib/utils'

// -------------------------------------------------------------------- Button
const BUTTON_VARIANTS = {
  primary:
    'bg-ink-900 text-white shadow-sm hover:bg-ink-800 active:bg-ink-950 disabled:bg-ink-300',
  brand:
    'bg-brand-600 text-white shadow-sm hover:bg-brand-700 active:bg-brand-800 disabled:bg-brand-300',
  secondary:
    'bg-white text-ink-800 ring-1 ring-inset ring-ink-300 shadow-sm hover:bg-ink-50 active:bg-ink-100 disabled:text-ink-400',
  ghost: 'text-ink-700 hover:bg-ink-100 active:bg-ink-200 disabled:text-ink-400',
  danger:
    'bg-danger-600 text-white shadow-sm hover:bg-danger-700 active:bg-danger-700 disabled:bg-danger-500/50',
  success:
    'bg-success-600 text-white shadow-sm hover:bg-success-700 active:bg-success-700 disabled:bg-success-500/50',
} as const

const BUTTON_SIZES = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-xl',
  lg: 'h-12 px-6 text-base gap-2 rounded-xl',
  icon: 'h-9 w-9 rounded-lg',
} as const

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof BUTTON_VARIANTS
  size?: keyof typeof BUTTON_SIZES
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', size = 'md', loading, disabled, children, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      // A loading button must not stay clickable, or a slow network turns one click
      // into three submissions.
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center font-medium transition-colors',
        'disabled:cursor-not-allowed',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

// --------------------------------------------------------------------- Badge
const BADGE_TONES = {
  neutral: 'bg-ink-100 text-ink-700 ring-ink-200',
  brand: 'bg-brand-50 text-brand-700 ring-brand-100',
  success: 'bg-success-50 text-success-700 ring-success-100',
  warning: 'bg-warning-50 text-warning-700 ring-warning-100',
  danger: 'bg-danger-50 text-danger-700 ring-danger-100',
  info: 'bg-info-50 text-info-700 ring-info-100',
} as const

export function Badge({
  children,
  tone = 'neutral',
  className,
  dot,
}: {
  children: React.ReactNode
  tone?: keyof typeof BADGE_TONES
  className?: string
  dot?: string
}) {
  return (
    <span className={cn('badge', BADGE_TONES[tone], className)}>
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', dot)} aria-hidden />}
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------- Card
export function Card({
  className,
  interactive,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return <div className={cn(interactive ? 'card-interactive' : 'card', className)} {...props} />
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('border-b border-ink-200 px-5 py-4', className)} {...props} />
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn('text-sm font-semibold text-ink-900', className)} {...props} />
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}

// --------------------------------------------------------------------- Input
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, hint, className, id, ...props },
  ref,
) {
  const inputId = id ?? props.name
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined

  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="label">
          {label}
          {props.required && <span className="ml-0.5 text-danger-600">*</span>}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn('input', error && 'input-error', className)}
        {...props}
      />
      {error ? (
        <p id={`${inputId}-error`} className="text-xs text-danger-600">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-xs text-ink-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
})

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
  error?: string
  hint?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, error, hint, className, id, ...props },
  ref,
) {
  const inputId = id ?? props.name
  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="label">
          {label}
          {props.required && <span className="ml-0.5 text-danger-600">*</span>}
        </label>
      )}
      <textarea
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        className={cn('input min-h-[100px] resize-y', error && 'input-error', className)}
        {...props}
      />
      {error ? (
        <p className="text-xs text-danger-600">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-500">{hint}</p>
      ) : null}
    </div>
  )
})

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, error, className, id, children, ...props },
  ref,
) {
  const inputId = id ?? props.name
  return (
    <div className="space-y-1.5">
      {label && (
        <label htmlFor={inputId} className="label">
          {label}
        </label>
      )}
      <select
        ref={ref}
        id={inputId}
        className={cn('input cursor-pointer pr-9', error && 'input-error', className)}
        {...props}
      >
        {children}
      </select>
      {error && <p className="text-xs text-danger-600">{error}</p>}
    </div>
  )
})

// ------------------------------------------------------------------- Avatar
export function Avatar({
  name,
  src,
  size = 'md',
  className,
}: {
  name: string
  src?: string | null
  size?: 'xs' | 'sm' | 'md' | 'lg'
  className?: string
}) {
  const sizes = {
    xs: 'h-6 w-6 text-[10px]',
    sm: 'h-8 w-8 text-xs',
    md: 'h-10 w-10 text-sm',
    lg: 'h-14 w-14 text-lg',
  }
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('')

  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={src}
        alt={name}
        className={cn('shrink-0 rounded-full object-cover ring-1 ring-ink-200', sizes[size], className)}
      />
    )
  }

  return (
    <span
      aria-hidden
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full bg-brand-100 font-semibold text-brand-700 ring-1 ring-brand-200',
        sizes[size],
        className,
      )}
    >
      {letters || '?'}
    </span>
  )
}

// ------------------------------------------------------------- Score display
/** Circular ATS score. The ring is the fastest way to read a score at a glance. */
export function ScoreRing({
  score,
  size = 56,
  label,
}: {
  score: number | null | undefined
  size?: number
  label?: string
}) {
  const value = score ?? 0
  const radius = (size - 6) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (Math.min(100, Math.max(0, value)) / 100) * circumference

  const colour =
    score == null
      ? 'stroke-ink-200'
      : value >= 85
        ? 'stroke-success-500'
        : value >= 70
          ? 'stroke-brand-500'
          : value >= 50
            ? 'stroke-warning-500'
            : 'stroke-ink-300'

  const textColour =
    score == null
      ? 'text-ink-400'
      : value >= 85
        ? 'text-success-700'
        : value >= 70
          ? 'text-brand-700'
          : value >= 50
            ? 'text-warning-700'
            : 'text-ink-500'

  return (
    <div
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`ATS score ${score == null ? 'not available' : `${Math.round(value)} percent`}`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={4}
          className="stroke-ink-100"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={cn(colour, 'transition-[stroke-dashoffset] duration-700 ease-out')}
        />
      </svg>
      <span className="absolute flex flex-col items-center leading-none">
        <span className={cn('font-semibold tabular-nums', textColour)} style={{ fontSize: size / 4 }}>
          {score == null ? '—' : Math.round(value)}
        </span>
        {label && <span className="mt-0.5 text-[9px] uppercase text-ink-400">{label}</span>}
      </span>
    </div>
  )
}

/** Horizontal bar for a single ATS dimension. */
export function ScoreBar({
  label,
  score,
  weight,
  description,
}: {
  label: string
  score: number
  weight?: number
  description?: string
}) {
  const colour =
    score >= 85
      ? 'bg-success-500'
      : score >= 70
        ? 'bg-brand-500'
        : score >= 50
          ? 'bg-warning-500'
          : 'bg-ink-300'

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-ink-800">{label}</span>
        <span className="flex items-baseline gap-2 text-sm">
          {weight !== undefined && weight > 0 && (
            <span className="text-xs text-ink-400">{Math.round(weight * 100)}% weight</span>
          )}
          <span className="font-semibold tabular-nums text-ink-900">{Math.round(score)}%</span>
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-100">
        <div
          className={cn('h-full rounded-full transition-all duration-700 ease-out', colour)}
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
      {description && <p className="text-xs leading-relaxed text-ink-500">{description}</p>}
    </div>
  )
}

// ------------------------------------------------------------------- States
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('skeleton', className)} />
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {Icon && (
        <span className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-ink-100">
          <Icon className="h-6 w-6 text-ink-400" />
        </span>
      )}
      <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-ink-500">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string
  message?: string
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      {message && <p className="mt-1.5 max-w-md text-sm text-ink-500">{message}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

// ------------------------------------------------------------------- Modal
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: React.ReactNode
  footer?: React.ReactNode
  size?: 'sm' | 'md' | 'lg'
}) {
  // Escape closes, and the page behind must not scroll while a modal is open.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  if (!open) return null

  const widths = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl' }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <div
        className="absolute inset-0 animate-fade-in bg-ink-950/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          'relative w-full animate-slide-up rounded-2xl bg-white shadow-popover',
          widths[size],
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-ink-200 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
            {description && <p className="mt-1 text-xs text-ink-500">{description}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 -mt-1 rounded-lg p-1.5 text-ink-400 transition-colors hover:bg-ink-100 hover:text-ink-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3.5">{footer}</div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------- Tabs
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; count?: number }[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div className="scroll-x border-b border-ink-200" role="tablist">
      <div className="flex min-w-max gap-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active === tab.id}
            onClick={() => onChange(tab.id)}
            className={cn(
              'relative whitespace-nowrap px-3.5 py-2.5 text-sm font-medium transition-colors',
              active === tab.id
                ? 'text-ink-900'
                : 'text-ink-500 hover:text-ink-700',
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span
                className={cn(
                  'ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                  active === tab.id ? 'bg-ink-900 text-white' : 'bg-ink-100 text-ink-500',
                )}
              >
                {tab.count}
              </span>
            )}
            {active === tab.id && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ink-900" />
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

// -------------------------------------------------------------- Stat / KPI
export function Stat({
  label,
  value,
  change,
  href,
  tone = 'neutral',
  icon: Icon,
}: {
  label: string
  value: number | string
  change?: string
  href?: string
  tone?: 'neutral' | 'brand' | 'success' | 'warning' | 'danger'
  icon?: React.ComponentType<{ className?: string }>
}) {
  const tones = {
    neutral: 'text-ink-900',
    brand: 'text-brand-700',
    success: 'text-success-700',
    warning: 'text-warning-700',
    danger: 'text-danger-700',
  }

  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-ink-300" />}
      </div>
      <p className={cn('mt-2 text-2xl font-semibold tabular-nums', tones[tone])}>{value}</p>
      {change && <p className="mt-1 text-xs text-ink-500">{change}</p>}
    </>
  )

  if (href) {
    return (
      <Link href={href} className="card-interactive block px-4 py-3.5">
        {content}
      </Link>
    )
  }
  return <div className="card px-4 py-3.5">{content}</div>
}

// ------------------------------------------------------------------ Tooltip
/** CSS-only tooltip. Enough for hints; nothing here needs a positioning library. */
export function Tooltip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1.5 hidden -translate-x-1/2
                   whitespace-nowrap rounded-lg bg-ink-900 px-2 py-1 text-xs text-white
                   shadow-popover group-hover:block"
      >
        {label}
      </span>
    </span>
  )
}

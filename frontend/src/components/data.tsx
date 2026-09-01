'use client'

/**
 * Presentation pieces shared by the list, detail and console pages.
 *
 * These exist because the same three shapes recur everywhere: a table with loading and
 * empty states, a paginator, and a labelled key/value block. Writing them once keeps the
 * pages themselves about their subject rather than about markup.
 */

import { AlertTriangle, Info, Radio } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { RealtimeStatus } from '@/hooks/use-realtime'
import type { PageMeta } from '@/lib/api'
import { cn } from '@/lib/utils'

import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from './ui'

// ---------------------------------------------------------------------- table
export interface Column<T> {
  key: string
  header: string
  /** Right-align numeric columns so digits line up. */
  align?: 'left' | 'right'
  /** Hidden below the `sm` breakpoint, for columns that are nice-to-have. */
  hideOnMobile?: boolean
  width?: string
  render: (row: T) => React.ReactNode
}

export function DataTable<T>({
  rows,
  columns,
  loading,
  error,
  onRetry,
  empty,
  rowKey,
  onRowClick,
}: {
  rows: T[] | undefined
  columns: Column<T>[]
  loading?: boolean
  error?: Error | null
  onRetry?: () => void
  empty: React.ReactNode
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
}) {
  if (loading) {
    return (
      <Card className="p-4">
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-11" />
          ))}
        </div>
      </Card>
    )
  }
  if (error) {
    return (
      <Card>
        <ErrorState message={error.message} onRetry={onRetry} />
      </Card>
    )
  }
  if (!rows?.length) return <Card>{empty}</Card>

  return (
    <Card className="overflow-hidden">
      <div className="scroll-x">
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b border-ink-200 bg-ink-50/60">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  style={column.width ? { width: column.width } : undefined}
                  className={cn(
                    'px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500',
                    column.align === 'right' ? 'text-right' : 'text-left',
                    column.hideOnMobile && 'hidden sm:table-cell',
                  )}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  'border-b border-ink-100 last:border-0',
                  onRowClick && 'cursor-pointer transition-colors hover:bg-ink-50',
                )}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={cn(
                      'px-4 py-3 align-middle text-ink-700',
                      column.align === 'right' && 'text-right tabular-nums',
                      column.hideOnMobile && 'hidden sm:table-cell',
                    )}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ------------------------------------------------------------------ paginator
export function Paginator({
  meta,
  onPage,
}: {
  meta: PageMeta | undefined
  onPage: (page: number) => void
}) {
  if (!meta || meta.total_pages <= 1) return null
  return (
    <div className="mt-5 flex items-center justify-between gap-4">
      <Button
        variant="secondary"
        size="sm"
        disabled={!meta.has_previous}
        onClick={() => onPage(meta.page - 1)}
      >
        Previous
      </Button>
      <span className="text-sm text-ink-500">
        Page {meta.page} of {meta.total_pages}
        <span className="hidden sm:inline"> · {meta.total_items} total</span>
      </span>
      <Button
        variant="secondary"
        size="sm"
        disabled={!meta.has_next}
        onClick={() => onPage(meta.page + 1)}
      >
        Next
      </Button>
    </div>
  )
}

// ------------------------------------------------------------ key/value block
export function Field({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={className}>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-400">{label}</dt>
      <dd className="mt-1 text-sm text-ink-800">{children}</dd>
    </div>
  )
}

export function FieldGrid({
  children,
  columns = 3,
}: {
  children: React.ReactNode
  columns?: 2 | 3 | 4
}) {
  const layout = {
    2: 'sm:grid-cols-2',
    3: 'sm:grid-cols-2 lg:grid-cols-3',
    4: 'sm:grid-cols-2 lg:grid-cols-4',
  }
  return <dl className={cn('grid gap-x-6 gap-y-4', layout[columns])}>{children}</dl>
}

// --------------------------------------------------------------------- notes
/**
 * A standing notice about how the system is configured — an unconfigured email provider,
 * a calendar that is not connected, an assessment awaiting a human grader.
 *
 * Used deliberately and often: the product's rule is that it never implies something
 * happened when it did not, and these notices are how that shows up in the interface.
 */
export function Notice({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: 'info' | 'warning' | 'neutral'
  title?: string
  children: React.ReactNode
  action?: React.ReactNode
}) {
  const tones = {
    info: 'border-info-100 bg-info-50 text-info-700',
    warning: 'border-warning-100 bg-warning-50 text-warning-700',
    neutral: 'border-ink-200 bg-ink-50 text-ink-600',
  }
  const Icon = tone === 'warning' ? AlertTriangle : Info

  return (
    <div className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', tones[tone])}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm leading-relaxed">
        {title && <p className="font-semibold">{title}</p>}
        <div className={cn(title && 'mt-0.5')}>{children}</div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

// ------------------------------------------------------------ live indicator
/** Shows the real connection state. "Live" appears only when the stream is actually open. */
export function LiveIndicator({ status }: { status: RealtimeStatus }) {
  const config = {
    live: { tone: 'success' as const, dot: 'bg-success-500', label: 'Live' },
    connecting: { tone: 'neutral' as const, dot: 'bg-ink-400 animate-pulse', label: 'Connecting' },
    offline: { tone: 'neutral' as const, dot: 'bg-ink-300', label: 'Not live' },
  }[status]

  return (
    <Badge tone={config.tone} dot={config.dot}>
      <span className="sr-only">Live updates: </span>
      {config.label}
    </Badge>
  )
}

/** A brief toast when a live event arrives, so the refresh is not silent. */
export function LiveToast({ message }: { message: string | null }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!message) return
    setVisible(true)
    const timer = setTimeout(() => setVisible(false), 4000)
    return () => clearTimeout(timer)
  }, [message])

  if (!visible || !message) return null

  return (
    <div
      role="status"
      className="fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 animate-slide-up items-center
                 gap-2 rounded-full bg-ink-900 px-4 py-2 text-sm text-white shadow-popover"
    >
      <Radio className="h-3.5 w-3.5 text-success-400" aria-hidden />
      {message}
    </div>
  )
}

// ------------------------------------------------------------------- filters
export function FilterBar({ children }: { children: React.ReactNode }) {
  return <div className="mt-5 flex flex-wrap items-end gap-3">{children}</div>
}

export function EmptyRows({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return <EmptyState icon={icon} title={title} description={description} action={action} />
}

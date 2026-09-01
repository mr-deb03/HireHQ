'use client'

/**
 * The audit trail.
 *
 * Every entry is written by the server, never by this page, and nothing here can be
 * edited or deleted — that is the point of an audit log. `changes` is rendered as a
 * before/after diff so a reviewer can see what actually moved, and the redaction that
 * happens at write time (§47: no passwords, tokens, résumé contents or API secrets) means
 * there is nothing sensitive to leak by displaying it.
 */

import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ScrollText, Search, ShieldCheck } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { PageBody, PageHeader } from '@/components/app-shell'
import { EmptyRows, Notice, Paginator } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Input,
  Select,
  Skeleton,
} from '@/components/ui'
import { api, type Page } from '@/lib/api'
import type { AuditLog } from '@/lib/types'
import { cn, formatDateTime, titleCase } from '@/lib/utils'

const ACTION_TONES: Record<string, 'success' | 'neutral' | 'warning' | 'danger' | 'info'> = {
  CREATE: 'success',
  UPDATE: 'info',
  DELETE: 'danger',
  LOGIN: 'neutral',
  LOGIN_FAILED: 'warning',
  LOGOUT: 'neutral',
  STATUS_CHANGE: 'info',
  PERMISSION_CHANGE: 'warning',
  EXPORT: 'warning',
  AI_DECISION_ASSIST: 'info',
  FILE_ACCESS: 'neutral',
}

function AuditLogsContent() {
  const router = useRouter()
  const params = useSearchParams()

  const action = params.get('action') ?? ''
  const entityType = params.get('entity_type') ?? ''
  const query = params.get('q') ?? ''
  const since = params.get('since') ?? ''
  const page = Number(params.get('page') ?? '1')

  const [search, setSearch] = useState(query)
  const [expanded, setExpanded] = useState<string | null>(null)

  const actionsQuery = useQuery({
    queryKey: ['audit', 'actions'],
    queryFn: () => api.get<string[]>('/audit-logs/actions'),
    staleTime: 30 * 60 * 1000,
  })

  const logsQuery = useQuery({
    queryKey: ['audit', 'logs', action, entityType, query, since, page],
    queryFn: () =>
      api.get<Page<AuditLog>>('/audit-logs', {
        query: {
          action: action || undefined,
          entity_type: entityType || undefined,
          q: query || undefined,
          since: since || undefined,
          page,
          page_size: 30,
        },
      }),
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/admin/audit-logs${next.toString() ? `?${next}` : ''}`)
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        description={
          logsQuery.data ? `${logsQuery.data.meta.total_items} recorded events` : 'Recorded events'
        }
      >
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              setParam('q', search)
            }}
            className="relative min-w-56 flex-1"
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search summaries and actors"
              aria-label="Search the audit log"
              className="input pl-9"
            />
          </form>

          <div className="w-52">
            <Select
              value={action}
              onChange={(e) => setParam('action', e.target.value)}
              aria-label="Filter by action"
            >
              <option value="">All actions</option>
              {(actionsQuery.data ?? []).map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </Select>
          </div>

          <div className="w-44">
            <Input
              type="date"
              aria-label="From date"
              value={since}
              onChange={(e) => setParam('since', e.target.value)}
            />
          </div>

          {(action || entityType || query || since) && (
            <Button variant="secondary" onClick={() => router.push('/admin/audit-logs')}>
              Clear
            </Button>
          )}
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        <Notice tone="neutral" title="Append-only by design">
          <span className="flex items-start gap-1.5">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Entries cannot be edited or deleted from this interface. Passwords, tokens,
            résumé contents and API secrets are redacted before anything is written, so
            nothing sensitive is stored here to begin with.
          </span>
        </Notice>

        {logsQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : logsQuery.isError ? (
          <Card>
            <ErrorState
              message={(logsQuery.error as Error).message}
              onRetry={() => logsQuery.refetch()}
            />
          </Card>
        ) : !logsQuery.data?.items.length ? (
          <Card>
            <EmptyRows
              icon={ScrollText}
              title="No matching events"
              description="Try widening the date range or clearing the action filter."
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <ul className="divide-y divide-ink-100">
              {logsQuery.data.items.map((log) => {
                const isOpen = expanded === log.id
                const hasDetail =
                  Object.keys(log.changes).length > 0 || Object.keys(log.meta).length > 0

                return (
                  <li key={log.id}>
                    <button
                      onClick={() => setExpanded(isOpen ? null : log.id)}
                      disabled={!hasDetail}
                      className={cn(
                        'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors',
                        hasDetail ? 'hover:bg-ink-50' : 'cursor-default',
                      )}
                    >
                      <span className="mt-0.5 shrink-0 text-ink-300">
                        {hasDetail ? (
                          isOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )
                        ) : (
                          <span className="block h-4 w-4" />
                        )}
                      </span>

                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <Badge tone={ACTION_TONES[log.action] ?? 'neutral'}>
                            {titleCase(log.action)}
                          </Badge>
                          <span className="text-sm text-ink-800">{log.summary}</span>
                        </span>
                        <span className="mt-1 block text-xs text-ink-500">
                          {log.actor_email ?? 'System'}
                          {log.actor_roles.length > 0 &&
                            ` (${log.actor_roles.map(titleCase).join(', ')})`}
                          {' · '}
                          {log.entity_type}
                          {log.ip_address && ` · ${log.ip_address}`}
                        </span>
                      </span>

                      <span className="shrink-0 text-xs tabular-nums text-ink-400">
                        {formatDateTime(log.created_at)}
                      </span>
                    </button>

                    {isOpen && (
                      <div className="border-t border-ink-100 bg-ink-50 px-4 py-3.5 pl-11">
                        {Object.keys(log.changes).length > 0 && (
                          <div>
                            <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
                              Changes
                            </h4>
                            <dl className="mt-2 space-y-1.5">
                              {Object.entries(log.changes).map(([field, value]) => {
                                const pair = value as { from?: unknown; to?: unknown }
                                const isDiff =
                                  pair && typeof pair === 'object' && ('from' in pair || 'to' in pair)
                                return (
                                  <div key={field} className="flex flex-wrap gap-2 text-xs">
                                    <dt className="font-medium text-ink-600">{titleCase(field)}</dt>
                                    <dd className="font-mono text-ink-700">
                                      {isDiff ? (
                                        <>
                                          <span className="text-danger-600 line-through">
                                            {JSON.stringify(pair.from) ?? 'null'}
                                          </span>
                                          <span className="mx-1.5 text-ink-400">→</span>
                                          <span className="text-success-700">
                                            {JSON.stringify(pair.to) ?? 'null'}
                                          </span>
                                        </>
                                      ) : (
                                        JSON.stringify(value)
                                      )}
                                    </dd>
                                  </div>
                                )
                              })}
                            </dl>
                          </div>
                        )}

                        {Object.keys(log.meta).length > 0 && (
                          <div className={Object.keys(log.changes).length > 0 ? 'mt-4' : ''}>
                            <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
                              Context
                            </h4>
                            <pre className="scroll-x mt-2 rounded-lg bg-white p-2.5 font-mono text-xs text-ink-700">
                              {JSON.stringify(log.meta, null, 2)}
                            </pre>
                          </div>
                        )}

                        {log.request_id && (
                          <p className="mt-3 font-mono text-xs text-ink-400">
                            request {log.request_id}
                          </p>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </Card>
        )}

        <Paginator meta={logsQuery.data?.meta} onPage={(p) => setParam('page', String(p))} />
      </PageBody>
    </>
  )
}

export default function AuditLogsPage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <AuditLogsContent />
    </Suspense>
  )
}

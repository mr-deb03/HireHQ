'use client'

/**
 * Interview calendar, plus the connection state of the external provider.
 *
 * `provider_status` is shown prominently and truthfully: when nothing is connected, the
 * page says invitations are *not* being sent rather than rendering a calendar that looks
 * like it is synchronised with the attendees' own (§69).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Link2,
  Link2Off,
  Video,
} from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { CalendarAccount, CalendarEvent, CalendarView } from '@/lib/types'
import { cn, formatDate } from '@/lib/utils'

interface ProviderStatus {
  provider: string
  delivers_invitations: boolean
  connected_account?: CalendarAccount | null
  message: string
}

type ViewMode = 'day' | 'week' | 'month' | 'agenda'

function shiftAnchor(anchor: Date, view: ViewMode, direction: 1 | -1): Date {
  const next = new Date(anchor)
  if (view === 'day') next.setDate(next.getDate() + direction)
  else if (view === 'week') next.setDate(next.getDate() + 7 * direction)
  else if (view === 'month') next.setMonth(next.getMonth() + direction)
  else next.setDate(next.getDate() + 30 * direction)
  return next
}

function CalendarContent() {
  const params = useSearchParams()
  const { can } = useAuth()

  const [view, setView] = useState<ViewMode>('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const [mineOnly, setMineOnly] = useState(false)

  const eventsQuery = useQuery({
    queryKey: ['calendar', view, anchor.toISOString().slice(0, 10), mineOnly],
    queryFn: () =>
      api.get<CalendarView>('/calendar/events', {
        query: {
          view,
          anchor: anchor.toISOString().slice(0, 10),
          mine_only: mineOnly || undefined,
        },
      }),
  })

  const statusQuery = useQuery({
    queryKey: ['calendar', 'status'],
    queryFn: () => api.get<ProviderStatus>('/calendar/status'),
  })

  // The OAuth callback redirects back here with ?connected=0|1.
  const connected = params.get('connected')
  const failureReason = params.get('reason')

  const grouped = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const event of eventsQuery.data?.events ?? []) {
      const day = event.start_at.slice(0, 10)
      map.set(day, [...(map.get(day) ?? []), event])
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [eventsQuery.data])

  return (
    <>
      <PageHeader
        title="Calendar"
        description="Interviews across your jobs."
        actions={
          <>
            <Link href="/recruiter/interviews">
              <Button variant="secondary" size="sm">
                List view
              </Button>
            </Link>
            {can('calendar:manage') && <ConnectButton status={statusQuery.data} />}
          </>
        }
      >
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1">
            <Button
              variant="secondary"
              size="icon"
              aria-label="Previous period"
              onClick={() => setAnchor((a) => shiftAnchor(a, view, -1))}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setAnchor(new Date())}>
              Today
            </Button>
            <Button
              variant="secondary"
              size="icon"
              aria-label="Next period"
              onClick={() => setAnchor((a) => shiftAnchor(a, view, 1))}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          <div className="flex rounded-xl bg-ink-100 p-0.5" role="tablist">
            {(['day', 'week', 'month', 'agenda'] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                role="tab"
                aria-selected={view === mode}
                onClick={() => setView(mode)}
                className={cn(
                  'rounded-lg px-3 py-1.5 text-sm font-medium capitalize transition-colors',
                  view === mode ? 'bg-white text-ink-900 shadow-sm' : 'text-ink-500 hover:text-ink-800',
                )}
              >
                {mode}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-2 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={mineOnly}
              onChange={(e) => setMineOnly(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-brand-600"
            />
            Only mine
          </label>

          {eventsQuery.data && (
            <span className="ml-auto text-sm text-ink-500">
              {formatDate(eventsQuery.data.start)} – {formatDate(eventsQuery.data.end)} ·{' '}
              {eventsQuery.data.total} {eventsQuery.data.total === 1 ? 'event' : 'events'}
            </span>
          )}
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {connected === '1' && (
          <Notice tone="info" title="Calendar connected">
            Interviews scheduled from now on will create invitations on your calendar.
          </Notice>
        )}
        {connected === '0' && (
          <Notice tone="warning" title="Calendar was not connected">
            {failureReason === 'invalid_state'
              ? 'That authorisation link had expired or did not match this session. Start the connection again.'
              : failureReason === 'exchange_failed'
                ? 'The provider rejected the authorisation. Check the client credentials on the server and try again.'
                : `The connection did not complete${failureReason ? ` (${failureReason})` : ''}.`}
          </Notice>
        )}

        {statusQuery.data && !statusQuery.data.connected_account && (
          <Notice
            tone={statusQuery.data.delivers_invitations ? 'info' : 'warning'}
            title={
              statusQuery.data.delivers_invitations
                ? 'No calendar account connected'
                : 'No calendar provider is configured'
            }
          >
            {statusQuery.data.message}
          </Notice>
        )}

        {statusQuery.data?.connected_account?.sync_error && (
          <Notice tone="warning" title="Calendar sync is failing">
            {statusQuery.data.connected_account.sync_error}
          </Notice>
        )}

        {eventsQuery.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : eventsQuery.isError ? (
          <Card>
            <ErrorState
              message={(eventsQuery.error as Error).message}
              onRetry={() => eventsQuery.refetch()}
            />
          </Card>
        ) : grouped.length === 0 ? (
          <Card>
            <EmptyState
              icon={CalendarDays}
              title="Nothing scheduled in this period"
              description="Move to another week, or schedule an interview from the pipeline board."
              action={
                <Link href="/recruiter/pipeline">
                  <Button>Open the pipeline</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <div className="space-y-5">
            {grouped.map(([day, events]) => (
              <div key={day}>
                <h3 className="sticky top-16 z-10 -mx-1 bg-ink-50/95 px-1 py-1.5 text-sm font-semibold text-ink-900 backdrop-blur">
                  {new Intl.DateTimeFormat('en-GB', {
                    weekday: 'long',
                    day: 'numeric',
                    month: 'long',
                  }).format(new Date(day))}
                </h3>
                <div className="mt-2 space-y-2">
                  {events.map((event) => (
                    <EventRow key={event.id} event={event} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </PageBody>
    </>
  )
}

function EventRow({ event }: { event: CalendarEvent }) {
  const synced = event.sync_status === 'SYNCED'

  const body = (
    <Card interactive={Boolean(event.interview_id)} className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-ink-900">{event.title}</h4>
            {/* An unsynced event exists in HireHQ only — no invitation reached anyone. */}
            {!synced && <Badge tone="neutral">HireHQ only</Badge>}
          </div>
          {event.description && (
            <p className="mt-1 line-clamp-2 text-sm text-ink-600">{event.description}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-600">
            <span className="tabular-nums">
              {new Intl.DateTimeFormat('en-GB', {
                hour: '2-digit',
                minute: '2-digit',
              }).format(new Date(event.start_at))}
              {' – '}
              {new Intl.DateTimeFormat('en-GB', {
                hour: '2-digit',
                minute: '2-digit',
              }).format(new Date(event.end_at))}
            </span>
            {event.location && <span>{event.location}</span>}
            {event.attendees.length > 0 && (
              <span className="text-ink-400">
                {event.attendees.length}{' '}
                {event.attendees.length === 1 ? 'attendee' : 'attendees'}
              </span>
            )}
          </div>
        </div>

        {event.meeting_link && (
          <a
            href={event.meeting_link}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="flex shrink-0 items-center gap-1.5 text-sm font-medium text-brand-600 hover:text-brand-700"
          >
            <Video className="h-4 w-4" />
            Join
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </Card>
  )

  return event.interview_id ? (
    <Link href={`/recruiter/interviews/${event.interview_id}`} className="block">
      {body}
    </Link>
  ) : (
    body
  )
}

function ConnectButton({ status }: { status?: ProviderStatus }) {
  const queryClient = useQueryClient()

  const connect = useMutation({
    mutationFn: () =>
      api.post<{ authorization_url: string; provider: string; instructions: string }>(
        '/calendar/connect',
      ),
    onSuccess: (result) => {
      // Full navigation rather than a popup: the provider's consent screen refuses to
      // render in an iframe, and popups are widely blocked.
      window.location.href = result.authorization_url
    },
    onError: (error) =>
      toast.error(
        error instanceof ApiError ? error.message : 'Could not start the calendar connection',
      ),
  })

  const disconnect = useMutation({
    mutationFn: () => api.delete('/calendar/disconnect'),
    onSuccess: () => {
      toast.success('Calendar disconnected. Stored tokens were deleted.')
      void queryClient.invalidateQueries({ queryKey: ['calendar'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not disconnect'),
  })

  if (status?.connected_account) {
    return (
      <Button
        variant="secondary"
        size="sm"
        loading={disconnect.isPending}
        onClick={() => disconnect.mutate()}
      >
        <Link2Off className="h-4 w-4" />
        Disconnect {status.connected_account.account_email}
      </Button>
    )
  }

  return (
    <Button
      size="sm"
      loading={connect.isPending}
      disabled={status ? !status.delivers_invitations : false}
      title={
        status && !status.delivers_invitations
          ? 'No calendar provider is configured on this server'
          : undefined
      }
      onClick={() => connect.mutate()}
    >
      <Link2 className="h-4 w-4" />
      Connect calendar
    </Button>
  )
}

export default function CalendarPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <CalendarContent />
    </Suspense>
  )
}

'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays,
  CalendarX,
  CheckCircle2,
  Clock,
  ExternalLink,
  MapPin,
  MessageSquare,
  Video,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { LiveIndicator, Notice } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  Select,
  Skeleton,
  Tabs,
  Textarea,
} from '@/components/ui'
import { useRealtime } from '@/hooks/use-realtime'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { InterviewStatus, InterviewSummary } from '@/lib/types'
import { cn, formatDateTime, formatRelative, titleCase } from '@/lib/utils'

const STATUS_TONES: Record<InterviewStatus, 'success' | 'neutral' | 'warning' | 'danger' | 'info'> =
  {
    SCHEDULED: 'info',
    CONFIRMED: 'success',
    RESCHEDULED: 'warning',
    COMPLETED: 'neutral',
    CANCELLED: 'danger',
    NO_SHOW: 'danger',
  }

const TABS = [
  { id: 'upcoming', label: 'Upcoming' },
  { id: 'pending-feedback', label: 'Awaiting feedback' },
  { id: 'past', label: 'Past' },
  { id: 'cancelled', label: 'Cancelled' },
]

function InterviewsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const { can } = useAuth()
  const { status: liveStatus } = useRealtime()

  const tab = params.get('tab') ?? 'upcoming'
  const page = Number(params.get('page') ?? '1')
  const [acting, setActing] = useState<{ mode: 'complete' | 'cancel' | 'reschedule'; interview: InterviewSummary } | null>(null)

  // "Awaiting feedback" has its own endpoint because it is scoped to what *this* user
  // still owes, which a status filter cannot express.
  const pendingQuery = useQuery({
    queryKey: ['interviews', 'pending-feedback'],
    queryFn: () => api.get<InterviewSummary[]>('/interviews/pending-feedback'),
    enabled: tab === 'pending-feedback',
  })

  const listQuery = useQuery({
    queryKey: ['interviews', tab, page],
    queryFn: () =>
      api.get<Page<InterviewSummary>>('/interviews', {
        query: {
          page,
          page_size: 20,
          upcoming: tab === 'upcoming' ? true : undefined,
          // `status` is a repeated query parameter, so pass an array even for one value.
          status:
            tab === 'cancelled'
              ? ['CANCELLED', 'NO_SHOW']
              : tab === 'past'
                ? ['COMPLETED']
                : undefined,
        },
      }),
    enabled: tab !== 'pending-feedback',
  })

  const rows = tab === 'pending-feedback' ? pendingQuery.data : listQuery.data?.items
  const loading = tab === 'pending-feedback' ? pendingQuery.isLoading : listQuery.isLoading
  const error = (tab === 'pending-feedback' ? pendingQuery.error : listQuery.error) as Error | null

  function setTab(next: string) {
    router.push(`/recruiter/interviews?tab=${next}`)
  }

  return (
    <>
      <PageHeader
        title="Interviews"
        description="Everything scheduled across your jobs."
        actions={
          <>
            <LiveIndicator status={liveStatus} />
            <Link href="/recruiter/calendar">
              <Button variant="secondary" size="sm">
                <CalendarDays className="h-4 w-4" />
                Calendar
              </Button>
            </Link>
          </>
        }
      >
        <div className="mt-5">
          <Tabs
            tabs={TABS.map((t) =>
              t.id === 'pending-feedback' && pendingQuery.data
                ? { ...t, count: pendingQuery.data.length }
                : t,
            )}
            active={tab}
            onChange={setTab}
          />
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {tab === 'pending-feedback' && (
          <Notice tone="info">
            Feedback is what turns an interview into a decision. Until it is submitted, the
            application cannot move past the interview stage.
          </Notice>
        )}

        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        ) : error ? (
          <Card>
            <ErrorState
              message={error.message}
              onRetry={() =>
                tab === 'pending-feedback' ? pendingQuery.refetch() : listQuery.refetch()
              }
            />
          </Card>
        ) : !rows?.length ? (
          <Card>
            <EmptyState
              icon={CalendarDays}
              title={
                tab === 'upcoming'
                  ? 'No interviews scheduled'
                  : tab === 'pending-feedback'
                    ? 'No feedback owed'
                    : `No ${tab} interviews`
              }
              description={
                tab === 'upcoming'
                  ? 'Schedule an interview from a shortlisted candidate on the pipeline board.'
                  : tab === 'pending-feedback'
                    ? 'Every interview you have taken part in has feedback recorded.'
                    : undefined
              }
              action={
                tab === 'upcoming' ? (
                  <Link href="/recruiter/pipeline">
                    <Button>Open the pipeline</Button>
                  </Link>
                ) : undefined
              }
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {rows.map((interview) => (
              <InterviewRow
                key={interview.id}
                interview={interview}
                canManage={can('interview:update')}
                onAction={(mode) => setActing({ mode, interview })}
              />
            ))}
          </div>
        )}

        {tab !== 'pending-feedback' && listQuery.data && listQuery.data.meta.total_pages > 1 && (
          <div className="flex items-center justify-between pt-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!listQuery.data.meta.has_previous}
              onClick={() => router.push(`/recruiter/interviews?tab=${tab}&page=${page - 1}`)}
            >
              Previous
            </Button>
            <span className="text-sm text-ink-500">
              Page {listQuery.data.meta.page} of {listQuery.data.meta.total_pages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={!listQuery.data.meta.has_next}
              onClick={() => router.push(`/recruiter/interviews?tab=${tab}&page=${page + 1}`)}
            >
              Next
            </Button>
          </div>
        )}
      </PageBody>

      {acting && (
        <InterviewActionModal
          mode={acting.mode}
          interview={acting.interview}
          onClose={() => setActing(null)}
        />
      )}
    </>
  )
}

function InterviewRow({
  interview,
  canManage,
  onAction,
}: {
  interview: InterviewSummary
  canManage: boolean
  onAction: (mode: 'complete' | 'cancel' | 'reschedule') => void
}) {
  const isPast = new Date(interview.scheduled_end) < new Date()
  const isOpen = !['COMPLETED', 'CANCELLED', 'NO_SHOW'].includes(interview.status)

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold text-ink-900">{interview.title}</h3>
            <Badge tone={STATUS_TONES[interview.status]}>{titleCase(interview.status)}</Badge>
            <Badge>{titleCase(interview.interview_type)}</Badge>
            {interview.round_name && <Badge tone="info">{interview.round_name}</Badge>}
          </div>

          <p className="mt-1 text-sm text-ink-600">
            <Link
              href={`/recruiter/candidates/${interview.candidate_id}`}
              className="font-medium text-ink-800 hover:text-brand-700"
            >
              {interview.candidate_name ?? 'Candidate'}
            </Link>
            {interview.job_title && <span className="text-ink-400"> · {interview.job_title}</span>}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-600">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-ink-400" />
              {formatDateTime(interview.scheduled_start)} · {interview.duration_minutes} min
            </span>
            {interview.location && (
              <span className="flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 text-ink-400" />
                {interview.location}
              </span>
            )}
            {interview.meeting_link && (
              <a
                href={interview.meeting_link}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 font-medium text-brand-600 hover:text-brand-700"
              >
                <Video className="h-3.5 w-3.5" />
                Join
                <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>

          {interview.participants.length > 0 && (
            <p className="mt-2 text-xs text-ink-500">
              {interview.participants.length}{' '}
              {interview.participants.length === 1 ? 'interviewer' : 'interviewers'}
              {interview.feedback_count > 0 && ` · ${interview.feedback_count} feedback submitted`}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <span
            className={cn(
              'text-xs',
              isPast && isOpen ? 'font-medium text-warning-700' : 'text-ink-400',
            )}
          >
            {formatRelative(interview.scheduled_start)}
          </span>

          <div className="flex flex-wrap justify-end gap-1.5">
            <Link href={`/recruiter/interviews/${interview.id}`}>
              <Button variant="ghost" size="sm">
                <MessageSquare className="h-3.5 w-3.5" />
                Feedback
              </Button>
            </Link>
            {canManage && isOpen && (
              <>
                <Button variant="ghost" size="sm" onClick={() => onAction('reschedule')}>
                  Reschedule
                </Button>
                {isPast && (
                  <Button variant="secondary" size="sm" onClick={() => onAction('complete')}>
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Complete
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => onAction('cancel')}>
                  <CalendarX className="h-3.5 w-3.5" />
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {interview.status === 'SCHEDULED' && (
        <p className="mt-3 border-t border-ink-100 pt-3 text-xs text-ink-500">
          The candidate has not confirmed this slot yet.
        </p>
      )}
    </Card>
  )
}

function InterviewActionModal({
  mode,
  interview,
  onClose,
}: {
  mode: 'complete' | 'cancel' | 'reschedule'
  interview: InterviewSummary
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [start, setStart] = useState(interview.scheduled_start.slice(0, 16))
  const [duration, setDuration] = useState(String(interview.duration_minutes))
  const [notifyCandidate, setNotifyCandidate] = useState(true)

  const action = useMutation({
    mutationFn: () => {
      if (mode === 'complete') {
        return api.post(`/interviews/${interview.id}/complete`, {})
      }
      if (mode === 'cancel') {
        return api.post(`/interviews/${interview.id}/cancel`, {
          reason: reason || undefined,
          notify: notifyCandidate,
        })
      }
      return api.post(`/interviews/${interview.id}/reschedule`, {
        scheduled_start: new Date(start).toISOString(),
        duration_minutes: Number(duration),
        reason: reason || undefined,
        notify: notifyCandidate,
      })
    },
    onSuccess: () => {
      toast.success(
        mode === 'complete'
          ? 'Marked complete. Interviewers can now submit feedback.'
          : mode === 'cancel'
            ? 'Interview cancelled.'
            : 'Interview rescheduled.',
      )
      void queryClient.invalidateQueries({ queryKey: ['interviews'] })
      void queryClient.invalidateQueries({ queryKey: ['calendar'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'That action did not go through'),
  })

  const titles = {
    complete: 'Mark interview complete',
    cancel: 'Cancel interview',
    reschedule: 'Reschedule interview',
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={titles[mode]}
      description={`${interview.candidate_name ?? 'Candidate'} · ${formatDateTime(interview.scheduled_start)}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={mode === 'cancel' ? 'danger' : 'primary'}
            loading={action.isPending}
            onClick={() => action.mutate()}
          >
            {mode === 'complete' ? 'Mark complete' : mode === 'cancel' ? 'Cancel interview' : 'Reschedule'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {mode === 'reschedule' && (
          <>
            <Input
              label="New start time"
              type="datetime-local"
              required
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            <Select
              label="Duration"
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            >
              {[15, 30, 45, 60, 90, 120].map((minutes) => (
                <option key={minutes} value={minutes}>
                  {minutes} minutes
                </option>
              ))}
            </Select>
          </>
        )}

        {mode === 'complete' ? (
          <Notice tone="info">
            Completing an interview does not move the application on its own — a recruiter
            decides the next step once feedback is in.
          </Notice>
        ) : (
          <Textarea
            label="Reason"
            hint="Shown to the candidate if they are notified, and recorded in the timeline."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}

        {mode !== 'complete' && (
          <label className="flex items-center gap-2.5 text-sm text-ink-700">
            <input
              type="checkbox"
              checked={notifyCandidate}
              onChange={(e) => setNotifyCandidate(e.target.checked)}
              className="h-4 w-4 rounded border-ink-300 text-brand-600"
            />
            Notify the candidate by email
          </label>
        )}
      </div>
    </Modal>
  )
}

export default function RecruiterInterviewsPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <InterviewsContent />
    </Suspense>
  )
}

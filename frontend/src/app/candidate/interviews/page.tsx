'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck, CalendarDays, Clock, ExternalLink, MapPin, Video } from 'lucide-react'
import Link from 'next/link'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { formatDateTime, formatRelative, titleCase } from '@/lib/utils'

/** What the candidate portal returns — deliberately narrower than the recruiter view. */
interface MyInterview {
  id: string
  title: string
  job_title?: string | null
  round: string
  type: string
  scheduled_start: string
  duration_minutes: number
  timezone: string
  meeting_link?: string | null
  location?: string | null
  instructions?: string | null
  status: string
}

export default function CandidateInterviewsPage() {
  const queryClient = useQueryClient()

  const interviewsQuery = useQuery({
    queryKey: ['my-interviews'],
    queryFn: () => api.get<MyInterview[]>('/me/interviews'),
  })

  const confirm = useMutation({
    mutationFn: (interviewId: string) =>
      api.post(`/me/interviews/${interviewId}/confirm`),
    onSuccess: () => {
      toast.success('Attendance confirmed. The team has been notified.')
      void queryClient.invalidateQueries({ queryKey: ['my-interviews'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not confirm'),
  })

  const upcoming = (interviewsQuery.data ?? []).filter(
    (interview) => new Date(interview.scheduled_start) >= new Date(),
  )
  const past = (interviewsQuery.data ?? []).filter(
    (interview) => new Date(interview.scheduled_start) < new Date(),
  )

  return (
    <>
      <PageHeader
        title="Your interviews"
        description="Everything scheduled with you, and what you need to know for each."
      />

      <PageBody className="space-y-5">
        {interviewsQuery.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : interviewsQuery.isError ? (
          <Card>
            <ErrorState
              message={(interviewsQuery.error as Error).message}
              onRetry={() => interviewsQuery.refetch()}
            />
          </Card>
        ) : !interviewsQuery.data?.length ? (
          <Card>
            <EmptyState
              icon={CalendarDays}
              title="No interviews scheduled"
              description="When a company invites you to interview, the details appear here — including how to join and anything they would like you to prepare."
              action={
                <Link href="/candidate/applications">
                  <Button variant="secondary">View your applications</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <>
            {upcoming.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold text-ink-900">Coming up</h2>
                <div className="mt-3 space-y-3">
                  {upcoming.map((interview) => (
                    <InterviewCard
                      key={interview.id}
                      interview={interview}
                      onConfirm={() => confirm.mutate(interview.id)}
                      confirming={confirm.isPending && confirm.variables === interview.id}
                    />
                  ))}
                </div>
              </section>
            )}

            {past.length > 0 && (
              <section>
                <h2 className="text-sm font-semibold text-ink-900">Past</h2>
                <div className="mt-3 space-y-3">
                  {past.map((interview) => (
                    <InterviewCard key={interview.id} interview={interview} isPast />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </PageBody>
    </>
  )
}

function InterviewCard({
  interview,
  isPast,
  onConfirm,
  confirming,
}: {
  interview: MyInterview
  isPast?: boolean
  onConfirm?: () => void
  confirming?: boolean
}) {
  const needsConfirmation = interview.status === 'SCHEDULED' && !isPast

  return (
    <Card className={isPast ? 'p-5 opacity-70' : 'p-5'}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold text-ink-900">{interview.title}</h3>
            <Badge tone={interview.status === 'CONFIRMED' ? 'success' : 'info'}>
              {titleCase(interview.status)}
            </Badge>
            <Badge>{titleCase(interview.type)}</Badge>
          </div>

          {interview.job_title && (
            <p className="mt-1 text-sm text-ink-600">
              {interview.job_title} · {interview.round}
            </p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-700">
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-ink-400" />
              {formatDateTime(interview.scheduled_start)} · {interview.duration_minutes} min
            </span>
            <span className="text-ink-400">{interview.timezone}</span>
            {interview.location && (
              <span className="flex items-center gap-1.5">
                <MapPin className="h-3.5 w-3.5 text-ink-400" />
                {interview.location}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className="text-xs text-ink-400">
            {formatRelative(interview.scheduled_start)}
          </span>
          {interview.meeting_link && !isPast && (
            <a href={interview.meeting_link} target="_blank" rel="noreferrer">
              <Button size="sm">
                <Video className="h-3.5 w-3.5" />
                Join
                <ExternalLink className="h-3 w-3" />
              </Button>
            </a>
          )}
          {needsConfirmation && onConfirm && (
            <Button variant="secondary" size="sm" loading={confirming} onClick={onConfirm}>
              <CalendarCheck className="h-3.5 w-3.5" />
              Confirm attendance
            </Button>
          )}
        </div>
      </div>

      {interview.instructions && (
        <div className="mt-4 border-t border-ink-100 pt-3.5">
          <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
            How to prepare
          </h4>
          <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {interview.instructions}
          </p>
        </div>
      )}

      {needsConfirmation && (
        <div className="mt-4">
          <Notice tone="info">
            Please confirm you can make this time. If it does not work, reply to the
            invitation email — rescheduling is normal and holds nothing against you.
          </Notice>
        </div>
      )}
    </Card>
  )
}

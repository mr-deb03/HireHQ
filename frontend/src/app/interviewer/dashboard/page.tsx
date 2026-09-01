'use client'

/**
 * The interviewer's home.
 *
 * Scoped to what this person is actually part of: interviews they are on, and feedback
 * they still owe. It does not show the wider pipeline — an interviewer's judgement is
 * more useful when it is not anchored to a score or to what other people have already
 * concluded.
 */

import { useQuery } from '@tanstack/react-query'
import { CalendarDays, CheckCircle2, Clock, MessageSquare, Video } from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Badge, Button, Card, EmptyState, Skeleton, Stat } from '@/components/ui'
import { api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { InterviewSummary } from '@/lib/types'
import { formatDateTime, formatRelative, titleCase } from '@/lib/utils'

export default function InterviewerDashboardPage() {
  const { user } = useAuth()

  const pendingQuery = useQuery({
    queryKey: ['interviews', 'pending-feedback'],
    queryFn: () => api.get<InterviewSummary[]>('/interviews/pending-feedback'),
  })

  const upcomingQuery = useQuery({
    queryKey: ['interviews', 'upcoming'],
    queryFn: () =>
      api.get<Page<InterviewSummary>>('/interviews', {
        query: { upcoming: true, page_size: 10 },
      }),
  })

  const pending = pendingQuery.data ?? []
  const upcoming = upcomingQuery.data?.items ?? []
  const today = upcoming.filter(
    (interview) =>
      new Date(interview.scheduled_start).toDateString() === new Date().toDateString(),
  )

  return (
    <>
      <PageHeader
        title={`Hello, ${user?.first_name ?? 'there'}`}
        description="Your interviews and the feedback still outstanding."
      />

      <PageBody className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Today" value={today.length} icon={CalendarDays} />
          <Stat label="Upcoming" value={upcoming.length} icon={Clock} />
          <Stat
            label="Feedback owed"
            value={pending.length}
            tone={pending.length > 0 ? 'warning' : 'success'}
            icon={MessageSquare}
          />
        </div>

        {pending.length > 0 && (
          <section>
            <Notice tone="warning" title={`${pending.length} interview${pending.length === 1 ? '' : 's'} awaiting your feedback`}>
              An application cannot move past the interview stage until feedback is in.
              Writing it while the conversation is fresh gives the best record.
            </Notice>

            <div className="mt-3 space-y-3">
              {pending.map((interview) => (
                <InterviewRow key={interview.id} interview={interview} needsFeedback />
              ))}
            </div>
          </section>
        )}

        <section>
          <h2 className="text-sm font-semibold text-ink-900">Coming up</h2>
          {upcomingQuery.isLoading ? (
            <div className="mt-3 space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          ) : upcoming.length === 0 ? (
            <Card className="mt-3">
              <EmptyState
                icon={CalendarDays}
                title="Nothing scheduled"
                description="Interviews you are invited to will appear here, with the joining link and anything the recruiter wants you to focus on."
              />
            </Card>
          ) : (
            <div className="mt-3 space-y-3">
              {upcoming.map((interview) => (
                <InterviewRow key={interview.id} interview={interview} />
              ))}
            </div>
          )}
        </section>

        <Notice tone="neutral" title="Assessing fairly">
          Rate what the candidate actually demonstrated, and say what would change your
          mind. Your feedback is part of an auditable record and carries real weight in the
          decision — which is exactly why it should rest on evidence from the conversation.
        </Notice>
      </PageBody>
    </>
  )
}

function InterviewRow({
  interview,
  needsFeedback,
}: {
  interview: InterviewSummary
  needsFeedback?: boolean
}) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink-900">{interview.title}</h3>
            <Badge>{titleCase(interview.interview_type)}</Badge>
            {needsFeedback && <Badge tone="warning">Feedback due</Badge>}
          </div>
          <p className="mt-1 text-sm text-ink-600">
            {interview.candidate_name ?? 'Candidate'}
            {interview.job_title && <span className="text-ink-400"> · {interview.job_title}</span>}
          </p>
          <p className="mt-2 flex items-center gap-1.5 text-sm text-ink-600">
            <Clock className="h-3.5 w-3.5 text-ink-400" />
            {formatDateTime(interview.scheduled_start)} · {interview.duration_minutes} min
            <span className="text-ink-400">({formatRelative(interview.scheduled_start)})</span>
          </p>
        </div>

        <div className="flex shrink-0 gap-1.5">
          {interview.meeting_link && !needsFeedback && (
            <a href={interview.meeting_link} target="_blank" rel="noreferrer">
              <Button variant="secondary" size="sm">
                <Video className="h-3.5 w-3.5" />
                Join
              </Button>
            </a>
          )}
          <Link href={`/recruiter/interviews/${interview.id}`}>
            <Button variant={needsFeedback ? 'primary' : 'ghost'} size="sm">
              {needsFeedback ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Give feedback
                </>
              ) : (
                'Open'
              )}
            </Button>
          </Link>
        </div>
      </div>
    </Card>
  )
}

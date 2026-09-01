'use client'

/**
 * The hiring manager's home.
 *
 * Focused on decisions they own: candidates waiting on them, feedback they owe, and
 * offers pending approval — rather than the recruiter's full operational view.
 */

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Briefcase,
  CalendarDays,
  Gift,
  MessageSquare,
  Users,
} from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, EmptyState, Skeleton, Stat } from '@/components/ui'
import { api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { DashboardData, InterviewSummary, JobSummary, Offer } from '@/lib/types'
import { formatCurrency, formatDateTime, formatRelative, titleCase } from '@/lib/utils'

export default function HiringManagerDashboardPage() {
  const { user, can } = useAuth()

  const dashboardQuery = useQuery({
    queryKey: ['dashboard', 'hiring-manager'],
    queryFn: () => api.get<DashboardData>('/analytics/dashboard'),
  })

  const jobsQuery = useQuery({
    queryKey: ['jobs', 'mine'],
    queryFn: () =>
      api.get<Page<JobSummary>>('/jobs', {
        query: { status: 'PUBLISHED', page_size: 10, sort: '-created_at' },
      }),
  })

  const pendingFeedbackQuery = useQuery({
    queryKey: ['interviews', 'pending-feedback'],
    queryFn: () => api.get<InterviewSummary[]>('/interviews/pending-feedback'),
  })

  const offersQuery = useQuery({
    queryKey: ['offers', 'DRAFT'],
    queryFn: () =>
      api.get<Page<Offer>>('/offers', { query: { status: 'DRAFT', page_size: 10 } }),
    enabled: can('offer:approve'),
  })

  const kpis = dashboardQuery.data?.kpis
  const awaitingApproval = (offersQuery.data?.items ?? []).filter((offer) => !offer.approved_at)

  return (
    <>
      <PageHeader
        title={dashboardQuery.data?.greeting ?? `Hello, ${user?.first_name ?? 'there'}`}
        description="Where your input is needed."
        actions={
          <Link href="/recruiter/pipeline">
            <Button variant="secondary" size="sm">
              <Users className="h-4 w-4" />
              Pipeline
            </Button>
          </Link>
        }
      />

      <PageBody className="space-y-5">
        {dashboardQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : kpis ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Awaiting review"
              value={kpis.pending_review}
              tone={kpis.pending_review > 0 ? 'warning' : 'neutral'}
              icon={AlertCircle}
              href="/recruiter/pipeline"
            />
            <Stat
              label="Upcoming interviews"
              value={kpis.upcoming_interviews}
              icon={CalendarDays}
              href="/recruiter/interviews"
            />
            <Stat
              label="Feedback pending"
              value={kpis.pending_feedback}
              tone={kpis.pending_feedback > 0 ? 'warning' : 'success'}
              icon={MessageSquare}
              href="/recruiter/interviews?tab=pending-feedback"
            />
            <Stat
              label="Offers out"
              value={kpis.offers_awaiting_response}
              icon={Gift}
              href="/recruiter/offers?status=SENT"
            />
          </div>
        ) : null}

        {dashboardQuery.data && dashboardQuery.data.attention_required.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Needs your attention</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-2.5">
                {dashboardQuery.data.attention_required.map((item) => (
                  <li key={item.key}>
                    <Link
                      href={item.url}
                      className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-ink-50"
                    >
                      <span className="text-ink-700">
                        <span className="font-semibold tabular-nums text-ink-900">
                          {item.count}
                        </span>{' '}
                        {item.label}
                      </span>
                      <Badge
                        tone={
                          item.priority === 'high'
                            ? 'danger'
                            : item.priority === 'medium'
                              ? 'warning'
                              : 'neutral'
                        }
                      >
                        {titleCase(item.priority)}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        )}

        {can('offer:approve') && awaitingApproval.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Offers awaiting your approval</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-3">
                {awaitingApproval.map((offer) => (
                  <li key={offer.id} className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink-900">
                        {offer.position_title}
                      </p>
                      <p className="font-mono text-xs text-ink-400">{offer.reference_code}</p>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-sm font-semibold tabular-nums text-ink-900">
                        {formatCurrency(offer.total_compensation, offer.currency)}
                      </span>
                      <Link href="/recruiter/offers?status=DRAFT">
                        <Button variant="secondary" size="sm">
                          Review
                        </Button>
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs leading-relaxed text-ink-500">
                Approving records that you signed off on the compensation. The offer is sent
                separately, so you can approve and still hold it back.
              </p>
            </CardBody>
          </Card>
        )}

        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Feedback you owe</CardTitle>
            </CardHeader>
            <CardBody>
              {pendingFeedbackQuery.isLoading ? (
                <Skeleton className="h-24" />
              ) : !pendingFeedbackQuery.data?.length ? (
                <p className="text-sm text-ink-500">
                  Nothing outstanding — every interview you were on has feedback recorded.
                </p>
              ) : (
                <ul className="space-y-3">
                  {pendingFeedbackQuery.data.map((interview) => (
                    <li
                      key={interview.id}
                      className="flex flex-wrap items-center justify-between gap-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink-900">
                          {interview.candidate_name ?? 'Candidate'}
                        </p>
                        <p className="text-xs text-ink-500">
                          {interview.job_title} · {formatDateTime(interview.scheduled_start)}
                        </p>
                      </div>
                      <Link href={`/recruiter/interviews/${interview.id}`}>
                        <Button size="sm">Give feedback</Button>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Open roles</CardTitle>
            </CardHeader>
            <CardBody>
              {jobsQuery.isLoading ? (
                <Skeleton className="h-24" />
              ) : !jobsQuery.data?.items.length ? (
                <EmptyState
                  icon={Briefcase}
                  title="No published roles"
                  description="Roles you are hiring for appear here once they are live."
                />
              ) : (
                <ul className="space-y-2.5">
                  {jobsQuery.data.items.map((job) => (
                    <li key={job.id}>
                      <Link
                        href={`/recruiter/jobs/${job.id}`}
                        className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 transition-colors hover:bg-ink-50"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink-900">
                            {job.title}
                          </p>
                          <p className="text-xs text-ink-400">
                            {job.published_at
                              ? `Published ${formatRelative(job.published_at)}`
                              : 'Draft'}
                          </p>
                        </div>
                        <span className="shrink-0 text-sm tabular-nums text-ink-600">
                          {job.application_count} applicants
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>

        {dashboardQuery.data && dashboardQuery.data.todays_interviews.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Today&rsquo;s interviews</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-3">
                {dashboardQuery.data.todays_interviews.map((interview) => (
                  <li
                    key={interview.id}
                    className="flex flex-wrap items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink-900">
                        {interview.candidate_name ?? 'Candidate'}
                      </p>
                      <p className="text-xs text-ink-500">
                        {interview.time} · {titleCase(interview.interview_type)}
                      </p>
                    </div>
                    {interview.meeting_link && (
                      <a href={interview.meeting_link} target="_blank" rel="noreferrer">
                        <Button variant="secondary" size="sm">
                          Join
                        </Button>
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        )}

        <Notice tone="neutral">
          ATS scores rank candidates against the requirements you wrote — they are a
          starting point for review, not a decision. The final call on every hire is yours.
        </Notice>
      </PageBody>
    </>
  )
}

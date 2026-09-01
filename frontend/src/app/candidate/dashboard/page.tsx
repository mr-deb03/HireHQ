'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Briefcase,
  CalendarClock,
  ClipboardList,
  Gift,
  Search,
  UserCircle,
  Video,
} from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  Skeleton,
  Stat,
} from '@/components/ui'
import { api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { MyApplication } from '@/lib/types'
import { formatDateTime, formatRelative } from '@/lib/utils'

interface CandidateDashboard {
  applications: number
  in_progress: number
  upcoming_interviews: number
  pending_offers: number
  profile_completeness: number
}

interface MyInterview {
  id: string
  title: string
  job_title?: string | null
  round: string
  type: string
  scheduled_start: string
  timezone: string
  meeting_link?: string | null
  location?: string | null
  status: string
}

export default function CandidateDashboardPage() {
  const { user } = useAuth()

  const summaryQuery = useQuery({
    queryKey: ['candidate-dashboard'],
    queryFn: () => api.get<CandidateDashboard>('/me/dashboard'),
  })

  const applicationsQuery = useQuery({
    queryKey: ['my-applications', 'recent'],
    queryFn: () =>
      api.get<Page<MyApplication>>('/me/applications', { query: { page_size: 5 } }),
  })

  const interviewsQuery = useQuery({
    queryKey: ['my-interviews'],
    queryFn: () => api.get<MyInterview[]>('/me/interviews'),
  })

  const summary = summaryQuery.data

  return (
    <>
      <PageHeader
        title={`Hello, ${user?.first_name ?? 'there'}`}
        description="Your applications, interviews and offers in one place."
        actions={
          <Link href="/jobs">
            <Button>
              <Search className="h-4 w-4" />
              Find jobs
            </Button>
          </Link>
        }
      />

      <PageBody className="max-w-5xl space-y-6">
        {summaryQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Applications"
              value={summary?.applications ?? 0}
              icon={ClipboardList}
              href="/candidate/applications"
            />
            <Stat
              label="In progress"
              value={summary?.in_progress ?? 0}
              tone="brand"
              icon={Briefcase}
            />
            <Stat
              label="Upcoming interviews"
              value={summary?.upcoming_interviews ?? 0}
              tone={summary?.upcoming_interviews ? 'success' : 'neutral'}
              icon={CalendarClock}
            />
            <Stat
              label="Offers"
              value={summary?.pending_offers ?? 0}
              tone={summary?.pending_offers ? 'success' : 'neutral'}
              icon={Gift}
              href="/candidate/offers"
            />
          </div>
        )}

        {summary && summary.profile_completeness < 100 && (
          <Card className="border-brand-100 bg-brand-50/50">
            <CardBody className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-start gap-3">
                <UserCircle className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
                <div>
                  <p className="text-sm font-medium text-brand-800">
                    Your profile is {summary.profile_completeness}% complete
                  </p>
                  <p className="mt-0.5 text-sm text-brand-700">
                    A complete profile matches you to more roles.
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="h-1.5 w-32 overflow-hidden rounded-full bg-brand-100">
                  <div
                    className="h-full rounded-full bg-brand-600 transition-all"
                    style={{ width: `${summary.profile_completeness}%` }}
                  />
                </div>
                <Link href="/candidate/profile">
                  <Button size="sm" variant="secondary">
                    Complete it
                  </Button>
                </Link>
              </div>
            </CardBody>
          </Card>
        )}

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle>Recent applications</CardTitle>
              <Link
                href="/candidate/applications"
                className="text-xs font-medium text-brand-600 hover:text-brand-700"
              >
                View all
              </Link>
            </CardHeader>
            <CardBody className="p-0">
              {applicationsQuery.isLoading ? (
                <div className="space-y-2 p-5">
                  <Skeleton className="h-14" />
                  <Skeleton className="h-14" />
                </div>
              ) : !applicationsQuery.data?.items.length ? (
                <EmptyState
                  icon={ClipboardList}
                  title="No applications yet"
                  description="Browse open roles and apply to get started."
                  action={
                    <Link href="/jobs">
                      <Button size="sm">Browse jobs</Button>
                    </Link>
                  }
                />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {applicationsQuery.data.items.map((application) => (
                    <li key={application.id}>
                      <Link
                        href={`/candidate/applications/${application.id}`}
                        className="flex items-center justify-between gap-3 px-5 py-3.5 transition-colors hover:bg-ink-50"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink-900">
                            {application.job_title}
                          </p>
                          <p className="truncate text-xs text-ink-500">
                            {application.company_name} · applied{' '}
                            {formatRelative(application.applied_at)}
                          </p>
                        </div>
                        <Badge tone="neutral">{application.status_label}</Badge>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Upcoming interviews</CardTitle>
            </CardHeader>
            <CardBody className="p-0">
              {interviewsQuery.isLoading ? (
                <div className="space-y-2 p-5">
                  <Skeleton className="h-14" />
                </div>
              ) : !interviewsQuery.data?.length ? (
                <EmptyState
                  icon={CalendarClock}
                  title="No interviews scheduled"
                  description="You will be notified when one is booked."
                />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {interviewsQuery.data.map((interview) => (
                    <li key={interview.id} className="px-5 py-3.5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-ink-900">
                            {interview.job_title ?? interview.title}
                          </p>
                          <p className="text-xs text-ink-500">{interview.round}</p>
                          <p className="mt-1 text-xs font-medium text-ink-700">
                            {formatDateTime(interview.scheduled_start)} ({interview.timezone})
                          </p>
                        </div>
                        {interview.meeting_link && (
                          <a
                            href={interview.meeting_link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="shrink-0"
                          >
                            <Button size="sm" variant="secondary">
                              <Video className="h-3.5 w-3.5" />
                              Join
                            </Button>
                          </a>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>
      </PageBody>
    </>
  )
}

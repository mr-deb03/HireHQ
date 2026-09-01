'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CalendarClock, Gift, Video } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'

import { PageBody } from '@/components/app-shell'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  ErrorState,
  Skeleton,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { formatDate, formatDateTime, formatRelative } from '@/lib/utils'

interface MyApplicationDetail {
  id: string
  reference_code: string
  status_label: string
  job_title: string
  company_name?: string | null
  location?: string | null
  applied_at: string
  last_updated: string
  can_withdraw: boolean
  cover_letter?: string | null
  timeline: { title: string; description?: string | null; at: string }[]
  upcoming_interviews: {
    id: string
    title: string
    round: string
    type: string
    scheduled_start: string
    timezone: string
    meeting_link?: string | null
    instructions?: string | null
  }[]
  pending_assessments: { attempt_id: string; status: string; expires_at?: string | null }[]
  offer?: {
    id: string
    reference_code: string
    position_title: string
    status: string
    joining_date?: string | null
    expires_at?: string | null
  } | null
}

export default function MyApplicationDetailPage() {
  const params = useParams<{ id: string }>()
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['my-application', params.id],
    queryFn: () => api.get<MyApplicationDetail>(`/me/applications/${params.id}`),
    enabled: Boolean(params.id),
  })

  const withdrawMutation = useMutation({
    mutationFn: () => api.post(`/me/applications/${params.id}/withdraw`, {}),
    onSuccess: () => {
      toast.success('Application withdrawn')
      void queryClient.invalidateQueries({ queryKey: ['my-application', params.id] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not withdraw'),
  })

  if (query.isLoading) {
    return (
      <PageBody className="max-w-3xl">
        <Skeleton className="h-96" />
      </PageBody>
    )
  }

  if (query.isError || !query.data) {
    return (
      <PageBody className="max-w-3xl">
        <Card>
          <ErrorState title="Application not found" />
        </Card>
      </PageBody>
    )
  }

  const application = query.data

  return (
    <PageBody className="max-w-3xl space-y-6">
      <Link
        href="/candidate/applications"
        className="inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        All applications
      </Link>

      <Card>
        <CardBody>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-title font-semibold tracking-tight text-ink-900">
                {application.job_title}
              </h1>
              <p className="mt-1 text-ink-600">{application.company_name}</p>
              {application.location && (
                <p className="text-sm text-ink-500">{application.location}</p>
              )}
              <p className="mt-3 font-mono text-xs text-ink-400">{application.reference_code}</p>
            </div>
            <div className="text-right">
              <Badge tone="brand">{application.status_label}</Badge>
              <p className="mt-2 text-xs text-ink-400">
                Applied {formatRelative(application.applied_at)}
              </p>
            </div>
          </div>

          {application.can_withdraw && (
            <div className="mt-5 border-t border-ink-100 pt-4">
              <Button
                variant="ghost"
                size="sm"
                loading={withdrawMutation.isPending}
                onClick={() => {
                  if (window.confirm('Withdraw this application? This cannot be undone.')) {
                    withdrawMutation.mutate()
                  }
                }}
              >
                Withdraw application
              </Button>
            </div>
          )}
        </CardBody>
      </Card>

      {application.offer && (
        <Card className="border-success-100 bg-success-50">
          <CardBody className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <Gift className="mt-0.5 h-5 w-5 shrink-0 text-success-600" />
              <div>
                <p className="text-sm font-semibold text-success-800">
                  You have an offer for {application.offer.position_title}
                </p>
                <p className="mt-0.5 text-sm text-success-700">
                  {application.offer.joining_date &&
                    `Proposed start ${formatDate(application.offer.joining_date)}. `}
                  {application.offer.expires_at &&
                    `Respond by ${formatDate(application.offer.expires_at)}.`}
                </p>
              </div>
            </div>
            <Link href="/candidate/offers">
              <Button size="sm">View offer</Button>
            </Link>
          </CardBody>
        </Card>
      )}

      {application.upcoming_interviews.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Upcoming interviews</CardTitle>
          </CardHeader>
          <CardBody className="space-y-4">
            {application.upcoming_interviews.map((interview) => (
              <div
                key={interview.id}
                className="flex flex-wrap items-start justify-between gap-3"
              >
                <div>
                  <p className="text-sm font-medium text-ink-900">{interview.round}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-sm text-ink-600">
                    <CalendarClock className="h-3.5 w-3.5 text-ink-400" />
                    {formatDateTime(interview.scheduled_start)} ({interview.timezone})
                  </p>
                  {interview.instructions && (
                    <p className="mt-2 rounded-lg bg-ink-50 px-3 py-2 text-xs leading-relaxed text-ink-600">
                      {interview.instructions}
                    </p>
                  )}
                </div>
                {interview.meeting_link && (
                  <a href={interview.meeting_link} target="_blank" rel="noopener noreferrer">
                    <Button size="sm">
                      <Video className="h-3.5 w-3.5" />
                      Join
                    </Button>
                  </a>
                )}
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Progress</CardTitle>
        </CardHeader>
        <CardBody>
          {application.timeline.length === 0 ? (
            <p className="text-sm text-ink-500">No updates yet.</p>
          ) : (
            <ol className="relative space-y-5 border-l border-ink-200 pl-6">
              {application.timeline.map((event, index) => (
                <li key={index} className="relative">
                  <span className="absolute -left-[27px] top-1 h-2.5 w-2.5 rounded-full bg-brand-500 ring-4 ring-white" />
                  <p className="text-sm font-medium text-ink-900">{event.title}</p>
                  {event.description && (
                    <p className="mt-0.5 text-sm text-ink-600">{event.description}</p>
                  )}
                  <p className="mt-0.5 text-xs text-ink-400">{formatDateTime(event.at)}</p>
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>
    </PageBody>
  )
}

'use client'

import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  Briefcase,
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock,
  MapPin,
  Users,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { ApplyDialog } from '@/components/apply-dialog'
import { PublicFooter, PublicHeader } from '@/components/marketing'
import { Badge, Button, Card, ErrorState, Skeleton } from '@/components/ui'
import { api } from '@/lib/api'
import type { PublicJobDetail } from '@/lib/types'
import {
  EMPLOYMENT_TYPE_LABELS,
  WORK_MODE_LABELS,
  formatDate,
  formatRelative,
  formatSalaryRange,
} from '@/lib/utils'

function JobDetailContent() {
  const params = useParams<{ id: string }>()
  const search = useSearchParams()
  const source = search.get('source') ?? undefined
  const [applyOpen, setApplyOpen] = useState(false)

  const jobQuery = useQuery({
    queryKey: ['public-job', params.id, source],
    queryFn: () =>
      api.get<PublicJobDetail>(`/public/jobs/${params.id}`, {
        auth: false,
        query: { source },
      }),
    enabled: Boolean(params.id),
  })

  if (jobQuery.isLoading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-4 h-4 w-1/3" />
        <Skeleton className="mt-8 h-64 w-full" />
      </div>
    )
  }

  if (jobQuery.isError || !jobQuery.data) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6">
        <Card>
          <ErrorState
            title="This role is not available"
            message="It may have been closed or the link may be incorrect."
          />
          <div className="flex justify-center pb-8">
            <Link href="/jobs">
              <Button variant="secondary">Browse all jobs</Button>
            </Link>
          </div>
        </Card>
      </div>
    )
  }

  const job = jobQuery.data
  const deadlinePassed =
    job.application_deadline && new Date(job.application_deadline) < new Date()

  return (
    <>
      <div className="border-b border-ink-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
          <Link
            href="/jobs"
            className="inline-flex items-center gap-1.5 text-sm text-ink-500 transition-colors hover:text-ink-800"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All jobs
          </Link>

          <div className="mt-5 flex flex-col justify-between gap-6 sm:flex-row sm:items-start">
            <div className="min-w-0">
              <h1 className="text-title-lg font-semibold tracking-tight text-ink-900">
                {job.title}
              </h1>
              {job.company && (
                <p className="mt-1.5 flex items-center gap-2 text-ink-600">
                  <Building2 className="h-4 w-4 text-ink-400" />
                  {job.company.name}
                  {job.company.industry && (
                    <span className="text-ink-400">· {job.company.industry}</span>
                  )}
                </p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Badge tone="brand">{WORK_MODE_LABELS[job.work_mode] ?? job.work_mode}</Badge>
                <Badge tone="neutral">
                  {EMPLOYMENT_TYPE_LABELS[job.employment_type] ?? job.employment_type}
                </Badge>
                {job.openings > 1 && (
                  <Badge tone="info">
                    <Users className="h-3 w-3" />
                    {job.openings} openings
                  </Badge>
                )}
              </div>
            </div>

            <div className="shrink-0">
              {job.already_applied ? (
                <div className="text-right">
                  <Badge tone="success">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Applied
                  </Badge>
                  {job.existing_application_id && (
                    <Link
                      href={`/candidate/applications/${job.existing_application_id}`}
                      className="mt-2 block text-sm font-medium text-brand-600 hover:text-brand-700"
                    >
                      Track your application
                    </Link>
                  )}
                </div>
              ) : deadlinePassed ? (
                <Badge tone="danger">Applications closed</Badge>
              ) : (
                <Button size="lg" onClick={() => setApplyOpen(true)}>
                  Apply for this role
                </Button>
              )}
            </div>
          </div>

          <dl className="mt-6 grid gap-4 border-t border-ink-200 pt-5 sm:grid-cols-4">
            {[
              {
                icon: MapPin,
                label: 'Location',
                value: job.location_text ?? 'Not specified',
              },
              {
                icon: Briefcase,
                label: 'Experience',
                value:
                  job.min_experience_years === 0 && !job.max_experience_years
                    ? 'Any'
                    : `${job.min_experience_years}${job.max_experience_years ? `–${job.max_experience_years}` : '+'} years`,
              },
              {
                icon: CalendarDays,
                label: 'Salary',
                value: formatSalaryRange(job.salary_min, job.salary_max, job.salary_currency),
              },
              {
                icon: Clock,
                label: 'Posted',
                value: formatRelative(job.published_at),
              },
            ].map((item) => (
              <div key={item.label}>
                <dt className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-500">
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                </dt>
                <dd className="mt-1 text-sm font-medium text-ink-900">{item.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
          <div className="space-y-6">
            <Card className="p-6">
              <h2 className="text-sm font-semibold text-ink-900">About this role</h2>
              <div className="prose-sm mt-3 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
                {job.description}
              </div>
            </Card>

            {job.responsibilities.length > 0 && (
              <Card className="p-6">
                <h2 className="text-sm font-semibold text-ink-900">What you will do</h2>
                <ul className="mt-3 space-y-2">
                  {job.responsibilities.map((item) => (
                    <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-ink-700">
                      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-400" />
                      {item}
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {job.benefits.length > 0 && (
              <Card className="p-6">
                <h2 className="text-sm font-semibold text-ink-900">Benefits</h2>
                <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                  {job.benefits.map((item) => (
                    <li key={item} className="flex gap-2.5 text-sm text-ink-700">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success-500" />
                      {item}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          <aside className="space-y-4">
            {job.required_skills.length > 0 && (
              <Card className="p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Required skills
                </h3>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {job.required_skills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-brand-50 px-2 py-1 text-xs font-medium text-brand-700 ring-1 ring-inset ring-brand-100"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </Card>
            )}

            {job.preferred_skills.length > 0 && (
              <Card className="p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Nice to have
                </h3>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {job.preferred_skills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-ink-100 px-2 py-1 text-xs font-medium text-ink-600"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              </Card>
            )}

            {job.education_requirements.length > 0 && (
              <Card className="p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Education
                </h3>
                <ul className="mt-3 space-y-1.5">
                  {job.education_requirements.map((item) => (
                    <li key={item} className="text-sm text-ink-700">
                      {item}
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {job.application_deadline && (
              <Card className="p-5">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Apply by
                </h3>
                <p className="mt-2 text-sm font-medium text-ink-900">
                  {formatDate(job.application_deadline)}
                </p>
              </Card>
            )}

            {!job.already_applied && !deadlinePassed && (
              <Button size="lg" className="w-full" onClick={() => setApplyOpen(true)}>
                Apply for this role
              </Button>
            )}
          </aside>
        </div>
      </div>

      <ApplyDialog
        job={job}
        open={applyOpen}
        source={source}
        onClose={() => setApplyOpen(false)}
        onApplied={() => {
          setApplyOpen(false)
          void jobQuery.refetch()
        }}
      />
    </>
  )
}

export default function JobDetailPage() {
  return (
    <div className="flex min-h-full flex-col bg-ink-50">
      <PublicHeader />
      <main className="flex-1">
        <Suspense fallback={<div className="min-h-[60vh]" />}>
          <JobDetailContent />
        </Suspense>
      </main>
      <PublicFooter />
    </div>
  )
}

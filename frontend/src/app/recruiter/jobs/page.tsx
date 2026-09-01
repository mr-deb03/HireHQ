'use client'

import { useQuery } from '@tanstack/react-query'
import { Briefcase, MapPin, Plus, Search, Users } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Badge, Button, Card, EmptyState, ErrorState, Select, Skeleton } from '@/components/ui'
import { api, type Page as ApiPage } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { JobStatus, JobSummary } from '@/lib/types'
import {
  EMPLOYMENT_TYPE_LABELS,
  WORK_MODE_LABELS,
  formatRelative,
  formatSalaryRange,
} from '@/lib/utils'

const STATUS_TONES: Record<JobStatus, 'success' | 'neutral' | 'warning' | 'danger' | 'info'> = {
  PUBLISHED: 'success',
  DRAFT: 'neutral',
  PAUSED: 'warning',
  CLOSED: 'danger',
  ARCHIVED: 'neutral',
}

function JobsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const { can } = useAuth()

  const status = params.get('status') ?? ''
  const [search, setSearch] = useState(params.get('q') ?? '')
  const query = params.get('q') ?? ''
  const page = Number(params.get('page') ?? '1')

  const jobsQuery = useQuery({
    queryKey: ['jobs', query, status, page],
    queryFn: () =>
      api.get<ApiPage<JobSummary>>('/jobs', {
        query: {
          q: query || undefined,
          status: status || undefined,
          page,
          page_size: 20,
          sort: '-created_at',
        },
      }),
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/recruiter/jobs${next.toString() ? `?${next}` : ''}`)
  }

  return (
    <>
      <PageHeader
        title="Jobs"
        description={
          jobsQuery.data
            ? `${jobsQuery.data.meta.total_items} ${jobsQuery.data.meta.total_items === 1 ? 'job' : 'jobs'}`
            : undefined
        }
        actions={
          can('job:create') && (
            <Link href="/recruiter/jobs/create">
              <Button>
                <Plus className="h-4 w-4" />
                New job
              </Button>
            </Link>
          )
        }
      >
        <div className="mt-5 flex flex-wrap gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              setParam('q', search)
            }}
            className="relative min-w-64 flex-1"
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search jobs by title or reference"
              aria-label="Search jobs"
              className="input pl-9"
            />
          </form>
          <div className="w-44">
            <Select
              value={status}
              onChange={(e) => setParam('status', e.target.value)}
              aria-label="Filter by status"
            >
              <option value="">All statuses</option>
              {(['PUBLISHED', 'DRAFT', 'PAUSED', 'CLOSED', 'ARCHIVED'] as JobStatus[]).map((s) => (
                <option key={s} value={s}>
                  {s.charAt(0) + s.slice(1).toLowerCase()}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </PageHeader>

      <PageBody>
        {jobsQuery.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        ) : jobsQuery.isError ? (
          <Card>
            <ErrorState
              message={(jobsQuery.error as Error).message}
              onRetry={() => jobsQuery.refetch()}
            />
          </Card>
        ) : !jobsQuery.data?.items.length ? (
          <Card>
            <EmptyState
              icon={Briefcase}
              title={query || status ? 'No jobs match those filters' : 'No jobs yet'}
              description={
                query || status
                  ? 'Try a different search or clear the filters.'
                  : 'Create your first job to start receiving applications.'
              }
              action={
                can('job:create') && !query && !status ? (
                  <Link href="/recruiter/jobs/create">
                    <Button>
                      <Plus className="h-4 w-4" />
                      Create a job
                    </Button>
                  </Link>
                ) : (
                  <Button variant="secondary" onClick={() => router.push('/recruiter/jobs')}>
                    Clear filters
                  </Button>
                )
              }
            />
          </Card>
        ) : (
          <>
            <div className="space-y-3">
              {jobsQuery.data.items.map((job) => (
                <Link key={job.id} href={`/recruiter/jobs/${job.id}`}>
                  <Card interactive className="p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-[15px] font-semibold text-ink-900">{job.title}</h3>
                          <Badge tone={STATUS_TONES[job.status]}>
                            {job.status.charAt(0) + job.status.slice(1).toLowerCase()}
                          </Badge>
                          {job.is_internal_only && <Badge tone="info">Internal</Badge>}
                        </div>

                        <p className="mt-1 font-mono text-xs text-ink-400">
                          {job.reference_code}
                        </p>

                        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-600">
                          {job.location_text && (
                            <span className="flex items-center gap-1.5">
                              <MapPin className="h-3.5 w-3.5 text-ink-400" />
                              {job.location_text}
                            </span>
                          )}
                          <span>{WORK_MODE_LABELS[job.work_mode]}</span>
                          <span>{EMPLOYMENT_TYPE_LABELS[job.employment_type]}</span>
                          <span>
                            {formatSalaryRange(job.salary_min, job.salary_max, job.salary_currency)}
                          </span>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-6 text-right">
                        <div>
                          <p className="text-lg font-semibold tabular-nums text-ink-900">
                            {job.application_count}
                          </p>
                          <p className="text-xs text-ink-500">applications</p>
                        </div>
                        <div>
                          <p className="text-lg font-semibold tabular-nums text-ink-900">
                            {job.openings}
                          </p>
                          <p className="text-xs text-ink-500">
                            {job.openings === 1 ? 'opening' : 'openings'}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 flex items-center justify-between border-t border-ink-100 pt-3 text-xs text-ink-400">
                      <span>
                        {job.published_at
                          ? `Published ${formatRelative(job.published_at)}`
                          : `Created ${formatRelative(job.created_at)}`}
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Users className="h-3 w-3" />
                        {job.view_count} views
                      </span>
                    </div>
                  </Card>
                </Link>
              ))}
            </div>

            {jobsQuery.data.meta.total_pages > 1 && (
              <div className="mt-6 flex items-center justify-between">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!jobsQuery.data.meta.has_previous}
                  onClick={() => setParam('page', String(page - 1))}
                >
                  Previous
                </Button>
                <span className="text-sm text-ink-500">
                  Page {jobsQuery.data.meta.page} of {jobsQuery.data.meta.total_pages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!jobsQuery.data.meta.has_next}
                  onClick={() => setParam('page', String(page + 1))}
                >
                  Next
                </Button>
              </div>
            )}
          </>
        )}
      </PageBody>
    </>
  )
}

export default function RecruiterJobsPage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <JobsContent />
    </Suspense>
  )
}

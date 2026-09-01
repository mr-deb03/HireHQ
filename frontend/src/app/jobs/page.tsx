'use client'

import { useQuery } from '@tanstack/react-query'
import { Briefcase, Building2, Clock, MapPin, Search, SlidersHorizontal, X } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useMemo, useState } from 'react'

import { PublicFooter, PublicHeader } from '@/components/marketing'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { api, type Page } from '@/lib/api'
import type { PublicJob } from '@/lib/types'
import {
  EMPLOYMENT_TYPE_LABELS,
  WORK_MODE_LABELS,
  formatRelative,
  formatSalaryRange,
} from '@/lib/utils'

interface PortalFilters {
  locations: { value: string; count: number }[]
  skills: { value: string; count: number }[]
  industries: { value: string; count: number }[]
  work_modes: string[]
  employment_types: string[]
  experience_bands: { label: string; min: number; max: number | null }[]
}

function JobCard({ job }: { job: PublicJob }) {
  return (
    <Link href={`/jobs/${job.id}`} className="block">
      <Card interactive className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-semibold text-ink-900">{job.title}</h3>
            {job.company && (
              <p className="mt-0.5 flex items-center gap-1.5 text-sm text-ink-600">
                <Building2 className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                <span className="truncate">{job.company.name}</span>
              </p>
            )}
          </div>
          <Badge tone="neutral">{WORK_MODE_LABELS[job.work_mode] ?? job.work_mode}</Badge>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-600">
          {job.location_text && (
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 text-ink-400" />
              {job.location_text}
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <Briefcase className="h-3.5 w-3.5 text-ink-400" />
            {job.min_experience_years === 0 && !job.max_experience_years
              ? 'Any experience'
              : `${job.min_experience_years}${job.max_experience_years ? `–${job.max_experience_years}` : '+'} yrs`}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-ink-400" />
            {formatRelative(job.published_at)}
          </span>
        </div>

        {job.required_skills.length > 0 && (
          <div className="mt-3.5 flex flex-wrap gap-1.5">
            {job.required_skills.slice(0, 6).map((skill) => (
              <span
                key={skill}
                className="rounded-md bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-600"
              >
                {skill}
              </span>
            ))}
            {job.required_skills.length > 6 && (
              <span className="px-1 py-0.5 text-xs text-ink-400">
                +{job.required_skills.length - 6}
              </span>
            )}
          </div>
        )}

        <div className="mt-4 flex items-center justify-between gap-3 border-t border-ink-100 pt-3.5">
          <span className="text-sm font-medium text-ink-900">
            {formatSalaryRange(job.salary_min, job.salary_max, job.salary_currency)}
          </span>
          <span className="text-xs text-ink-500">
            {EMPLOYMENT_TYPE_LABELS[job.employment_type] ?? job.employment_type}
          </span>
        </div>
      </Card>
    </Link>
  )
}

function JobsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const [showFilters, setShowFilters] = useState(false)

  const query = params.get('q') ?? ''
  const location = params.get('location') ?? ''
  const workMode = params.getAll('work_mode')
  const employmentType = params.getAll('employment_type')
  const skills = params.getAll('skills')
  const minExperience = params.get('min_experience') ?? ''
  const page = Number(params.get('page') ?? '1')

  const [searchInput, setSearchInput] = useState(query)

  const setParam = useCallback(
    (updates: Record<string, string | string[] | null>) => {
      const next = new URLSearchParams(params.toString())
      for (const [key, value] of Object.entries(updates)) {
        next.delete(key)
        if (Array.isArray(value)) value.forEach((v) => next.append(key, v))
        else if (value) next.set(key, value)
      }
      // Any filter change invalidates the current page number.
      if (!('page' in updates)) next.delete('page')
      router.push(`/jobs${next.toString() ? `?${next}` : ''}`)
    },
    [params, router],
  )

  const jobsQuery = useQuery({
    queryKey: ['public-jobs', query, location, workMode, employmentType, skills, minExperience, page],
    queryFn: () =>
      api.get<Page<PublicJob>>('/public/jobs', {
        auth: false,
        query: {
          q: query || undefined,
          location: location || undefined,
          work_mode: workMode.length ? workMode : undefined,
          employment_type: employmentType.length ? employmentType : undefined,
          skills: skills.length ? skills : undefined,
          min_experience: minExperience || undefined,
          page,
          page_size: 12,
        },
      }),
  })

  const filtersQuery = useQuery({
    queryKey: ['portal-filters'],
    queryFn: () => api.get<PortalFilters>('/public/filters', { auth: false }),
    staleTime: 10 * 60_000,
  })

  const activeFilterCount = useMemo(
    () =>
      workMode.length + employmentType.length + skills.length + (minExperience ? 1 : 0) +
      (location ? 1 : 0),
    [workMode, employmentType, skills, minExperience, location],
  )

  function toggle(key: string, value: string, current: string[]) {
    setParam({
      [key]: current.includes(value) ? current.filter((v) => v !== value) : [...current, value],
    })
  }

  const filterPanel = (
    <div className="space-y-6">
      {activeFilterCount > 0 && (
        <button
          onClick={() => router.push('/jobs')}
          className="flex w-full items-center justify-between rounded-lg bg-ink-100 px-3 py-2 text-xs font-medium text-ink-700 hover:bg-ink-200"
        >
          Clear all filters
          <X className="h-3.5 w-3.5" />
        </button>
      )}

      <div>
        <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
          Work mode
        </h4>
        <div className="space-y-1.5">
          {(filtersQuery.data?.work_modes ?? ['REMOTE', 'HYBRID', 'ONSITE']).map((mode) => (
            <label key={mode} className="flex cursor-pointer items-center gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={workMode.includes(mode)}
                onChange={() => toggle('work_mode', mode, workMode)}
                className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="text-ink-700">{WORK_MODE_LABELS[mode] ?? mode}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
          Employment type
        </h4>
        <div className="space-y-1.5">
          {(filtersQuery.data?.employment_types ?? []).map((type) => (
            <label key={type} className="flex cursor-pointer items-center gap-2.5 text-sm">
              <input
                type="checkbox"
                checked={employmentType.includes(type)}
                onChange={() => toggle('employment_type', type, employmentType)}
                className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="text-ink-700">{EMPLOYMENT_TYPE_LABELS[type] ?? type}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
          Experience
        </h4>
        <div className="space-y-1.5">
          {(filtersQuery.data?.experience_bands ?? []).map((band) => (
            <label key={band.label} className="flex cursor-pointer items-center gap-2.5 text-sm">
              <input
                type="radio"
                name="experience"
                checked={minExperience === String(band.min)}
                onChange={() => setParam({ min_experience: String(band.min) })}
                className="h-4 w-4 border-ink-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="text-ink-700">{band.label}</span>
            </label>
          ))}
        </div>
      </div>

      {(filtersQuery.data?.skills.length ?? 0) > 0 && (
        <div>
          <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
            Popular skills
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {filtersQuery.data!.skills.slice(0, 18).map((skill) => (
              <button
                key={skill.value}
                onClick={() => toggle('skills', skill.value, skills)}
                className={
                  skills.includes(skill.value)
                    ? 'rounded-md bg-brand-600 px-2 py-1 text-xs font-medium text-white'
                    : 'rounded-md bg-ink-100 px-2 py-1 text-xs font-medium text-ink-600 hover:bg-ink-200'
                }
              >
                {skill.value}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )

  return (
    <div className="flex min-h-full flex-col bg-ink-50">
      <PublicHeader />

      <main className="flex-1">
        <div className="border-b border-ink-200 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
            <h1 className="text-title-lg font-semibold tracking-tight text-ink-900">
              Open roles
            </h1>
            <p className="mt-1.5 text-ink-600">
              {jobsQuery.data
                ? `${jobsQuery.data.meta.total_items} ${jobsQuery.data.meta.total_items === 1 ? 'role' : 'roles'} matching your search`
                : 'Find your next role'}
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                setParam({ q: searchInput || null })
              }}
              className="mt-5 flex gap-2"
            >
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
                <input
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Search by title, skill or company"
                  aria-label="Search jobs"
                  className="input pl-9"
                />
              </div>
              <Button type="submit">Search</Button>
              <Button
                type="button"
                variant="secondary"
                className="lg:hidden"
                onClick={() => setShowFilters((v) => !v)}
              >
                <SlidersHorizontal className="h-4 w-4" />
                {activeFilterCount > 0 && (
                  <span className="ml-1 rounded-full bg-brand-600 px-1.5 text-[10px] text-white">
                    {activeFilterCount}
                  </span>
                )}
              </Button>
            </form>
          </div>
        </div>

        <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
          <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
            <aside className={showFilters ? 'block' : 'hidden lg:block'}>
              <div className="card sticky top-24 p-5">{filterPanel}</div>
            </aside>

            <div>
              {jobsQuery.isLoading ? (
                <div className="grid gap-4 sm:grid-cols-2">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-52" />
                  ))}
                </div>
              ) : jobsQuery.isError ? (
                <Card>
                  <ErrorState
                    title="Could not load jobs"
                    message={(jobsQuery.error as Error).message}
                    onRetry={() => jobsQuery.refetch()}
                  />
                </Card>
              ) : jobsQuery.data && jobsQuery.data.items.length === 0 ? (
                <Card>
                  <EmptyState
                    icon={Search}
                    title="No roles match those filters"
                    description="Try removing a filter or searching for a different skill."
                    action={
                      <Button variant="secondary" onClick={() => router.push('/jobs')}>
                        Clear filters
                      </Button>
                    }
                  />
                </Card>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {jobsQuery.data?.items.map((job) => <JobCard key={job.id} job={job} />)}
                  </div>

                  {jobsQuery.data && jobsQuery.data.meta.total_pages > 1 && (
                    <div className="mt-8 flex items-center justify-between">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={!jobsQuery.data.meta.has_previous}
                        onClick={() => setParam({ page: String(page - 1) })}
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
                        onClick={() => setParam({ page: String(page + 1) })}
                      >
                        Next
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </main>

      <PublicFooter />
    </div>
  )
}

export default function JobsPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-ink-50" />}>
      <JobsContent />
    </Suspense>
  )
}

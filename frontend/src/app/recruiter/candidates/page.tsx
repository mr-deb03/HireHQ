'use client'

import { useQuery } from '@tanstack/react-query'
import { Filter, Search, Users } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { PageBody, PageHeader } from '@/components/app-shell'
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from '@/components/ui'
import { api, type Page as ApiPage } from '@/lib/api'
import type { CandidateSummary } from '@/lib/types'
import { formatExperience, formatNoticePeriod, formatRelative } from '@/lib/utils'

function CandidatesContent() {
  const router = useRouter()
  const params = useSearchParams()

  const query = params.get('q') ?? ''
  const minScore = params.get('min_ats_score') ?? ''
  const minExperience = params.get('min_experience') ?? ''
  const skillsParam = params.getAll('skills')
  const page = Number(params.get('page') ?? '1')

  const [search, setSearch] = useState(query)
  const [showFilters, setShowFilters] = useState(
    Boolean(minScore || minExperience || skillsParam.length),
  )
  const [filterDraft, setFilterDraft] = useState({
    min_ats_score: minScore,
    min_experience: minExperience,
    skills: skillsParam.join(', '),
  })

  const candidatesQuery = useQuery({
    queryKey: ['candidates', query, minScore, minExperience, skillsParam, page],
    queryFn: () =>
      api.get<ApiPage<CandidateSummary>>('/candidates', {
        query: {
          q: query || undefined,
          min_ats_score: minScore || undefined,
          min_experience: minExperience || undefined,
          skills: skillsParam.length ? skillsParam : undefined,
          page,
          page_size: 20,
        },
      }),
  })

  function apply(updates: Record<string, string | string[] | null>) {
    const next = new URLSearchParams(params.toString())
    for (const [key, value] of Object.entries(updates)) {
      next.delete(key)
      if (Array.isArray(value)) value.forEach((v) => v && next.append(key, v))
      else if (value) next.set(key, value)
    }
    if (!('page' in updates)) next.delete('page')
    router.push(`/recruiter/candidates${next.toString() ? `?${next}` : ''}`)
  }

  return (
    <>
      <PageHeader
        title="Candidates"
        description={
          candidatesQuery.data
            ? `${candidatesQuery.data.meta.total_items} in your talent database`
            : undefined
        }
      >
        <div className="mt-5 flex flex-wrap gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              apply({ q: search })
            }}
            className="relative min-w-64 flex-1"
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, email, phone or title"
              aria-label="Search candidates"
              className="input pl-9"
            />
          </form>
          <Button variant="secondary" onClick={() => setShowFilters((v) => !v)}>
            <Filter className="h-4 w-4" />
            Filters
          </Button>
        </div>

        {showFilters && (
          <div className="mt-4 grid animate-slide-up gap-3 rounded-xl border border-ink-200 bg-ink-50 p-4 sm:grid-cols-4">
            <Input
              label="Minimum ATS score"
              type="number"
              min={0}
              max={100}
              value={filterDraft.min_ats_score}
              onChange={(e) =>
                setFilterDraft({ ...filterDraft, min_ats_score: e.target.value })
              }
            />
            <Input
              label="Minimum experience"
              type="number"
              min={0}
              value={filterDraft.min_experience}
              onChange={(e) =>
                setFilterDraft({ ...filterDraft, min_experience: e.target.value })
              }
            />
            <Input
              label="Skills (comma separated)"
              value={filterDraft.skills}
              onChange={(e) => setFilterDraft({ ...filterDraft, skills: e.target.value })}
              placeholder="React, TypeScript"
              hint="All listed skills must be present"
            />
            <div className="flex items-end gap-2">
              <Button
                className="flex-1"
                onClick={() =>
                  apply({
                    min_ats_score: filterDraft.min_ats_score || null,
                    min_experience: filterDraft.min_experience || null,
                    skills: filterDraft.skills
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              >
                Apply
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setFilterDraft({ min_ats_score: '', min_experience: '', skills: '' })
                  router.push('/recruiter/candidates')
                }}
              >
                Clear
              </Button>
            </div>
          </div>
        )}
      </PageHeader>

      <PageBody>
        {candidatesQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : candidatesQuery.isError ? (
          <Card>
            <ErrorState
              message={(candidatesQuery.error as Error).message}
              onRetry={() => candidatesQuery.refetch()}
            />
          </Card>
        ) : !candidatesQuery.data?.items.length ? (
          <Card>
            <EmptyState
              icon={Users}
              title="No candidates match"
              description="Adjust your search or filters to widen the results."
            />
          </Card>
        ) : (
          <>
            <Card className="overflow-hidden">
              <ul className="divide-y divide-ink-100">
                {candidatesQuery.data.items.map((candidate) => (
                  <li key={candidate.id}>
                    <Link
                      href={`/recruiter/candidates/${candidate.id}`}
                      className="flex items-center gap-4 px-5 py-4 transition-colors hover:bg-ink-50"
                    >
                      <Avatar name={candidate.full_name} src={candidate.photo_url} />

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="truncate text-sm font-medium text-ink-900">
                            {candidate.full_name}
                          </p>
                          {candidate.email_verified && <Badge tone="success">Verified</Badge>}
                          {candidate.is_internal_employee && <Badge tone="info">Internal</Badge>}
                        </div>
                        <p className="truncate text-sm text-ink-600">
                          {candidate.current_designation ?? 'No title'}
                          {candidate.current_company && ` · ${candidate.current_company}`}
                        </p>
                        {candidate.skills.length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {candidate.skills.slice(0, 5).map((skill) => (
                              <span
                                key={skill.id}
                                className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                              >
                                {skill.name}
                              </span>
                            ))}
                            {candidate.skills.length > 5 && (
                              <span className="px-1 text-[10px] text-ink-400">
                                +{candidate.skills.length - 5}
                              </span>
                            )}
                          </div>
                        )}
                      </div>

                      <dl className="hidden shrink-0 gap-6 text-right sm:flex">
                        <div>
                          <dt className="text-[10px] uppercase text-ink-400">Experience</dt>
                          <dd className="text-sm font-medium text-ink-900">
                            {formatExperience(candidate.total_experience_years)}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-[10px] uppercase text-ink-400">Notice</dt>
                          <dd className="text-sm font-medium text-ink-900">
                            {formatNoticePeriod(candidate.notice_period_days)}
                          </dd>
                        </div>
                        <div className="w-24">
                          <dt className="text-[10px] uppercase text-ink-400">Added</dt>
                          <dd className="text-sm font-medium text-ink-900">
                            {formatRelative(candidate.created_at)}
                          </dd>
                        </div>
                      </dl>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>

            {candidatesQuery.data.meta.total_pages > 1 && (
              <div className="mt-6 flex items-center justify-between">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!candidatesQuery.data.meta.has_previous}
                  onClick={() => apply({ page: String(page - 1) })}
                >
                  Previous
                </Button>
                <span className="text-sm text-ink-500">
                  Page {candidatesQuery.data.meta.page} of{' '}
                  {candidatesQuery.data.meta.total_pages}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!candidatesQuery.data.meta.has_next}
                  onClick={() => apply({ page: String(page + 1) })}
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

export default function CandidatesPage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <CandidatesContent />
    </Suspense>
  )
}

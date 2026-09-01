'use client'

/**
 * Ranked applicants for one job.
 *
 * The ranking is presented as a *decision aid*, never a verdict: every row links through
 * to the full explanation, the disclaimer is always on screen, and there is no bulk
 * "reject below N" action — §63 forbids rejecting anyone on an opaque score alone.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, RefreshCw, ShieldAlert, Users } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { DataTable, EmptyRows, Notice, type Column } from '@/components/data'
import { Badge, Button, Card, CardBody, Input, ScoreRing, Select, Skeleton } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { JobDetail, RankedCandidate } from '@/lib/types'
import { RECOMMENDATION_STYLES, STATUS_STYLES, cn, formatExperience } from '@/lib/utils'

interface RescoreResult {
  total: number
  scored: number
  failed: number
  message: string
}

export default function JobApplicationsPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const [minScore, setMinScore] = useState('')
  const [limit, setLimit] = useState('50')

  const jobQuery = useQuery({
    queryKey: ['job', id],
    queryFn: () => api.get<JobDetail>(`/jobs/${id}`),
  })

  const rankingQuery = useQuery({
    queryKey: ['ranking', id, minScore, limit],
    queryFn: () =>
      api.get<RankedCandidate[]>(`/ats/jobs/${id}/ranking`, {
        query: { limit: Number(limit), min_score: minScore || undefined },
      }),
  })

  const rescore = useMutation({
    mutationFn: () => api.post<RescoreResult>(`/ats/jobs/${id}/rescore`),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['ranking', id] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not rescore'),
  })

  const columns: Column<RankedCandidate>[] = [
    {
      key: 'rank',
      header: '#',
      width: '56px',
      render: (row) => (
        <span className="font-semibold tabular-nums text-ink-400">{row.rank}</span>
      ),
    },
    {
      key: 'candidate',
      header: 'Candidate',
      render: (row) => (
        <Link
          href={`/recruiter/candidates/${row.candidate_id}`}
          className="block hover:text-brand-700"
        >
          <span className="font-medium text-ink-900">{row.candidate_name}</span>
          {row.current_designation && (
            <span className="block text-xs text-ink-500">{row.current_designation}</span>
          )}
        </Link>
      ),
    },
    {
      key: 'experience',
      header: 'Experience',
      hideOnMobile: true,
      render: (row) => formatExperience(row.total_experience_years),
    },
    {
      key: 'score',
      header: 'ATS score',
      align: 'right',
      render: (row) => (
        <div className="flex items-center justify-end gap-3">
          {row.recommendation && (
            <span
              className={cn(
                'badge hidden sm:inline-flex',
                RECOMMENDATION_STYLES[row.recommendation].badge,
              )}
            >
              {RECOMMENDATION_STYLES[row.recommendation].label}
            </span>
          )}
          <ScoreRing score={row.ats_score} size={42} />
        </div>
      ),
    },
    {
      key: 'skills',
      header: 'Skill match',
      hideOnMobile: true,
      render: (row) => (
        <div className="max-w-xs">
          <div className="flex flex-wrap gap-1">
            {row.matched_skills.slice(0, 3).map((skill) => (
              <span
                key={skill}
                className="rounded bg-success-50 px-1.5 py-0.5 text-xs text-success-700"
              >
                {skill}
              </span>
            ))}
            {row.matched_skills.length > 3 && (
              <span className="text-xs text-ink-400">+{row.matched_skills.length - 3}</span>
            )}
          </div>
          {row.missing_skills.length > 0 && (
            <p className="mt-1 truncate text-xs text-ink-400">
              Missing: {row.missing_skills.slice(0, 3).join(', ')}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row) => (
        <span className={cn('badge', STATUS_STYLES[row.status].badge)}>
          {STATUS_STYLES[row.status].label}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (row) => (
        <Link href={`/recruiter/candidates/${row.candidate_id}?application=${row.application_id}`}>
          <Button variant="ghost" size="sm">
            Review
          </Button>
        </Link>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title={jobQuery.data ? `Applicants · ${jobQuery.data.title}` : 'Applicants'}
        description={
          rankingQuery.data
            ? `${rankingQuery.data.length} ranked by ATS score`
            : 'Ranked by ATS score'
        }
        actions={
          <>
            <Link href={`/recruiter/jobs/${id}`}>
              <Button variant="ghost" size="sm">
                <ArrowLeft className="h-4 w-4" />
                Back to job
              </Button>
            </Link>
            {can('ats:run') && (
              <Button
                variant="secondary"
                size="sm"
                loading={rescore.isPending}
                onClick={() => rescore.mutate()}
              >
                <RefreshCw className="h-4 w-4" />
                Rescore all
              </Button>
            )}
          </>
        }
      >
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="w-40">
            <Input
              label="Minimum score"
              type="number"
              min={0}
              max={100}
              placeholder="Any"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
            />
          </div>
          <div className="w-40">
            <Select label="Show" value={limit} onChange={(e) => setLimit(e.target.value)}>
              <option value="25">Top 25</option>
              <option value="50">Top 50</option>
              <option value="100">Top 100</option>
              <option value="500">All</option>
            </Select>
          </div>
        </div>
      </PageHeader>

      <PageBody className="space-y-5">
        <Notice tone="neutral" title="Scores support your judgement — they do not replace it">
          <span className="flex items-start gap-1.5">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Every score is explainable: open a candidate to see the five dimensions, their
            weights and the exact skills matched. Rankings reflect stated requirements only.
            No candidate is rejected automatically, and low-ranked applicants are worth a
            look — a résumé can under-represent someone.
          </span>
        </Notice>

        {jobQuery.isLoading ? (
          <Skeleton className="h-96" />
        ) : (
          <DataTable
            rows={rankingQuery.data}
            columns={columns}
            loading={rankingQuery.isLoading}
            error={rankingQuery.error as Error | null}
            onRetry={() => rankingQuery.refetch()}
            rowKey={(row) => row.application_id}
            empty={
              <EmptyRows
                icon={Users}
                title={minScore ? 'No applicants above that score' : 'No scored applicants yet'}
                description={
                  minScore
                    ? 'Lower the minimum score to see more of the pipeline.'
                    : 'Applications are scored automatically once a résumé has been parsed.'
                }
                action={
                  minScore ? (
                    <Button variant="secondary" onClick={() => setMinScore('')}>
                      Clear filter
                    </Button>
                  ) : undefined
                }
              />
            }
          />
        )}

        {rescore.isSuccess && rescore.data.failed > 0 && (
          <Card>
            <CardBody>
              <Badge tone="warning">
                {rescore.data.failed} of {rescore.data.total} could not be scored
              </Badge>
              <p className="mt-2 text-sm text-ink-600">
                Those applications usually have no parsed résumé yet. They stay in the
                pipeline and are shown without a score rather than being ranked last.
              </p>
            </CardBody>
          </Card>
        )}
      </PageBody>
    </>
  )
}

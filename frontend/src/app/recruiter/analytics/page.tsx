'use client'

import { useQuery } from '@tanstack/react-query'
import { BarChart3, TrendingDown } from 'lucide-react'
import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Field, FieldGrid, Notice } from '@/components/data'
import {
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  Skeleton,
  Stat,
  Tabs,
} from '@/components/ui'
import { api } from '@/lib/api'
import type {
  AtsBand,
  DropOffRow,
  FunnelReport,
  JobPerformanceReport,
  RecruiterRow,
  SourceReport,
  TimeToHireReport,
  VolumePoint,
} from '@/lib/types'
import { titleCase } from '@/lib/utils'

/**
 * Chart colours, defined once. Sequential bands read as a single ramp; the funnel is a
 * single hue so the eye compares heights rather than chasing colour.
 */
const BRAND = '#4f46e5'
const AXIS = '#9ca3af'
const GRID = '#e5e7eb'
const BAND_RAMP = ['#e0e7ff', '#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1', '#4f46e5', '#4338ca']

const TABS = [
  { id: 'funnel', label: 'Funnel' },
  { id: 'sources', label: 'Sources' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'quality', label: 'Score & speed' },
]

export default function AnalyticsPage() {
  const [tab, setTab] = useState('funnel')

  const funnelQuery = useQuery({
    queryKey: ['analytics', 'funnel'],
    queryFn: () => api.get<FunnelReport>('/analytics/funnel'),
  })

  const volumeQuery = useQuery({
    queryKey: ['analytics', 'volume'],
    queryFn: () => api.get<VolumePoint[]>('/analytics/applications-over-time', {
      query: { days: 30 },
    }),
  })

  return (
    <>
      <PageHeader title="Analytics" description="How your hiring is actually going.">
        <div className="mt-5">
          <Tabs tabs={TABS} active={tab} onChange={setTab} />
        </div>
      </PageHeader>

      <PageBody className="space-y-5">
        {funnelQuery.data && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Applications" value={funnelQuery.data.total_applications} />
            <Stat label="Hired" value={funnelQuery.data.total_hired} tone="success" />
            <Stat
              label="Overall conversion"
              value={`${funnelQuery.data.overall_conversion_pct}%`}
            />
            <Stat
              label="Last 30 days"
              value={(volumeQuery.data ?? []).reduce((sum, p) => sum + p.applications, 0)}
            />
          </div>
        )}

        {tab === 'funnel' && (
          <FunnelTab report={funnelQuery.data} loading={funnelQuery.isLoading} volume={volumeQuery.data} />
        )}
        {tab === 'sources' && <SourcesTab />}
        {tab === 'jobs' && <JobsTab />}
        {tab === 'quality' && <QualityTab />}
      </PageBody>
    </>
  )
}

function FunnelTab({
  report,
  loading,
  volume,
}: {
  report?: FunnelReport
  loading: boolean
  volume?: VolumePoint[]
}) {
  const dropOffQuery = useQuery({
    queryKey: ['analytics', 'drop-off'],
    queryFn: () => api.get<DropOffRow[]>('/analytics/drop-off'),
  })

  if (loading) return <Skeleton className="h-96" />
  if (!report) return null

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Recruitment funnel</CardTitle>
        </CardHeader>
        <CardBody>
          {report.total_applications === 0 ? (
            <EmptyState
              icon={BarChart3}
              title="No applications yet"
              description="Publish a job and the funnel fills in as people apply."
            />
          ) : (
            <>
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={report.stages} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                    <XAxis
                      dataKey="label"
                      tick={{ fontSize: 11, fill: AXIS }}
                      axisLine={{ stroke: GRID }}
                      tickLine={false}
                      interval={0}
                      angle={-25}
                      textAnchor="end"
                      height={60}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: AXIS }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(79,70,229,0.06)' }}
                      contentStyle={{
                        borderRadius: 12,
                        border: `1px solid ${GRID}`,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="count" fill={BRAND} radius={[4, 4, 0, 0]} name="Reached" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/*
                Cumulative, not exclusive: someone who reached Offer is counted at every
                earlier stage too, so a rejection later does not erase the fact that they
                got there. The label says so, because the alternative reading is a common
                and expensive misunderstanding of a funnel.
              */}
              <p className="mt-4 text-xs leading-relaxed text-ink-500">
                Each stage counts everyone who <em>reached</em> it, including candidates who
                later moved on or were rejected. Conversion is stage-to-stage.
              </p>

              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {report.stages.slice(1).map((stage) => (
                  <div key={stage.stage} className="rounded-xl border border-ink-200 px-3.5 py-2.5">
                    <p className="text-xs text-ink-500">{stage.label}</p>
                    <p className="mt-0.5 text-sm">
                      <span className="font-semibold tabular-nums text-ink-900">
                        {stage.count}
                      </span>
                      {stage.conversion_from_previous_pct != null && (
                        <span className="ml-2 text-ink-500">
                          {stage.conversion_from_previous_pct}% of previous
                        </span>
                      )}
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardBody>
      </Card>

      {volume && volume.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle>Applications over the last 30 days</CardTitle>
          </CardHeader>
          <CardBody>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={volume} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: AXIS }}
                    axisLine={{ stroke: GRID }}
                    tickLine={false}
                    tickFormatter={(value: string) => value.slice(5)}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: AXIS }}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, border: `1px solid ${GRID}`, fontSize: 12 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="applications"
                    stroke={BRAND}
                    strokeWidth={2}
                    dot={false}
                    name="Applications"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Where candidates leave</CardTitle>
        </CardHeader>
        <CardBody>
          {dropOffQuery.isLoading ? (
            <Skeleton className="h-24" />
          ) : !dropOffQuery.data?.length ? (
            <p className="text-sm text-ink-500">Nobody has left the process yet.</p>
          ) : (
            <ul className="space-y-2.5">
              {dropOffQuery.data.map((row) => (
                <li key={row.status} className="flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2 text-ink-700">
                    <TrendingDown className="h-3.5 w-3.5 text-ink-400" />
                    {row.label}
                  </span>
                  <span className="font-semibold tabular-nums text-ink-900">{row.count}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function SourcesTab() {
  const sourcesQuery = useQuery({
    queryKey: ['analytics', 'sources'],
    queryFn: () => api.get<SourceReport[]>('/analytics/sources'),
  })

  if (sourcesQuery.isLoading) return <Skeleton className="h-96" />
  if (!sourcesQuery.data?.length) {
    return (
      <Card>
        <EmptyState icon={BarChart3} title="No source data yet" />
      </Card>
    )
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Where your hires come from</CardTitle>
      </CardHeader>
      <div className="scroll-x">
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b border-ink-200 bg-ink-50/60">
              {['Source', 'Applications', 'Shortlisted', 'Interviewed', 'Offers', 'Hired', 'Hire rate', 'Avg. score'].map(
                (header, index) => (
                  <th
                    key={header}
                    scope="col"
                    className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500 ${
                      index === 0 ? 'text-left' : 'text-right'
                    }`}
                  >
                    {header}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {sourcesQuery.data.map((row) => (
              <tr key={row.source} className="border-b border-ink-100 last:border-0">
                <td className="px-4 py-3 font-medium text-ink-900">{row.label}</td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                  {row.applications}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                  {row.shortlisted}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                  {row.interviewed}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">{row.offers}</td>
                <td className="px-4 py-3 text-right font-semibold tabular-nums text-ink-900">
                  {row.hired}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                  {row.hire_rate_pct}%
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                  {row.average_ats_score ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <CardBody className="border-t border-ink-100">
        <p className="text-xs leading-relaxed text-ink-500">
          Counted from stage timestamps, not current status: someone who reached interview
          and was later rejected still counts as interviewed. Otherwise every channel would
          look worse than it is.
        </p>
      </CardBody>
    </Card>
  )
}

function JobsTab() {
  const jobsQuery = useQuery({
    queryKey: ['analytics', 'jobs'],
    queryFn: () => api.get<JobPerformanceReport>('/analytics/jobs'),
  })

  const recruitersQuery = useQuery({
    queryKey: ['analytics', 'recruiters'],
    queryFn: () => api.get<RecruiterRow[]>('/analytics/recruiters'),
  })

  if (jobsQuery.isLoading) return <Skeleton className="h-96" />

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Highest volume</CardTitle>
        </CardHeader>
        <CardBody>
          {!jobsQuery.data?.highest_volume.length ? (
            <p className="text-sm text-ink-500">No jobs with applications yet.</p>
          ) : (
            <ul className="space-y-3">
              {jobsQuery.data.highest_volume.map((job) => (
                <li key={job.job_id} className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-900">{job.title}</p>
                    <p className="font-mono text-xs text-ink-400">{job.reference_code}</p>
                  </div>
                  <div className="flex gap-5 text-sm tabular-nums">
                    <span className="text-ink-700">{job.applications} applied</span>
                    <span className="text-ink-700">{job.interviewed} interviewed</span>
                    <span className="font-semibold text-ink-900">{job.hired} hired</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Best interview conversion</CardTitle>
        </CardHeader>
        <CardBody>
          {!jobsQuery.data?.best_interview_conversion.length ? (
            <p className="text-sm text-ink-500">
              Needs at least three applications on a job before a rate means anything.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {jobsQuery.data.best_interview_conversion.map((job) => (
                <li key={job.job_id} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate text-ink-700">{job.title}</span>
                  <span className="font-semibold tabular-nums text-ink-900">
                    {job.interview_conversion_pct}%
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      {recruitersQuery.data && recruitersQuery.data.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>By recruiter</CardTitle>
          </CardHeader>
          <CardBody>
            <ul className="space-y-2.5">
              {recruitersQuery.data.map((row) => (
                <li
                  key={row.recruiter_id}
                  className="flex flex-wrap items-center justify-between gap-3 text-sm"
                >
                  <span className="text-ink-700">{row.name}</span>
                  <span className="flex gap-5 tabular-nums">
                    <span className="text-ink-600">{row.applications_assigned} assigned</span>
                    <span className="text-ink-600">{row.shortlisted} shortlisted</span>
                    <span className="font-semibold text-ink-900">{row.hired} hired</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-xs leading-relaxed text-ink-500">
              Volume reflects how work was distributed as much as how it was done. Read
              these alongside the roles each recruiter was given, not on their own.
            </p>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function QualityTab() {
  const distributionQuery = useQuery({
    queryKey: ['analytics', 'ats-distribution'],
    queryFn: () => api.get<AtsBand[]>('/analytics/ats-distribution'),
  })

  const timeQuery = useQuery({
    queryKey: ['analytics', 'time-to-hire'],
    queryFn: () => api.get<TimeToHireReport>('/analytics/time-to-hire'),
  })

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>ATS score distribution</CardTitle>
        </CardHeader>
        <CardBody>
          {distributionQuery.isLoading ? (
            <Skeleton className="h-56" />
          ) : !distributionQuery.data?.some((band) => band.count > 0) ? (
            <p className="text-sm text-ink-500">No scored applications yet.</p>
          ) : (
            <>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={distributionQuery.data}
                    margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
                    <XAxis
                      dataKey="band"
                      tick={{ fontSize: 11, fill: AXIS }}
                      axisLine={{ stroke: GRID }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: AXIS }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip
                      cursor={{ fill: 'rgba(79,70,229,0.06)' }}
                      contentStyle={{
                        borderRadius: 12,
                        border: `1px solid ${GRID}`,
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]} name="Applications">
                      {distributionQuery.data.map((band, index) => (
                        <Cell key={band.band} fill={BAND_RAMP[index] ?? BRAND} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-4 text-xs leading-relaxed text-ink-500">
                A distribution skewed low usually means the job description asks for more
                than the market offers, rather than that the applicants are weak.
              </p>
            </>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Time to hire</CardTitle>
        </CardHeader>
        <CardBody>
          {timeQuery.isLoading ? (
            <Skeleton className="h-56" />
          ) : !timeQuery.data || timeQuery.data.hires_measured === 0 ? (
            <Notice tone="neutral">
              {timeQuery.data?.note ??
                'No completed hires yet, so time-to-hire cannot be computed.'}
            </Notice>
          ) : (
            <>
              <FieldGrid columns={2}>
                <Field label="Average">{timeQuery.data.average_days_to_hire} days</Field>
                <Field label="Median">{timeQuery.data.median_days_to_hire} days</Field>
                <Field label="Fastest">{timeQuery.data.fastest_days} days</Field>
                <Field label="Slowest">{timeQuery.data.slowest_days} days</Field>
              </FieldGrid>

              {Object.keys(timeQuery.data.stage_durations_days).length > 0 && (
                <div className="mt-5 border-t border-ink-100 pt-4">
                  <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
                    Time in each stage
                  </h4>
                  <ul className="mt-2.5 space-y-2">
                    {Object.entries(timeQuery.data.stage_durations_days).map(([stage, days]) => (
                      <li key={stage} className="flex items-center justify-between text-sm">
                        <span className="text-ink-700">{titleCase(stage)}</span>
                        <span className="font-medium tabular-nums text-ink-900">{days} days</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <p className="mt-4 text-xs leading-relaxed text-ink-500">
                Measured across {timeQuery.data.hires_measured}{' '}
                {timeQuery.data.hires_measured === 1 ? 'hire' : 'hires'}. With a small
                number, one unusual case moves the average a lot — read the median first.
              </p>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

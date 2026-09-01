'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowRight,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  Gift,
  MessageSquareText,
  Plus,
  Sparkles,
  Users,
  Video,
} from 'lucide-react'
import Link from 'next/link'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { PageBody, PageHeader } from '@/components/app-shell'
import { LiveIndicator, LiveToast } from '@/components/data'
import { useRealtime } from '@/hooks/use-realtime'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Skeleton,
  Stat,
} from '@/components/ui'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { AiStatus, DashboardData } from '@/lib/types'
import { cn, titleCase } from '@/lib/utils'

const ATTENTION_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  new_applications: FileCheck2,
  strong_matches: Sparkles,
  pending_feedback: MessageSquareText,
  interviews_today: CalendarClock,
  offers_awaiting: Gift,
}

export default function RecruiterDashboard() {
  const { can } = useAuth()

  // Live events arrive as hints to refetch; the numbers themselves always come from the
  // permission-checked endpoint, so a stale stream costs freshness, never correctness.
  const { status: liveStatus, lastEvent } = useRealtime()

  const dashboard = useQuery({
    queryKey: ['dashboard', 'recruiter'],
    queryFn: () => api.get<DashboardData>('/analytics/dashboard'),
  })

  const aiStatus = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/ai/status'),
    staleTime: 5 * 60_000,
  })

  if (dashboard.isLoading) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <PageBody className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-72" />
        </PageBody>
      </>
    )
  }

  if (dashboard.isError) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <PageBody>
          <Card>
            <ErrorState
              message={(dashboard.error as Error).message}
              onRetry={() => dashboard.refetch()}
            />
          </Card>
        </PageBody>
      </>
    )
  }

  const data = dashboard.data!
  const funnelData = data.funnel.map((stage) => ({
    name: stage.label.replace(' ', '\n'),
    label: stage.label,
    count: stage.count,
    conversion: stage.conversion_from_previous_pct,
  }))

  return (
    <>
      <PageHeader
        title={data.greeting}
        description="Here is what needs your attention today."
        actions={
          <>
            <LiveIndicator status={liveStatus} />
            {can('ai:assistant:use') && (
              <Link href="/recruiter/assistant">
                <Button variant="secondary">
                  <Sparkles className="h-4 w-4" />
                  Ask HireHQ
                </Button>
              </Link>
            )}
            {can('job:create') && (
              <Link href="/recruiter/jobs/create">
                <Button>
                  <Plus className="h-4 w-4" />
                  New job
                </Button>
              </Link>
            )}
          </>
        }
      />

      <PageBody className="space-y-6">
        {/* ------------------------------------------------ attention list */}
        {data.attention_required.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.attention_required.map((item) => {
              const Icon = ATTENTION_ICONS[item.key] ?? AlertCircle
              return (
                <Link key={item.key} href={item.url}>
                  <Card
                    interactive
                    className={cn(
                      'flex items-center gap-3.5 p-4',
                      item.priority === 'high' && 'ring-1 ring-inset ring-warning-100',
                    )}
                  >
                    <span
                      className={cn(
                        'inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
                        item.priority === 'high'
                          ? 'bg-warning-50 text-warning-600'
                          : 'bg-ink-100 text-ink-500',
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-lg font-semibold tabular-nums text-ink-900">
                        {item.count}
                      </p>
                      <p className="truncate text-sm text-ink-600">{item.label}</p>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0 text-ink-300" />
                  </Card>
                </Link>
              )
            })}
          </div>
        )}

        {/* ------------------------------------------------------------ KPIs */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Active jobs"
            value={data.kpis.active_jobs}
            icon={Briefcase}
            href="/recruiter/jobs?status=PUBLISHED"
          />
          <Stat
            label="Applications"
            value={data.kpis.total_applications}
            change={`${data.kpis.new_applications_this_week} new this week`}
            icon={Users}
            href="/recruiter/pipeline"
          />
          <Stat
            label="Shortlisted"
            value={data.kpis.shortlisted}
            tone="brand"
            icon={CheckCircle2}
            href="/recruiter/pipeline?status=SHORTLISTED"
          />
          <Stat
            label="Hired"
            value={data.kpis.hired}
            tone="success"
            icon={Gift}
            href="/recruiter/pipeline?status=HIRED"
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          {/* ------------------------------------------------------ funnel */}
          <Card className="lg:col-span-2">
            <CardHeader className="flex items-center justify-between">
              <CardTitle>Recruitment funnel</CardTitle>
              <Link
                href="/recruiter/analytics"
                className="text-xs font-medium text-brand-600 hover:text-brand-700"
              >
                Full analytics
              </Link>
            </CardHeader>
            <CardBody>
              {funnelData.every((d) => d.count === 0) ? (
                <EmptyState
                  icon={Users}
                  title="No applications yet"
                  description="Publish a job to start receiving applications."
                />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={funnelData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e5e1" />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 11, fill: '#76766f' }}
                        axisLine={false}
                        tickLine={false}
                        interval={0}
                        angle={-20}
                        textAnchor="end"
                        height={58}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#76766f' }}
                        axisLine={false}
                        tickLine={false}
                        allowDecimals={false}
                      />
                      <RechartsTooltip
                        cursor={{ fill: '#f1f1ef' }}
                        contentStyle={{
                          borderRadius: 12,
                          border: '1px solid #e5e5e1',
                          fontSize: 12,
                          boxShadow: '0 12px 32px -8px rgb(16 16 14 / 0.16)',
                        }}
                        formatter={(value: number, _name, entry) => [
                          `${value} candidates${
                            entry.payload.conversion != null
                              ? ` · ${entry.payload.conversion}% from previous`
                              : ''
                          }`,
                          '',
                        ]}
                      />
                      <Bar dataKey="count" fill="#4f46e5" radius={[6, 6, 0, 0]} maxBarSize={54} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardBody>
          </Card>

          {/* -------------------------------------------- today's interviews */}
          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle>Today&apos;s interviews</CardTitle>
              <Badge tone={data.todays_interviews.length ? 'brand' : 'neutral'}>
                {data.todays_interviews.length}
              </Badge>
            </CardHeader>
            <CardBody className="p-0">
              {data.todays_interviews.length === 0 ? (
                <EmptyState
                  icon={CalendarClock}
                  title="No interviews today"
                  description="Your schedule is clear."
                />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {data.todays_interviews.map((interview) => (
                    <li key={interview.id} className="flex items-start gap-3 px-5 py-3.5">
                      <span className="w-14 shrink-0 text-sm font-semibold tabular-nums text-ink-900">
                        {interview.time}
                      </span>
                      <div className="min-w-0 flex-1">
                        <Link
                          href={`/recruiter/candidates/${interview.candidate_id}`}
                          className="block truncate text-sm font-medium text-ink-900 hover:text-brand-600"
                        >
                          {interview.candidate_name ?? 'Candidate'}
                        </Link>
                        <p className="truncate text-xs text-ink-500">
                          {titleCase(interview.interview_type)}
                        </p>
                      </div>
                      {interview.meeting_link && (
                        <a
                          href={interview.meeting_link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="shrink-0 rounded-lg p-1.5 text-brand-600 transition-colors hover:bg-brand-50"
                          aria-label="Join meeting"
                        >
                          <Video className="h-4 w-4" />
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        </div>

        {/* ------------------------------------------------ AI engine notice */}
        {aiStatus.data && !aiStatus.data.is_language_model && (
          <Card className="border-info-100 bg-info-50">
            <CardBody className="flex items-start gap-3">
              <Sparkles className="mt-0.5 h-4.5 w-4.5 shrink-0 text-info-600" />
              <div>
                <p className="text-sm font-medium text-info-700">
                  Running on the built-in engine
                </p>
                <p className="mt-1 text-sm leading-relaxed text-info-700/90">
                  {aiStatus.data.message}
                </p>
              </div>
            </CardBody>
          </Card>
        )}
      </PageBody>

      <LiveToast message={lastEvent?.label ?? null} />
    </>
  )
}

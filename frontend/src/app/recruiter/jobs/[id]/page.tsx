'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  BarChart3,
  Copy,
  ExternalLink,
  MapPin,
  Send,
  Sparkles,
  Users,
} from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Field, FieldGrid, Notice } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  ErrorState,
  Modal,
  Select,
  Skeleton,
  Tabs,
  Textarea,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { JobDetail, JobStats, JobStatus } from '@/lib/types'
import {
  EMPLOYMENT_TYPE_LABELS,
  WORK_MODE_LABELS,
  formatDate,
  formatRelative,
  formatSalaryRange,
  titleCase,
} from '@/lib/utils'

const STATUS_TONES: Record<JobStatus, 'success' | 'neutral' | 'warning' | 'danger'> = {
  PUBLISHED: 'success',
  DRAFT: 'neutral',
  PAUSED: 'warning',
  CLOSED: 'danger',
  ARCHIVED: 'neutral',
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const [tab, setTab] = useState('overview')
  const [statusOpen, setStatusOpen] = useState(false)

  const jobQuery = useQuery({
    queryKey: ['job', id],
    queryFn: () => api.get<JobDetail>(`/jobs/${id}`),
  })

  const statsQuery = useQuery({
    queryKey: ['job-stats', id],
    queryFn: () => api.get<JobStats>(`/jobs/${id}/stats`),
    enabled: Boolean(jobQuery.data),
  })

  const publish = useMutation({
    mutationFn: () => api.post<JobDetail>(`/jobs/${id}/publish`),
    onSuccess: () => {
      toast.success('Job published. It is now live on the careers page.')
      void queryClient.invalidateQueries({ queryKey: ['job', id] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Publish failed'),
  })

  const duplicate = useMutation({
    mutationFn: () => api.post<JobDetail>(`/jobs/${id}/duplicate`),
    onSuccess: (job) => {
      toast.success('Duplicated as a new draft.')
      router.push(`/recruiter/jobs/${job.id}`)
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not duplicate'),
  })

  if (jobQuery.isLoading) {
    return (
      <PageBody>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-4 h-64" />
      </PageBody>
    )
  }

  if (jobQuery.isError || !jobQuery.data) {
    return (
      <PageBody>
        <Card>
          <ErrorState
            title="Could not load this job"
            message={(jobQuery.error as Error)?.message}
            onRetry={() => jobQuery.refetch()}
          />
        </Card>
      </PageBody>
    )
  }

  const job = jobQuery.data
  const stats = statsQuery.data

  return (
    <>
      <PageHeader
        title={job.title}
        description={`${job.reference_code} · Created ${formatRelative(job.created_at)}`}
        actions={
          <>
            <Link href="/recruiter/jobs">
              <Button variant="ghost" size="sm">
                <ArrowLeft className="h-4 w-4" />
                All jobs
              </Button>
            </Link>
            {job.status === 'PUBLISHED' && (
              <Link href={`/jobs/${job.id}`} target="_blank">
                <Button variant="secondary" size="sm">
                  <ExternalLink className="h-4 w-4" />
                  View public page
                </Button>
              </Link>
            )}
            {can('job:create') && (
              <Button
                variant="secondary"
                size="sm"
                loading={duplicate.isPending}
                onClick={() => duplicate.mutate()}
              >
                <Copy className="h-4 w-4" />
                Duplicate
              </Button>
            )}
            {can('job:publish') && job.status === 'DRAFT' && (
              <Button size="sm" loading={publish.isPending} onClick={() => publish.mutate()}>
                <Send className="h-4 w-4" />
                Publish
              </Button>
            )}
            {can('job:update') && job.status !== 'DRAFT' && (
              <Button variant="secondary" size="sm" onClick={() => setStatusOpen(true)}>
                Change status
              </Button>
            )}
          </>
        }
      >
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink-600">
          <Badge tone={STATUS_TONES[job.status]}>{titleCase(job.status)}</Badge>
          {job.is_internal_only && <Badge tone="info">Internal only</Badge>}
          {job.location_text && (
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 text-ink-400" />
              {job.location_text}
            </span>
          )}
          <span>{WORK_MODE_LABELS[job.work_mode]}</span>
          <span>{EMPLOYMENT_TYPE_LABELS[job.employment_type]}</span>
          <span>{formatSalaryRange(job.salary_min, job.salary_max, job.salary_currency)}</span>
        </div>

        <div className="mt-5">
          <Tabs
            tabs={[
              { id: 'overview', label: 'Overview' },
              { id: 'requirements', label: 'Requirements', count: job.skills.length },
              {
                id: 'screening',
                label: 'Screening',
                count: job.screening_questions.length,
              },
              { id: 'performance', label: 'Performance' },
            ]}
            active={tab}
            onChange={setTab}
          />
        </div>
      </PageHeader>

      <PageBody className="space-y-5">
        {/* ------------------------------------------------------- headline */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Applications" value={job.application_count} />
          <StatCard label="Openings" value={job.openings} />
          <StatCard
            label="Average ATS score"
            value={stats?.average_ats_score != null ? `${stats.average_ats_score}%` : '—'}
          />
          <StatCard label="Page views" value={job.view_count} />
        </div>

        <div className="flex flex-wrap gap-2">
          <Link href={`/recruiter/jobs/${job.id}/applications`}>
            <Button variant="secondary" size="sm">
              <Users className="h-4 w-4" />
              Ranked applicants
            </Button>
          </Link>
          <Link href={`/recruiter/pipeline?job_id=${job.id}`}>
            <Button variant="secondary" size="sm">
              <BarChart3 className="h-4 w-4" />
              Pipeline board
            </Button>
          </Link>
        </div>

        {tab === 'overview' && <OverviewTab job={job} />}
        {tab === 'requirements' && <RequirementsTab job={job} />}
        {tab === 'screening' && <ScreeningTab job={job} />}
        {tab === 'performance' && (
          <PerformanceTab stats={stats} loading={statsQuery.isLoading} />
        )}
      </PageBody>

      <StatusModal
        jobId={job.id}
        current={job.status}
        open={statusOpen}
        onClose={() => setStatusOpen(false)}
      />
    </>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card px-4 py-3.5">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-ink-900">{value}</p>
    </div>
  )
}

function OverviewTab({ job }: { job: JobDetail }) {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Description</CardTitle>
        </CardHeader>
        <CardBody>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {job.description}
          </p>

          {job.responsibilities.length > 0 && (
            <>
              <h4 className="mt-6 text-sm font-semibold text-ink-900">Responsibilities</h4>
              <ul className="mt-2 space-y-1.5">
                {job.responsibilities.map((item, i) => (
                  <li key={i} className="flex gap-2 text-sm text-ink-700">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-400" />
                    {item}
                  </li>
                ))}
              </ul>
            </>
          )}

          {job.benefits.length > 0 && (
            <>
              <h4 className="mt-6 text-sm font-semibold text-ink-900">Benefits</h4>
              <ul className="mt-2 space-y-1.5">
                {job.benefits.map((item, i) => (
                  <li key={i} className="flex gap-2 text-sm text-ink-700">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-400" />
                    {item}
                  </li>
                ))}
              </ul>
            </>
          )}
        </CardBody>
      </Card>

      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>Details</CardTitle>
          </CardHeader>
          <CardBody>
            <FieldGrid columns={2}>
              <Field label="Experience">
                {job.min_experience_years}
                {job.max_experience_years ? `–${job.max_experience_years}` : '+'} yrs
              </Field>
              <Field label="Openings">{job.openings}</Field>
              <Field label="Published">
                {job.published_at ? formatDate(job.published_at) : 'Not published'}
              </Field>
              <Field label="Deadline">
                {job.application_deadline ? formatDate(job.application_deadline) : 'None'}
              </Field>
            </FieldGrid>
          </CardBody>
        </Card>

        {job.ai_analysis_confirmed_at && (
          <Notice tone="neutral" title="AI-assisted requirements">
            <span className="flex items-start gap-1.5">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              A person reviewed and confirmed the extracted requirements on{' '}
              {formatDate(job.ai_analysis_confirmed_at)}. The analysis is a suggestion; the
              requirements shown here are the ones that were approved.
            </span>
          </Notice>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Hiring team</CardTitle>
          </CardHeader>
          <CardBody>
            {job.hiring_team.length === 0 ? (
              <p className="text-sm text-ink-500">No one assigned yet.</p>
            ) : (
              <ul className="space-y-2">
                {job.hiring_team.map((member) => (
                  <li key={member.id} className="flex items-center justify-between text-sm">
                    <span className="text-ink-700">{member.user_id.slice(0, 8)}…</span>
                    <Badge>{titleCase(member.team_role)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function RequirementsTab({ job }: { job: JobDetail }) {
  const required = job.skills.filter((s) => s.importance === 'REQUIRED')
  const preferred = job.skills.filter((s) => s.importance !== 'REQUIRED')

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Skills</CardTitle>
        </CardHeader>
        <CardBody className="space-y-5">
          <SkillGroup
            title="Required"
            description="Weighted most heavily in the ATS skills score."
            skills={required}
          />
          <SkillGroup title="Preferred" skills={preferred} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Education & certifications</CardTitle>
        </CardHeader>
        <CardBody className="space-y-5">
          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
              Education
            </h4>
            {job.education_requirements.length === 0 ? (
              <p className="mt-1.5 text-sm text-ink-500">No specific requirement.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {job.education_requirements.map((item, i) => (
                  <li key={i} className="text-sm text-ink-700">
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">
              Certifications
            </h4>
            {job.certifications.length === 0 ? (
              <p className="mt-1.5 text-sm text-ink-500">None required.</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {job.certifications.map((item, i) => (
                  <li key={i} className="text-sm text-ink-700">
                    {item}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  )
}

function SkillGroup({
  title,
  description,
  skills,
}: {
  title: string
  description?: string
  skills: JobDetail['skills']
}) {
  return (
    <div>
      <h4 className="text-xs font-medium uppercase tracking-wide text-ink-400">{title}</h4>
      {description && <p className="mt-0.5 text-xs text-ink-500">{description}</p>}
      {skills.length === 0 ? (
        <p className="mt-2 text-sm text-ink-500">None listed.</p>
      ) : (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {skills.map((skill) => (
            <span
              key={skill.id}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink-100 px-2.5 py-1 text-sm text-ink-700"
            >
              {skill.name}
              {skill.weight !== undefined && skill.weight > 1 && (
                <span className="text-xs text-ink-400">×{skill.weight}</span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function ScreeningTab({ job }: { job: JobDetail }) {
  if (job.screening_questions.length === 0) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-ink-500">
            No screening questions. Applicants go straight to the resume step.
          </p>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Screening questions</CardTitle>
      </CardHeader>
      <CardBody>
        <ol className="space-y-4">
          {job.screening_questions.map((question, index) => (
            <li key={question.id} className="border-b border-ink-100 pb-4 last:border-0 last:pb-0">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="text-sm font-medium text-ink-900">
                  <span className="mr-2 text-ink-400">{index + 1}.</span>
                  {question.question}
                </p>
                <div className="flex shrink-0 gap-1.5">
                  <Badge>{titleCase(question.question_type)}</Badge>
                  {question.is_required && <Badge tone="info">Required</Badge>}
                  {question.is_knockout && <Badge tone="warning">Knockout</Badge>}
                </div>
              </div>
              {question.options.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {question.options.map((option) => (
                    <span
                      key={option}
                      className="rounded bg-ink-100 px-2 py-0.5 text-xs text-ink-600"
                    >
                      {option}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ol>

        {job.screening_questions.some((q) => q.is_knockout) && (
          <div className="mt-5">
            <Notice tone="warning" title="Knockout questions are in use">
              A knockout answer marks the application for review — it does not reject
              anyone automatically. A recruiter still makes the decision.
            </Notice>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function PerformanceTab({ stats, loading }: { stats?: JobStats; loading: boolean }) {
  if (loading) return <Skeleton className="h-64" />
  if (!stats) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-ink-500">No performance data available yet.</p>
        </CardBody>
      </Card>
    )
  }

  const funnel = Object.entries(stats.funnel)
  const max = Math.max(1, ...funnel.map(([, count]) => count))

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Funnel</CardTitle>
        </CardHeader>
        <CardBody>
          {funnel.length === 0 ? (
            <p className="text-sm text-ink-500">No applications yet.</p>
          ) : (
            <div className="space-y-3">
              {funnel.map(([stage, count]) => (
                <div key={stage}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="text-ink-700">{titleCase(stage)}</span>
                    <span className="font-semibold tabular-nums text-ink-900">{count}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-100">
                    <div
                      className="h-full rounded-full bg-brand-500 transition-all duration-700"
                      style={{ width: `${(count / max) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sources</CardTitle>
        </CardHeader>
        <CardBody>
          {Object.keys(stats.top_sources).length === 0 ? (
            <p className="text-sm text-ink-500">No applications yet.</p>
          ) : (
            <dl className="space-y-2.5">
              {Object.entries(stats.top_sources).map(([source, count]) => (
                <div key={source} className="flex items-center justify-between text-sm">
                  <dt className="text-ink-700">{titleCase(source)}</dt>
                  <dd className="font-semibold tabular-nums text-ink-900">{count}</dd>
                </div>
              ))}
            </dl>
          )}

          <div className="mt-5 grid grid-cols-2 gap-4 border-t border-ink-100 pt-4">
            <Field label="Interviews scheduled">{stats.interviews_scheduled}</Field>
            <Field label="Offers extended">{stats.offers_extended}</Field>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}

function StatusModal({
  jobId,
  current,
  open,
  onClose,
}: {
  jobId: string
  current: JobStatus
  open: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<JobStatus>(current)
  const [reason, setReason] = useState('')

  const change = useMutation({
    mutationFn: () => api.post(`/jobs/${jobId}/status`, { status, reason: reason || undefined }),
    onSuccess: () => {
      toast.success(`Job is now ${titleCase(status).toLowerCase()}.`)
      void queryClient.invalidateQueries({ queryKey: ['job', jobId] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not change the status'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change job status"
      description="Closing a job stops new applications; applicants already in the pipeline are unaffected."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={change.isPending} onClick={() => change.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value as JobStatus)}
        >
          {(['PUBLISHED', 'PAUSED', 'CLOSED', 'ARCHIVED'] as JobStatus[]).map((value) => (
            <option key={value} value={value}>
              {titleCase(value)}
            </option>
          ))}
        </Select>
        <Textarea
          label="Reason"
          hint="Recorded in the audit log."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
    </Modal>
  )
}

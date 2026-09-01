'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  Brain,
  Briefcase,
  CheckCircle2,
  ExternalLink,
  Github,
  GraduationCap,
  Linkedin,
  Mail,
  MapPin,
  Phone,
  Plus,
  ShieldCheck,
  Sparkles,
  XCircle,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody } from '@/components/app-shell'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Modal,
  ScoreBar,
  ScoreRing,
  Select,
  Skeleton,
  Tabs,
  Textarea,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  ApplicationStatus,
  AtsScore,
  CandidateDetail,
} from '@/lib/types'
import {
  RECOMMENDATION_STYLES,
  STATUS_STYLES,
  cn,
  formatDate,
  formatExperience,
  formatNoticePeriod,
  formatRelative,
  titleCase,
} from '@/lib/utils'

interface CandidateApplication {
  id: string
  reference_code: string
  status: ApplicationStatus
  ats_score?: number | null
  ats_rank?: number | null
  created_at: string
  job_id: string
  job_title?: string | null
}

interface Note {
  id: string
  body: string
  is_private: boolean
  created_at: string
  author?: { full_name: string } | null
}

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const [tab, setTab] = useState('overview')
  const [statusModal, setStatusModal] = useState<CandidateApplication | null>(null)
  const [noteOpen, setNoteOpen] = useState(false)

  const candidateQuery = useQuery({
    queryKey: ['candidate', params.id],
    queryFn: () => api.get<CandidateDetail>(`/candidates/${params.id}`),
    enabled: Boolean(params.id),
  })

  const applicationsQuery = useQuery({
    queryKey: ['candidate-applications', params.id],
    queryFn: () => api.get<CandidateApplication[]>(`/candidates/${params.id}/applications`),
    enabled: Boolean(params.id),
  })

  const primaryApplication = applicationsQuery.data?.[0]

  const atsQuery = useQuery({
    queryKey: ['ats', primaryApplication?.id],
    queryFn: () => api.get<AtsScore>(`/ats/applications/${primaryApplication!.id}`),
    enabled: Boolean(primaryApplication?.id) && can('ats:read'),
    // A candidate may simply not have been scored yet; that is not an error worth retrying.
    retry: false,
  })

  const notesQuery = useQuery({
    queryKey: ['candidate-notes', params.id],
    queryFn: () => api.get<Note[]>(`/candidates/${params.id}/notes`),
    enabled: Boolean(params.id) && tab === 'notes',
  })

  const summaryMutation = useMutation({
    mutationFn: () =>
      api.post<{ summary: string; strengths: string[]; considerations: string[]; engine: string }>(
        `/candidates/${params.id}/generate-summary`,
        { job_id: primaryApplication?.job_id ?? null },
      ),
    onSuccess: () => {
      toast.success('Summary generated')
      void queryClient.invalidateQueries({ queryKey: ['candidate', params.id] })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Failed'),
  })

  if (candidateQuery.isLoading) {
    return (
      <PageBody className="space-y-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </PageBody>
    )
  }

  if (candidateQuery.isError || !candidateQuery.data) {
    return (
      <PageBody>
        <Card>
          <ErrorState
            title="Candidate not found"
            message={(candidateQuery.error as Error)?.message}
          />
        </Card>
      </PageBody>
    )
  }

  const candidate = candidateQuery.data
  const openFlags = candidate.review_flags.filter((f) => !f.resolved)

  const tabs = [
    { id: 'overview', label: 'Overview' },
    ...(can('ats:read') ? [{ id: 'ats', label: 'ATS analysis' }] : []),
    { id: 'experience', label: 'Experience', count: candidate.experience.length },
    { id: 'applications', label: 'Applications', count: applicationsQuery.data?.length },
    ...(can('candidate:note:write') ? [{ id: 'notes', label: 'Notes' }] : []),
  ]

  return (
    <>
      {/* --------------------------------------------------------- header */}
      <div className="border-b border-ink-200 bg-white">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          <Link
            href="/recruiter/candidates"
            className="inline-flex items-center gap-1.5 text-sm text-ink-500 hover:text-ink-800"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All candidates
          </Link>

          <div className="mt-5 flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex min-w-0 gap-4">
              <Avatar name={candidate.full_name} src={candidate.photo_url} size="lg" />
              <div className="min-w-0">
                <h1 className="text-title-lg font-semibold tracking-tight text-ink-900">
                  {candidate.full_name}
                </h1>
                <p className="mt-0.5 text-ink-600">
                  {candidate.current_designation ?? 'Candidate'}
                  {candidate.current_company && (
                    <span className="text-ink-400"> · {candidate.current_company}</span>
                  )}
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm text-ink-600">
                  <a
                    href={`mailto:${candidate.email}`}
                    className="flex items-center gap-1.5 hover:text-brand-600"
                  >
                    <Mail className="h-3.5 w-3.5 text-ink-400" />
                    {candidate.email}
                  </a>
                  {candidate.phone && (
                    <span className="flex items-center gap-1.5">
                      <Phone className="h-3.5 w-3.5 text-ink-400" />
                      {candidate.phone}
                    </span>
                  )}
                  {candidate.location && (
                    <span className="flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5 text-ink-400" />
                      {candidate.location}
                    </span>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  {candidate.linkedin_url && (
                    <a
                      href={candidate.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-ink-100 px-2.5 py-1 text-xs font-medium text-ink-700 hover:bg-ink-200"
                    >
                      <Linkedin className="h-3 w-3" />
                      LinkedIn
                      <ExternalLink className="h-2.5 w-2.5 text-ink-400" />
                    </a>
                  )}
                  {candidate.github_url && (
                    <a
                      href={candidate.github_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg bg-ink-100 px-2.5 py-1 text-xs font-medium text-ink-700 hover:bg-ink-200"
                    >
                      <Github className="h-3 w-3" />
                      GitHub
                      <ExternalLink className="h-2.5 w-2.5 text-ink-400" />
                    </a>
                  )}
                </div>
              </div>
            </div>

            <div className="flex shrink-0 items-start gap-6">
              {can('ats:read') && (
                <div className="text-center">
                  <ScoreRing score={atsQuery.data?.overall_score ?? primaryApplication?.ats_score} size={72} />
                  <p className="mt-1.5 text-[10px] font-medium uppercase tracking-wide text-ink-400">
                    ATS score
                  </p>
                </div>
              )}

              <div className="flex flex-col items-end gap-2">
                {primaryApplication && (
                  <Badge
                    tone="neutral"
                    className={STATUS_STYLES[primaryApplication.status].badge}
                    dot={STATUS_STYLES[primaryApplication.status].dot}
                  >
                    {STATUS_STYLES[primaryApplication.status].label}
                  </Badge>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  {can('application:update:status') && primaryApplication && (
                    <Button size="sm" onClick={() => setStatusModal(primaryApplication)}>
                      Move stage
                    </Button>
                  )}
                  {can('candidate:note:write') && (
                    <Button size="sm" variant="secondary" onClick={() => setNoteOpen(true)}>
                      <Plus className="h-3.5 w-3.5" />
                      Note
                    </Button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ------------------------------------- verification + flags */}
          <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-ink-100 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-400">
                Verification
              </span>
              {candidate.email_verified ? (
                <Badge tone="success">
                  <CheckCircle2 className="h-3 w-3" />
                  Email verified
                </Badge>
              ) : (
                <Badge tone="neutral">
                  <XCircle className="h-3 w-3" />
                  Email unverified
                </Badge>
              )}
              {candidate.verification_signals.includes('RESUME_UPLOADED') && (
                <Badge tone="success">
                  <CheckCircle2 className="h-3 w-3" />
                  Resume on file
                </Badge>
              )}
              {candidate.verification_signals.includes('PROFILE_COMPLETE') && (
                <Badge tone="success">
                  <CheckCircle2 className="h-3 w-3" />
                  Profile complete
                </Badge>
              )}
            </div>

            {openFlags.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-ink-400">
                  Review flags
                </span>
                {openFlags.map((flag) => (
                  <Badge key={flag.code} tone="warning" className="max-w-md">
                    <AlertTriangle className="h-3 w-3 shrink-0" />
                    <span className="truncate">{flag.message}</span>
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <Tabs tabs={tabs} active={tab} onChange={setTab} />
        </div>
      </div>

      {/* ----------------------------------------------------------- body */}
      <PageBody>
        {tab === 'overview' && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-6 lg:col-span-2">
              <Card>
                <CardHeader className="flex items-center justify-between">
                  <CardTitle>AI profile summary</CardTitle>
                  {can('ai:generate') && (
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={summaryMutation.isPending}
                      onClick={() => summaryMutation.mutate()}
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      {candidate.ai_summary ? 'Regenerate' : 'Generate'}
                    </Button>
                  )}
                </CardHeader>
                <CardBody>
                  {candidate.ai_summary ? (
                    <>
                      <p className="text-sm leading-relaxed text-ink-700">
                        {candidate.ai_summary}
                      </p>
                      <p className="mt-3 border-t border-ink-100 pt-3 text-xs text-ink-400">
                        AI-generated from this candidate&apos;s own profile data
                        {candidate.ai_summary_generated_at &&
                          ` · ${formatRelative(candidate.ai_summary_generated_at)}`}
                        . Review before relying on it — the hiring decision is yours.
                      </p>
                    </>
                  ) : (
                    <EmptyState
                      icon={Brain}
                      title="No summary yet"
                      description="Generate a recruiter-facing summary from this candidate's profile."
                    />
                  )}
                </CardBody>
              </Card>

              {candidate.summary && (
                <Card>
                  <CardHeader>
                    <CardTitle>Candidate&apos;s own summary</CardTitle>
                  </CardHeader>
                  <CardBody>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
                      {candidate.summary}
                    </p>
                  </CardBody>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle>Skills</CardTitle>
                </CardHeader>
                <CardBody>
                  {candidate.skills.length === 0 ? (
                    <p className="text-sm text-ink-500">No skills recorded.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {candidate.skills.map((skill) => {
                        const matched = atsQuery.data?.matched_skills.some(
                          (s) => s.toLowerCase() === skill.name.toLowerCase(),
                        )
                        return (
                          <span
                            key={skill.id}
                            className={cn(
                              'rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset',
                              matched
                                ? 'bg-success-50 text-success-700 ring-success-100'
                                : 'bg-ink-100 text-ink-700 ring-ink-200',
                            )}
                          >
                            {skill.name}
                          </span>
                        )
                      })}
                    </div>
                  )}
                </CardBody>
              </Card>
            </div>

            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>At a glance</CardTitle>
                </CardHeader>
                <CardBody>
                  <dl className="space-y-3 text-sm">
                    {[
                      ['Experience', formatExperience(candidate.total_experience_years)],
                      ['Notice period', formatNoticePeriod(candidate.notice_period_days)],
                      [
                        'Expected salary',
                        candidate.expected_salary
                          ? `${candidate.salary_currency} ${candidate.expected_salary.toLocaleString()}`
                          : '—',
                      ],
                      ['Source', candidate.source ? titleCase(candidate.source) : '—'],
                      ['In database since', formatDate(candidate.created_at)],
                    ].map(([label, value]) => (
                      <div key={label} className="flex justify-between gap-3">
                        <dt className="text-ink-500">{label}</dt>
                        <dd className="text-right font-medium text-ink-900">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </CardBody>
              </Card>

              {candidate.education.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Education</CardTitle>
                  </CardHeader>
                  <CardBody className="space-y-3">
                    {candidate.education.map((entry) => (
                      <div key={entry.id} className="flex gap-2.5">
                        <GraduationCap className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-ink-900">{entry.degree}</p>
                          <p className="text-xs text-ink-500">
                            {[entry.institution, entry.end_year].filter(Boolean).join(' · ')}
                          </p>
                        </div>
                      </div>
                    ))}
                  </CardBody>
                </Card>
              )}
            </div>
          </div>
        )}

        {tab === 'ats' && (
          <AtsPanel query={atsQuery} hasApplication={Boolean(primaryApplication)} />
        )}

        {tab === 'experience' && (
          <Card>
            <CardHeader>
              <CardTitle>Work history</CardTitle>
            </CardHeader>
            <CardBody>
              {candidate.experience.length === 0 ? (
                <EmptyState
                  icon={Briefcase}
                  title="No work history"
                  description="Nothing was extracted from the resume, and nothing has been entered manually."
                />
              ) : (
                <ol className="relative space-y-6 border-l border-ink-200 pl-6">
                  {candidate.experience.map((role) => (
                    <li key={role.id} className="relative">
                      <span className="absolute -left-[27px] top-1.5 h-2.5 w-2.5 rounded-full bg-brand-500 ring-4 ring-white" />
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h4 className="text-sm font-semibold text-ink-900">{role.position}</h4>
                        <span className="text-xs text-ink-500">
                          {role.start_date ? formatDate(role.start_date) : '—'} –{' '}
                          {role.is_current ? 'Present' : role.end_date ? formatDate(role.end_date) : '—'}
                        </span>
                      </div>
                      <p className="text-sm text-ink-600">{role.company_name}</p>
                      {role.responsibilities.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {role.responsibilities.map((item, i) => (
                            <li key={i} className="flex gap-2 text-sm text-ink-600">
                              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-300" />
                              {item}
                            </li>
                          ))}
                        </ul>
                      )}
                      {role.technologies.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {role.technologies.map((tech) => (
                            <span
                              key={tech}
                              className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                            >
                              {tech}
                            </span>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </CardBody>
          </Card>
        )}

        {tab === 'applications' && (
          <Card>
            <CardHeader>
              <CardTitle>Applications</CardTitle>
            </CardHeader>
            <CardBody className="p-0">
              {!applicationsQuery.data?.length ? (
                <EmptyState icon={Briefcase} title="No applications" />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {applicationsQuery.data.map((application) => (
                    <li
                      key={application.id}
                      className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-ink-900">
                          {application.job_title ?? 'Role'}
                        </p>
                        <p className="text-xs text-ink-500">
                          {application.reference_code} · applied{' '}
                          {formatRelative(application.created_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        {application.ats_score != null && (
                          <span className="text-sm font-semibold tabular-nums text-ink-900">
                            {Math.round(application.ats_score)}%
                            {application.ats_rank && (
                              <span className="ml-1 text-xs font-normal text-ink-400">
                                #{application.ats_rank}
                              </span>
                            )}
                          </span>
                        )}
                        <Badge
                          className={STATUS_STYLES[application.status].badge}
                          dot={STATUS_STYLES[application.status].dot}
                        >
                          {STATUS_STYLES[application.status].label}
                        </Badge>
                        {can('application:update:status') && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setStatusModal(application)}
                          >
                            Move
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        )}

        {tab === 'notes' && (
          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle>Internal notes</CardTitle>
              <Button size="sm" variant="secondary" onClick={() => setNoteOpen(true)}>
                <Plus className="h-3.5 w-3.5" />
                Add note
              </Button>
            </CardHeader>
            <CardBody className="p-0">
              {notesQuery.isLoading ? (
                <div className="space-y-2 p-5">
                  <Skeleton className="h-16" />
                  <Skeleton className="h-16" />
                </div>
              ) : !notesQuery.data?.length ? (
                <EmptyState
                  icon={ShieldCheck}
                  title="No notes yet"
                  description="Notes are internal and never visible to the candidate."
                />
              ) : (
                <ul className="divide-y divide-ink-100">
                  {notesQuery.data.map((note) => (
                    <li key={note.id} className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-ink-900">
                          {note.author?.full_name ?? 'Someone'}
                        </span>
                        <span className="text-xs text-ink-400">
                          {formatRelative(note.created_at)}
                        </span>
                        {note.is_private && <Badge tone="warning">Private</Badge>}
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
                        {note.body}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        )}
      </PageBody>

      <StatusModal
        application={statusModal}
        onClose={() => setStatusModal(null)}
        onDone={() => {
          setStatusModal(null)
          void queryClient.invalidateQueries({ queryKey: ['candidate-applications', params.id] })
        }}
      />

      <NoteModal
        open={noteOpen}
        candidateId={params.id}
        onClose={() => setNoteOpen(false)}
        onDone={() => {
          setNoteOpen(false)
          void queryClient.invalidateQueries({ queryKey: ['candidate-notes', params.id] })
        }}
      />
    </>
  )
}

// ------------------------------------------------------------- ATS panel
function AtsPanel({
  query,
  hasApplication,
}: {
  query: { data?: AtsScore; isLoading: boolean; isError: boolean }
  hasApplication: boolean
}) {
  if (query.isLoading) return <Skeleton className="h-96" />

  if (!hasApplication || query.isError || !query.data) {
    return (
      <Card>
        <EmptyState
          icon={Brain}
          title="No ATS analysis yet"
          description={
            hasApplication
              ? 'This application has not been scored. Scoring runs automatically after a resume is parsed.'
              : 'This candidate has not applied to a role, so there is nothing to score against.'
          }
        />
      </Card>
    )
  }

  const score = query.data
  const components = score.explanation.components
  const order = ['skills', 'experience', 'education', 'responsibilities', 'semantic'] as const
  const labels: Record<string, string> = {
    skills: 'Skills match',
    experience: 'Experience match',
    education: 'Education match',
    responsibilities: 'Responsibilities match',
    semantic: 'Semantic match',
  }

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card>
          <CardHeader>
            <CardTitle>Score breakdown</CardTitle>
          </CardHeader>
          <CardBody className="space-y-5">
            {order.map((key) => {
              const component = components[key]
              if (!component) return null
              return (
                <ScoreBar
                  key={key}
                  label={labels[key] ?? key}
                  score={component.score}
                  weight={component.weight}
                  description={component.explanation}
                />
              )
            })}
          </CardBody>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-success-600" />
                Matched
              </CardTitle>
            </CardHeader>
            <CardBody>
              {score.matched_skills.length === 0 ? (
                <p className="text-sm text-ink-500">No requirements matched.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {score.matched_skills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-success-50 px-2 py-1 text-xs font-medium text-success-700 ring-1 ring-inset ring-success-100"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <XCircle className="h-3.5 w-3.5 text-warning-600" />
                Missing or weak
              </CardTitle>
            </CardHeader>
            <CardBody>
              {score.missing_skills.length === 0 ? (
                <p className="text-sm text-ink-500">Nothing missing — all requirements matched.</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {score.missing_skills.map((skill) => (
                    <span
                      key={skill}
                      className="rounded-md bg-warning-50 px-2 py-1 text-xs font-medium text-warning-700 ring-1 ring-inset ring-warning-100"
                    >
                      {skill}
                    </span>
                  ))}
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="space-y-4">
        <Card>
          <CardBody className="text-center">
            <ScoreRing score={score.overall_score} size={104} />
            <div className="mt-4">
              <Badge className={RECOMMENDATION_STYLES[score.recommendation].badge}>
                {RECOMMENDATION_STYLES[score.recommendation].label}
              </Badge>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-ink-600">
              {score.explanation.summary}
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>How this was calculated</CardTitle>
          </CardHeader>
          <CardBody className="space-y-3 text-xs text-ink-600">
            <dl className="space-y-1.5">
              {Object.entries(score.weights_used).map(([key, weight]) => (
                <div key={key} className="flex justify-between">
                  <dt className="capitalize">{key}</dt>
                  <dd className="font-medium tabular-nums text-ink-800">
                    {Math.round(weight * 100)}%
                  </dd>
                </div>
              ))}
            </dl>
            <p className="border-t border-ink-100 pt-3">
              Engine v{score.engine_version} · semantic via {score.semantic_engine}
            </p>
          </CardBody>
        </Card>

        <Card className="border-info-100 bg-info-50">
          <CardBody>
            <p className="text-xs leading-relaxed text-info-700">{score.disclaimer}</p>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

// ----------------------------------------------------------- status modal
function StatusModal({
  application,
  onClose,
  onDone,
}: {
  application: CandidateApplication | null
  onClose: () => void
  onDone: () => void
}) {
  const [status, setStatus] = useState('')
  const [reason, setReason] = useState('')
  const [sendEmail, setSendEmail] = useState(false)

  const detailQuery = useQuery({
    queryKey: ['application', application?.id],
    queryFn: () => api.get<{ allowed_transitions: string[] }>(`/applications/${application!.id}`),
    enabled: Boolean(application),
  })

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/applications/${application!.id}/status`, {
        status,
        reason: reason || null,
        send_email: sendEmail,
      }),
    onSuccess: () => {
      toast.success('Application moved')
      setStatus('')
      setReason('')
      setSendEmail(false)
      onDone()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not move the application'),
  })

  if (!application) return null

  return (
    <Modal
      open
      onClose={onClose}
      title="Move to another stage"
      description={`${application.job_title ?? 'Application'} · ${application.reference_code}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={!status}
          >
            Move
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select
          label="New status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">Select a stage</option>
          {detailQuery.data?.allowed_transitions.map((option) => (
            <option key={option} value={option}>
              {STATUS_STYLES[option as ApplicationStatus]?.label ?? option}
            </option>
          ))}
        </Select>

        <Textarea
          label="Reason (recorded on the timeline)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="Why is this candidate moving?"
        />

        <label className="flex cursor-pointer gap-2.5">
          <input
            type="checkbox"
            checked={sendEmail}
            onChange={(e) => setSendEmail(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
          />
          <span className="text-sm text-ink-700">
            Email the candidate about this change
            <span className="mt-0.5 block text-xs text-ink-500">
              Uses your company&apos;s template for this stage. The result is recorded honestly —
              if no email provider is configured, nothing is sent.
            </span>
          </span>
        </label>
      </div>
    </Modal>
  )
}

function NoteModal({
  open,
  candidateId,
  onClose,
  onDone,
}: {
  open: boolean
  candidateId: string
  onClose: () => void
  onDone: () => void
}) {
  const [body, setBody] = useState('')
  const [isPrivate, setIsPrivate] = useState(false)

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/candidates/${candidateId}/notes`, { body, is_private: isPrivate }),
    onSuccess: () => {
      toast.success('Note added')
      setBody('')
      setIsPrivate(false)
      onDone()
    },
    onError: () => toast.error('Could not add the note'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add an internal note"
      description="Notes are never visible to the candidate."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            loading={mutation.isPending}
            disabled={!body.trim()}
          >
            Save note
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Textarea
          label="Note"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={5}
          placeholder="What should the team know?"
        />
        <label className="flex cursor-pointer gap-2.5">
          <input
            type="checkbox"
            checked={isPrivate}
            onChange={(e) => setIsPrivate(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
          />
          <span className="text-sm text-ink-700">
            Private note
            <span className="mt-0.5 block text-xs text-ink-500">
              Visible only to you and company admins.
            </span>
          </span>
        </label>
      </div>
    </Modal>
  )
}

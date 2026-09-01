'use client'

/**
 * One interview: its details, the feedback already submitted, and the form for adding
 * your own.
 *
 * Two rules shape this page. Private remarks are omitted by the server unless the reader
 * holds `feedback:read:private` — so a missing value means "not visible to you", and the
 * UI says exactly that rather than implying none were written (§28). And the AI digest is
 * labelled as a summary of what interviewers wrote, never as an assessment of its own.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Clock, EyeOff, Lock, MapPin, Sparkles, Video } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Field, FieldGrid, Notice } from '@/components/data'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  ErrorState,
  Select,
  Skeleton,
  Textarea,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  InterviewDetail,
  InterviewFeedback,
  InterviewRecommendation,
} from '@/lib/types'
import { cn, formatDateTime, titleCase } from '@/lib/utils'

const RECOMMENDATION_TONES: Record<
  InterviewRecommendation,
  { badge: string; label: string }
> = {
  STRONG_HIRE: { badge: 'bg-success-100 text-success-700 ring-success-500/20', label: 'Strong hire' },
  HIRE: { badge: 'bg-success-50 text-success-700 ring-success-100', label: 'Hire' },
  MAYBE: { badge: 'bg-warning-50 text-warning-700 ring-warning-100', label: 'Maybe' },
  NO_HIRE: { badge: 'bg-danger-50 text-danger-700 ring-danger-100', label: 'No hire' },
}

const COMPETENCIES = [
  { key: 'technical_skills', label: 'Technical skills' },
  { key: 'communication', label: 'Communication' },
  { key: 'problem_solving', label: 'Problem solving' },
  { key: 'domain_knowledge', label: 'Domain knowledge' },
  { key: 'culture_fit', label: 'Ways of working' },
] as const

interface FeedbackSummary {
  summary: string
  strengths: string[]
  weaknesses: string[]
  consensus?: string | null
  engine: string
  feedback_count: number
  disclaimer: string
}

export default function InterviewDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user, can } = useAuth()

  const interviewQuery = useQuery({
    queryKey: ['interview', id],
    queryFn: () => api.get<InterviewDetail>(`/interviews/${id}`),
  })

  const feedbackQuery = useQuery({
    queryKey: ['feedback', id],
    queryFn: () => api.get<InterviewFeedback[]>(`/interviews/${id}/feedback`),
  })

  if (interviewQuery.isLoading) {
    return (
      <PageBody>
        <Skeleton className="h-10 w-72" />
        <Skeleton className="mt-4 h-64" />
      </PageBody>
    )
  }

  if (interviewQuery.isError || !interviewQuery.data) {
    return (
      <PageBody>
        <Card>
          <ErrorState
            title="Could not load this interview"
            message={(interviewQuery.error as Error)?.message}
            onRetry={() => interviewQuery.refetch()}
          />
        </Card>
      </PageBody>
    )
  }

  const interview = interviewQuery.data
  const feedback = feedbackQuery.data ?? []
  const mine = feedback.find((f) => f.interviewer_id === user?.id)
  const isParticipant = interview.participants.some((p) => p.user_id === user?.id)
  const canGiveFeedback = can('feedback:submit') && (isParticipant || can('interview:update'))

  return (
    <>
      <PageHeader
        title={interview.title}
        description={`Round ${interview.round_number}${interview.round_name ? ` · ${interview.round_name}` : ''}`}
        actions={
          <Link href="/recruiter/interviews">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="h-4 w-4" />
              All interviews
            </Button>
          </Link>
        }
      >
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink-600">
          <Badge>{titleCase(interview.interview_type)}</Badge>
          <Badge tone={interview.status === 'COMPLETED' ? 'neutral' : 'info'}>
            {titleCase(interview.status)}
          </Badge>
          <span className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-ink-400" />
            {formatDateTime(interview.scheduled_start)} · {interview.duration_minutes} min
          </span>
          {interview.location && (
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 text-ink-400" />
              {interview.location}
            </span>
          )}
          {interview.meeting_link && (
            <a
              href={interview.meeting_link}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-1.5 font-medium text-brand-600 hover:text-brand-700"
            >
              <Video className="h-3.5 w-3.5" />
              Join meeting
            </a>
          )}
        </div>
      </PageHeader>

      <PageBody className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          {canGiveFeedback && (
            <FeedbackForm interviewId={interview.id} existing={mine} />
          )}

          <Card>
            <CardHeader className="flex items-center justify-between">
              <CardTitle>Feedback ({feedback.length})</CardTitle>
              {feedback.length > 1 && can('ai:assistant:use') && (
                <SummariseButton applicationId={interview.application_id} />
              )}
            </CardHeader>
            <CardBody className="space-y-5">
              {feedbackQuery.isLoading ? (
                <Skeleton className="h-32" />
              ) : feedback.length === 0 ? (
                <p className="text-sm text-ink-500">
                  No feedback submitted yet. The application cannot move past the interview
                  stage until at least one interviewer has recorded theirs.
                </p>
              ) : (
                feedback.map((entry) => <FeedbackCard key={entry.id} feedback={entry} />)
              )}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Candidate</CardTitle>
            </CardHeader>
            <CardBody>
              <Link
                href={`/recruiter/candidates/${interview.candidate_id}`}
                className="flex items-center gap-3 hover:text-brand-700"
              >
                <Avatar name={interview.candidate_name ?? 'Candidate'} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink-900">
                    {interview.candidate_name ?? 'Candidate'}
                  </p>
                  {interview.job_title && (
                    <p className="truncate text-xs text-ink-500">{interview.job_title}</p>
                  )}
                </div>
              </Link>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Interviewers</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-3">
                {interview.participants.map((participant) => (
                  <li key={participant.id} className="flex items-center gap-3">
                    <Avatar
                      name={participant.user?.full_name ?? 'Interviewer'}
                      src={participant.user?.avatar_url}
                      size="sm"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-ink-800">
                        {participant.user?.full_name ?? 'Interviewer'}
                      </p>
                      <p className="text-xs text-ink-500">{titleCase(participant.role)}</p>
                    </div>
                    {participant.is_required && <Badge>Required</Badge>}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Logistics</CardTitle>
            </CardHeader>
            <CardBody>
              <FieldGrid columns={2}>
                <Field label="Timezone">{interview.timezone}</Field>
                <Field label="Reschedules">{interview.reschedule_count}</Field>
                <Field label="Candidate confirmed">
                  {interview.candidate_confirmed_at
                    ? formatDateTime(interview.candidate_confirmed_at)
                    : 'Not yet'}
                </Field>
                <Field label="Calendar">
                  {interview.calendar_sync?.status === 'SYNCED' ? (
                    <Badge tone="success">Synced</Badge>
                  ) : (
                    <Badge tone="neutral">HireHQ only</Badge>
                  )}
                </Field>
              </FieldGrid>

              {interview.calendar_sync &&
                interview.calendar_sync.status !== 'SYNCED' && (
                  <div className="mt-4">
                    <Notice tone="warning" title="No external invitation was sent">
                      {interview.calendar_sync.detail ??
                        'No calendar provider is connected, so this interview exists in HireHQ only. Attendees have not received a calendar invitation.'}
                    </Notice>
                  </div>
                )}
            </CardBody>
          </Card>

          {interview.internal_notes && (
            <Card>
              <CardHeader className="flex items-center gap-2">
                <Lock className="h-3.5 w-3.5 text-ink-400" />
                <CardTitle>Internal notes</CardTitle>
              </CardHeader>
              <CardBody>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
                  {interview.internal_notes}
                </p>
                <p className="mt-3 text-xs text-ink-400">Never shown to the candidate.</p>
              </CardBody>
            </Card>
          )}
        </div>
      </PageBody>
    </>
  )
}

function FeedbackCard({ feedback }: { feedback: InterviewFeedback }) {
  const { can } = useAuth()
  const recommendation = RECOMMENDATION_TONES[feedback.recommendation]

  return (
    <div className="border-b border-ink-100 pb-5 last:border-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar
            name={feedback.interviewer?.full_name ?? 'Interviewer'}
            src={feedback.interviewer?.avatar_url}
            size="sm"
          />
          <div>
            <p className="text-sm font-medium text-ink-900">
              {feedback.interviewer?.full_name ?? 'Interviewer'}
            </p>
            <p className="text-xs text-ink-500">
              {feedback.submitted_at ? formatDateTime(feedback.submitted_at) : 'Draft'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tabular-nums text-ink-900">
            {feedback.overall_rating.toFixed(1)}/5
          </span>
          <span className={cn('badge', recommendation.badge)}>{recommendation.label}</span>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
        {COMPETENCIES.map(({ key, label }) => {
          const value = feedback[key]
          if (value == null) return null
          return (
            <div key={key} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-ink-600">{label}</span>
              <span className="font-medium tabular-nums text-ink-900">{value}/5</span>
            </div>
          )
        })}
      </div>

      {feedback.strengths && (
        <div className="mt-4">
          <h5 className="text-xs font-medium uppercase tracking-wide text-ink-400">Strengths</h5>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {feedback.strengths}
          </p>
        </div>
      )}
      {feedback.weaknesses && (
        <div className="mt-3">
          <h5 className="text-xs font-medium uppercase tracking-wide text-ink-400">
            Areas of concern
          </h5>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {feedback.weaknesses}
          </p>
        </div>
      )}
      {feedback.comments && (
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
          {feedback.comments}
        </p>
      )}

      {feedback.private_remarks ? (
        <div className="mt-4 rounded-xl border border-ink-200 bg-ink-50 px-3.5 py-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ink-500">
            <Lock className="h-3 w-3" />
            Private remarks
          </p>
          <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {feedback.private_remarks}
          </p>
        </div>
      ) : (
        !can('feedback:read:private') && (
          <p className="mt-4 flex items-center gap-1.5 text-xs text-ink-400">
            <EyeOff className="h-3 w-3" />
            Any private remarks on this feedback are hidden from your role.
          </p>
        )
      )}
    </div>
  )
}

function SummariseButton({ applicationId }: { applicationId: string }) {
  const [summary, setSummary] = useState<FeedbackSummary | null>(null)

  const summarise = useMutation({
    mutationFn: () =>
      api.post<FeedbackSummary>(`/interviews/applications/${applicationId}/summarize-feedback`),
    onSuccess: setSummary,
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not summarise'),
  })

  if (summary) {
    return (
      <div className="w-full">
        <div className="rounded-xl border border-ink-200 bg-ink-50 px-4 py-3.5">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ink-500">
            <Sparkles className="h-3 w-3" />
            Digest of {summary.feedback_count} feedback entries · {summary.engine}
          </p>
          <p className="mt-2 text-sm leading-relaxed text-ink-700">{summary.summary}</p>
          {summary.consensus && (
            <p className="mt-2 text-sm text-ink-700">
              <span className="font-medium">Consensus:</span> {summary.consensus}
            </p>
          )}
          <p className="mt-3 text-xs leading-relaxed text-ink-400">{summary.disclaimer}</p>
        </div>
      </div>
    )
  }

  return (
    <Button variant="ghost" size="sm" loading={summarise.isPending} onClick={() => summarise.mutate()}>
      <Sparkles className="h-3.5 w-3.5" />
      Summarise
    </Button>
  )
}

function FeedbackForm({
  interviewId,
  existing,
}: {
  interviewId: string
  existing?: InterviewFeedback
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(!existing)

  const [form, setForm] = useState({
    overall_rating: existing?.overall_rating ?? 3,
    recommendation: (existing?.recommendation ?? 'MAYBE') as InterviewRecommendation,
    technical_skills: existing?.technical_skills ?? null,
    communication: existing?.communication ?? null,
    problem_solving: existing?.problem_solving ?? null,
    domain_knowledge: existing?.domain_knowledge ?? null,
    culture_fit: existing?.culture_fit ?? null,
    strengths: existing?.strengths ?? '',
    weaknesses: existing?.weaknesses ?? '',
    comments: existing?.comments ?? '',
    private_remarks: existing?.private_remarks ?? '',
  })

  const submit = useMutation({
    mutationFn: (isDraft: boolean) =>
      api.post(`/interviews/${interviewId}/feedback`, {
        ...form,
        strengths: form.strengths || undefined,
        weaknesses: form.weaknesses || undefined,
        comments: form.comments || undefined,
        private_remarks: form.private_remarks || undefined,
        is_draft: isDraft,
      }),
    onSuccess: (_data, isDraft) => {
      toast.success(isDraft ? 'Draft saved.' : 'Feedback submitted.')
      void queryClient.invalidateQueries({ queryKey: ['feedback', interviewId] })
      void queryClient.invalidateQueries({ queryKey: ['interviews'] })
      if (!isDraft) setOpen(false)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save your feedback'),
  })

  if (!open) {
    return (
      <Card>
        <CardBody className="flex items-center justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-ink-900">Your feedback is recorded</p>
            <p className="mt-0.5 text-sm text-ink-500">
              {existing?.is_draft ? 'Saved as a draft — not yet submitted.' : 'Submitted.'}
            </p>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
            Edit
          </Button>
        </CardBody>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your feedback</CardTitle>
      </CardHeader>
      <CardBody className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="overall" className="label">
              Overall rating
            </label>
            <div className="mt-1.5 flex items-center gap-3">
              <input
                id="overall"
                type="range"
                min={1}
                max={5}
                step={0.5}
                value={form.overall_rating}
                onChange={(e) =>
                  setForm({ ...form, overall_rating: Number(e.target.value) })
                }
                className="flex-1 accent-brand-600"
              />
              <span className="w-10 text-sm font-semibold tabular-nums text-ink-900">
                {form.overall_rating.toFixed(1)}
              </span>
            </div>
          </div>

          <Select
            label="Recommendation"
            value={form.recommendation}
            onChange={(e) =>
              setForm({ ...form, recommendation: e.target.value as InterviewRecommendation })
            }
          >
            {(Object.keys(RECOMMENDATION_TONES) as InterviewRecommendation[]).map((value) => (
              <option key={value} value={value}>
                {RECOMMENDATION_TONES[value].label}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <p className="label">Competencies</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {COMPETENCIES.map(({ key, label }) => (
              <Select
                key={key}
                label={label}
                value={form[key] == null ? '' : String(form[key])}
                onChange={(e) =>
                  setForm({ ...form, [key]: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Not assessed</option>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n} / 5
                  </option>
                ))}
              </Select>
            ))}
          </div>
        </div>

        <Textarea
          label="Strengths"
          placeholder="What did they do well? Cite specifics from the conversation."
          value={form.strengths}
          onChange={(e) => setForm({ ...form, strengths: e.target.value })}
        />
        <Textarea
          label="Areas of concern"
          placeholder="What would you want probed in a later round?"
          value={form.weaknesses}
          onChange={(e) => setForm({ ...form, weaknesses: e.target.value })}
        />
        <Textarea
          label="Additional comments"
          value={form.comments}
          onChange={(e) => setForm({ ...form, comments: e.target.value })}
        />
        <Textarea
          label="Private remarks"
          hint="Visible only to you and company admins. Never shown to the candidate."
          value={form.private_remarks}
          onChange={(e) => setForm({ ...form, private_remarks: e.target.value })}
        />

        <Notice tone="neutral">
          Base your assessment on what the candidate demonstrated. Avoid characteristics
          unrelated to the role — this record is auditable and informs a hiring decision.
        </Notice>

        <div className="flex justify-end gap-2">
          {existing && (
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          )}
          <Button
            variant="secondary"
            loading={submit.isPending && submit.variables === true}
            onClick={() => submit.mutate(true)}
          >
            Save draft
          </Button>
          <Button
            loading={submit.isPending && submit.variables === false}
            onClick={() => submit.mutate(false)}
          >
            Submit feedback
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

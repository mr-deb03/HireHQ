'use client'

/**
 * Assessments and the attempts people have made on them.
 *
 * The pivotal thing this page gets right: an attempt with answers still awaiting a human
 * shows "needs grading" rather than a score. A percentage covering only the auto-gradable
 * half would read like a final mark, and a hiring decision would be made on it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, GraduationCap, Timer } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { DataTable, EmptyRows, Notice, Paginator, type Column } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Skeleton,
  Tabs,
  Textarea,
} from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Assessment, AssessmentAttempt } from '@/lib/types'
import { formatRelative, titleCase } from '@/lib/utils'

function AssessmentsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const tab = params.get('tab') ?? 'attempts'

  return (
    <>
      <PageHeader
        title="Assessments"
        description="Technical screens, and the attempts candidates have made."
      >
        <div className="mt-5">
          <Tabs
            tabs={[
              { id: 'attempts', label: 'Attempts' },
              { id: 'grading', label: 'Needs grading' },
              { id: 'library', label: 'Library' },
            ]}
            active={tab}
            onChange={(id) => router.push(`/recruiter/assessments?tab=${id}`)}
          />
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {tab === 'library' ? <Library /> : <Attempts needsGrading={tab === 'grading'} />}
      </PageBody>
    </>
  )
}

function Attempts({ needsGrading }: { needsGrading: boolean }) {
  const [page, setPage] = useState(1)
  const [grading, setGrading] = useState<AssessmentAttempt | null>(null)

  const attemptsQuery = useQuery({
    queryKey: ['assessment-attempts', needsGrading, page],
    queryFn: () =>
      api.get<Page<AssessmentAttempt>>('/assessments/attempts/list', {
        query: { needs_grading: needsGrading || undefined, page, page_size: 20 },
      }),
  })

  const columns: Column<AssessmentAttempt>[] = [
    {
      key: 'candidate',
      header: 'Candidate',
      render: (attempt) => (
        <Link
          href={`/recruiter/candidates/${attempt.candidate_id}`}
          className="font-medium text-ink-900 hover:text-brand-700"
        >
          {attempt.candidate_id.slice(0, 8)}…
        </Link>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (attempt) => (
        <Badge
          tone={
            attempt.status === 'EVALUATED'
              ? 'success'
              : attempt.status === 'SUBMITTED'
                ? 'info'
                : attempt.status === 'EXPIRED'
                  ? 'danger'
                  : 'neutral'
          }
        >
          {titleCase(attempt.status)}
        </Badge>
      ),
    },
    {
      key: 'score',
      header: 'Result',
      align: 'right',
      render: (attempt) => <AttemptResult attempt={attempt} />,
    },
    {
      key: 'submitted',
      header: 'Submitted',
      hideOnMobile: true,
      render: (attempt) =>
        attempt.submitted_at ? formatRelative(attempt.submitted_at) : '—',
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (attempt) =>
        attempt.pending_manual_review.length > 0 ? (
          <Button variant="secondary" size="sm" onClick={() => setGrading(attempt)}>
            <GraduationCap className="h-3.5 w-3.5" />
            Grade
          </Button>
        ) : null,
    },
  ]

  return (
    <>
      {needsGrading ? (
        <Notice tone="info" title="These answers need a person">
          Coding, SQL and free-text answers that no runner could verify are held here rather
          than being guessed at. Until they are graded, the candidate has no final result —
          and the attempt reports no pass or fail.
        </Notice>
      ) : (
        <Notice tone="neutral">
          A percentage covers only the questions that could be graded automatically. Where
          answers are still with a human, the result says so instead of showing a score that
          would read like a final mark.
        </Notice>
      )}

      <DataTable
        rows={attemptsQuery.data?.items}
        columns={columns}
        loading={attemptsQuery.isLoading}
        error={attemptsQuery.error as Error | null}
        onRetry={() => attemptsQuery.refetch()}
        rowKey={(attempt) => attempt.id}
        empty={
          <EmptyRows
            icon={ClipboardList}
            title={needsGrading ? 'Nothing awaiting grading' : 'No attempts yet'}
            description={
              needsGrading
                ? 'Every submitted answer that needed a human has been graded.'
                : 'Invite a candidate to an assessment from their application.'
            }
          />
        }
      />

      <Paginator meta={attemptsQuery.data?.meta} onPage={setPage} />

      {grading && <GradeModal attempt={grading} onClose={() => setGrading(null)} />}
    </>
  )
}

function AttemptResult({ attempt }: { attempt: AssessmentAttempt }) {
  const pending = attempt.pending_manual_review.length

  if (attempt.status !== 'SUBMITTED' && attempt.status !== 'EVALUATED') {
    return <span className="text-ink-400">—</span>
  }

  return (
    <div className="flex flex-col items-end gap-0.5">
      {attempt.percentage != null ? (
        <span className="font-semibold tabular-nums text-ink-900">{attempt.percentage}%</span>
      ) : (
        <span className="text-sm text-ink-500">Not scored</span>
      )}

      {pending > 0 ? (
        /*
          `passed` is deliberately null while anything is pending, so the UI must not
          present the partial percentage as a verdict.
        */
        <span className="flex items-center gap-1 text-xs text-warning-700">
          <Timer className="h-3 w-3" />
          {pending} awaiting review
        </span>
      ) : attempt.passed != null ? (
        <span className={attempt.passed ? 'text-xs text-success-700' : 'text-xs text-ink-500'}>
          {attempt.passed ? 'Passed' : 'Below threshold'}
        </span>
      ) : null}

      {attempt.score != null && attempt.max_score != null && (
        <span className="text-xs text-ink-400 tabular-nums">
          {attempt.score} / {attempt.max_score} pts
        </span>
      )}
    </div>
  )
}

function GradeModal({
  attempt,
  onClose,
}: {
  attempt: AssessmentAttempt
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [index, setIndex] = useState(0)
  const [points, setPoints] = useState('')
  const [comment, setComment] = useState('')

  const questionId = attempt.pending_manual_review[index]

  const grade = useMutation({
    mutationFn: () =>
      api.post<AssessmentAttempt>(`/assessments/attempts/${attempt.id}/grade`, {
        question_id: questionId,
        points: Number(points),
        comment: comment || undefined,
      }),
    onSuccess: (updated) => {
      toast.success('Answer graded.')
      void queryClient.invalidateQueries({ queryKey: ['assessment-attempts'] })
      setPoints('')
      setComment('')
      if (updated.pending_manual_review.length === 0) onClose()
      else setIndex(0)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save the grade'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title="Grade an answer"
      description={`${attempt.pending_manual_review.length} ${
        attempt.pending_manual_review.length === 1 ? 'answer' : 'answers'
      } awaiting review`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            loading={grade.isPending}
            disabled={points === '' || Number.isNaN(Number(points))}
            onClick={() => grade.mutate()}
          >
            Save grade
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {attempt.pending_manual_review.length > 1 && (
          <div className="flex flex-wrap gap-1.5">
            {attempt.pending_manual_review.map((id, i) => (
              <button
                key={id}
                onClick={() => setIndex(i)}
                className={
                  i === index
                    ? 'rounded-lg bg-ink-900 px-2.5 py-1 text-xs font-medium text-white'
                    : 'rounded-lg bg-ink-100 px-2.5 py-1 text-xs font-medium text-ink-600 hover:bg-ink-200'
                }
              >
                Answer {i + 1}
              </button>
            ))}
          </div>
        )}

        <Notice tone="neutral">
          Read the submission on the candidate&rsquo;s application, then award points here.
          The grade and your comment are recorded against your name.
        </Notice>

        <Input
          label="Points awarded"
          type="number"
          min={0}
          step="0.5"
          required
          hint="Cannot exceed the points the question is worth."
          value={points}
          onChange={(e) => setPoints(e.target.value)}
        />

        <Textarea
          label="Comment"
          hint="Why this score. Helps whoever reviews the decision later."
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
    </Modal>
  )
}

function Library() {
  const { can } = useAuth()

  const assessmentsQuery = useQuery({
    queryKey: ['assessments'],
    queryFn: () => api.get<Assessment[]>('/assessments'),
  })

  if (assessmentsQuery.isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40" />
        ))}
      </div>
    )
  }

  if (!assessmentsQuery.data?.length) {
    return (
      <Card>
        <EmptyState
          icon={ClipboardList}
          title="No assessments yet"
          description={
            can('assessment:manage')
              ? 'Build a screen once and reuse it across every job that needs the same skills.'
              : 'Nobody has set up an assessment for your company yet.'
          }
        />
      </Card>
    )
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {assessmentsQuery.data.map((assessment) => {
        const needsHuman = assessment.questions.filter((q) =>
          ['CODING', 'SQL', 'SHORT_ANSWER'].includes(q.question_type),
        ).length

        return (
          <Card key={assessment.id} className="p-5">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-[15px] font-semibold text-ink-900">{assessment.title}</h3>
              <Badge tone={assessment.is_active ? 'success' : 'neutral'}>
                {assessment.is_active ? 'Active' : 'Inactive'}
              </Badge>
            </div>

            {assessment.description && (
              <p className="mt-1.5 line-clamp-2 text-sm text-ink-600">
                {assessment.description}
              </p>
            )}

            <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-ink-100 pt-3 text-center">
              <div>
                <dt className="text-xs text-ink-400">Questions</dt>
                <dd className="mt-0.5 font-semibold tabular-nums text-ink-900">
                  {assessment.questions.length}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-ink-400">Points</dt>
                <dd className="mt-0.5 font-semibold tabular-nums text-ink-900">
                  {assessment.total_points}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-ink-400">Minutes</dt>
                <dd className="mt-0.5 font-semibold tabular-nums text-ink-900">
                  {assessment.duration_minutes}
                </dd>
              </div>
            </dl>

            {needsHuman > 0 && (
              <p className="mt-3 text-xs text-ink-500">
                {needsHuman} {needsHuman === 1 ? 'question' : 'questions'} may need a human
                grader, depending on how this server is configured to run code.
              </p>
            )}
          </Card>
        )
      })}
    </div>
  )
}

export default function RecruiterAssessmentsPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <AssessmentsContent />
    </Suspense>
  )
}

'use client'

/**
 * Taking an assessment, opened from the emailed link.
 *
 * The server strips answer keys and hidden test cases before this page ever sees the
 * questions, so there is nothing here to leak. On submission the result is reported
 * honestly: objective questions score immediately, and anything a person still has to
 * grade is described as awaiting review rather than folded into a percentage that would
 * read like a final mark.
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Clock, FileWarning, Send } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'

import { Notice } from '@/components/data'
import { Logo } from '@/components/marketing'
import {
  Badge,
  Button,
  Card,
  CardBody,
  EmptyState,
  Modal,
  Select,
  Skeleton,
  Textarea,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import type { AssessmentAnswerInput, CandidateAssessment } from '@/lib/types'
import { cn } from '@/lib/utils'

interface SubmitResult {
  attempt_id: string
  submitted_at?: string | null
  questions_awaiting_review: number
}

type AnswerState = Record<string, AssessmentAnswerInput>

function useCountdown(expiresAt?: string | null) {
  const [remaining, setRemaining] = useState<number | null>(null)

  useEffect(() => {
    if (!expiresAt) return
    const tick = () =>
      setRemaining(Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)))
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [expiresAt])

  return remaining
}

function formatClock(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

function AssessmentContent() {
  const { id } = useParams<{ id: string }>()
  const params = useSearchParams()
  const token = params.get('token') ?? ''

  const [answers, setAnswers] = useState<AnswerState>({})
  const [confirming, setConfirming] = useState(false)
  const [startedAt] = useState(() => Date.now())

  // Opening the assessment starts the server-side timer, so it must happen exactly once.
  const attemptQuery = useQuery({
    queryKey: ['assessment-attempt', id, token],
    queryFn: () =>
      api.get<CandidateAssessment>(`/assessments/take/${id}`, { auth: false, query: { token } }),
    enabled: Boolean(token),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })

  const submit = useMutation({
    mutationFn: () =>
      api.post<SubmitResult>(
        `/assessments/take/${id}/submit`,
        {
          answers: Object.values(answers).map((answer) => ({
            ...answer,
            time_spent_seconds: Math.floor((Date.now() - startedAt) / 1000),
          })),
        },
        { auth: false, query: { token } },
      ),
    onSuccess: () => setConfirming(false),
  })

  const remaining = useCountdown(attemptQuery.data?.expires_at)
  // Memoised so the fallback empty array is not a fresh identity on every render, which
  // would defeat the answered-count memo below.
  const questions = useMemo(
    () => attemptQuery.data?.assessment.questions ?? [],
    [attemptQuery.data],
  )
  const answeredCount = useMemo(
    () =>
      questions.filter((q) => {
        const answer = answers[q.id]
        return Boolean(
          answer &&
            ((answer.selected_options?.length ?? 0) > 0 ||
              answer.answer_text?.trim() ||
              answer.code_submission?.trim()),
        )
      }).length,
    [questions, answers],
  )

  const setAnswer = useCallback((questionId: string, patch: Partial<AssessmentAnswerInput>) => {
    setAnswers((current) => ({
      ...current,
      [questionId]: { question_id: questionId, ...current[questionId], ...patch },
    }))
  }, [])

  // Time is up: submit what exists rather than losing the work entirely.
  useEffect(() => {
    if (remaining === 0 && !submit.isSuccess && !submit.isPending && questions.length) {
      submit.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remaining])

  if (!token) {
    return (
      <Shell>
        <Card>
          <EmptyState
            icon={FileWarning}
            title="This link is incomplete"
            description="The assessment link is missing its access token. Open the most recent link from your invitation email."
          />
        </Card>
      </Shell>
    )
  }

  if (attemptQuery.isLoading) {
    return (
      <Shell>
        <Skeleton className="h-96" />
      </Shell>
    )
  }

  if (attemptQuery.isError || !attemptQuery.data) {
    const error = attemptQuery.error
    const alreadyDone =
      error instanceof ApiError && error.code === 'BUSINESS_RULE_VIOLATION'
    return (
      <Shell>
        <Card>
          <EmptyState
            icon={FileWarning}
            title={alreadyDone ? 'This assessment is closed' : 'Could not open this assessment'}
            description={
              (error as Error)?.message ??
              'The link may have expired or already been used. Contact your recruiter for a new one.'
            }
          />
        </Card>
      </Shell>
    )
  }

  if (submit.isSuccess) {
    return (
      <Shell>
        <Card>
          <CardBody className="p-8 text-center">
            <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50">
              <CheckCircle2 className="h-6 w-6 text-success-600" />
            </span>
            <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
              Assessment submitted
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-ink-600">
              Thank you. Your answers have been recorded.
            </p>

            <div className="mt-6 text-left">
              {submit.data.questions_awaiting_review > 0 ? (
                <Notice tone="info" title="Some answers need a person to review them">
                  {submit.data.questions_awaiting_review}{' '}
                  {submit.data.questions_awaiting_review === 1 ? 'answer is' : 'answers are'}{' '}
                  waiting on a human grader, so no score is being reported yet. The hiring
                  team will be in touch once your result is complete.
                </Notice>
              ) : (
                <Notice tone="neutral">
                  Your result goes to the hiring team, who will decide the next step. You
                  will hear from them either way.
                </Notice>
              )}
            </div>

            <Link href="/candidate/dashboard" className="mt-6 inline-block">
              <Button variant="secondary">Go to my applications</Button>
            </Link>
          </CardBody>
        </Card>
      </Shell>
    )
  }

  const assessment = attemptQuery.data.assessment
  const lowTime = remaining !== null && remaining < 300

  return (
    <Shell>
      {/* ------------------------------------------------------------ header */}
      <div className="sticky top-0 z-30 -mx-4 mb-5 border-b border-ink-200 bg-white/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold text-ink-900">
              {assessment.title}
            </h1>
            <p className="text-xs text-ink-500">
              {answeredCount} of {questions.length} answered · {assessment.total_points} points
            </p>
          </div>

          <div className="flex items-center gap-3">
            {remaining !== null && (
              <span
                className={cn(
                  'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-semibold tabular-nums',
                  lowTime ? 'bg-danger-50 text-danger-700' : 'bg-ink-100 text-ink-700',
                )}
                role="timer"
                aria-live={lowTime ? 'polite' : 'off'}
              >
                <Clock className="h-3.5 w-3.5" />
                {formatClock(remaining)}
              </span>
            )}
            <Button
              size="sm"
              disabled={answeredCount === 0}
              onClick={() => setConfirming(true)}
            >
              <Send className="h-3.5 w-3.5" />
              Submit
            </Button>
          </div>
        </div>

        <div className="mt-2 h-1 overflow-hidden rounded-full bg-ink-100">
          <div
            className="h-full rounded-full bg-brand-500 transition-all duration-300"
            style={{ width: `${(answeredCount / Math.max(1, questions.length)) * 100}%` }}
          />
        </div>
      </div>

      {assessment.description && (
        <Card className="mb-5">
          <CardBody>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
              {assessment.description}
            </p>
          </CardBody>
        </Card>
      )}

      {lowTime && (
        <div className="mb-5">
          <Notice tone="warning" title="Less than five minutes left">
            When the timer reaches zero your answers are submitted automatically, so nothing
            you have written is lost.
          </Notice>
        </div>
      )}

      {/* --------------------------------------------------------- questions */}
      <div className="space-y-4">
        {questions.map((question, index) => (
          <Card key={question.id}>
            <CardBody className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="text-sm font-medium leading-relaxed text-ink-900">
                  <span className="mr-2 text-ink-400">{index + 1}.</span>
                  {question.prompt}
                </p>
                <Badge>
                  {question.points} {question.points === 1 ? 'point' : 'points'}
                </Badge>
              </div>

              {(question.question_type === 'MCQ_SINGLE' ||
                question.question_type === 'MCQ_MULTIPLE' ||
                question.question_type === 'APTITUDE') && (
                <fieldset className="space-y-2">
                  <legend className="sr-only">
                    {question.question_type === 'MCQ_MULTIPLE'
                      ? 'Select all that apply'
                      : 'Select one'}
                  </legend>
                  {question.question_type === 'MCQ_MULTIPLE' && (
                    <p className="text-xs text-ink-500">Select all that apply.</p>
                  )}
                  {question.options.map((option) => {
                    const selected = answers[question.id]?.selected_options ?? []
                    const isMulti = question.question_type === 'MCQ_MULTIPLE'
                    const checked = selected.includes(option.id)
                    return (
                      <label
                        key={option.id}
                        className={cn(
                          'flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-2.5 transition-colors',
                          checked
                            ? 'border-brand-300 bg-brand-50'
                            : 'border-ink-200 hover:bg-ink-50',
                        )}
                      >
                        <input
                          type={isMulti ? 'checkbox' : 'radio'}
                          name={question.id}
                          checked={checked}
                          onChange={() =>
                            setAnswer(question.id, {
                              selected_options: isMulti
                                ? checked
                                  ? selected.filter((o) => o !== option.id)
                                  : [...selected, option.id]
                                : [option.id],
                            })
                          }
                          className="mt-0.5 h-4 w-4 shrink-0 border-ink-300 text-brand-600"
                        />
                        <span className="text-sm text-ink-800">{option.text}</span>
                      </label>
                    )
                  })}
                </fieldset>
              )}

              {question.question_type === 'SHORT_ANSWER' && (
                <Textarea
                  label="Your answer"
                  value={answers[question.id]?.answer_text ?? ''}
                  onChange={(e) => setAnswer(question.id, { answer_text: e.target.value })}
                />
              )}

              {(question.question_type === 'CODING' || question.question_type === 'SQL') && (
                <CodeAnswer
                  question={question}
                  answer={answers[question.id]}
                  onChange={(patch) => setAnswer(question.id, patch)}
                />
              )}
            </CardBody>
          </Card>
        ))}
      </div>

      <div className="mt-6 flex justify-end">
        <Button size="lg" disabled={answeredCount === 0} onClick={() => setConfirming(true)}>
          <Send className="h-4 w-4" />
          Submit assessment
        </Button>
      </div>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Submit your assessment?"
        description="You cannot change your answers afterwards."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)}>
              Keep working
            </Button>
            <Button loading={submit.isPending} onClick={() => submit.mutate()}>
              Submit
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {answeredCount < questions.length && (
            <Notice tone="warning">
              <span className="flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {questions.length - answeredCount} of {questions.length} questions are still
                unanswered. Unanswered questions score nothing.
              </span>
            </Notice>
          )}
          {submit.isError && (
            <div
              role="alert"
              className="rounded-xl border border-danger-100 bg-danger-50 px-3.5 py-2.5 text-sm text-danger-700"
            >
              {(submit.error as Error).message}
            </div>
          )}
          <p className="text-sm text-ink-600">
            {answeredCount} of {questions.length} answered.
          </p>
        </div>
      </Modal>
    </Shell>
  )
}

function CodeAnswer({
  question,
  answer,
  onChange,
}: {
  question: CandidateAssessment['assessment']['questions'][number]
  answer?: AssessmentAnswerInput
  onChange: (patch: Partial<AssessmentAnswerInput>) => void
}) {
  const languages = question.allowed_languages.length
    ? question.allowed_languages
    : question.question_type === 'SQL'
      ? ['sql']
      : ['python']

  // Seed the editor with the starter code the first time this question is opened.
  useEffect(() => {
    if (answer?.code_submission === undefined && question.starter_code) {
      onChange({ code_submission: question.starter_code, language: languages[0] })
    } else if (answer?.language === undefined) {
      onChange({ language: languages[0] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-3">
      {languages.length > 1 && (
        <div className="w-48">
          <Select
            label="Language"
            value={answer?.language ?? languages[0]}
            onChange={(e) => onChange({ language: e.target.value })}
          >
            {languages.map((language) => (
              <option key={language} value={language}>
                {language}
              </option>
            ))}
          </Select>
        </div>
      )}

      <div>
        <label htmlFor={`code-${question.id}`} className="label">
          Your solution
        </label>
        <textarea
          id={`code-${question.id}`}
          spellCheck={false}
          value={answer?.code_submission ?? ''}
          onChange={(e) => onChange({ code_submission: e.target.value })}
          className="input mt-1.5 min-h-56 resize-y font-mono text-[13px] leading-relaxed"
          placeholder={
            question.question_type === 'SQL' ? 'SELECT …' : '# Write your solution here'
          }
        />
      </div>

      {question.example_test_cases.length > 0 && (
        <div className="rounded-xl border border-ink-200 bg-ink-50 px-3.5 py-3">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
            Example cases
          </p>
          <div className="mt-2 space-y-2">
            {question.example_test_cases.map((testCase, index) => (
              <div key={index} className="font-mono text-xs text-ink-700">
                {testCase.input && (
                  <p>
                    <span className="text-ink-400">in: </span>
                    {testCase.input}
                  </p>
                )}
                {testCase.expected_output && (
                  <p>
                    <span className="text-ink-400">out: </span>
                    {testCase.expected_output}
                  </p>
                )}
              </div>
            ))}
          </div>
          <p className="mt-2.5 text-xs text-ink-500">
            Your solution is also run against cases that are not shown here.
          </p>
        </div>
      )}
    </div>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Logo />
        </div>
      </header>
      <div className="mx-auto max-w-3xl px-4 py-8">{children}</div>
    </div>
  )
}

export default function TakeAssessmentPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <AssessmentContent />
    </Suspense>
  )
}

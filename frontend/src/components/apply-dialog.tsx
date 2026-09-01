'use client'

import { CheckCircle2, FileText, Upload, X } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

import { ApiError, tokens } from '@/lib/api'
import type { PublicJobDetail, ScreeningQuestion } from '@/lib/types'
import { cn } from '@/lib/utils'

import { Button, Input, Modal, Select, Textarea } from './ui'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
const MAX_RESUME_MB = 10

type StepId = 'personal' | 'professional' | 'education' | 'resume' | 'screening' | 'consent'

interface FormState {
  first_name: string
  last_name: string
  email: string
  phone: string
  location: string
  current_designation: string
  current_company: string
  total_experience_years: string
  expected_salary: string
  notice_period_days: string
  linkedin_url: string
  github_url: string
  portfolio_url: string
  highest_qualification: string
  institution: string
  graduation_year: string
  cover_letter: string
  consent_given: boolean
}

const EMPTY: FormState = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  location: '',
  current_designation: '',
  current_company: '',
  total_experience_years: '',
  expected_salary: '',
  notice_period_days: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  highest_qualification: '',
  institution: '',
  graduation_year: '',
  cover_letter: '',
  consent_given: false,
}

export function ApplyDialog({
  job,
  open,
  onClose,
  onApplied,
  source,
}: {
  job: PublicJobDetail
  open: boolean
  onClose: () => void
  onApplied: () => void
  source?: string
}) {
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [answers, setAnswers] = useState<Record<string, unknown>>({})
  const [resume, setResume] = useState<File | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ reference_code: string; id: string } | null>(null)

  const steps: { id: StepId; label: string }[] = [
    { id: 'personal', label: 'About you' },
    { id: 'professional', label: 'Experience' },
    { id: 'education', label: 'Education' },
    { id: 'resume', label: 'Resume' },
    ...(job.screening_questions.length ? [{ id: 'screening' as StepId, label: 'Questions' }] : []),
    { id: 'consent', label: 'Review' },
  ]

  const current = steps[step]!
  const isLast = step === steps.length - 1

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => {
      if (!prev[key as string]) return prev
      const next = { ...prev }
      delete next[key as string]
      return next
    })
  }

  function validateStep(): boolean {
    const found: Record<string, string> = {}

    if (current.id === 'personal') {
      if (!form.first_name.trim()) found.first_name = 'Enter your first name'
      if (!form.last_name.trim()) found.last_name = 'Enter your last name'
      if (!form.email.trim()) found.email = 'Enter your email address'
      else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
        found.email = 'Enter a valid email address'
    }

    if (current.id === 'professional' && form.total_experience_years) {
      const years = Number(form.total_experience_years)
      if (Number.isNaN(years) || years < 0 || years > 60) {
        found.total_experience_years = 'Enter a number between 0 and 60'
      }
    }

    if (current.id === 'resume' && resume) {
      const extension = resume.name.split('.').pop()?.toLowerCase()
      if (!extension || !['pdf', 'docx'].includes(extension)) {
        found.resume = 'Upload a PDF or DOCX file'
      } else if (resume.size > MAX_RESUME_MB * 1024 * 1024) {
        found.resume = `Your file is ${(resume.size / 1024 / 1024).toFixed(1)} MB. The limit is ${MAX_RESUME_MB} MB.`
      }
    }

    if (current.id === 'screening') {
      for (const question of job.screening_questions) {
        if (!question.is_required) continue
        const value = answers[question.id]
        const missing =
          value === undefined ||
          value === '' ||
          (Array.isArray(value) && value.length === 0)
        if (missing) found[question.id] = 'This question is required'
      }
    }

    if (current.id === 'consent' && !form.consent_given) {
      found.consent_given = 'You must consent to continue'
    }

    setErrors(found)
    return Object.keys(found).length === 0
  }

  function next() {
    if (validateStep()) setStep((s) => Math.min(s + 1, steps.length - 1))
  }

  function buildAnswers() {
    return job.screening_questions
      .filter((q) => answers[q.id] !== undefined && answers[q.id] !== '')
      .map((q) => {
        const value = answers[q.id]
        switch (q.question_type) {
          case 'YES_NO':
            return { question_id: q.id, answer_boolean: value === 'yes' || value === true }
          case 'NUMERIC':
          case 'EXPERIENCE':
          case 'SALARY':
          case 'NOTICE_PERIOD':
            return { question_id: q.id, answer_number: Number(value) }
          case 'SINGLE_CHOICE':
            return { question_id: q.id, answer_options: [String(value)] }
          case 'MULTIPLE_CHOICE':
            return { question_id: q.id, answer_options: value as string[] }
          default:
            return { question_id: q.id, answer_text: String(value) }
        }
      })
  }

  async function submit() {
    if (!validateStep()) return
    setSubmitting(true)
    setErrors({})

    const payload = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      email: form.email.trim(),
      phone: form.phone.trim() || null,
      location: form.location.trim() || null,
      current_designation: form.current_designation.trim() || null,
      current_company: form.current_company.trim() || null,
      total_experience_years: form.total_experience_years
        ? Number(form.total_experience_years)
        : null,
      expected_salary: form.expected_salary ? Number(form.expected_salary) : null,
      notice_period_days: form.notice_period_days ? Number(form.notice_period_days) : null,
      linkedin_url: form.linkedin_url.trim() || null,
      github_url: form.github_url.trim() || null,
      portfolio_url: form.portfolio_url.trim() || null,
      highest_qualification: form.highest_qualification.trim() || null,
      institution: form.institution.trim() || null,
      graduation_year: form.graduation_year ? Number(form.graduation_year) : null,
      cover_letter: form.cover_letter.trim() || null,
      screening_answers: buildAnswers(),
      consent_given: form.consent_given,
      privacy_policy_accepted: true,
    }

    // multipart/form-data: the JSON body plus the resume file, matching the API.
    const body = new FormData()
    body.append('application', JSON.stringify(payload))
    if (resume) body.append('resume', resume)

    try {
      const url = new URL(`${API_URL}/public/jobs/${job.id}/apply`)
      if (source) url.searchParams.set('source', source)

      const headers: Record<string, string> = {}
      const token = tokens.access()
      // Sending the token when present links the application to the signed-in account.
      if (token) headers.Authorization = `Bearer ${token}`

      const response = await fetch(url.toString(), { method: 'POST', body, headers })
      const json = await response.json()

      if (!response.ok) {
        const error = json?.error
        throw new ApiError(
          error?.code ?? 'UNKNOWN',
          error?.message ?? 'Your application could not be submitted',
          response.status,
          error?.details,
        )
      }

      setResult({
        reference_code: json.data.reference_code,
        id: json.data.application_id,
      })
      toast.success('Application submitted')
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === 'ALREADY_APPLIED') {
          toast.error('You have already applied for this role')
          onApplied()
          return
        }
        const fields = error.fieldErrors
        if (Object.keys(fields).length) {
          setErrors(fields)
          // Send the user back to the step that actually contains the problem.
          const personalFields = ['first_name', 'last_name', 'email', 'phone', 'location']
          if (Object.keys(fields).some((f) => personalFields.includes(f))) setStep(0)
        }
        toast.error(error.message)
      } else {
        toast.error('Your application could not be submitted. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function reset() {
    setStep(0)
    setForm(EMPTY)
    setAnswers({})
    setResume(null)
    setErrors({})
    setResult(null)
  }

  // ------------------------------------------------------------- success
  if (result) {
    return (
      <Modal
        open={open}
        onClose={() => {
          reset()
          onApplied()
        }}
        title="Application submitted"
        size="sm"
      >
        <div className="py-2 text-center">
          <span className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50">
            <CheckCircle2 className="h-6 w-6 text-success-600" />
          </span>
          <h3 className="mt-4 text-sm font-semibold text-ink-900">
            Thanks, {form.first_name} — we have your application
          </h3>
          <p className="mt-2 text-sm leading-relaxed text-ink-600">
            Your reference is{' '}
            <span className="font-mono font-semibold text-ink-900">{result.reference_code}</span>.
            Keep it to check your progress at any time.
          </p>
          {resume && (
            <p className="mt-3 text-xs text-ink-500">
              We are processing your resume now and will match it against this role.
            </p>
          )}
          <div className="mt-6 flex flex-col gap-2">
            <Link href={`/track?reference=${result.reference_code}&email=${encodeURIComponent(form.email)}`}>
              <Button className="w-full">Track this application</Button>
            </Link>
            <Button
              variant="secondary"
              className="w-full"
              onClick={() => {
                reset()
                onApplied()
              }}
            >
              Done
            </Button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Apply — ${job.title}`}
      description={job.company?.name ?? undefined}
      size="lg"
      footer={
        <div className="flex w-full items-center justify-between">
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0 || submitting}
          >
            Back
          </Button>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            {isLast ? (
              <Button onClick={submit} loading={submitting}>
                Submit application
              </Button>
            ) : (
              <Button onClick={next}>Continue</Button>
            )}
          </div>
        </div>
      }
    >
      {/* Step indicator */}
      <div className="mb-6 flex items-center gap-1.5">
        {steps.map((s, index) => (
          <div key={s.id} className="flex flex-1 flex-col gap-1.5">
            <div
              className={cn(
                'h-1 rounded-full transition-colors',
                index < step ? 'bg-success-500' : index === step ? 'bg-ink-900' : 'bg-ink-200',
              )}
            />
            <span
              className={cn(
                'hidden text-[10px] font-medium sm:block',
                index === step ? 'text-ink-900' : 'text-ink-400',
              )}
            >
              {s.label}
            </span>
          </div>
        ))}
      </div>

      {current.id === 'personal' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="First name"
            name="first_name"
            required
            value={form.first_name}
            onChange={(e) => update('first_name', e.target.value)}
            error={errors.first_name}
          />
          <Input
            label="Last name"
            name="last_name"
            required
            value={form.last_name}
            onChange={(e) => update('last_name', e.target.value)}
            error={errors.last_name}
          />
          <Input
            label="Email"
            name="email"
            type="email"
            required
            value={form.email}
            onChange={(e) => update('email', e.target.value)}
            error={errors.email}
            hint="We will send updates about your application here"
            className="sm:col-span-2"
          />
          <Input
            label="Phone"
            name="phone"
            type="tel"
            value={form.phone}
            onChange={(e) => update('phone', e.target.value)}
            error={errors.phone}
          />
          <Input
            label="Location"
            name="location"
            value={form.location}
            onChange={(e) => update('location', e.target.value)}
            placeholder="City, Country"
          />
        </div>
      )}

      {current.id === 'professional' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Current job title"
            name="current_designation"
            value={form.current_designation}
            onChange={(e) => update('current_designation', e.target.value)}
          />
          <Input
            label="Current company"
            name="current_company"
            value={form.current_company}
            onChange={(e) => update('current_company', e.target.value)}
          />
          <Input
            label="Total experience (years)"
            name="total_experience_years"
            type="number"
            min={0}
            max={60}
            step={0.5}
            value={form.total_experience_years}
            onChange={(e) => update('total_experience_years', e.target.value)}
            error={errors.total_experience_years}
          />
          <Input
            label="Notice period (days)"
            name="notice_period_days"
            type="number"
            min={0}
            max={365}
            value={form.notice_period_days}
            onChange={(e) => update('notice_period_days', e.target.value)}
          />
          <Input
            label="Expected salary"
            name="expected_salary"
            type="number"
            min={0}
            value={form.expected_salary}
            onChange={(e) => update('expected_salary', e.target.value)}
            className="sm:col-span-2"
          />
          <Input
            label="LinkedIn"
            name="linkedin_url"
            value={form.linkedin_url}
            onChange={(e) => update('linkedin_url', e.target.value)}
            placeholder="https://linkedin.com/in/..."
          />
          <Input
            label="GitHub or portfolio"
            name="github_url"
            value={form.github_url}
            onChange={(e) => update('github_url', e.target.value)}
            placeholder="https://github.com/..."
          />
        </div>
      )}

      {current.id === 'education' && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Highest qualification"
            name="highest_qualification"
            value={form.highest_qualification}
            onChange={(e) => update('highest_qualification', e.target.value)}
            placeholder="B.Tech in Computer Science"
            className="sm:col-span-2"
          />
          <Input
            label="Institution"
            name="institution"
            value={form.institution}
            onChange={(e) => update('institution', e.target.value)}
          />
          <Input
            label="Graduation year"
            name="graduation_year"
            type="number"
            min={1950}
            max={2100}
            value={form.graduation_year}
            onChange={(e) => update('graduation_year', e.target.value)}
          />
          <p className="text-xs text-ink-500 sm:col-span-2">
            If you upload a resume, we will read your full education and work history from it —
            this is only a summary.
          </p>
        </div>
      )}

      {current.id === 'resume' && (
        <div className="space-y-4">
          <div>
            <label className="label mb-2">Resume</label>
            {resume ? (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-ink-200 bg-ink-50 px-4 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <FileText className="h-5 w-5 shrink-0 text-brand-600" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-900">{resume.name}</p>
                    <p className="text-xs text-ink-500">
                      {(resume.size / 1024).toFixed(0)} KB
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setResume(null)}
                  className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-200 hover:text-ink-700"
                  aria-label="Remove file"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <label
                className={cn(
                  'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 transition-colors',
                  errors.resume
                    ? 'border-danger-300 bg-danger-50'
                    : 'border-ink-300 hover:border-brand-400 hover:bg-brand-50/40',
                )}
              >
                <Upload className="h-6 w-6 text-ink-400" />
                <span className="text-sm font-medium text-ink-800">
                  Click to upload your resume
                </span>
                <span className="text-xs text-ink-500">PDF or DOCX, up to {MAX_RESUME_MB} MB</span>
                <input
                  type="file"
                  accept=".pdf,.docx"
                  className="hidden"
                  onChange={(e) => {
                    setResume(e.target.files?.[0] ?? null)
                    setErrors((prev) => {
                      const next = { ...prev }
                      delete next.resume
                      return next
                    })
                  }}
                />
              </label>
            )}
            {errors.resume && <p className="mt-1.5 text-xs text-danger-600">{errors.resume}</p>}
            <p className="mt-2 text-xs text-ink-500">
              Optional, but strongly recommended — we parse your resume to build your profile and
              match it against this role.
            </p>
          </div>

          <Textarea
            label="Cover letter"
            name="cover_letter"
            value={form.cover_letter}
            onChange={(e) => update('cover_letter', e.target.value)}
            placeholder="Anything you would like the hiring team to know"
            rows={5}
          />
        </div>
      )}

      {current.id === 'screening' && (
        <div className="space-y-5">
          {job.screening_questions.map((question) => (
            <ScreeningField
              key={question.id}
              question={question}
              value={answers[question.id]}
              error={errors[question.id]}
              onChange={(value) => {
                setAnswers((prev) => ({ ...prev, [question.id]: value }))
                setErrors((prev) => {
                  const next = { ...prev }
                  delete next[question.id]
                  return next
                })
              }}
            />
          ))}
        </div>
      )}

      {current.id === 'consent' && (
        <div className="space-y-5">
          <div className="rounded-xl bg-ink-50 p-4">
            <h4 className="text-sm font-semibold text-ink-900">Review your application</h4>
            <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {[
                ['Name', `${form.first_name} ${form.last_name}`.trim() || '—'],
                ['Email', form.email || '—'],
                ['Phone', form.phone || '—'],
                ['Location', form.location || '—'],
                ['Current role', form.current_designation || '—'],
                ['Experience', form.total_experience_years ? `${form.total_experience_years} years` : '—'],
                ['Resume', resume?.name ?? 'Not attached'],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 sm:block">
                  <dt className="text-ink-500">{label}</dt>
                  <dd className="truncate font-medium text-ink-900">{value}</dd>
                </div>
              ))}
            </dl>
          </div>

          <label
            className={cn(
              'flex cursor-pointer gap-3 rounded-xl border p-4 transition-colors',
              errors.consent_given ? 'border-danger-300 bg-danger-50' : 'border-ink-200',
            )}
          >
            <input
              type="checkbox"
              checked={form.consent_given}
              onChange={(e) => update('consent_given', e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
            />
            <span className="text-sm leading-relaxed text-ink-700">
              I consent to {job.company?.name ?? 'this company'} storing and processing my
              application data — including my resume — to assess me for this role. I understand
              my application will be analysed automatically to match it against the job
              requirements, and that hiring decisions are made by their team.
            </span>
          </label>
          {errors.consent_given && (
            <p className="-mt-3 text-xs text-danger-600">{errors.consent_given}</p>
          )}
        </div>
      )}
    </Modal>
  )
}

function ScreeningField({
  question,
  value,
  error,
  onChange,
}: {
  question: ScreeningQuestion
  value: unknown
  error?: string
  onChange: (value: unknown) => void
}) {
  const label = (
    <span className="label mb-1.5 block">
      {question.question}
      {question.is_required && <span className="ml-0.5 text-danger-600">*</span>}
    </span>
  )

  switch (question.question_type) {
    case 'YES_NO':
      return (
        <div>
          {label}
          <div className="flex gap-2">
            {['yes', 'no'].map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onChange(option)}
                className={cn(
                  'flex-1 rounded-xl border px-4 py-2.5 text-sm font-medium capitalize transition-colors',
                  value === option
                    ? 'border-brand-600 bg-brand-50 text-brand-700'
                    : 'border-ink-300 text-ink-700 hover:bg-ink-50',
                )}
              >
                {option}
              </button>
            ))}
          </div>
          {error && <p className="mt-1.5 text-xs text-danger-600">{error}</p>}
        </div>
      )

    case 'SINGLE_CHOICE':
      return (
        <Select
          label={question.question}
          value={(value as string) ?? ''}
          error={error}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Select an option</option>
          {question.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </Select>
      )

    case 'MULTIPLE_CHOICE': {
      const selected = (value as string[]) ?? []
      return (
        <div>
          {label}
          <div className="space-y-1.5">
            {question.options.map((option) => (
              <label key={option} className="flex cursor-pointer items-center gap-2.5 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(option)}
                  onChange={() =>
                    onChange(
                      selected.includes(option)
                        ? selected.filter((o) => o !== option)
                        : [...selected, option],
                    )
                  }
                  className="h-4 w-4 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="text-ink-700">{option}</span>
              </label>
            ))}
          </div>
          {error && <p className="mt-1.5 text-xs text-danger-600">{error}</p>}
        </div>
      )
    }

    case 'NUMERIC':
    case 'EXPERIENCE':
    case 'SALARY':
    case 'NOTICE_PERIOD':
      return (
        <Input
          label={question.question}
          type="number"
          min={0}
          step={question.question_type === 'EXPERIENCE' ? 0.5 : 1}
          required={question.is_required}
          value={(value as string) ?? ''}
          error={error}
          onChange={(e) => onChange(e.target.value)}
        />
      )

    default:
      return (
        <Textarea
          label={question.question}
          required={question.is_required}
          value={(value as string) ?? ''}
          error={error}
          rows={3}
          onChange={(e) => onChange(e.target.value)}
        />
      )
  }
}

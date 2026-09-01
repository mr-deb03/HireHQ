'use client'

import { useMutation } from '@tanstack/react-query'
import { ArrowLeft, Check, Plus, Sparkles, X } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Input,
  Select,
  Textarea,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import type { JobAnalysis, JobDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

interface SkillDraft {
  name: string
  weight: number
  importance: 'REQUIRED' | 'PREFERRED'
}

export default function CreateJobPage() {
  const router = useRouter()

  const [step, setStep] = useState<'details' | 'review' | 'done'>('details')
  const [form, setForm] = useState({
    title: '',
    description: '',
    location_text: '',
    work_mode: 'ONSITE',
    employment_type: 'FULL_TIME',
    min_experience_years: '0',
    max_experience_years: '',
    salary_min: '',
    salary_max: '',
    openings: '1',
  })

  const [analysis, setAnalysis] = useState<JobAnalysis | null>(null)
  const [skills, setSkills] = useState<SkillDraft[]>([])
  const [responsibilities, setResponsibilities] = useState<string[]>([])
  const [education, setEducation] = useState<string[]>([])
  const [newSkill, setNewSkill] = useState('')
  const [createdJob, setCreatedJob] = useState<JobDetail | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // ------------------------------------------------------- AI analysis
  const analyseMutation = useMutation({
    mutationFn: () =>
      api.post<JobAnalysis>('/jobs/analyze-description', {
        title: form.title,
        description: form.description,
      }),
    onSuccess: (result) => {
      setAnalysis(result)
      setSkills([
        ...result.required_skills.map((s) => ({
          name: s.name,
          weight: 3,
          importance: 'REQUIRED' as const,
        })),
        ...result.preferred_skills.map((s) => ({
          name: s.name,
          weight: 2,
          importance: 'PREFERRED' as const,
        })),
      ])
      setResponsibilities(result.responsibilities)
      setEducation(result.education_requirements)
      if (result.min_experience_years) {
        setForm((f) => ({
          ...f,
          min_experience_years: String(result.min_experience_years),
          max_experience_years: result.max_experience_years
            ? String(result.max_experience_years)
            : f.max_experience_years,
        }))
      }
      setStep('review')
      toast.success('Requirements extracted — review before publishing')
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not analyse the description'),
  })

  // ---------------------------------------------------- create the job
  const createMutation = useMutation({
    mutationFn: async () => {
      const job = await api.post<JobDetail>('/jobs', {
        title: form.title,
        description: form.description,
        location_text: form.location_text || null,
        work_mode: form.work_mode,
        employment_type: form.employment_type,
        min_experience_years: Number(form.min_experience_years) || 0,
        max_experience_years: form.max_experience_years
          ? Number(form.max_experience_years)
          : null,
        salary_min: form.salary_min ? Number(form.salary_min) : null,
        salary_max: form.salary_max ? Number(form.salary_max) : null,
        openings: Number(form.openings) || 1,
        responsibilities,
        education_requirements: education,
        required_skills: skills
          .filter((s) => s.importance === 'REQUIRED')
          .map((s) => ({ name: s.name, weight: s.weight })),
        preferred_skills: skills
          .filter((s) => s.importance === 'PREFERRED')
          .map((s) => ({ name: s.name, weight: s.weight })),
      })
      return job
    },
    onSuccess: (job) => {
      setCreatedJob(job)
      setStep('done')
      toast.success('Job created as a draft')
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        setErrors(error.fieldErrors)
        toast.error(error.message)
      } else {
        toast.error('Could not create the job')
      }
    },
  })

  const publishMutation = useMutation({
    mutationFn: () => api.post<JobDetail>(`/jobs/${createdJob!.id}/publish`),
    onSuccess: (job) => {
      toast.success('Job published')
      router.push(`/recruiter/jobs/${job.id}`)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.details?.problems) {
        const problems = error.details.problems as string[]
        toast.error(`Not ready to publish: ${problems.join('; ')}`)
      } else {
        toast.error(error instanceof ApiError ? error.message : 'Could not publish')
      }
    },
  })

  function validateDetails() {
    const found: Record<string, string> = {}
    if (form.title.trim().length < 3) found.title = 'Enter a job title'
    if (form.description.trim().length < 100) {
      found.description = 'Write at least 100 characters so the analysis has something to work with'
    }
    setErrors(found)
    return Object.keys(found).length === 0
  }

  function addSkill(importance: 'REQUIRED' | 'PREFERRED') {
    const name = newSkill.trim()
    if (!name) return
    if (skills.some((s) => s.name.toLowerCase() === name.toLowerCase())) {
      toast.error('That skill is already listed')
      return
    }
    setSkills([...skills, { name, weight: importance === 'REQUIRED' ? 3 : 2, importance }])
    setNewSkill('')
  }

  return (
    <>
      <PageHeader
        title="Create a job"
        description="Write the description, let HireHQ extract the requirements, then confirm them."
        actions={
          <Link href="/recruiter/jobs">
            <Button variant="ghost">
              <ArrowLeft className="h-4 w-4" />
              Back to jobs
            </Button>
          </Link>
        }
      />

      <PageBody className="max-w-4xl">
        {/* ------------------------------------------------------ step 1 */}
        {step === 'details' && (
          <Card>
            <CardHeader>
              <CardTitle>Job details</CardTitle>
            </CardHeader>
            <CardBody className="space-y-5">
              <Input
                label="Job title"
                required
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                error={errors.title}
                placeholder="Senior React Developer"
              />

              <Textarea
                label="Job description"
                required
                rows={14}
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                error={errors.description}
                hint="Include responsibilities and requirements. The more structure, the better the extraction."
                placeholder={
                  'We are looking for...\n\nResponsibilities:\n- ...\n\nRequirements:\n- 4+ years of experience\n- Strong React and TypeScript\n\nNice to have:\n- AWS, Docker'
                }
              />

              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Location"
                  value={form.location_text}
                  onChange={(e) => setForm({ ...form, location_text: e.target.value })}
                  placeholder="Bengaluru, Karnataka"
                />
                <Select
                  label="Work mode"
                  value={form.work_mode}
                  onChange={(e) => setForm({ ...form, work_mode: e.target.value })}
                >
                  <option value="ONSITE">On-site</option>
                  <option value="HYBRID">Hybrid</option>
                  <option value="REMOTE">Remote</option>
                </Select>
                <Select
                  label="Employment type"
                  value={form.employment_type}
                  onChange={(e) => setForm({ ...form, employment_type: e.target.value })}
                >
                  <option value="FULL_TIME">Full-time</option>
                  <option value="PART_TIME">Part-time</option>
                  <option value="CONTRACT">Contract</option>
                  <option value="INTERNSHIP">Internship</option>
                  <option value="FRESHER">Fresher</option>
                </Select>
                <Input
                  label="Openings"
                  type="number"
                  min={1}
                  value={form.openings}
                  onChange={(e) => setForm({ ...form, openings: e.target.value })}
                />
                <Input
                  label="Minimum salary"
                  type="number"
                  min={0}
                  value={form.salary_min}
                  onChange={(e) => setForm({ ...form, salary_min: e.target.value })}
                />
                <Input
                  label="Maximum salary"
                  type="number"
                  min={0}
                  value={form.salary_max}
                  onChange={(e) => setForm({ ...form, salary_max: e.target.value })}
                  error={errors.salary_max}
                />
              </div>

              <div className="flex justify-end gap-2 border-t border-ink-100 pt-4">
                <Button
                  onClick={() => {
                    if (validateDetails()) analyseMutation.mutate()
                  }}
                  loading={analyseMutation.isPending}
                >
                  <Sparkles className="h-4 w-4" />
                  Analyse and continue
                </Button>
              </div>
            </CardBody>
          </Card>
        )}

        {/* ------------------------------------------------------ step 2 */}
        {step === 'review' && analysis && (
          <div className="space-y-6">
            <Card className="border-brand-100 bg-brand-50/50">
              <CardBody className="flex items-start gap-3">
                <Sparkles className="mt-0.5 h-4.5 w-4.5 shrink-0 text-brand-600" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-brand-800">
                    Review these requirements before publishing
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-brand-700">
                    Extracted by <span className="font-medium">{analysis.engine}</span> with{' '}
                    {Math.round(analysis.confidence * 100)}% confidence. Nothing is applied to the
                    job until you confirm — edit anything that looks wrong.
                  </p>
                  {analysis.confidence < 0.6 && (
                    <p className="mt-2 rounded-lg bg-warning-50 px-2.5 py-1.5 text-xs text-warning-700">
                      Confidence is low. The description may be too short or unstructured — check
                      the skills carefully.
                    </p>
                  )}
                </div>
              </CardBody>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Skills and requirements</CardTitle>
              </CardHeader>
              <CardBody className="space-y-5">
                {(['REQUIRED', 'PREFERRED'] as const).map((importance) => (
                  <div key={importance}>
                    <h4 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
                      {importance === 'REQUIRED' ? 'Required skills' : 'Preferred skills'}
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {skills.filter((s) => s.importance === importance).length === 0 && (
                        <p className="text-sm text-ink-400">
                          None {importance === 'REQUIRED' ? '— add at least one' : ''}
                        </p>
                      )}
                      {skills
                        .filter((s) => s.importance === importance)
                        .map((skill) => (
                          <span
                            key={skill.name}
                            className={cn(
                              'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1 ring-inset',
                              importance === 'REQUIRED'
                                ? 'bg-brand-50 text-brand-700 ring-brand-100'
                                : 'bg-ink-100 text-ink-700 ring-ink-200',
                            )}
                          >
                            {skill.name}
                            {importance === 'REQUIRED' && (
                              <select
                                value={skill.weight}
                                onChange={(e) =>
                                  setSkills(
                                    skills.map((s) =>
                                      s.name === skill.name
                                        ? { ...s, weight: Number(e.target.value) }
                                        : s,
                                    ),
                                  )
                                }
                                aria-label={`Importance of ${skill.name}`}
                                className="rounded border-0 bg-white/70 py-0 pl-1 pr-4 text-[10px] font-semibold focus:ring-1 focus:ring-brand-400"
                              >
                                {[1, 2, 3, 4, 5].map((w) => (
                                  <option key={w} value={w}>
                                    ×{w}
                                  </option>
                                ))}
                              </select>
                            )}
                            <button
                              onClick={() =>
                                setSkills(skills.filter((s) => s.name !== skill.name))
                              }
                              aria-label={`Remove ${skill.name}`}
                              className="rounded p-0.5 hover:bg-black/10"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </span>
                        ))}
                    </div>
                  </div>
                ))}

                <div className="flex gap-2 border-t border-ink-100 pt-4">
                  <input
                    value={newSkill}
                    onChange={(e) => setNewSkill(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addSkill('REQUIRED')
                      }
                    }}
                    placeholder="Add a skill"
                    className="input flex-1"
                  />
                  <Button variant="secondary" onClick={() => addSkill('REQUIRED')}>
                    <Plus className="h-3.5 w-3.5" />
                    Required
                  </Button>
                  <Button variant="ghost" onClick={() => addSkill('PREFERRED')}>
                    Preferred
                  </Button>
                </div>

                <p className="text-xs leading-relaxed text-ink-500">
                  The multiplier sets how much each required skill counts towards the skills
                  score. A ×5 skill matters five times more than a ×1 skill.
                </p>
              </CardBody>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Responsibilities</CardTitle>
              </CardHeader>
              <CardBody>
                {responsibilities.length === 0 ? (
                  <p className="text-sm text-ink-400">
                    None extracted. Candidates are matched against these, so adding a few
                    improves scoring accuracy.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {responsibilities.map((item, index) => (
                      <li key={index} className="flex items-start gap-2.5">
                        <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-400" />
                        <span className="flex-1 text-sm text-ink-700">{item}</span>
                        <button
                          onClick={() =>
                            setResponsibilities(responsibilities.filter((_, i) => i !== index))
                          }
                          aria-label="Remove"
                          className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Education and experience</CardTitle>
              </CardHeader>
              <CardBody className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {education.length === 0 ? (
                    <p className="text-sm text-ink-400">No education requirement.</p>
                  ) : (
                    education.map((item) => (
                      <span
                        key={item}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-ink-100 px-2.5 py-1.5 text-xs font-medium text-ink-700"
                      >
                        {item}
                        <button
                          onClick={() => setEducation(education.filter((e) => e !== item))}
                          aria-label={`Remove ${item}`}
                          className="rounded p-0.5 hover:bg-black/10"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))
                  )}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <Input
                    label="Minimum experience (years)"
                    type="number"
                    min={0}
                    value={form.min_experience_years}
                    onChange={(e) =>
                      setForm({ ...form, min_experience_years: e.target.value })
                    }
                  />
                  <Input
                    label="Maximum experience (years)"
                    type="number"
                    min={0}
                    value={form.max_experience_years}
                    onChange={(e) =>
                      setForm({ ...form, max_experience_years: e.target.value })
                    }
                  />
                </div>
              </CardBody>
            </Card>

            <div className="flex justify-between">
              <Button variant="ghost" onClick={() => setStep('details')}>
                <ArrowLeft className="h-4 w-4" />
                Edit description
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                loading={createMutation.isPending}
                disabled={skills.filter((s) => s.importance === 'REQUIRED').length === 0}
              >
                <Check className="h-4 w-4" />
                Confirm and create draft
              </Button>
            </div>
          </div>
        )}

        {/* ------------------------------------------------------ step 3 */}
        {step === 'done' && createdJob && (
          <Card>
            <CardBody className="py-10 text-center">
              <span className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50">
                <Check className="h-6 w-6 text-success-600" />
              </span>
              <h2 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
                {createdJob.title} is ready
              </h2>
              <p className="mt-2 text-sm text-ink-600">
                Saved as a draft with {createdJob.skills.length} requirements. Reference{' '}
                <span className="font-mono font-medium">{createdJob.reference_code}</span>.
              </p>
              <div className="mt-4 flex justify-center">
                <Badge tone="neutral">{createdJob.status}</Badge>
              </div>

              <div className="mt-7 flex flex-wrap justify-center gap-3">
                <Button
                  onClick={() => publishMutation.mutate()}
                  loading={publishMutation.isPending}
                >
                  Publish now
                </Button>
                <Link href={`/recruiter/jobs/${createdJob.id}`}>
                  <Button variant="secondary">Review the job first</Button>
                </Link>
              </div>
            </CardBody>
          </Card>
        )}
      </PageBody>
    </>
  )
}

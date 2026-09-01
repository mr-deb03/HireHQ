'use client'

import {
  ArrowRight,
  BarChart3,
  Brain,
  CalendarCheck,
  CheckCircle2,
  FileSearch,
  Search,
  ShieldCheck,
  Workflow,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { PublicFooter, PublicHeader } from '@/components/marketing'
import { Button } from '@/components/ui'

const PIPELINE = [
  { label: 'Application', detail: 'Candidate applies' },
  { label: 'Resume parsed', detail: 'Structured profile' },
  { label: 'ATS score', detail: 'Explainable match' },
  { label: 'Shortlist', detail: 'Recruiter confirms' },
  { label: 'Interview', detail: 'Scheduled + reminders' },
  { label: 'Offer', detail: 'Sent and tracked' },
  { label: 'Hired', detail: 'Onboarding starts' },
]

const FEATURES = [
  {
    icon: FileSearch,
    title: 'Resume parsing that holds up',
    body:
      'PDFs and Word documents are validated, scanned and parsed into structured skills, ' +
      'experience and education — with a confidence score, so weak extractions get flagged ' +
      'rather than trusted.',
  },
  {
    icon: Brain,
    title: 'Explainable ATS scoring',
    body:
      'Five independent dimensions — skills, experience, education, responsibilities and ' +
      'semantic fit — each with its own reasoning. Weights are configurable per company ' +
      'and per job.',
  },
  {
    icon: Workflow,
    title: 'Automation with a human gate',
    body:
      'Build trigger → condition → action workflows that shortlist, tag, email and notify. ' +
      'Anything consequential — rejecting, hiring, offering — requires human approval.',
  },
  {
    icon: CalendarCheck,
    title: 'Interviews end to end',
    body:
      'Conflict-checked scheduling, calendar sync, automatic reminders and structured ' +
      'scorecards, with private interviewer remarks that candidates never see.',
  },
  {
    icon: BarChart3,
    title: 'Analytics that answer questions',
    body:
      'Funnel conversion, source performance, ATS distribution, time-to-hire and time in ' +
      'each stage — all computed in the database, not in a spreadsheet.',
  },
  {
    icon: ShieldCheck,
    title: 'Built for multi-tenant SaaS',
    body:
      'Strict tenant isolation, role-based access control, immutable audit logs, signed ' +
      'file URLs and candidate consent tracking from the first line of schema.',
  },
]

export default function LandingPage() {
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')

  function search(event: React.FormEvent) {
    event.preventDefault()
    const params = new URLSearchParams()
    if (query.trim()) params.set('q', query.trim())
    if (location.trim()) params.set('location', location.trim())
    router.push(`/jobs${params.toString() ? `?${params}` : ''}`)
  }

  return (
    <div className="flex min-h-full flex-col bg-white">
      <PublicHeader />

      <main className="flex-1">
        {/* ---------------------------------------------------------- hero */}
        <section className="relative overflow-hidden border-b border-ink-200">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_50%_at_50%_0%,theme(colors.brand.50),transparent)]"
          />
          <div className="relative mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
            <div className="mx-auto max-w-3xl text-center">
              <span className="inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white px-3 py-1 text-xs font-medium text-ink-600 shadow-sm">
                <span className="h-1.5 w-1.5 rounded-full bg-success-500" />
                Applicant tracking, job portal and hiring automation
              </span>

              <h1 className="mt-6 text-balance text-4xl font-semibold tracking-tight text-ink-900 sm:text-display-lg">
                From application to hire — automated
              </h1>

              <p className="mx-auto mt-5 max-w-2xl text-balance text-lg leading-relaxed text-ink-600">
                HireHQ parses every resume, scores every application against the role with a
                breakdown you can actually read, and moves candidates through your pipeline —
                while your team keeps every decision that matters.
              </p>

              <form
                onSubmit={search}
                className="mx-auto mt-9 flex max-w-2xl flex-col gap-2 rounded-2xl border border-ink-200 bg-white p-2 shadow-card sm:flex-row"
              >
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Job title, skill or company"
                    aria-label="Job title, skill or company"
                    className="h-11 w-full rounded-xl border-0 bg-transparent pl-9 pr-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none"
                  />
                </div>
                <div className="hidden w-px bg-ink-200 sm:block" />
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Location"
                  aria-label="Location"
                  className="h-11 rounded-xl border-0 bg-transparent px-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none sm:w-44"
                />
                <Button type="submit" size="lg" className="shrink-0">
                  Search jobs
                </Button>
              </form>

              <p className="mt-4 text-sm text-ink-500">
                Or{' '}
                <Link href="/jobs" className="font-medium text-brand-600 hover:text-brand-700">
                  browse every open role
                </Link>
              </p>
            </div>
          </div>
        </section>

        {/* -------------------------------------------------- how it works */}
        <section id="how-it-works" className="border-b border-ink-200 bg-ink-50 py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="max-w-2xl">
              <h2 className="text-title-lg font-semibold tracking-tight text-ink-900">
                One pipeline, from click to contract
              </h2>
              <p className="mt-3 text-ink-600">
                Every stage is automated where it is safe to automate, and paused where a
                person should decide.
              </p>
            </div>

            <ol className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
              {PIPELINE.map((step, index) => (
                <li key={step.label} className="relative">
                  <div className="card h-full px-4 py-4">
                    <span className="inline-flex h-6 w-6 items-center justify-center rounded-lg bg-ink-900 text-[11px] font-semibold text-white">
                      {index + 1}
                    </span>
                    <p className="mt-3 text-sm font-semibold text-ink-900">{step.label}</p>
                    <p className="mt-1 text-xs leading-relaxed text-ink-500">{step.detail}</p>
                  </div>
                  {index < PIPELINE.length - 1 && (
                    <ArrowRight
                      aria-hidden
                      className="absolute -right-2.5 top-1/2 hidden h-4 w-4 -translate-y-1/2 text-ink-300 lg:block"
                    />
                  )}
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ------------------------------------------------------ features */}
        <section id="for-recruiters" className="py-20">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="max-w-2xl">
              <h2 className="text-title-lg font-semibold tracking-tight text-ink-900">
                Built for recruiters who are drowning in applications
              </h2>
              <p className="mt-3 text-ink-600">
                Hundreds of applications per role, reviewed properly, without hiring three more
                coordinators.
              </p>
            </div>

            <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature) => (
                <div key={feature.title} className="card p-5">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
                    <feature.icon className="h-4.5 w-4.5" />
                  </span>
                  <h3 className="mt-4 text-sm font-semibold text-ink-900">{feature.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-600">{feature.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------------------------------------------------- governance */}
        <section className="border-y border-ink-200 bg-ink-900 py-16 text-white">
          <div className="mx-auto max-w-6xl px-4 sm:px-6">
            <div className="grid gap-10 lg:grid-cols-2 lg:items-center">
              <div>
                <h2 className="text-title-lg font-semibold tracking-tight">
                  Automation you can defend
                </h2>
                <p className="mt-3 leading-relaxed text-ink-300">
                  Screening software makes decisions about people&apos;s livelihoods. HireHQ is
                  built so those decisions stay reviewable, reversible and attributable.
                </p>
                <Link href="/jobs" className="mt-6 inline-block">
                  <Button variant="secondary" size="lg">
                    See open roles
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </Link>
              </div>

              <ul className="space-y-3">
                {[
                  'No candidate is ever rejected automatically — automation can advance, only people can decline.',
                  'Every ATS score stores the weights and reasoning used, so it can be audited later.',
                  'Protected attributes are never inferred, stored, or used in scoring.',
                  'Every AI-assisted output is logged with the engine that produced it and the human who reviewed it.',
                  'When an integration is not configured, the product says so — it never fakes a sent email.',
                ].map((line) => (
                  <li key={line} className="flex gap-3">
                    <CheckCircle2 className="mt-0.5 h-4.5 w-4.5 shrink-0 text-success-500" />
                    <span className="text-sm leading-relaxed text-ink-200">{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------ cta */}
        <section className="py-20">
          <div className="mx-auto max-w-3xl px-4 text-center sm:px-6">
            <h2 className="text-title-lg font-semibold tracking-tight text-ink-900">
              Ready to look at your pipeline?
            </h2>
            <p className="mt-3 text-ink-600">
              Create a candidate account to apply for roles, or sign in with a recruiter
              account to see the full hiring workspace.
            </p>
            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <Link href="/register">
                <Button size="lg">Create an account</Button>
              </Link>
              <Link href="/jobs">
                <Button variant="secondary" size="lg">
                  Browse jobs
                </Button>
              </Link>
            </div>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  )
}

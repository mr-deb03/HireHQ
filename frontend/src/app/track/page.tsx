'use client'

import { useMutation } from '@tanstack/react-query'
import { Building2, PackageSearch, Search } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { Logo } from '@/components/marketing'
import { Button, Card, EmptyState, Input } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import type { TrackedApplication } from '@/lib/types'
import { formatDate, formatRelative } from '@/lib/utils'

function TrackContent() {
  const params = useSearchParams()
  const [reference, setReference] = useState(params.get('ref') ?? '')
  const [email, setEmail] = useState('')

  const lookup = useMutation({
    mutationFn: ({ code, address }: { code: string; address: string }) =>
      api.get<TrackedApplication>(`/public/track/${encodeURIComponent(code.trim())}`, {
        auth: false,
        query: { email: address.trim() },
      }),
  })

  const notFound = lookup.error instanceof ApiError && lookup.error.status === 404

  return (
    <div className="min-h-full bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-4">
          <Logo />
          <Link href="/jobs" className="text-sm font-medium text-ink-600 hover:text-ink-900">
            Browse jobs
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-title-lg font-semibold tracking-tight text-ink-900">
          Track your application
        </h1>
        <p className="mt-1.5 text-sm text-ink-600">
          Enter the reference code from your confirmation email, plus the address you
          applied with. No account needed.
        </p>

        <Card className="mt-6 p-5">
          <form
            onSubmit={(event) => {
              event.preventDefault()
              if (reference.trim() && email.trim()) {
                lookup.mutate({ code: reference, address: email })
              }
            }}
            className="space-y-4"
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Reference code"
                name="reference"
                required
                placeholder="APP-2024-0001"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                className="font-mono uppercase"
              />
              <Input
                label="Email you applied with"
                name="email"
                type="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>

            {/*
              Both are required by the server. A reference code on its own would let
              anyone who guessed one read a stranger's progress.
            */}
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-ink-500">
                Both are needed so nobody else can look up your application.
              </p>
              <Button type="submit" size="lg" loading={lookup.isPending} className="w-40">
                <Search className="h-4 w-4" />
                Track
              </Button>
            </div>
          </form>
        </Card>

        {lookup.isError && (
          <Card className="mt-5">
            <EmptyState
              icon={PackageSearch}
              title={notFound ? 'No matching application' : 'Could not look that up'}
              description={
                notFound
                  ? 'Check both the reference code and the email address against your confirmation email — they have to match the same application.'
                  : (lookup.error as Error).message
              }
            />
          </Card>
        )}

        {lookup.isSuccess && <TrackResult application={lookup.data} />}
      </div>
    </div>
  )
}

function TrackResult({ application }: { application: TrackedApplication }) {
  return (
    <div className="mt-6 space-y-5">
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="font-mono text-xs text-ink-400">{application.reference_code}</p>
            <h2 className="mt-1 text-[17px] font-semibold text-ink-900">
              {application.job_title ?? 'Application'}
            </h2>
            {application.company_name && (
              <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-600">
                <Building2 className="h-3.5 w-3.5 text-ink-400" />
                {application.company_name}
              </p>
            )}
          </div>
          <span className="rounded-full bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-700 ring-1 ring-inset ring-brand-100">
            {application.status}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-2 border-t border-ink-100 pt-4 text-sm">
          <div>
            <span className="text-ink-400">Applied</span>{' '}
            <span className="text-ink-800">{formatDate(application.applied_at)}</span>
          </div>
          {application.last_updated && (
            <div>
              <span className="text-ink-400">Last updated</span>{' '}
              <span className="text-ink-800">{formatRelative(application.last_updated)}</span>
            </div>
          )}
        </div>
      </Card>

      <Card className="p-5">
        <h3 className="text-sm font-semibold text-ink-900">Progress</h3>
        {/*
          The server sends only events flagged as candidate-visible, so internal notes,
          scores and interviewer remarks cannot appear here (§28).
        */}
        {application.timeline.length === 0 ? (
          <p className="mt-3 text-sm text-ink-500">
            No updates yet. You will see each step here as it happens.
          </p>
        ) : (
          <ol className="mt-4 space-y-0">
            {application.timeline.map((event, index) => (
              <li key={`${event.at}-${index}`} className="relative flex gap-4 pb-6 last:pb-0">
                <div className="flex flex-col items-center">
                  <span
                    className={
                      index === 0
                        ? 'mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-brand-500 ring-4 ring-brand-100'
                        : 'mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-ink-300'
                    }
                  />
                  {index < application.timeline.length - 1 && (
                    <span className="mt-1 w-px flex-1 bg-ink-200" />
                  )}
                </div>
                <div className="-mt-0.5 min-w-0 flex-1">
                  <p className="text-sm font-medium text-ink-900">{event.title}</p>
                  {event.description && (
                    <p className="mt-0.5 text-sm leading-relaxed text-ink-600">
                      {event.description}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-ink-400">{formatRelative(event.at)}</p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>

      <p className="text-center text-sm text-ink-500">
        Want interview invitations and offers in one place?{' '}
        <Link href="/register" className="font-medium text-brand-600 hover:text-brand-700">
          Create a free account
        </Link>
      </p>
    </div>
  )
}

export default function TrackPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <TrackContent />
    </Suspense>
  )
}

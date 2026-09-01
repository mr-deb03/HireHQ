'use client'

/**
 * Platform overview for super admins.
 *
 * The provider panel is the most useful thing here: it reports what is *genuinely*
 * configured — whether the AI is a real model or the deterministic local engine, whether
 * storage is durable, whether email actually transmits. An operator can see at a glance
 * which parts of the product are running for real and which are running in a local mode,
 * which is precisely the confusion §69 exists to prevent.
 */

import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  Briefcase,
  Building2,
  CalendarDays,
  CheckCircle2,
  FileText,
  HardDrive,
  Mail,
  MinusCircle,
  Users,
} from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Card, CardBody, CardHeader, CardTitle, ErrorState, Skeleton, Stat } from '@/components/ui'
import { api } from '@/lib/api'
import type { PlatformStats } from '@/lib/types'
import { cn } from '@/lib/utils'

/** Which key on each provider entry means "this is the real thing, not a local stand-in". */
const PROVIDER_PANEL = [
  {
    key: 'ai',
    label: 'AI',
    icon: Bot,
    realKey: 'real_model',
    realText: 'Language model configured',
    fallbackText: 'Deterministic local engine — results are rule-based, not generated',
  },
  {
    key: 'storage',
    label: 'File storage',
    icon: HardDrive,
    realKey: 'durable',
    realText: 'Durable object storage',
    fallbackText: 'Local filesystem — development only, not durable',
  },
  {
    key: 'email',
    label: 'Email',
    icon: Mail,
    realKey: 'transmits',
    realText: 'Messages are delivered',
    fallbackText: 'Recorded but never delivered — no provider configured',
  },
  {
    key: 'calendar',
    label: 'Calendar',
    icon: CalendarDays,
    realKey: 'delivers_invitations',
    realText: 'Invitations are sent',
    fallbackText: 'No provider — interviews exist in HireHQ only',
  },
] as const

export default function AdminDashboardPage() {
  const statsQuery = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.get<PlatformStats>('/admin/stats'),
  })

  if (statsQuery.isLoading) {
    return (
      <PageBody>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="mt-5 h-64" />
      </PageBody>
    )
  }

  if (statsQuery.isError || !statsQuery.data) {
    return (
      <PageBody>
        <Card>
          <ErrorState
            title="Could not load platform statistics"
            message={(statsQuery.error as Error)?.message}
            onRetry={() => statsQuery.refetch()}
          />
        </Card>
      </PageBody>
    )
  }

  const stats = statsQuery.data
  const degraded = PROVIDER_PANEL.filter(
    (entry) => !stats.providers[entry.key]?.[entry.realKey],
  )

  return (
    <>
      <PageHeader title="Platform overview" description="Every company on this deployment." />

      <PageBody className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Companies"
            value={stats.companies.total ?? 0}
            change={`${stats.companies.active ?? 0} active · ${stats.companies.trial ?? 0} trial`}
            icon={Building2}
            href="/admin/companies"
          />
          <Stat
            label="Users"
            value={stats.users.total ?? 0}
            change={`${stats.users.new_this_week ?? 0} new this week`}
            icon={Users}
            href="/admin/users"
          />
          <Stat
            label="Jobs"
            value={stats.jobs.total ?? 0}
            change={`${stats.jobs.published ?? 0} published`}
            icon={Briefcase}
          />
          <Stat
            label="Applications"
            value={stats.applications.total ?? 0}
            change={`${stats.applications.this_week ?? 0} this week`}
            icon={FileText}
          />
        </div>

        {degraded.length > 0 && (
          <Notice tone="warning" title="Some integrations are not configured for real use">
            {degraded.map((entry) => entry.label).join(', ')}{' '}
            {degraded.length === 1 ? 'is' : 'are'} running in a local or unconfigured mode.
            The product reports this honestly to users rather than pretending the work
            happened — see the detail below.
          </Notice>
        )}

        <Card>
          <CardHeader>
            <CardTitle>Provider configuration</CardTitle>
          </CardHeader>
          <CardBody>
            <ul className="divide-y divide-ink-100">
              {PROVIDER_PANEL.map((entry) => {
                const provider = stats.providers[entry.key] ?? {}
                const isReal = Boolean(provider[entry.realKey])
                return (
                  <li key={entry.key} className="flex items-start gap-3 py-3.5 first:pt-0 last:pb-0">
                    <span
                      className={cn(
                        'mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                        isReal ? 'bg-success-50 text-success-600' : 'bg-warning-50 text-warning-600',
                      )}
                    >
                      <entry.icon className="h-4 w-4" />
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-ink-900">{entry.label}</p>
                        <code className="rounded bg-ink-100 px-1.5 py-0.5 text-xs text-ink-600">
                          {String(provider.name ?? 'unknown')}
                        </code>
                      </div>
                      <p className="mt-0.5 text-sm text-ink-600">
                        {isReal ? entry.realText : entry.fallbackText}
                      </p>
                    </div>

                    <span className="shrink-0">
                      {isReal ? (
                        <CheckCircle2 className="h-4 w-4 text-success-500" aria-label="Configured" />
                      ) : (
                        <MinusCircle
                          className="h-4 w-4 text-warning-500"
                          aria-label="Not configured"
                        />
                      )}
                    </span>
                  </li>
                )
              })}
            </ul>
          </CardBody>
        </Card>

        <div className="grid gap-5 sm:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Candidates</CardTitle>
            </CardHeader>
            <CardBody>
              <p className="text-3xl font-semibold tabular-nums text-ink-900">
                {stats.candidates}
              </p>
              <p className="mt-1 text-sm text-ink-500">
                Candidate records across every company. Each is scoped to its own tenant and
                is never visible from another.
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Administration</CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="space-y-2 text-sm">
                <li>
                  <Link
                    href="/admin/companies"
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    Companies →
                  </Link>
                </li>
                <li>
                  <Link
                    href="/admin/users"
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    Users across all tenants →
                  </Link>
                </li>
                <li>
                  <Link
                    href="/admin/audit-logs"
                    className="font-medium text-brand-600 hover:text-brand-700"
                  >
                    Audit log →
                  </Link>
                </li>
              </ul>
            </CardBody>
          </Card>
        </div>
      </PageBody>
    </>
  )
}

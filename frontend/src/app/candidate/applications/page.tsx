'use client'

import { useQuery } from '@tanstack/react-query'
import { ClipboardList, Search } from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { api, type Page } from '@/lib/api'
import type { MyApplication } from '@/lib/types'
import { formatRelative } from '@/lib/utils'

export default function MyApplicationsPage() {
  const query = useQuery({
    queryKey: ['my-applications', 'all'],
    queryFn: () =>
      api.get<Page<MyApplication>>('/me/applications', { query: { page_size: 50 } }),
  })

  return (
    <>
      <PageHeader
        title="Your applications"
        description="Every role you have applied for, and where each one stands."
        actions={
          <Link href="/jobs">
            <Button>
              <Search className="h-4 w-4" />
              Find more jobs
            </Button>
          </Link>
        }
      />

      <PageBody className="max-w-4xl">
        {query.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : query.isError ? (
          <Card>
            <ErrorState
              message={(query.error as Error).message}
              onRetry={() => query.refetch()}
            />
          </Card>
        ) : !query.data?.items.length ? (
          <Card>
            <EmptyState
              icon={ClipboardList}
              title="You have not applied anywhere yet"
              description="Browse open roles and submit your first application."
              action={
                <Link href="/jobs">
                  <Button>Browse jobs</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <div className="space-y-3">
            {query.data.items.map((application) => (
              <Link key={application.id} href={`/candidate/applications/${application.id}`}>
                <Card interactive className="p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h3 className="text-[15px] font-semibold text-ink-900">
                        {application.job_title}
                      </h3>
                      <p className="mt-0.5 text-sm text-ink-600">{application.company_name}</p>
                      {application.location && (
                        <p className="text-sm text-ink-500">{application.location}</p>
                      )}
                      <p className="mt-2 font-mono text-xs text-ink-400">
                        {application.reference_code}
                      </p>
                    </div>
                    <div className="text-right">
                      <Badge tone="brand">{application.status_label}</Badge>
                      <p className="mt-2 text-xs text-ink-400">
                        Applied {formatRelative(application.applied_at)}
                      </p>
                      <p className="text-xs text-ink-400">
                        Updated {formatRelative(application.last_updated)}
                      </p>
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </PageBody>
    </>
  )
}

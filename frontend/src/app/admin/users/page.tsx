'use client'

import { useQuery } from '@tanstack/react-query'
import { Search, Users } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { PageBody, PageHeader } from '@/components/app-shell'
import { DataTable, EmptyRows, Notice, Paginator, type Column } from '@/components/data'
import { Avatar, Badge, Button, Skeleton } from '@/components/ui'
import { api, type Page } from '@/lib/api'
import type { AdminUser, UserStatus } from '@/lib/types'
import { formatDate, formatRelative, titleCase } from '@/lib/utils'

const STATUS_TONES: Record<UserStatus, 'success' | 'neutral' | 'warning' | 'danger'> = {
  ACTIVE: 'success',
  PENDING_VERIFICATION: 'warning',
  INACTIVE: 'neutral',
  SUSPENDED: 'danger',
}

function UsersContent() {
  const router = useRouter()
  const params = useSearchParams()

  const query = params.get('q') ?? ''
  const companyId = params.get('company_id') ?? ''
  const page = Number(params.get('page') ?? '1')
  const [search, setSearch] = useState(query)

  const usersQuery = useQuery({
    queryKey: ['admin', 'users', query, companyId, page],
    queryFn: () =>
      api.get<Page<AdminUser>>('/admin/users', {
        query: {
          q: query || undefined,
          company_id: companyId || undefined,
          page,
          page_size: 25,
        },
      }),
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/admin/users${next.toString() ? `?${next}` : ''}`)
  }

  const columns: Column<AdminUser>[] = [
    {
      key: 'user',
      header: 'User',
      render: (user) => (
        <div className="flex items-center gap-3">
          <Avatar name={user.full_name} size="sm" />
          <div className="min-w-0">
            <span className="block truncate font-medium text-ink-900">{user.full_name}</span>
            <span className="block truncate text-xs text-ink-500">{user.email}</span>
          </div>
        </div>
      ),
    },
    {
      key: 'company',
      header: 'Company',
      render: (user) =>
        user.company && user.company_id ? (
          <button
            onClick={() => setParam('company_id', user.company_id!)}
            className="text-left text-ink-700 hover:text-brand-700"
          >
            {user.company}
          </button>
        ) : (
          <span className="text-ink-400">Platform</span>
        ),
    },
    {
      key: 'roles',
      header: 'Roles',
      hideOnMobile: true,
      render: (user) => (
        <div className="flex flex-wrap gap-1">
          {user.roles.map((role) => (
            <Badge key={role}>{titleCase(role)}</Badge>
          ))}
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (user) => <Badge tone={STATUS_TONES[user.status]}>{titleCase(user.status)}</Badge>,
    },
    {
      key: 'last_login',
      header: 'Last sign-in',
      hideOnMobile: true,
      render: (user) =>
        user.last_login_at ? formatRelative(user.last_login_at) : (
          <span className="text-ink-400">Never</span>
        ),
    },
    {
      key: 'created',
      header: 'Joined',
      hideOnMobile: true,
      render: (user) => formatDate(user.created_at),
    },
  ]

  return (
    <>
      <PageHeader
        title="Users"
        description={
          usersQuery.data
            ? `${usersQuery.data.meta.total_items} across every company`
            : 'Users across every company'
        }
      >
        <div className="mt-5 flex flex-wrap gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              setParam('q', search)
            }}
            className="relative min-w-64 flex-1"
          >
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email"
              aria-label="Search users"
              className="input pl-9"
            />
          </form>
          {companyId && (
            <Button variant="secondary" onClick={() => setParam('company_id', '')}>
              Clear company filter
            </Button>
          )}
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        <Notice tone="neutral">
          Account records only — names, roles and sign-in state. A super admin cannot read
          any company&rsquo;s candidates, applications or résumés from here; tenant
          isolation is enforced by the server, not by this page hiding a link.
        </Notice>

        <DataTable
          rows={usersQuery.data?.items}
          columns={columns}
          loading={usersQuery.isLoading}
          error={usersQuery.error as Error | null}
          onRetry={() => usersQuery.refetch()}
          rowKey={(user) => user.id}
          empty={
            <EmptyRows
              icon={Users}
              title={query || companyId ? 'No users match those filters' : 'No users yet'}
              action={
                query || companyId ? (
                  <Button variant="secondary" onClick={() => router.push('/admin/users')}>
                    Clear filters
                  </Button>
                ) : undefined
              }
            />
          }
        />

        <Paginator meta={usersQuery.data?.meta} onPage={(p) => setParam('page', String(p))} />
      </PageBody>
    </>
  )
}

export default function AdminUsersPage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <UsersContent />
    </Suspense>
  )
}

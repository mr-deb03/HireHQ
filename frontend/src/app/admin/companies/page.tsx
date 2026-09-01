'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Plus, Search } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { DataTable, EmptyRows, Notice, Paginator, type Column } from '@/components/data'
import { Badge, Button, Input, Modal, Select, Skeleton, Textarea } from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import type { AdminCompany, CompanyStatus } from '@/lib/types'
import { formatDate, titleCase } from '@/lib/utils'

const STATUS_TONES: Record<CompanyStatus, 'success' | 'neutral' | 'warning' | 'danger'> = {
  ACTIVE: 'success',
  TRIAL: 'warning',
  SUSPENDED: 'danger',
  ARCHIVED: 'neutral',
}

function CompaniesContent() {
  const router = useRouter()
  const params = useSearchParams()

  const query = params.get('q') ?? ''
  const status = params.get('status') ?? ''
  const page = Number(params.get('page') ?? '1')

  const [search, setSearch] = useState(query)
  const [creating, setCreating] = useState(false)
  const [changing, setChanging] = useState<AdminCompany | null>(null)

  const companiesQuery = useQuery({
    queryKey: ['admin', 'companies', query, status, page],
    queryFn: () =>
      api.get<Page<AdminCompany>>('/admin/companies', {
        query: { q: query || undefined, status: status || undefined, page, page_size: 25 },
      }),
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/admin/companies${next.toString() ? `?${next}` : ''}`)
  }

  const columns: Column<AdminCompany>[] = [
    {
      key: 'name',
      header: 'Company',
      render: (company) => (
        <div>
          <span className="font-medium text-ink-900">{company.name}</span>
          <span className="block font-mono text-xs text-ink-400">{company.slug}</span>
        </div>
      ),
    },
    {
      key: 'industry',
      header: 'Industry',
      hideOnMobile: true,
      render: (company) => company.industry ?? '—',
    },
    { key: 'users', header: 'Users', align: 'right', render: (company) => company.user_count },
    { key: 'jobs', header: 'Jobs', align: 'right', render: (company) => company.job_count },
    {
      key: 'applications',
      header: 'Applications',
      align: 'right',
      hideOnMobile: true,
      render: (company) => company.application_count,
    },
    {
      key: 'plan',
      header: 'Plan',
      hideOnMobile: true,
      render: (company) => <Badge>{titleCase(company.subscription_plan)}</Badge>,
    },
    {
      key: 'status',
      header: 'Status',
      render: (company) => (
        <Badge tone={STATUS_TONES[company.status]}>{titleCase(company.status)}</Badge>
      ),
    },
    {
      key: 'created',
      header: 'Created',
      hideOnMobile: true,
      render: (company) => formatDate(company.created_at),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (company) => (
        <Button variant="ghost" size="sm" onClick={() => setChanging(company)}>
          Change status
        </Button>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Companies"
        description={
          companiesQuery.data
            ? `${companiesQuery.data.meta.total_items} on this deployment`
            : 'Every tenant on this deployment'
        }
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            New company
          </Button>
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
              placeholder="Search by name"
              aria-label="Search companies"
              className="input pl-9"
            />
          </form>
          <div className="w-44">
            <Select
              value={status}
              onChange={(e) => setParam('status', e.target.value)}
              aria-label="Filter by status"
            >
              <option value="">All statuses</option>
              {(['ACTIVE', 'TRIAL', 'SUSPENDED', 'ARCHIVED'] as CompanyStatus[]).map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        <Notice tone="neutral">
          This view lists tenants and their totals. It does not open any company&rsquo;s
          candidate, application or résumé data — tenant isolation applies to super admins
          too.
        </Notice>

        <DataTable
          rows={companiesQuery.data?.items}
          columns={columns}
          loading={companiesQuery.isLoading}
          error={companiesQuery.error as Error | null}
          onRetry={() => companiesQuery.refetch()}
          rowKey={(company) => company.id}
          empty={
            <EmptyRows
              icon={Building2}
              title={query || status ? 'No companies match those filters' : 'No companies yet'}
              action={
                query || status ? (
                  <Button variant="secondary" onClick={() => router.push('/admin/companies')}>
                    Clear filters
                  </Button>
                ) : (
                  <Button onClick={() => setCreating(true)}>Create the first company</Button>
                )
              }
            />
          }
        />

        <Paginator meta={companiesQuery.data?.meta} onPage={(p) => setParam('page', String(p))} />
      </PageBody>

      {creating && <CreateCompanyModal onClose={() => setCreating(false)} />}
      {changing && <StatusModal company={changing} onClose={() => setChanging(null)} />}
    </>
  )
}

function CreateCompanyModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    name: '',
    industry: '',
    website: '',
    admin_email: '',
    admin_first_name: '',
    admin_last_name: '',
  })

  interface CompanyCreated {
    company: AdminCompany
    admin_user_id: string
    admin_email: string
    /** One-time link the new admin uses to set their password. */
    setup_link: string
    invitation_email_status: string
    message: string
  }

  const [created, setCreated] = useState<CompanyCreated | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api.post<CompanyCreated>('/admin/companies', {
        name: form.name,
        industry: form.industry || undefined,
        website: form.website || undefined,
        admin_email: form.admin_email,
        admin_first_name: form.admin_first_name,
        admin_last_name: form.admin_last_name,
      }),
    onSuccess: (result) => {
      setCreated(result)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'companies'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not create the company'),
  })

  if (created) {
    const delivered = created.invitation_email_status === 'SENT'
    return (
      <Modal
        open
        onClose={onClose}
        title="Company created"
        description={created.company.name}
        footer={<Button onClick={onClose}>Done</Button>}
      >
        <div className="space-y-4">
          <p className="text-sm text-ink-700">
            The first company admin is{' '}
            <span className="font-medium">{created.admin_email}</span>.
          </p>

          {/*
            The setup link is shown regardless of delivery, because when no email
            provider is configured this is the only way the new admin can get in — and
            saying "an invitation has been sent" would be false.
          */}
          <Notice
            tone={delivered ? 'neutral' : 'warning'}
            title={delivered ? 'Invitation sent' : 'The invitation was not emailed'}
          >
            <p className="text-sm">{created.message}</p>
            <p className="mt-2 break-all font-mono text-xs">{created.setup_link}</p>
            {!delivered && (
              <p className="mt-2 text-xs leading-relaxed">
                Pass this link to them over a channel you trust. It is single-use and
                expires.
              </p>
            )}
          </Notice>
        </div>
      </Modal>
    )
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="New company"
      description="Creates the tenant and its first administrator."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={create.isPending}
            disabled={
              !form.name.trim() ||
              !form.admin_email.trim() ||
              !form.admin_first_name.trim() ||
              !form.admin_last_name.trim()
            }
            onClick={() => create.mutate()}
          >
            Create company
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="Company name"
          required
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Industry"
            value={form.industry}
            onChange={(e) => setForm({ ...form, industry: e.target.value })}
          />
          <Input
            label="Website"
            type="url"
            placeholder="https://example.com"
            value={form.website}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
          />
        </div>

        <div className="border-t border-ink-100 pt-4">
          <p className="text-sm font-medium text-ink-900">First administrator</p>
          <p className="mt-0.5 text-xs text-ink-500">
            They can invite the rest of the team once they sign in.
          </p>
          <div className="mt-3 space-y-4">
            <Input
              label="Email"
              type="email"
              required
              value={form.admin_email}
              onChange={(e) => setForm({ ...form, admin_email: e.target.value })}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="First name"
                required
                value={form.admin_first_name}
                onChange={(e) => setForm({ ...form, admin_first_name: e.target.value })}
              />
              <Input
                label="Last name"
                required
                value={form.admin_last_name}
                onChange={(e) => setForm({ ...form, admin_last_name: e.target.value })}
              />
            </div>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function StatusModal({ company, onClose }: { company: AdminCompany; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<CompanyStatus>(company.status)
  const [reason, setReason] = useState('')

  const change = useMutation({
    mutationFn: () =>
      api.post(`/admin/companies/${company.id}/status`, {
        status,
        reason: reason || undefined,
      }),
    onSuccess: () => {
      toast.success(`${company.name} is now ${titleCase(status).toLowerCase()}.`)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'companies'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not change the status'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="Change company status"
      description={company.name}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={status === 'SUSPENDED' ? 'danger' : 'primary'}
            loading={change.isPending}
            onClick={() => change.mutate()}
          >
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value as CompanyStatus)}
        >
          {(['ACTIVE', 'TRIAL', 'SUSPENDED', 'ARCHIVED'] as CompanyStatus[]).map((value) => (
            <option key={value} value={value}>
              {titleCase(value)}
            </option>
          ))}
        </Select>

        {status === 'SUSPENDED' && (
          <Notice tone="warning" title="Suspension locks everyone out">
            Every user at {company.name} loses access immediately, including their
            administrators. Candidate data is retained, not deleted.
          </Notice>
        )}

        <Textarea
          label="Reason"
          hint="Recorded in the audit log against your account."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </div>
    </Modal>
  )
}

export default function AdminCompaniesPage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <CompaniesContent />
    </Suspense>
  )
}

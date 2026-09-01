'use client'

/**
 * Automation rules and their run history.
 *
 * The governance rule from §63 is enforced twice on the server (at save and at execution)
 * and surfaced here so a recruiter meets it before they hit an error: moving an
 * application to Rejected, Hired or Offer automatically requires "a person approves each
 * run" to be switched on. The builder shows that plainly rather than letting someone
 * design a rule the server will refuse.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  CircleSlash,
  Pencil,
  Plus,
  ShieldAlert,
  Trash2,
  Workflow as WorkflowIcon,
  Zap,
} from 'lucide-react'
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
  Modal,
  Skeleton,
  Tabs,
} from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  Workflow,
  WorkflowExecution,
  WorkflowExecutionStatus,
  WorkflowSchema,
} from '@/lib/types'
import { cn, formatRelative, titleCase } from '@/lib/utils'

import { WorkflowBuilder } from './builder'

const EXECUTION_TONES: Record<
  WorkflowExecutionStatus,
  'success' | 'neutral' | 'warning' | 'danger' | 'info'
> = {
  PENDING: 'warning',
  RUNNING: 'info',
  COMPLETED: 'success',
  FAILED: 'danger',
  SKIPPED: 'neutral',
}

function WorkflowsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const tab = params.get('tab') ?? 'rules'
  const [editing, setEditing] = useState<Workflow | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Workflow | null>(null)

  const schemaQuery = useQuery({
    queryKey: ['workflow-schema'],
    queryFn: () => api.get<WorkflowSchema>('/workflows/schema'),
    staleTime: 30 * 60 * 1000,
  })

  const workflowsQuery = useQuery({
    queryKey: ['workflows'],
    queryFn: () => api.get<Workflow[]>('/workflows'),
  })

  const toggle = useMutation({
    mutationFn: (workflow: Workflow) => api.post(`/workflows/${workflow.id}/toggle`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not change that'),
  })

  const remove = useMutation({
    mutationFn: (workflow: Workflow) => api.delete(`/workflows/${workflow.id}`),
    onSuccess: () => {
      toast.success('Workflow deleted.')
      void queryClient.invalidateQueries({ queryKey: ['workflows'] })
      setDeleting(null)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not delete'),
  })

  return (
    <>
      <PageHeader
        title="Workflows"
        description="Rules that act on applications automatically."
        actions={
          can('workflow:manage') && (
            <Button size="sm" onClick={() => setEditing('new')}>
              <Plus className="h-4 w-4" />
              New workflow
            </Button>
          )
        }
      >
        <div className="mt-5">
          <Tabs
            tabs={[
              { id: 'rules', label: 'Rules', count: workflowsQuery.data?.length },
              { id: 'runs', label: 'Run history' },
              { id: 'approvals', label: 'Awaiting approval' },
            ]}
            active={tab}
            onChange={(id) => router.push(`/recruiter/workflows?tab=${id}`)}
          />
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {tab === 'rules' && (
          <>
            <Notice tone="neutral" title="Automation has limits, by design">
              <span className="flex items-start gap-1.5">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                A workflow can move an application to Rejected, Hired or Offer only when
                you also require a person to approve each run. No candidate is ever
                rejected by a rule alone.
              </span>
            </Notice>

            {workflowsQuery.isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 3 }).map((_, i) => (
                  <Skeleton key={i} className="h-28" />
                ))}
              </div>
            ) : !workflowsQuery.data?.length ? (
              <Card>
                <EmptyState
                  icon={WorkflowIcon}
                  title="No workflows yet"
                  description="Automate the repetitive parts: acknowledge every application, shortlist strong matches for review, tag by source."
                  action={
                    can('workflow:manage') ? (
                      <Button onClick={() => setEditing('new')}>
                        <Plus className="h-4 w-4" />
                        Create a workflow
                      </Button>
                    ) : undefined
                  }
                />
              </Card>
            ) : (
              <div className="space-y-3">
                {workflowsQuery.data.map((workflow) => (
                  <WorkflowCard
                    key={workflow.id}
                    workflow={workflow}
                    canManage={can('workflow:manage')}
                    toggling={toggle.isPending && toggle.variables?.id === workflow.id}
                    onToggle={() => toggle.mutate(workflow)}
                    onEdit={() => setEditing(workflow)}
                    onDelete={() => setDeleting(workflow)}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {tab === 'runs' && <ExecutionsTable />}
        {tab === 'approvals' && <ExecutionsTable awaitingApproval />}
      </PageBody>

      {editing && schemaQuery.data && (
        <WorkflowBuilder
          schema={schemaQuery.data}
          workflow={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}

      {deleting && (
        <Modal
          open
          onClose={() => setDeleting(null)}
          title="Delete this workflow?"
          description={deleting.name}
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                loading={remove.isPending}
                onClick={() => remove.mutate(deleting)}
              >
                Delete
              </Button>
            </>
          }
        >
          <p className="text-sm text-ink-600">
            Past runs stay in the history for audit. Only the rule itself is removed — if
            you just want it to stop firing, disable it instead.
          </p>
        </Modal>
      )}
    </>
  )
}

function WorkflowCard({
  workflow,
  canManage,
  toggling,
  onToggle,
  onEdit,
  onDelete,
}: {
  workflow: Workflow
  canManage: boolean
  toggling: boolean
  onToggle: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const conditionCount = Array.isArray(
    (workflow.conditions as { rules?: unknown[] })?.rules,
  )
    ? ((workflow.conditions as { rules: unknown[] }).rules ?? []).length
    : 0

  return (
    <Card className={cn('p-5', !workflow.is_enabled && 'opacity-70')}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold text-ink-900">{workflow.name}</h3>
            <Badge tone={workflow.is_enabled ? 'success' : 'neutral'}>
              {workflow.is_enabled ? 'Active' : 'Disabled'}
            </Badge>
            {workflow.requires_human_approval && (
              <Badge tone="warning">Needs approval</Badge>
            )}
          </div>

          {workflow.description && (
            <p className="mt-1 text-sm text-ink-600">{workflow.description}</p>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-2.5 py-1 text-brand-700">
              <Zap className="h-3.5 w-3.5" />
              {titleCase(workflow.trigger)}
            </span>
            {conditionCount > 0 && (
              <span className="rounded-lg bg-ink-100 px-2.5 py-1 text-ink-700">
                {conditionCount} {conditionCount === 1 ? 'condition' : 'conditions'}
              </span>
            )}
            <span className="text-ink-400">→</span>
            {workflow.steps.map((step) => (
              <span
                key={step.id}
                className={cn(
                  'rounded-lg px-2.5 py-1',
                  step.is_enabled ? 'bg-ink-100 text-ink-700' : 'bg-ink-50 text-ink-400 line-through',
                )}
              >
                {titleCase(step.action_type)}
              </span>
            ))}
          </div>

          <p className="mt-3 text-xs text-ink-400">
            Run {workflow.execution_count} {workflow.execution_count === 1 ? 'time' : 'times'}
            {workflow.last_executed_at && ` · last ${formatRelative(workflow.last_executed_at)}`}
            {workflow.job_ids.length > 0
              ? ` · limited to ${workflow.job_ids.length} job${workflow.job_ids.length === 1 ? '' : 's'}`
              : ' · all jobs'}
          </p>
        </div>

        {canManage && (
          <div className="flex shrink-0 gap-1.5">
            <Button variant="ghost" size="sm" loading={toggling} onClick={onToggle}>
              {workflow.is_enabled ? (
                <>
                  <CircleSlash className="h-3.5 w-3.5" />
                  Disable
                </>
              ) : (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Enable
                </>
              )}
            </Button>
            <Button variant="ghost" size="sm" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="sm" onClick={onDelete}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        )}
      </div>
    </Card>
  )
}

function ExecutionsTable({ awaitingApproval }: { awaitingApproval?: boolean }) {
  const queryClient = useQueryClient()
  const { can } = useAuth()
  const [page, setPage] = useState(1)

  const executionsQuery = useQuery({
    queryKey: ['workflow-executions', awaitingApproval, page],
    queryFn: () =>
      api.get<Page<WorkflowExecution>>('/workflows/executions/list', {
        query: { awaiting_approval: awaitingApproval || undefined, page, page_size: 20 },
      }),
  })

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      api.post(`/workflows/executions/${id}/${approve ? 'approve' : 'reject'}`),
    onSuccess: (_data, variables) => {
      toast.success(variables.approve ? 'Approved — the actions ran.' : 'Run rejected.')
      void queryClient.invalidateQueries({ queryKey: ['workflow-executions'] })
      void queryClient.invalidateQueries({ queryKey: ['applications'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'That decision did not go through'),
  })

  const columns: Column<WorkflowExecution>[] = [
    {
      key: 'workflow',
      header: 'Workflow',
      render: (row) => (
        <div>
          <span className="font-medium text-ink-900">{row.workflow_name ?? 'Workflow'}</span>
          <span className="block text-xs text-ink-400">
            {row.entity_type} · {formatRelative(row.created_at)}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Result',
      render: (row) => (
        <div>
          <Badge tone={EXECUTION_TONES[row.status]}>{titleCase(row.status)}</Badge>
          {/*
            The engine records why a run did nothing, in the condition grammar's own
            words ("ats_score (62.0) lt 45 -> fail"). Showing it verbatim is what makes
            the automation auditable rather than mysterious.
          */}
          {row.skip_reason && (
            <p className="mt-1 max-w-md font-mono text-xs text-ink-500">{row.skip_reason}</p>
          )}
          {row.error && (
            <p className="mt-1 max-w-md text-xs text-danger-600">{row.error}</p>
          )}
        </div>
      ),
    },
    {
      key: 'steps',
      header: 'Actions taken',
      hideOnMobile: true,
      render: (row) =>
        row.step_results.length === 0 ? (
          <span className="text-ink-400">—</span>
        ) : (
          <ul className="space-y-0.5">
            {row.step_results.slice(0, 3).map((result, index) => (
              <li key={index} className="text-xs text-ink-600">
                {String(
                  (result as { detail?: string; action?: string }).detail ??
                    (result as { action?: string }).action ??
                    '',
                )}
              </li>
            ))}
            {row.step_results.length > 3 && (
              <li className="text-xs text-ink-400">+{row.step_results.length - 3} more</li>
            )}
          </ul>
        ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (row) =>
        row.awaiting_approval && can('workflow:manage') ? (
          <div className="flex justify-end gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              loading={decide.isPending && decide.variables?.id === row.id}
              onClick={() => decide.mutate({ id: row.id, approve: true })}
            >
              Approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => decide.mutate({ id: row.id, approve: false })}
            >
              Reject
            </Button>
          </div>
        ) : row.approved_at ? (
          <span className="text-xs text-ink-400">approved {formatRelative(row.approved_at)}</span>
        ) : null,
    },
  ]

  return (
    <div className="space-y-4">
      {awaitingApproval && (
        <Notice tone="warning" title="These runs are paused until you decide">
          Each of these would move an application to a status only a person may set. Review
          the candidate before approving — approval is recorded against your name.
        </Notice>
      )}

      <DataTable
        rows={executionsQuery.data?.items}
        columns={columns}
        loading={executionsQuery.isLoading}
        error={executionsQuery.error as Error | null}
        onRetry={() => executionsQuery.refetch()}
        rowKey={(row) => row.id}
        empty={
          <EmptyRows
            icon={WorkflowIcon}
            title={awaitingApproval ? 'Nothing awaiting approval' : 'No runs yet'}
            description={
              awaitingApproval
                ? 'Workflows that need a human decision will queue up here.'
                : 'Workflow runs appear here as soon as a trigger fires — including the ones that were skipped, and why.'
            }
          />
        }
      />

      <Paginator meta={executionsQuery.data?.meta} onPage={setPage} />
    </div>
  )
}

export default function WorkflowsPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <WorkflowsContent />
    </Suspense>
  )
}

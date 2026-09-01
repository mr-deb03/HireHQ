'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Clock, GripVertical, Users } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { LiveIndicator, LiveToast } from '@/components/data'
import { useRealtime } from '@/hooks/use-realtime'
import {
  Avatar,
  Card,
  EmptyState,
  ErrorState,
  Select,
  Skeleton,
  Tooltip,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { ApplicationStatus, JobSummary, KanbanBoard, KanbanCard } from '@/lib/types'
import { STATUS_STYLES, cn, formatExperience, formatRelative } from '@/lib/utils'

function Card_({ card, onDragStart }: { card: KanbanCard; onDragStart: () => void }) {
  const score = card.ats_score

  return (
    <Link href={`/recruiter/candidates/${card.candidate_id}`}>
      <div
        draggable
        onDragStart={onDragStart}
        className="group card cursor-grab p-3 transition-all hover:border-ink-300 hover:shadow-card-hover active:cursor-grabbing"
      >
        <div className="flex items-start gap-2.5">
          <Avatar name={card.candidate_name} src={card.candidate_photo_url} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink-900">{card.candidate_name}</p>
            {card.current_designation && (
              <p className="truncate text-xs text-ink-500">{card.current_designation}</p>
            )}
          </div>
          <GripVertical className="h-3.5 w-3.5 shrink-0 text-ink-200 opacity-0 transition-opacity group-hover:opacity-100" />
        </div>

        <div className="mt-2.5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 text-[11px] text-ink-500">
            <Clock className="h-3 w-3" />
            {formatExperience(card.total_experience_years)}
          </div>
          {score != null && (
            <span
              className={cn(
                'rounded-md px-1.5 py-0.5 text-[11px] font-semibold tabular-nums',
                score >= 85
                  ? 'bg-success-50 text-success-700'
                  : score >= 70
                    ? 'bg-brand-50 text-brand-700'
                    : score >= 50
                      ? 'bg-warning-50 text-warning-700'
                      : 'bg-ink-100 text-ink-500',
              )}
            >
              {Math.round(score)}%
            </span>
          )}
        </div>

        {(card.has_pending_feedback || card.tags.length > 0) && (
          <div className="mt-2 flex flex-wrap items-center gap-1">
            {card.has_pending_feedback && (
              <Tooltip label="Interview feedback is pending">
                <span className="inline-flex items-center gap-1 rounded bg-warning-50 px-1.5 py-0.5 text-[10px] font-medium text-warning-700">
                  <AlertTriangle className="h-2.5 w-2.5" />
                  Feedback due
                </span>
              </Tooltip>
            )}
            {card.tags.slice(0, 2).map((tag) => (
              <span
                key={tag}
                className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <p className="mt-2 text-[10px] text-ink-400">Applied {formatRelative(card.applied_at)}</p>
      </div>
    </Link>
  )
}

function PipelineContent() {
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  // A new application or a finished ATS run invalidates the board; the refetch that
  // follows is the authoritative read.
  const { status: liveStatus, lastEvent } = useRealtime()

  const [jobId, setJobId] = useState(params.get('job_id') ?? '')
  const [dragging, setDragging] = useState<KanbanCard | null>(null)
  const [dragOver, setDragOver] = useState<ApplicationStatus | null>(null)

  const jobsQuery = useQuery({
    queryKey: ['jobs', 'for-pipeline'],
    queryFn: () =>
      api.get<{ items: JobSummary[] }>('/jobs', { query: { page_size: 100, status: 'PUBLISHED' } }),
  })

  const boardQuery = useQuery({
    queryKey: ['kanban', jobId],
    queryFn: () =>
      api.get<KanbanBoard>('/applications/board/kanban', {
        query: { job_id: jobId || undefined },
      }),
  })

  const moveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: ApplicationStatus }) =>
      api.post(`/applications/${id}/move`, { status, position: 0 }),
    onSuccess: (_data, variables) => {
      toast.success(`Moved to ${STATUS_STYLES[variables.status].label}`)
      void queryClient.invalidateQueries({ queryKey: ['kanban'] })
    },
    onError: (error) => {
      // The state machine rejects invalid moves; surface exactly why.
      if (error instanceof ApiError) {
        const allowed = error.details?.allowed as string[] | undefined
        toast.error(
          allowed?.length
            ? `${error.message}. You can move it to: ${allowed
                .map((s) => STATUS_STYLES[s as ApplicationStatus]?.label ?? s)
                .join(', ')}.`
            : error.message,
        )
      } else {
        toast.error('Could not move this application')
      }
      void queryClient.invalidateQueries({ queryKey: ['kanban'] })
    },
  })

  function onDrop(status: ApplicationStatus) {
    setDragOver(null)
    if (!dragging || dragging.stage_position === undefined) return
    const card = dragging
    setDragging(null)
    if (!can('application:update:status')) {
      toast.error('You do not have permission to move applications')
      return
    }
    moveMutation.mutate({ id: card.id, status })
  }

  return (
    <>
      <PageHeader
        title="Pipeline"
        description="Drag a candidate between stages. Invalid moves are refused with a reason."
        actions={
          <>
            <LiveIndicator status={liveStatus} />
            <div className="w-64">
              <Select
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
                aria-label="Filter by job"
              >
                <option value="">All jobs</option>
                {jobsQuery.data?.items.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.title}
                  </option>
                ))}
              </Select>
            </div>
          </>
        }
      />

      <PageBody className="max-w-none">
        {boardQuery.isLoading ? (
          <div className="scroll-x flex gap-4 pb-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-96 w-72 shrink-0" />
            ))}
          </div>
        ) : boardQuery.isError ? (
          <Card>
            <ErrorState
              message={(boardQuery.error as Error).message}
              onRetry={() => boardQuery.refetch()}
            />
          </Card>
        ) : boardQuery.data?.total === 0 ? (
          <Card>
            <EmptyState
              icon={Users}
              title="No applications yet"
              description="Once candidates apply, they will appear here and move through your pipeline."
            />
          </Card>
        ) : (
          <div className="scroll-x flex gap-4 pb-4">
            {boardQuery.data?.columns.map((column) => {
              const style = STATUS_STYLES[column.status]
              const isTarget = dragOver === column.status
              return (
                <div
                  key={column.status}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragOver(column.status)
                  }}
                  onDragLeave={() => setDragOver(null)}
                  onDrop={() => onDrop(column.status)}
                  className={cn(
                    'flex w-72 shrink-0 flex-col rounded-2xl border p-3 transition-colors',
                    isTarget
                      ? 'border-brand-400 bg-brand-50/60'
                      : 'border-ink-200 bg-white/60',
                  )}
                >
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn('h-2 w-2 rounded-full', style.dot)} />
                      <h3 className="text-sm font-semibold text-ink-900">{style.label}</h3>
                    </div>
                    <span className="rounded-full bg-ink-100 px-2 py-0.5 text-xs font-semibold tabular-nums text-ink-600">
                      {column.count}
                    </span>
                  </div>

                  <div className="flex flex-1 flex-col gap-2 overflow-y-auto">
                    {column.cards.length === 0 ? (
                      <p className="rounded-xl border border-dashed border-ink-200 px-3 py-6 text-center text-xs text-ink-400">
                        Nothing here
                      </p>
                    ) : (
                      column.cards.map((card) => (
                        <Card_ key={card.id} card={card} onDragStart={() => setDragging(card)} />
                      ))
                    )}
                    {column.count > column.cards.length && (
                      <p className="py-2 text-center text-xs text-ink-400">
                        +{column.count - column.cards.length} more
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </PageBody>

      <LiveToast message={lastEvent?.label ?? null} />
    </>
  )
}

export default function PipelinePage() {
  return (
    <Suspense fallback={<PageBody><Skeleton className="h-96" /></PageBody>}>
      <PipelineContent />
    </Suspense>
  )
}

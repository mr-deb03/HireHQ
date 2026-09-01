'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Plus, RefreshCw, Trash2, UserMinus, Users } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Modal,
  Skeleton,
  Textarea,
} from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { CandidateSummary, TalentPool } from '@/lib/types'
import { cn, formatExperience, formatRelative } from '@/lib/utils'

export default function TalentPoolPage() {
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<TalentPool | null>(null)
  const [deleting, setDeleting] = useState<TalentPool | null>(null)

  const poolsQuery = useQuery({
    queryKey: ['talent-pools'],
    queryFn: () => api.get<TalentPool[]>('/talent-pool'),
  })

  const refresh = useMutation({
    mutationFn: (pool: TalentPool) => api.post<TalentPool>(`/talent-pool/${pool.id}/refresh`),
    onSuccess: (pool) => {
      toast.success(`${pool.name} now has ${pool.member_count} members.`)
      void queryClient.invalidateQueries({ queryKey: ['talent-pools'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not refresh'),
  })

  const remove = useMutation({
    mutationFn: (pool: TalentPool) => api.delete(`/talent-pool/${pool.id}`),
    onSuccess: () => {
      toast.success('Pool deleted. The candidates themselves are untouched.')
      void queryClient.invalidateQueries({ queryKey: ['talent-pools'] })
      setDeleting(null)
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not delete'),
  })

  return (
    <>
      <PageHeader
        title="Talent pool"
        description="Keep good candidates reachable for the next role."
        actions={
          can('talent_pool:manage') && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              New pool
            </Button>
          )
        }
      />

      <PageBody className="space-y-4">
        <Notice tone="neutral">
          A pool is a shortlist you keep on purpose — candidates who were strong but not
          right this time. Everyone in one can still ask to be removed, and pools respect
          the same retention policy as the rest of their data.
        </Notice>

        {poolsQuery.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-36" />
            ))}
          </div>
        ) : !poolsQuery.data?.length ? (
          <Card>
            <EmptyState
              icon={FolderOpen}
              title="No talent pools yet"
              description="Group candidates you would happily hire later — by skill, seniority or the role they nearly got."
              action={
                can('talent_pool:manage') ? (
                  <Button onClick={() => setCreating(true)}>
                    <Plus className="h-4 w-4" />
                    Create a pool
                  </Button>
                ) : undefined
              }
            />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {poolsQuery.data.map((pool) => (
              <Card key={pool.id} className="flex flex-col p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {pool.colour && (
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-full"
                          style={{ backgroundColor: pool.colour }}
                          aria-hidden
                        />
                      )}
                      <h3 className="truncate text-[15px] font-semibold text-ink-900">
                        {pool.name}
                      </h3>
                    </div>
                    {pool.description && (
                      <p className="mt-1 line-clamp-2 text-sm text-ink-600">{pool.description}</p>
                    )}
                  </div>
                  {pool.is_dynamic && <Badge tone="info">Auto</Badge>}
                </div>

                <p className="mt-4 flex items-baseline gap-1.5">
                  <span className="text-2xl font-semibold tabular-nums text-ink-900">
                    {pool.member_count}
                  </span>
                  <span className="text-sm text-ink-500">
                    {pool.member_count === 1 ? 'candidate' : 'candidates'}
                  </span>
                </p>

                <p className="mt-1 text-xs text-ink-400">
                  Created {formatRelative(pool.created_at)}
                </p>

                <div className="mt-4 flex flex-wrap gap-1.5 border-t border-ink-100 pt-3">
                  <Button variant="secondary" size="sm" onClick={() => setSelected(pool)}>
                    <Users className="h-3.5 w-3.5" />
                    Members
                  </Button>
                  {can('talent_pool:manage') && pool.is_dynamic && (
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={refresh.isPending && refresh.variables?.id === pool.id}
                      onClick={() => refresh.mutate(pool)}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Refresh
                    </Button>
                  )}
                  {can('talent_pool:manage') && (
                    <Button variant="ghost" size="sm" onClick={() => setDeleting(pool)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </PageBody>

      {creating && <CreatePoolModal onClose={() => setCreating(false)} />}
      {selected && <MembersModal pool={selected} onClose={() => setSelected(null)} />}

      {deleting && (
        <Modal
          open
          onClose={() => setDeleting(null)}
          title="Delete this pool?"
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
                Delete pool
              </Button>
            </>
          }
        >
          <p className="text-sm text-ink-600">
            The {deleting.member_count} candidates in it stay in your database — only the
            grouping is removed.
          </p>
        </Modal>
      )}
    </>
  )
}

function CreatePoolModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [colour, setColour] = useState('#4f46e5')

  const create = useMutation({
    mutationFn: () =>
      api.post<TalentPool>('/talent-pool', {
        name,
        description: description || undefined,
        colour,
      }),
    onSuccess: () => {
      toast.success('Pool created.')
      void queryClient.invalidateQueries({ queryKey: ['talent-pools'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not create the pool'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="New talent pool"
      description="Add candidates to it from their profile or in bulk from the pipeline."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>
            Create pool
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input
          label="Name"
          required
          placeholder="Senior backend — keep warm"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Textarea
          label="Description"
          hint="Why these candidates belong together, so a colleague can tell at a glance."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div>
          <label htmlFor="pool-colour" className="label">
            Colour
          </label>
          <div className="mt-1.5 flex items-center gap-3">
            <input
              id="pool-colour"
              type="color"
              value={colour}
              onChange={(e) => setColour(e.target.value)}
              className="h-9 w-16 cursor-pointer rounded-lg border border-ink-300"
            />
            <span className="font-mono text-xs text-ink-500">{colour}</span>
          </div>
        </div>
      </div>
    </Modal>
  )
}

function MembersModal({ pool, onClose }: { pool: TalentPool; onClose: () => void }) {
  const queryClient = useQueryClient()
  const { can } = useAuth()

  // Paginated on the server, so read `items` rather than treating the body as an array.
  const membersQuery = useQuery({
    queryKey: ['talent-pool-members', pool.id],
    queryFn: () =>
      api.get<Page<CandidateSummary>>(`/talent-pool/${pool.id}/members`, {
        query: { page_size: 100 },
      }),
  })
  const members = membersQuery.data?.items

  const removeMember = useMutation({
    mutationFn: (candidateId: string) =>
      api.delete(`/talent-pool/${pool.id}/members/${candidateId}`),
    onSuccess: () => {
      toast.success('Removed from the pool.')
      void queryClient.invalidateQueries({ queryKey: ['talent-pool-members', pool.id] })
      void queryClient.invalidateQueries({ queryKey: ['talent-pools'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not remove'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={pool.name}
      description={`${pool.member_count} ${pool.member_count === 1 ? 'candidate' : 'candidates'}`}
      footer={<Button onClick={onClose}>Close</Button>}
    >
      {membersQuery.isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : !members?.length ? (
        <EmptyState
          icon={Users}
          title="This pool is empty"
          description="Add candidates from their profile, or in bulk from the pipeline board."
        />
      ) : (
        <ul className="divide-y divide-ink-100">
          {members.map((candidate) => (
            <li key={candidate.id} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <Link
                  href={`/recruiter/candidates/${candidate.id}`}
                  className="text-sm font-medium text-ink-900 hover:text-brand-700"
                >
                  {candidate.full_name}
                </Link>
                <p className="truncate text-xs text-ink-500">
                  {candidate.current_designation ?? 'No title recorded'}
                  {candidate.current_company && ` at ${candidate.current_company}`}
                  {' · '}
                  {formatExperience(candidate.total_experience_years)}
                </p>
              </div>

              {candidate.skills.length > 0 && (
                <div className="hidden shrink-0 gap-1 sm:flex">
                  {candidate.skills.slice(0, 3).map((skill) => (
                    <span
                      key={skill.id}
                      className={cn('rounded bg-ink-100 px-1.5 py-0.5 text-xs text-ink-600')}
                    >
                      {skill.name}
                    </span>
                  ))}
                </div>
              )}

              {can('talent_pool:manage') && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`Remove ${candidate.full_name} from ${pool.name}`}
                  loading={removeMember.isPending && removeMember.variables === candidate.id}
                  onClick={() => removeMember.mutate(candidate.id)}
                >
                  <UserMinus className="h-3.5 w-3.5" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}

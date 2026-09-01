'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Gift, Send, ShieldCheck, XCircle } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { DataTable, EmptyRows, Notice, Paginator, type Column } from '@/components/data'
import { Badge, Button, Modal, Skeleton, Tabs, Textarea } from '@/components/ui'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Offer, OfferStatus } from '@/lib/types'
import { formatCurrency, formatDate, formatRelative, titleCase } from '@/lib/utils'

const STATUS_TONES: Record<OfferStatus, 'success' | 'neutral' | 'warning' | 'danger' | 'info'> = {
  DRAFT: 'neutral',
  SENT: 'info',
  VIEWED: 'info',
  ACCEPTED: 'success',
  REJECTED: 'danger',
  WITHDRAWN: 'neutral',
  EXPIRED: 'warning',
}

const TABS = [
  { id: '', label: 'All' },
  { id: 'DRAFT', label: 'Drafts' },
  { id: 'SENT', label: 'Awaiting response' },
  { id: 'ACCEPTED', label: 'Accepted' },
  { id: 'REJECTED', label: 'Declined' },
]

interface SendResult {
  offer: Offer
  /** `NOT_SENT_NO_PROVIDER` when no email provider is configured, so nothing was delivered. */
  email_delivery_status: string
  /** The tokenised link the candidate uses to view and respond. */
  candidate_offer_url: string
  message: string
}

function OffersContent() {
  const router = useRouter()
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const { can } = useAuth()

  const status = params.get('status') ?? ''
  const page = Number(params.get('page') ?? '1')
  const [acting, setActing] = useState<{ mode: 'withdraw' | 'approve'; offer: Offer } | null>(null)
  const [sendResult, setSendResult] = useState<SendResult | null>(null)

  const offersQuery = useQuery({
    queryKey: ['offers', status, page],
    queryFn: () =>
      api.get<Page<Offer>>('/offers', {
        query: { status: status || undefined, page, page_size: 20 },
      }),
  })

  const send = useMutation({
    mutationFn: (offerId: string) => api.post<SendResult>(`/offers/${offerId}/send`),
    onSuccess: (result) => {
      setSendResult(result)
      if (result.email_delivery_status === 'SENT') toast.success('Offer emailed to the candidate.')
      else toast.warning(result.message)
      void queryClient.invalidateQueries({ queryKey: ['offers'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not send the offer'),
  })

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/recruiter/offers${next.toString() ? `?${next}` : ''}`)
  }

  const columns: Column<Offer>[] = [
    {
      key: 'reference',
      header: 'Reference',
      render: (offer) => (
        <div>
          <span className="font-mono text-xs text-ink-400">{offer.reference_code}</span>
          <Link
            href={`/recruiter/candidates/${offer.candidate_id}`}
            className="block font-medium text-ink-900 hover:text-brand-700"
          >
            {offer.position_title}
          </Link>
        </div>
      ),
    },
    {
      key: 'compensation',
      header: 'Total comp.',
      align: 'right',
      render: (offer) => (
        <div>
          <span className="font-semibold text-ink-900">
            {formatCurrency(offer.total_compensation, offer.currency)}
          </span>
          <span className="block text-xs text-ink-400">
            base {formatCurrency(offer.base_salary, offer.currency)}
          </span>
        </div>
      ),
    },
    {
      key: 'joining',
      header: 'Joining',
      hideOnMobile: true,
      render: (offer) => (offer.joining_date ? formatDate(offer.joining_date) : '—'),
    },
    {
      key: 'status',
      header: 'Status',
      render: (offer) => (
        <div className="flex flex-col items-start gap-1">
          <Badge tone={STATUS_TONES[offer.status]}>{titleCase(offer.status)}</Badge>
          {offer.status === 'SENT' && offer.expires_at && (
            <span className="text-xs text-ink-400">
              expires {formatRelative(offer.expires_at)}
            </span>
          )}
          {offer.status === 'REJECTED' && offer.decline_reason && (
            <span className="max-w-48 truncate text-xs text-ink-500" title={offer.decline_reason}>
              {offer.decline_reason}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (offer) => (
        <div className="flex justify-end gap-1.5">
          {can('offer:approve') && offer.status === 'DRAFT' && !offer.approved_at && (
            <Button variant="ghost" size="sm" onClick={() => setActing({ mode: 'approve', offer })}>
              <ShieldCheck className="h-3.5 w-3.5" />
              Approve
            </Button>
          )}
          {can('offer:create') && offer.status === 'DRAFT' && (
            <Button
              variant="secondary"
              size="sm"
              loading={send.isPending && send.variables === offer.id}
              onClick={() => send.mutate(offer.id)}
            >
              <Send className="h-3.5 w-3.5" />
              Send
            </Button>
          )}
          {can('offer:create') && ['SENT', 'VIEWED'].includes(offer.status) && (
            <Button variant="ghost" size="sm" onClick={() => setActing({ mode: 'withdraw', offer })}>
              <XCircle className="h-3.5 w-3.5" />
              Withdraw
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Offers"
        description={
          offersQuery.data ? `${offersQuery.data.meta.total_items} offers` : 'Offers you have made'
        }
      >
        <div className="mt-5">
          <Tabs tabs={TABS} active={status} onChange={(id) => setParam('status', id)} />
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {sendResult && sendResult.email_delivery_status !== 'SENT' && (
          <Notice tone="warning" title="The offer was not emailed">
            {sendResult.message}
            <p className="mt-2 break-all font-mono text-xs">
              Share this link with the candidate directly: {sendResult.candidate_offer_url}
            </p>
          </Notice>
        )}

        <DataTable
          rows={offersQuery.data?.items}
          columns={columns}
          loading={offersQuery.isLoading}
          error={offersQuery.error as Error | null}
          onRetry={() => offersQuery.refetch()}
          rowKey={(offer) => offer.id}
          empty={
            <EmptyRows
              icon={Gift}
              title={status ? `No ${titleCase(status).toLowerCase()} offers` : 'No offers yet'}
              description={
                status
                  ? 'Try a different tab.'
                  : 'Create an offer from a candidate who has passed their interviews.'
              }
              action={
                status ? (
                  <Button variant="secondary" onClick={() => setParam('status', '')}>
                    Show all
                  </Button>
                ) : (
                  <Link href="/recruiter/pipeline">
                    <Button>Open the pipeline</Button>
                  </Link>
                )
              }
            />
          }
        />

        <Paginator meta={offersQuery.data?.meta} onPage={(p) => setParam('page', String(p))} />
      </PageBody>

      {acting && (
        <OfferActionModal
          mode={acting.mode}
          offer={acting.offer}
          onClose={() => setActing(null)}
        />
      )}
    </>
  )
}

function OfferActionModal({
  mode,
  offer,
  onClose,
}: {
  mode: 'withdraw' | 'approve'
  offer: Offer
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')

  const action = useMutation({
    mutationFn: () =>
      mode === 'approve'
        ? api.post(`/offers/${offer.id}/approve`)
        : api.post(`/offers/${offer.id}/withdraw`, { reason: reason || undefined }),
    onSuccess: () => {
      toast.success(mode === 'approve' ? 'Offer approved.' : 'Offer withdrawn.')
      void queryClient.invalidateQueries({ queryKey: ['offers'] })
      onClose()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'That action did not go through'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title={mode === 'approve' ? 'Approve this offer' : 'Withdraw this offer'}
      description={`${offer.reference_code} · ${offer.position_title}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={mode === 'withdraw' ? 'danger' : 'primary'}
            loading={action.isPending}
            onClick={() => action.mutate()}
          >
            {mode === 'approve' ? 'Approve' : 'Withdraw offer'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {mode === 'approve' ? (
          <Notice tone="info">
            <span className="flex items-start gap-1.5">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Approving records that you signed off on{' '}
              {formatCurrency(offer.total_compensation, offer.currency)} total compensation.
              The offer still has to be sent separately.
            </span>
          </Notice>
        ) : (
          <Notice tone="warning">
            The candidate will no longer be able to accept. If they have already accepted,
            withdrawal is refused — reach out to them directly instead.
          </Notice>
        )}

        {mode === 'withdraw' && (
          <Textarea
            label="Reason"
            hint="Recorded in the audit log."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        )}
      </div>
    </Modal>
  )
}

export default function RecruiterOffersPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <OffersContent />
    </Suspense>
  )
}

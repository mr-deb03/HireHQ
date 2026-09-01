'use client'

/**
 * The candidate's view of their offer, opened from the emailed link.
 *
 * Deliberately unauthenticated: the token in the URL is the authorisation, so a
 * candidate does not need an account to read or respond to an offer. The server returns
 * offer terms only — no scores, notes or pipeline data reach this page.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CalendarCheck, CheckCircle2, FileWarning, PartyPopper } from 'lucide-react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { Notice } from '@/components/data'
import { Logo } from '@/components/marketing'
import { Badge, Button, Card, CardBody, EmptyState, Skeleton, Textarea } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import type { PublicOffer } from '@/lib/types'
import { formatCurrency, formatDate, formatRelative, titleCase } from '@/lib/utils'

interface RespondResult {
  reference_code: string
  status: string
  onboarding_started: boolean
}

function OfferContent() {
  const { id } = useParams<{ id: string }>()
  const params = useSearchParams()
  const queryClient = useQueryClient()
  const token = params.get('token') ?? ''

  const [declining, setDeclining] = useState(false)
  const [declineReason, setDeclineReason] = useState('')

  const offerQuery = useQuery({
    queryKey: ['public-offer', id, token],
    queryFn: () =>
      api.get<PublicOffer>(`/offers/${id}/view`, { auth: false, query: { token } }),
    enabled: Boolean(token),
    retry: false,
  })

  const respond = useMutation({
    mutationFn: (accepted: boolean) =>
      api.post<RespondResult>(
        `/offers/${id}/respond`,
        { accepted, decline_reason: accepted ? undefined : declineReason || undefined },
        { auth: false, query: { token } },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['public-offer', id] })
      setDeclining(false)
    },
  })

  if (!token) {
    return (
      <Shell>
        <Card>
          <EmptyState
            icon={FileWarning}
            title="This link is incomplete"
            description="The offer link is missing its access token. Open the most recent link from your offer email."
          />
        </Card>
      </Shell>
    )
  }

  if (offerQuery.isLoading) {
    return (
      <Shell>
        <Skeleton className="h-96" />
      </Shell>
    )
  }

  if (offerQuery.isError || !offerQuery.data) {
    const expired =
      offerQuery.error instanceof ApiError && offerQuery.error.status === 403
    return (
      <Shell>
        <Card>
          <EmptyState
            icon={FileWarning}
            title={expired ? 'This offer link is no longer valid' : 'Could not open this offer'}
            description={
              (offerQuery.error as Error)?.message ??
              'The link may have expired or been withdrawn. Contact your recruiter for a new one.'
            }
          />
        </Card>
      </Shell>
    )
  }

  const offer = offerQuery.data
  const responded = respond.isSuccess || ['ACCEPTED', 'REJECTED'].includes(offer.status)
  const accepted = respond.data?.status === 'ACCEPTED' || offer.status === 'ACCEPTED'

  return (
    <Shell company={offer.company_name}>
      {responded && (
        <div className="mb-5">
          {accepted ? (
            <Notice tone="info" title="Offer accepted">
              <span className="flex items-start gap-1.5">
                <PartyPopper className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                Congratulations. Your onboarding has started — the team will be in touch
                with next steps and any documents they need.
              </span>
            </Notice>
          ) : (
            <Notice tone="neutral" title="Offer declined">
              Thank you for letting us know. Your decision has been recorded and the hiring
              team notified.
            </Notice>
          )}
        </div>
      )}

      <Card>
        <CardBody className="p-6 sm:p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="font-mono text-xs text-ink-400">{offer.reference_code}</p>
              <h1 className="mt-1.5 text-title-lg font-semibold tracking-tight text-ink-900">
                {offer.position_title}
              </h1>
              {offer.company_name && (
                <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-600">
                  <Building2 className="h-3.5 w-3.5 text-ink-400" />
                  {offer.company_name}
                  {offer.department && <span className="text-ink-400">· {offer.department}</span>}
                </p>
              )}
            </div>
            <Badge tone={accepted ? 'success' : responded ? 'neutral' : 'info'}>
              {titleCase(offer.status)}
            </Badge>
          </div>

          {/* ----------------------------------------------- compensation */}
          <div className="mt-7 rounded-2xl bg-ink-50 p-5">
            <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
              Total compensation
            </p>
            <p className="mt-1.5 text-3xl font-semibold tabular-nums text-ink-900">
              {formatCurrency(offer.total_compensation, offer.currency, { compact: false })}
              <span className="ml-1.5 text-sm font-normal text-ink-500">
                per {offer.salary_period.toLowerCase().replace('ly', '')}
              </span>
            </p>

            <dl className="mt-5 grid gap-x-6 gap-y-3 border-t border-ink-200 pt-4 sm:grid-cols-3">
              <Money label="Base salary" value={offer.base_salary} currency={offer.currency} />
              {offer.variable_pay != null && (
                <Money label="Variable pay" value={offer.variable_pay} currency={offer.currency} />
              )}
              {offer.joining_bonus != null && (
                <Money
                  label="Joining bonus"
                  value={offer.joining_bonus}
                  currency={offer.currency}
                />
              )}
            </dl>
          </div>

          {/* ---------------------------------------------------- details */}
          <dl className="mt-6 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {offer.joining_date && (
              <Detail label="Start date">
                <span className="flex items-center gap-1.5">
                  <CalendarCheck className="h-3.5 w-3.5 text-ink-400" />
                  {formatDate(offer.joining_date)}
                </span>
              </Detail>
            )}
            {offer.location && <Detail label="Location">{offer.location}</Detail>}
            {offer.employment_type && (
              <Detail label="Employment type">{titleCase(offer.employment_type)}</Detail>
            )}
            {offer.reporting_to && <Detail label="Reporting to">{offer.reporting_to}</Detail>}
            {offer.probation_months != null && (
              <Detail label="Probation">
                {offer.probation_months === 0
                  ? 'None'
                  : `${offer.probation_months} month${offer.probation_months === 1 ? '' : 's'}`}
              </Detail>
            )}
          </dl>

          {offer.benefits.length > 0 && (
            <div className="mt-6">
              <h2 className="text-sm font-semibold text-ink-900">Benefits</h2>
              <ul className="mt-2.5 grid gap-2 sm:grid-cols-2">
                {offer.benefits.map((benefit) => (
                  <li key={benefit} className="flex items-start gap-2 text-sm text-ink-700">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success-500" />
                    {benefit}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {offer.notes && (
            <div className="mt-6 rounded-xl border border-ink-200 px-4 py-3.5">
              <h2 className="text-sm font-semibold text-ink-900">A note from the team</h2>
              <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
                {offer.notes}
              </p>
            </div>
          )}

          {/* --------------------------------------------------- response */}
          {offer.can_respond && !responded && (
            <div className="mt-8 border-t border-ink-200 pt-6">
              {offer.expires_at && (
                <p className="mb-4 text-sm text-ink-600">
                  This offer expires {formatRelative(offer.expires_at)} (
                  {formatDate(offer.expires_at)}).
                </p>
              )}

              {respond.isError && (
                <div
                  role="alert"
                  className="mb-4 rounded-xl border border-danger-100 bg-danger-50 px-3.5 py-2.5 text-sm text-danger-700"
                >
                  {(respond.error as Error).message}
                </div>
              )}

              {declining ? (
                <div className="space-y-4">
                  <Textarea
                    label="Reason for declining"
                    hint="Optional, and shared with the hiring team only."
                    value={declineReason}
                    onChange={(e) => setDeclineReason(e.target.value)}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="danger"
                      loading={respond.isPending}
                      onClick={() => respond.mutate(false)}
                    >
                      Confirm decline
                    </Button>
                    <Button variant="ghost" onClick={() => setDeclining(false)}>
                      Go back
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant="success"
                    size="lg"
                    loading={respond.isPending}
                    onClick={() => respond.mutate(true)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Accept offer
                  </Button>
                  <Button variant="secondary" size="lg" onClick={() => setDeclining(true)}>
                    Decline
                  </Button>
                </div>
              )}

              <p className="mt-4 text-xs leading-relaxed text-ink-500">
                Take the time you need. If anything here does not match what you discussed,
                contact your recruiter before responding — this decision is recorded.
              </p>
            </div>
          )}

          {!offer.can_respond && !responded && (
            <div className="mt-8 border-t border-ink-200 pt-6">
              <Notice tone="neutral">
                This offer is currently {titleCase(offer.status).toLowerCase()} and cannot be
                responded to. Contact your recruiter if you think that is a mistake.
              </Notice>
            </div>
          )}
        </CardBody>
      </Card>
    </Shell>
  )
}

function Money({
  label,
  value,
  currency,
}: {
  label: string
  value: number
  currency: string
}) {
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums text-ink-900">
        {formatCurrency(value, currency, { compact: false })}
      </dd>
    </div>
  )
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-400">{label}</dt>
      <dd className="mt-1 text-sm text-ink-800">{children}</dd>
    </div>
  )
}

function Shell({ children, company }: { children: React.ReactNode; company?: string | null }) {
  return (
    <div className="min-h-full bg-ink-50">
      <header className="border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-4">
          <Logo />
          {company && <span className="text-sm text-ink-500">{company}</span>}
        </div>
      </header>
      <div className="mx-auto max-w-3xl px-4 py-10">
        {children}
        <p className="mt-8 text-center text-sm text-ink-500">
          <Link href="/login" className="hover:text-ink-800">
            Sign in to see all your applications
          </Link>
        </p>
      </div>
    </div>
  )
}

export default function PublicOfferPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <OfferContent />
    </Suspense>
  )
}

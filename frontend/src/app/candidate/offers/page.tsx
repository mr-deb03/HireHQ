'use client'

import { useQuery } from '@tanstack/react-query'
import { CalendarCheck, CheckCircle2, Gift } from 'lucide-react'
import Link from 'next/link'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Notice } from '@/components/data'
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '@/components/ui'
import { api } from '@/lib/api'
import type { OfferStatus } from '@/lib/types'
import { formatCurrency, formatDate, formatRelative, titleCase } from '@/lib/utils'

/** The candidate portal's offer summary — terms only, no internal fields. */
interface MyOffer {
  id: string
  reference_code: string
  company_name?: string | null
  position_title: string
  base_salary: number
  total_compensation: number
  currency: string
  salary_period: string
  benefits: string[]
  joining_date?: string | null
  status: OfferStatus
  expires_at?: string | null
  can_respond: boolean
}

const STATUS_TONES: Record<OfferStatus, 'success' | 'neutral' | 'warning' | 'danger' | 'info'> = {
  DRAFT: 'neutral',
  SENT: 'info',
  VIEWED: 'info',
  ACCEPTED: 'success',
  REJECTED: 'neutral',
  WITHDRAWN: 'neutral',
  EXPIRED: 'warning',
}

export default function CandidateOffersPage() {
  const offersQuery = useQuery({
    queryKey: ['my-offers'],
    queryFn: () => api.get<MyOffer[]>('/me/offers'),
  })

  const pending = (offersQuery.data ?? []).filter((offer) => offer.can_respond)

  return (
    <>
      <PageHeader title="Your offers" description="Offers extended to you, and their terms." />

      <PageBody className="space-y-5">
        {pending.length > 0 && (
          <Notice tone="info" title={`${pending.length} awaiting your response`}>
            Take the time you need. If anything does not match what you discussed, ask
            before you respond — a question is always reasonable.
          </Notice>
        )}

        {offersQuery.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, i) => (
              <Skeleton key={i} className="h-48" />
            ))}
          </div>
        ) : offersQuery.isError ? (
          <Card>
            <ErrorState
              message={(offersQuery.error as Error).message}
              onRetry={() => offersQuery.refetch()}
            />
          </Card>
        ) : !offersQuery.data?.length ? (
          <Card>
            <EmptyState
              icon={Gift}
              title="No offers yet"
              description="When a company makes you an offer, its full terms appear here and you can accept or decline."
              action={
                <Link href="/candidate/applications">
                  <Button variant="secondary">View your applications</Button>
                </Link>
              }
            />
          </Card>
        ) : (
          <div className="space-y-4">
            {offersQuery.data.map((offer) => (
              <Card key={offer.id} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="font-mono text-xs text-ink-400">{offer.reference_code}</p>
                    <h3 className="mt-1 text-[17px] font-semibold text-ink-900">
                      {offer.position_title}
                    </h3>
                    {offer.company_name && (
                      <p className="mt-0.5 text-sm text-ink-600">{offer.company_name}</p>
                    )}
                  </div>
                  <Badge tone={STATUS_TONES[offer.status]}>{titleCase(offer.status)}</Badge>
                </div>

                <div className="mt-4 rounded-xl bg-ink-50 px-4 py-3.5">
                  <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                    Total compensation
                  </p>
                  <p className="mt-1 text-2xl font-semibold tabular-nums text-ink-900">
                    {formatCurrency(offer.total_compensation, offer.currency, { compact: false })}
                    <span className="ml-1.5 text-sm font-normal text-ink-500">
                      per {offer.salary_period.toLowerCase().replace('ly', '')}
                    </span>
                  </p>
                  <p className="mt-1 text-sm text-ink-600">
                    Base {formatCurrency(offer.base_salary, offer.currency, { compact: false })}
                  </p>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-ink-700">
                  {offer.joining_date && (
                    <span className="flex items-center gap-1.5">
                      <CalendarCheck className="h-3.5 w-3.5 text-ink-400" />
                      Starts {formatDate(offer.joining_date)}
                    </span>
                  )}
                  {offer.expires_at && offer.can_respond && (
                    <span className="text-warning-700">
                      Expires {formatRelative(offer.expires_at)}
                    </span>
                  )}
                </div>

                {offer.benefits.length > 0 && (
                  <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5">
                    {offer.benefits.slice(0, 6).map((benefit) => (
                      <li key={benefit} className="flex items-center gap-1.5 text-sm text-ink-600">
                        <CheckCircle2 className="h-3.5 w-3.5 text-success-500" />
                        {benefit}
                      </li>
                    ))}
                  </ul>
                )}

                {offer.can_respond && (
                  <div className="mt-5 border-t border-ink-100 pt-4">
                    {/*
                      Responding happens on the tokenised page linked from the offer
                      email, which is where the full terms and the accept/decline actions
                      live. Duplicating the decision here would risk the two views drifting.
                    */}
                    <p className="text-sm text-ink-600">
                      Open the link in your offer email to read the full terms and respond.
                      Can&rsquo;t find it? Ask your recruiter to resend it.
                    </p>
                  </div>
                )}

                {offer.status === 'ACCEPTED' && (
                  <div className="mt-4">
                    <Notice tone="info">
                      You accepted this offer. Your onboarding checklist is on your
                      dashboard.
                    </Notice>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </PageBody>
    </>
  )
}

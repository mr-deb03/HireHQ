'use client'

/**
 * The recruiter inbox.
 *
 * Two honesty rules shape this page. Outbound messages show their real delivery status —
 * a message recorded while no provider was configured reads "not sent", never "sent"
 * (§69). And incoming replies only appear if a mailbox is actually connected, so the
 * empty state explains that rather than implying nobody has written back.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  Inbox,
  Link2,
  Link2Off,
  Mail,
  RefreshCw,
  Send,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { PageBody, PageHeader } from '@/components/app-shell'
import { LiveIndicator, Notice } from '@/components/data'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Modal,
  Select,
  Skeleton,
  Tabs,
} from '@/components/ui'
import { useRealtime } from '@/hooks/use-realtime'
import { ApiError, api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type {
  EmailAccount,
  EmailDeliveryStatus,
  EmailMessage,
  EmailProviderStatus,
} from '@/lib/types'
import { cn, formatRelative, titleCase } from '@/lib/utils'

const DELIVERY_TONES: Record<EmailDeliveryStatus, 'success' | 'neutral' | 'warning' | 'danger'> = {
  SENT: 'success',
  QUEUED: 'neutral',
  RECEIVED: 'success',
  FAILED: 'danger',
  NOT_SENT_NO_PROVIDER: 'warning',
}

const DELIVERY_LABELS: Record<EmailDeliveryStatus, string> = {
  SENT: 'Sent',
  QUEUED: 'Queued',
  RECEIVED: 'Received',
  FAILED: 'Failed',
  NOT_SENT_NO_PROVIDER: 'Not sent',
}

interface SyncResult {
  synced: boolean
  messages_imported: number
  matched_to_candidates: number
  last_synced_at?: string | null
  detail: string
}

function EmailsContent() {
  const router = useRouter()
  const params = useSearchParams()
  const { can } = useAuth()
  const { status: liveStatus } = useRealtime()

  const direction = params.get('direction') ?? ''
  const page = Number(params.get('page') ?? '1')
  const [reading, setReading] = useState<EmailMessage | null>(null)
  const [managingAccounts, setManagingAccounts] = useState(false)

  const messagesQuery = useQuery({
    queryKey: ['email-messages', direction, page],
    queryFn: () =>
      api.get<Page<EmailMessage>>('/emails/messages', {
        query: { direction: direction || undefined, page, page_size: 25 },
      }),
  })

  const providerQuery = useQuery({
    queryKey: ['email-provider-status'],
    queryFn: () => api.get<EmailProviderStatus>('/emails/provider-status'),
  })

  const accountsQuery = useQuery({
    queryKey: ['email-accounts'],
    queryFn: () => api.get<EmailAccount[]>('/emails/accounts'),
    enabled: can('email:account:connect'),
  })

  const connected = params.get('connected')
  const noInbound = (accountsQuery.data?.length ?? 0) === 0

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params.toString())
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    router.push(`/recruiter/emails${next.toString() ? `?${next}` : ''}`)
  }

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Everything HireHQ has sent, plus replies from connected mailboxes."
        actions={
          <>
            <LiveIndicator status={liveStatus} />
            {can('email:account:connect') && (
              <Button variant="secondary" size="sm" onClick={() => setManagingAccounts(true)}>
                <Link2 className="h-4 w-4" />
                Mailboxes
                {accountsQuery.data && accountsQuery.data.length > 0 && (
                  <span className="ml-0.5 rounded bg-ink-200 px-1.5 text-xs">
                    {accountsQuery.data.length}
                  </span>
                )}
              </Button>
            )}
          </>
        }
      >
        <div className="mt-5">
          <Tabs
            tabs={[
              { id: '', label: 'All' },
              { id: 'OUTBOUND', label: 'Sent' },
              { id: 'INBOUND', label: 'Received' },
            ]}
            active={direction}
            onChange={(id) => setParam('direction', id)}
          />
        </div>
      </PageHeader>

      <PageBody className="space-y-4">
        {connected === '1' && (
          <Notice tone="info" title="Mailbox connected">
            Replies will be imported within a few minutes, and matched to the candidate who
            sent them.
          </Notice>
        )}
        {connected === '0' && (
          <Notice tone="warning" title="Mailbox was not connected">
            The authorisation did not complete
            {params.get('reason') ? ` (${params.get('reason')})` : ''}. Start it again from
            Mailboxes.
          </Notice>
        )}

        {providerQuery.data && !providerQuery.data.transmits && (
          <Notice tone="warning" title="Outgoing email is not configured">
            {providerQuery.data.message} Messages below marked <strong>Not sent</strong> were
            composed and recorded but never delivered to anyone.
          </Notice>
        )}

        {direction === 'INBOUND' && noInbound && can('email:account:connect') && (
          <Notice
            tone="info"
            title="No mailbox is connected"
            action={
              <Button size="sm" variant="secondary" onClick={() => setManagingAccounts(true)}>
                Connect
              </Button>
            }
          >
            HireHQ can only show replies once someone connects the mailbox candidates write
            to. Nothing is being read from anyone&rsquo;s email until then.
          </Notice>
        )}

        {messagesQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        ) : messagesQuery.isError ? (
          <Card>
            <ErrorState
              message={(messagesQuery.error as Error).message}
              onRetry={() => messagesQuery.refetch()}
            />
          </Card>
        ) : !messagesQuery.data?.items.length ? (
          <Card>
            <EmptyState
              icon={Inbox}
              title={direction === 'INBOUND' ? 'No replies yet' : 'No messages yet'}
              description={
                direction === 'INBOUND'
                  ? noInbound
                    ? 'Connect a mailbox and candidate replies will appear here.'
                    : 'Nothing has come in since the last sync.'
                  : 'Emails sent from HireHQ — status changes, interview invitations, offers — appear here.'
              }
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <ul className="divide-y divide-ink-100">
              {messagesQuery.data.items.map((message) => (
                <li key={message.id}>
                  <button
                    onClick={() => setReading(message)}
                    className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-ink-50"
                  >
                    <span
                      className={cn(
                        'mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg',
                        message.direction === 'INBOUND'
                          ? 'bg-brand-50 text-brand-600'
                          : 'bg-ink-100 text-ink-500',
                      )}
                    >
                      {message.direction === 'INBOUND' ? (
                        <Mail className="h-3.5 w-3.5" />
                      ) : (
                        <Send className="h-3.5 w-3.5" />
                      )}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium text-ink-900">
                          {message.subject}
                        </span>
                        {message.is_automated && <Badge>Automated</Badge>}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-ink-500">
                        {message.direction === 'INBOUND'
                          ? `From ${message.from_name ?? message.from_address}`
                          : `To ${message.to_addresses.join(', ')}`}
                      </span>
                    </span>

                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <Badge tone={DELIVERY_TONES[message.delivery_status]}>
                        {DELIVERY_LABELS[message.delivery_status]}
                      </Badge>
                      <span className="text-xs text-ink-400">
                        {formatRelative(message.sent_at ?? message.created_at)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {messagesQuery.data && messagesQuery.data.meta.total_pages > 1 && (
          <div className="flex items-center justify-between">
            <Button
              variant="secondary"
              size="sm"
              disabled={!messagesQuery.data.meta.has_previous}
              onClick={() => setParam('page', String(page - 1))}
            >
              Previous
            </Button>
            <span className="text-sm text-ink-500">
              Page {messagesQuery.data.meta.page} of {messagesQuery.data.meta.total_pages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              disabled={!messagesQuery.data.meta.has_next}
              onClick={() => setParam('page', String(page + 1))}
            >
              Next
            </Button>
          </div>
        )}
      </PageBody>

      {reading && <MessageModal message={reading} onClose={() => setReading(null)} />}
      {managingAccounts && (
        <MailboxModal accounts={accountsQuery.data ?? []} onClose={() => setManagingAccounts(false)} />
      )}
    </>
  )
}

function MessageModal({ message, onClose }: { message: EmailMessage; onClose: () => void }) {
  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={message.subject}
      description={
        message.direction === 'INBOUND'
          ? `From ${message.from_name ?? message.from_address}`
          : `To ${message.to_addresses.join(', ')}`
      }
      footer={
        <>
          {message.candidate_id && (
            <Link href={`/recruiter/candidates/${message.candidate_id}`}>
              <Button variant="secondary">Open candidate</Button>
            </Link>
          )}
          <Button onClick={onClose}>Close</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={DELIVERY_TONES[message.delivery_status]}>
            {DELIVERY_LABELS[message.delivery_status]}
          </Badge>
          {message.transport && <Badge>{message.transport}</Badge>}
          <span className="text-xs text-ink-400">
            {formatRelative(message.sent_at ?? message.created_at)}
          </span>
        </div>

        {message.delivery_status === 'NOT_SENT_NO_PROVIDER' && (
          <Notice tone="warning" title="This message was never delivered">
            It was composed and recorded while no email provider was configured. The
            recipient has not seen it.
          </Notice>
        )}
        {message.delivery_status === 'FAILED' && message.failure_reason && (
          <Notice tone="warning" title="Delivery failed">
            {message.failure_reason}
          </Notice>
        )}

        {message.body_text ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {message.body_text}
          </p>
        ) : message.body_html ? (
          /*
            Rendered as text rather than injected as HTML: an inbound message is
            attacker-controlled content, and no candidate reply is worth an XSS.
          */
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink-700">
            {message.body_html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()}
          </p>
        ) : (
          <p className="text-sm text-ink-500">This message has no body.</p>
        )}
      </div>
    </Modal>
  )
}

function MailboxModal({
  accounts,
  onClose,
}: {
  accounts: EmailAccount[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState<'google' | 'microsoft'>('google')

  const connect = useMutation({
    mutationFn: () =>
      api.post<{ authorization_url: string }>('/emails/accounts/connect', undefined, {
        query: { provider },
      }),
    onSuccess: (result) => {
      window.location.href = result.authorization_url
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not start the connection'),
  })

  const sync = useMutation({
    mutationFn: (accountId: string) => api.post<SyncResult>(`/emails/accounts/${accountId}/sync`),
    onSuccess: (result) => {
      if (result.synced) toast.success(result.detail)
      else toast.warning(result.detail)
      void queryClient.invalidateQueries({ queryKey: ['email-messages'] })
      void queryClient.invalidateQueries({ queryKey: ['email-accounts'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Sync failed'),
  })

  const disconnect = useMutation({
    mutationFn: (accountId: string) => api.delete(`/emails/accounts/${accountId}`),
    onSuccess: () => {
      toast.success('Mailbox disconnected. Stored tokens were deleted.')
      void queryClient.invalidateQueries({ queryKey: ['email-accounts'] })
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not disconnect'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="Connected mailboxes"
      description="Import candidate replies into HireHQ."
      footer={<Button onClick={onClose}>Done</Button>}
    >
      <div className="space-y-5">
        <Notice tone="neutral" title="Read-only access">
          HireHQ requests permission to <strong>read</strong> mail only. It imports replies
          and never sends from, deletes from, or otherwise changes a personal mailbox.
          Outgoing mail always goes through the server&rsquo;s own SMTP settings.
        </Notice>

        {accounts.length > 0 && (
          <ul className="space-y-2.5">
            {accounts.map((account) => (
              <li
                key={account.id}
                className="rounded-xl border border-ink-200 px-3.5 py-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-900">
                      {account.email_address}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-500">
                      {titleCase(account.provider)}
                      {account.last_synced_at
                        ? ` · synced ${formatRelative(account.last_synced_at)}`
                        : ' · never synced'}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={sync.isPending && sync.variables === account.id}
                      onClick={() => sync.mutate(account.id)}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Sync
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={disconnect.isPending && disconnect.variables === account.id}
                      onClick={() => disconnect.mutate(account.id)}
                    >
                      <Link2Off className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>

                {account.sync_error && (
                  <p className="mt-2 flex items-start gap-1.5 text-xs text-warning-700">
                    <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                    {account.sync_error}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        <div className="border-t border-ink-100 pt-5">
          <p className="text-sm font-medium text-ink-900">Connect another mailbox</p>
          <div className="mt-2.5 flex items-end gap-2">
            <div className="flex-1">
              <Select
                aria-label="Provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value as 'google' | 'microsoft')}
              >
                <option value="google">Google Workspace / Gmail</option>
                <option value="microsoft">Microsoft 365 / Outlook</option>
              </Select>
            </div>
            <Button loading={connect.isPending} onClick={() => connect.mutate()}>
              <Link2 className="h-4 w-4" />
              Connect
            </Button>
          </div>
          <p className="mt-2 text-xs text-ink-500">
            You will be taken to {provider === 'google' ? 'Google' : 'Microsoft'} to grant
            access, then returned here.
          </p>
        </div>
      </div>
    </Modal>
  )
}

export default function RecruiterEmailsPage() {
  return (
    <Suspense
      fallback={
        <PageBody>
          <Skeleton className="h-96" />
        </PageBody>
      }
    >
      <EmailsContent />
    </Suspense>
  )
}

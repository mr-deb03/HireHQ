'use client'

import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, MailWarning } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useRef, useState } from 'react'

import { Notice } from '@/components/data'
import { Logo } from '@/components/marketing'
import { Button, Card, Input, Skeleton } from '@/components/ui'
import { ApiError, api } from '@/lib/api'

interface MessageResponse {
  message: string
  email_delivery?: string | null
}

function VerifyContent() {
  const params = useSearchParams()
  const token = params.get('token') ?? ''

  const [state, setState] = useState<'verifying' | 'verified' | 'failed' | 'no-token'>(
    token ? 'verifying' : 'no-token',
  )
  const [error, setError] = useState<string | null>(null)

  // React 18 mounts effects twice in development. A verification token is single-use, so
  // the second call would fail and show an error for a verification that actually worked.
  const attempted = useRef(false)

  useEffect(() => {
    if (!token || attempted.current) return
    attempted.current = true

    api
      .post<MessageResponse>('/auth/verify-email', { token }, { auth: false })
      .then(() => setState('verified'))
      .catch((err) => {
        setError(
          err instanceof ApiError
            ? err.message
            : 'This verification link could not be used.',
        )
        setState('failed')
      })
  }, [token])

  return (
    <div className="flex min-h-full flex-col justify-center bg-ink-50 px-4 py-12">
      <div className="mx-auto w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <Card className="p-7">
          {state === 'verifying' && (
            <>
              <Skeleton className="h-11 w-11 rounded-2xl" />
              <Skeleton className="mt-4 h-6 w-48" />
              <Skeleton className="mt-2 h-4 w-full" />
              <p className="sr-only" role="status">
                Verifying your email address
              </p>
            </>
          )}

          {state === 'verified' && (
            <>
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-success-50">
                <CheckCircle2 className="h-5 w-5 text-success-600" />
              </span>
              <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
                Email verified
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                Your address is confirmed. You can sign in and start applying.
              </p>
              <Link href="/login" className="mt-6 block">
                <Button size="lg" className="w-full">
                  Sign in
                </Button>
              </Link>
            </>
          )}

          {(state === 'failed' || state === 'no-token') && (
            <>
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-warning-50">
                <MailWarning className="h-5 w-5 text-warning-600" />
              </span>
              <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
                {state === 'no-token' ? 'This link is incomplete' : 'Verification failed'}
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                {state === 'no-token'
                  ? 'The link is missing its token. Use the most recent verification email, or request a new one below.'
                  : (error ??
                    'The link may have expired or already been used. Request a new one below.')}
              </p>

              <div className="mt-6 border-t border-ink-100 pt-6">
                <ResendForm />
              </div>
            </>
          )}
        </Card>

        <p className="mt-6 text-center text-sm text-ink-500">
          <Link href="/login" className="hover:text-ink-800">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  )
}

function ResendForm() {
  const [email, setEmail] = useState('')

  const resend = useMutation({
    mutationFn: (address: string) =>
      api.post<MessageResponse>('/auth/resend-verification', { email: address }, { auth: false }),
  })

  if (resend.isSuccess) {
    const undeliverable = resend.data.email_delivery === 'NOT_SENT_NO_PROVIDER'
    return undeliverable ? (
      <Notice tone="warning" title="This server cannot send email">
        No outbound email provider is configured, so no verification email was delivered.
        Ask an administrator to verify your account directly, or to configure SMTP.
      </Notice>
    ) : (
      <p className="text-sm text-ink-600">
        If <span className="font-medium text-ink-800">{email}</span> has an unverified
        account, a new verification email is on its way.
      </p>
    )
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        resend.mutate(email)
      }}
      className="space-y-3"
    >
      <Input
        label="Send a new verification email"
        name="email"
        type="email"
        autoComplete="email"
        required
        placeholder="you@example.com"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Button type="submit" variant="secondary" className="w-full" loading={resend.isPending}>
        Resend verification email
      </Button>
    </form>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <VerifyContent />
    </Suspense>
  )
}

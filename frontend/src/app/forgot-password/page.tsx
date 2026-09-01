'use client'

import { ArrowLeft, MailCheck } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { Logo } from '@/components/marketing'
import { Notice } from '@/components/data'
import { Button, Card, Input } from '@/components/ui'
import { ApiError, api } from '@/lib/api'

interface MessageResponse {
  message: string
  /**
   * Describes the server, not the account: `NOT_SENT_NO_PROVIDER` means this deployment
   * has no outbound email at all, so no reset link could have been delivered to anyone.
   */
  email_delivery?: string | null
}

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<MessageResponse | null>(null)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setLoading(true)
    try {
      setResult(
        await api.post<MessageResponse>('/auth/forgot-password', { email }, { auth: false }),
      )
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not send the reset link.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-full flex-col justify-center bg-ink-50 px-4 py-12">
      <div className="mx-auto w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <Card className="p-7">
          {result ? (
            <>
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-success-50">
                <MailCheck className="h-5 w-5 text-success-600" />
              </span>
              <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
                {result.email_delivery === 'NOT_SENT_NO_PROVIDER'
                  ? 'Request received'
                  : 'Check your email'}
              </h1>
              {/*
                The response is deliberately identical whether or not the address exists,
                so this text must not imply an account was found — and must not promise
                delivery the server could not perform.
              */}
              <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                {result.email_delivery === 'NOT_SENT_NO_PROVIDER' ? (
                  <>
                    Your request for{' '}
                    <span className="font-medium text-ink-800">{email}</span> was recorded.
                  </>
                ) : (
                  <>
                    If an account exists for{' '}
                    <span className="font-medium text-ink-800">{email}</span>, a password
                    reset link is on its way. It expires in one hour.
                  </>
                )}
              </p>

              {result.email_delivery === 'NOT_SENT_NO_PROVIDER' && (
                <div className="mt-5">
                  <Notice tone="warning" title="This server cannot send email">
                    No outbound email provider is configured, so no reset link was
                    delivered — to this or any address. Ask an administrator to reset your
                    password directly, or to configure SMTP.
                  </Notice>
                </div>
              )}

              <Link href="/login" className="mt-6 block">
                <Button variant="secondary" className="w-full">
                  <ArrowLeft className="h-4 w-4" />
                  Back to sign in
                </Button>
              </Link>
            </>
          ) : (
            <>
              <h1 className="text-title font-semibold tracking-tight text-ink-900">
                Reset your password
              </h1>
              <p className="mt-1.5 text-sm text-ink-600">
                Enter the email you sign in with and we will send you a reset link.
              </p>

              <form onSubmit={onSubmit} className="mt-6 space-y-4">
                {error && (
                  <div
                    role="alert"
                    className="rounded-xl border border-danger-100 bg-danger-50 px-3.5 py-2.5 text-sm text-danger-700"
                  >
                    {error}
                  </div>
                )}

                <Input
                  label="Email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />

                <Button type="submit" size="lg" className="w-full" loading={loading}>
                  Send reset link
                </Button>
              </form>

              <p className="mt-6 text-center text-sm text-ink-600">
                <Link href="/login" className="font-medium text-brand-600 hover:text-brand-700">
                  Back to sign in
                </Link>
              </p>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

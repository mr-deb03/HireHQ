'use client'

import { CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Logo } from '@/components/marketing'
import { Button, Card, Input } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { cn } from '@/lib/utils'

/** Mirrors the backend's PASSWORD_MIN_LENGTH; the server is still the authority. */
const MIN_LENGTH = 10

function strengthOf(password: string): { score: number; label: string; tone: string } {
  let score = 0
  if (password.length >= MIN_LENGTH) score += 1
  if (password.length >= 14) score += 1
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1
  if (/\d/.test(password)) score += 1
  if (/[^A-Za-z0-9]/.test(password)) score += 1

  if (score <= 2) return { score, label: 'Weak', tone: 'bg-danger-500' }
  if (score === 3) return { score, label: 'Fair', tone: 'bg-warning-500' }
  if (score === 4) return { score, label: 'Good', tone: 'bg-brand-500' }
  return { score, label: 'Strong', tone: 'bg-success-500' }
}

function ResetForm() {
  const router = useRouter()
  const params = useSearchParams()
  const token = params.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const strength = useMemo(() => strengthOf(password), [password])
  const mismatch = confirm.length > 0 && confirm !== password

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (mismatch) return
    setError(null)
    setLoading(true)
    try {
      await api.post('/auth/reset-password', { token, password }, { auth: false })
      setDone(true)
      toast.success('Password reset. Please sign in.')
      // Give the confirmation a moment to be read rather than flashing past.
      setTimeout(() => router.push('/login'), 2500)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Could not reset your password. The link may have expired.',
      )
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
          {!token ? (
            <>
              <h1 className="text-title font-semibold tracking-tight text-ink-900">
                This link is incomplete
              </h1>
              <p className="mt-1.5 text-sm text-ink-600">
                The reset link is missing its token. Request a new one and use the most
                recent email.
              </p>
              <Link href="/forgot-password" className="mt-6 block">
                <Button className="w-full">Request a new link</Button>
              </Link>
            </>
          ) : done ? (
            <>
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-2xl bg-success-50">
                <CheckCircle2 className="h-5 w-5 text-success-600" />
              </span>
              <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
                Password updated
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                Every other session has been signed out. Taking you to sign in…
              </p>
              <Link href="/login" className="mt-6 block">
                <Button className="w-full">Sign in now</Button>
              </Link>
            </>
          ) : (
            <>
              <h1 className="text-title font-semibold tracking-tight text-ink-900">
                Choose a new password
              </h1>
              <p className="mt-1.5 text-sm text-ink-600">
                At least {MIN_LENGTH} characters. Signing in elsewhere will be ended.
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

                <div>
                  <Input
                    label="New password"
                    name="password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={MIN_LENGTH}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  {password && (
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex h-1 flex-1 gap-1">
                        {[0, 1, 2, 3, 4].map((i) => (
                          <div
                            key={i}
                            className={cn(
                              'h-full flex-1 rounded-full',
                              i < strength.score ? strength.tone : 'bg-ink-100',
                            )}
                          />
                        ))}
                      </div>
                      <span className="text-xs text-ink-500">{strength.label}</span>
                    </div>
                  )}
                </div>

                <Input
                  label="Confirm password"
                  name="confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  error={mismatch ? 'The two passwords do not match' : undefined}
                />

                <Button
                  type="submit"
                  size="lg"
                  className="w-full"
                  loading={loading}
                  disabled={mismatch || password.length < MIN_LENGTH}
                >
                  Reset password
                </Button>
              </form>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <ResetForm />
    </Suspense>
  )
}

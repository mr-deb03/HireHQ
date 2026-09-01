'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import { toast } from 'sonner'

import { Logo } from '@/components/marketing'
import { Button, Card, Input } from '@/components/ui'
import { ApiError } from '@/lib/api'
import { homeFor, useAuth } from '@/lib/auth'

function LoginForm() {
  const router = useRouter()
  const params = useSearchParams()
  const { signIn } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const user = await signIn(email, password)
      toast.success(`Welcome back, ${user.first_name}`)
      const next = params.get('next')
      router.push(next && next.startsWith('/') ? next : homeFor(user))
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
        // Unverified accounts need a different action, not just an error.
        if (err.code === 'EMAIL_NOT_VERIFIED') {
          setError('Please verify your email address before signing in.')
        }
      } else {
        setError('Could not sign in. Please try again.')
      }
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
          <h1 className="text-title font-semibold tracking-tight text-ink-900">Sign in</h1>
          <p className="mt-1.5 text-sm text-ink-600">
            Access your hiring workspace or track your applications.
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

            <div>
              <Input
                label="Password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <div className="mt-1.5 text-right">
                <Link
                  href="/forgot-password"
                  className="text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  Forgot your password?
                </Link>
              </div>
            </div>

            <Button type="submit" size="lg" className="w-full" loading={loading}>
              Sign in
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-ink-600">
            New here?{' '}
            <Link href="/register" className="font-medium text-brand-600 hover:text-brand-700">
              Create a candidate account
            </Link>
          </p>
        </Card>

        <p className="mt-6 text-center text-sm text-ink-500">
          <Link href="/jobs" className="hover:text-ink-800">
            Browse jobs without an account
          </Link>
        </p>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-full bg-ink-50" />}>
      <LoginForm />
    </Suspense>
  )
}

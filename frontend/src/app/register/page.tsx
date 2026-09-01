'use client'

import { CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

import { Logo } from '@/components/marketing'
import { Button, Card, Input } from '@/components/ui'
import { ApiError, api } from '@/lib/api'

interface RegisterResponse {
  user: { email: string; first_name: string }
  verification_email_status: string
  message: string
}

/** Mirrors the backend password policy so users get feedback before submitting. */
function passwordProblems(password: string): string[] {
  const problems: string[] = []
  if (password.length < 10) problems.push('at least 10 characters')
  if (!/[a-z]/.test(password)) problems.push('a lowercase letter')
  if (!/[A-Z]/.test(password)) problems.push('an uppercase letter')
  if (!/\d/.test(password)) problems.push('a digit')
  if (/^[a-zA-Z0-9]*$/.test(password)) problems.push('a symbol')
  return problems
}

export default function RegisterPage() {
  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    email: '',
    password: '',
    phone: '',
  })
  const [accepted, setAccepted] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState<RegisterResponse | null>(null)

  const problems = form.password ? passwordProblems(form.password) : []

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const found: Record<string, string> = {}
    if (!form.first_name.trim()) found.first_name = 'Enter your first name'
    if (!form.last_name.trim()) found.last_name = 'Enter your last name'
    if (!form.email.trim()) found.email = 'Enter your email address'
    if (problems.length) found.password = `Your password needs ${problems.join(', ')}`
    if (!accepted) found.accept_terms = 'You must accept the terms to continue'

    setErrors(found)
    if (Object.keys(found).length) return

    setLoading(true)
    try {
      const result = await api.post<RegisterResponse>(
        '/auth/register',
        { ...form, phone: form.phone || null, accept_terms: true },
        { auth: false },
      )
      setDone(result)
      toast.success('Account created')
    } catch (error) {
      if (error instanceof ApiError) {
        const fields = error.fieldErrors
        setErrors(Object.keys(fields).length ? fields : { email: error.message })
        toast.error(error.message)
      } else {
        toast.error('Could not create your account. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    // The backend tells us truthfully whether the verification email was transmitted,
    // and the page must not claim otherwise.
    const emailSent = done.verification_email_status === 'SENT'
    return (
      <div className="flex min-h-full flex-col justify-center bg-ink-50 px-4 py-12">
        <div className="mx-auto w-full max-w-md">
          <div className="mb-8 flex justify-center">
            <Logo />
          </div>
          <Card className="p-7 text-center">
            <span className="mx-auto inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-success-50">
              <CheckCircle2 className="h-6 w-6 text-success-600" />
            </span>
            <h1 className="mt-4 text-title font-semibold tracking-tight text-ink-900">
              Account created
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-ink-600">{done.message}</p>

            {!emailSent && (
              <div className="mt-4 rounded-xl border border-warning-100 bg-warning-50 px-3.5 py-3 text-left text-xs leading-relaxed text-warning-700">
                <strong className="font-semibold">No email was sent.</strong> This server has no
                email provider configured, so the verification message could not be delivered.
                An administrator can verify your account directly.
              </div>
            )}

            <Link href="/login" className="mt-6 block">
              <Button className="w-full">Go to sign in</Button>
            </Link>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-full flex-col justify-center bg-ink-50 px-4 py-12">
      <div className="mx-auto w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <Card className="p-7">
          <h1 className="text-title font-semibold tracking-tight text-ink-900">
            Create your account
          </h1>
          <p className="mt-1.5 text-sm text-ink-600">
            Apply for roles and track every application in one place.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="First name"
                name="first_name"
                required
                autoComplete="given-name"
                value={form.first_name}
                onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                error={errors.first_name}
              />
              <Input
                label="Last name"
                name="last_name"
                required
                autoComplete="family-name"
                value={form.last_name}
                onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                error={errors.last_name}
              />
            </div>

            <Input
              label="Email"
              name="email"
              type="email"
              required
              autoComplete="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              error={errors.email}
            />

            <Input
              label="Phone"
              name="phone"
              type="tel"
              autoComplete="tel"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />

            <Input
              label="Password"
              name="password"
              type="password"
              required
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              error={errors.password}
              hint={
                form.password && problems.length
                  ? `Needs ${problems.join(', ')}`
                  : 'At least 10 characters, with upper and lower case, a digit and a symbol'
              }
            />

            <label className="flex cursor-pointer gap-2.5">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(e) => setAccepted(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-ink-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="text-sm leading-relaxed text-ink-600">
                I accept the terms of service and privacy policy, and consent to HireHQ
                processing my data to support my job applications.
              </span>
            </label>
            {errors.accept_terms && (
              <p className="-mt-2 text-xs text-danger-600">{errors.accept_terms}</p>
            )}

            <Button type="submit" size="lg" className="w-full" loading={loading}>
              Create account
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-ink-600">
            Already have an account?{' '}
            <Link href="/login" className="font-medium text-brand-600 hover:text-brand-700">
              Sign in
            </Link>
          </p>
        </Card>
      </div>
    </div>
  )
}

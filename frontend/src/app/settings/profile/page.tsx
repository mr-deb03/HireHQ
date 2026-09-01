'use client'

import { useMutation } from '@tanstack/react-query'
import { KeyRound, LogOut, ShieldCheck, UserCog } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

import { AppShell, PageBody, PageHeader } from '@/components/app-shell'
import { Field, FieldGrid, Notice } from '@/components/data'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Input,
  Skeleton,
} from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import { useAuth, useRequireAuth } from '@/lib/auth'
import type { AuthenticatedUser } from '@/lib/types'
import { formatDateTime, titleCase } from '@/lib/utils'

const MIN_PASSWORD_LENGTH = 10

export default function ProfileSettingsPage() {
  const { loading } = useRequireAuth()
  const { user, hasRole } = useAuth()

  if (loading || !user) {
    return (
      <div className="min-h-full bg-ink-50 p-6">
        <div className="mx-auto max-w-3xl space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  const variant = hasRole('SUPER_ADMIN')
    ? 'admin'
    : hasRole('CANDIDATE') && !user.company_id
      ? 'candidate'
      : 'recruiter'

  return (
    <AppShell variant={variant}>
      <PageHeader title="Profile settings" description="Your account and how you sign in." />
      <PageBody className="max-w-3xl space-y-5">
        <IdentityCard user={user} />
        <DetailsCard user={user} />
        <PasswordCard />
        <SessionsCard />
      </PageBody>
    </AppShell>
  )
}

function IdentityCard({ user }: { user: AuthenticatedUser }) {
  return (
    <Card>
      <CardBody className="flex flex-wrap items-center gap-5">
        <Avatar name={user.full_name} src={user.avatar_url} size="lg" />
        <div className="min-w-0 flex-1">
          <h2 className="text-title font-semibold tracking-tight text-ink-900">
            {user.full_name}
          </h2>
          <p className="mt-0.5 text-sm text-ink-600">{user.email}</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {user.roles.map((role) => (
              <Badge key={role.id} tone="brand">
                {titleCase(role.name)}
              </Badge>
            ))}
          </div>
        </div>
        {user.company && (
          <div className="rounded-xl bg-ink-50 px-3.5 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              Company
            </p>
            <p className="mt-0.5 text-sm font-medium text-ink-800">{user.company.name}</p>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function DetailsCard({ user }: { user: AuthenticatedUser }) {
  const { refresh } = useAuth()
  const [form, setForm] = useState({
    first_name: user.first_name,
    last_name: user.last_name,
    phone: user.phone ?? '',
    job_title: user.job_title ?? '',
  })

  const save = useMutation({
    mutationFn: () =>
      api.patch<AuthenticatedUser>('/auth/me', {
        first_name: form.first_name,
        last_name: form.last_name,
        phone: form.phone || null,
        job_title: form.job_title || null,
      }),
    onSuccess: async () => {
      toast.success('Profile updated.')
      await refresh()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save your profile'),
  })

  const dirty =
    form.first_name !== user.first_name ||
    form.last_name !== user.last_name ||
    form.phone !== (user.phone ?? '') ||
    form.job_title !== (user.job_title ?? '')

  return (
    <Card>
      <CardHeader className="flex items-center gap-2">
        <UserCog className="h-3.5 w-3.5 text-ink-400" />
        <CardTitle>Your details</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="First name"
            required
            value={form.first_name}
            onChange={(e) => setForm({ ...form, first_name: e.target.value })}
          />
          <Input
            label="Last name"
            required
            value={form.last_name}
            onChange={(e) => setForm({ ...form, last_name: e.target.value })}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Phone"
            type="tel"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
          <Input
            label="Job title"
            value={form.job_title}
            onChange={(e) => setForm({ ...form, job_title: e.target.value })}
          />
        </div>

        {/* Email is the sign-in identity; changing it needs verification, not a text box. */}
        <Notice tone="neutral">
          To change the email address you sign in with, contact an administrator — it is
          your account identity and needs re-verification.
        </Notice>

        <div className="flex justify-end">
          <Button loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
            Save changes
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')

  const change = useMutation({
    mutationFn: () =>
      api.post('/auth/change-password', { current_password: current, password: next }),
    onSuccess: () => {
      toast.success('Password changed. Every other session has been signed out.')
      setCurrent('')
      setNext('')
      setConfirm('')
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not change your password'),
  })

  const mismatch = confirm.length > 0 && confirm !== next
  const valid = current && next.length >= MIN_PASSWORD_LENGTH && !mismatch

  return (
    <Card>
      <CardHeader className="flex items-center gap-2">
        <KeyRound className="h-3.5 w-3.5 text-ink-400" />
        <CardTitle>Password</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <Input
          label="Current password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="New password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <Input
            label="Confirm new password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={mismatch ? 'The two passwords do not match' : undefined}
          />
        </div>

        <Notice tone="neutral">
          Changing your password signs out every other device immediately. You will stay
          signed in here.
        </Notice>

        <div className="flex justify-end">
          <Button loading={change.isPending} disabled={!valid} onClick={() => change.mutate()}>
            Change password
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

function SessionsCard() {
  const { user, signOut } = useAuth()

  const logoutAll = useMutation({
    mutationFn: () => api.post('/auth/logout-all'),
    onSuccess: async () => {
      toast.success('Signed out everywhere.')
      await signOut()
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not sign out everywhere'),
  })

  return (
    <Card>
      <CardHeader className="flex items-center gap-2">
        <ShieldCheck className="h-3.5 w-3.5 text-ink-400" />
        <CardTitle>Security</CardTitle>
      </CardHeader>
      <CardBody className="space-y-4">
        <FieldGrid columns={2}>
          <Field label="Email verified">
            {user?.status === 'PENDING_VERIFICATION' ? (
              <span className="flex items-center gap-2">
                <Badge tone="warning">Not verified</Badge>
                <Link
                  href="/verify-email"
                  className="text-xs font-medium text-brand-600 hover:text-brand-700"
                >
                  Resend
                </Link>
              </span>
            ) : (
              <Badge tone="success">Verified</Badge>
            )}
          </Field>
          <Field label="Account created">
            {user?.created_at ? formatDateTime(user.created_at) : '—'}
          </Field>
        </FieldGrid>

        <div className="border-t border-ink-100 pt-4">
          <p className="text-sm font-medium text-ink-900">Sign out everywhere</p>
          <p className="mt-0.5 text-sm text-ink-600">
            Ends every session, including this one. Use it if you think someone else has
            access to your account.
          </p>
          <Button
            variant="danger"
            className="mt-3"
            loading={logoutAll.isPending}
            onClick={() => logoutAll.mutate()}
          >
            <LogOut className="h-4 w-4" />
            Sign out everywhere
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Bell,
  Briefcase,
  Building2,
  CalendarDays,
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  FileText,
  Gift,
  LayoutDashboard,
  LogOut,
  Mail,
  Menu,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { api, type Page } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Notification } from '@/lib/types'
import { cn, formatRelative } from '@/lib/utils'

import { Logo } from './marketing'
import { Avatar, Badge, EmptyState } from './ui'

interface NavItem {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  /** Hidden unless the user holds one of these permissions. */
  permissions?: string[]
}

const RECRUITER_NAV: NavItem[] = [
  { href: '/recruiter/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/recruiter/jobs', label: 'Jobs', icon: Briefcase, permissions: ['job:read'] },
  { href: '/recruiter/pipeline', label: 'Pipeline', icon: ClipboardList, permissions: ['application:read'] },
  { href: '/recruiter/candidates', label: 'Candidates', icon: Users, permissions: ['candidate:read'] },
  { href: '/recruiter/interviews', label: 'Interviews', icon: CalendarDays, permissions: ['interview:read', 'interview:read:assigned'] },
  { href: '/recruiter/assessments', label: 'Assessments', icon: ClipboardCheck, permissions: ['assessment:manage', 'assessment:result:read'] },
  { href: '/recruiter/offers', label: 'Offers', icon: Gift, permissions: ['offer:read'] },
  { href: '/recruiter/talent-pool', label: 'Talent pool', icon: FileText, permissions: ['talent_pool:read'] },
  { href: '/recruiter/emails', label: 'Inbox', icon: Mail, permissions: ['email:read'] },
  { href: '/recruiter/workflows', label: 'Workflows', icon: Workflow, permissions: ['workflow:read', 'workflow:manage'] },
  { href: '/recruiter/analytics', label: 'Analytics', icon: Building2, permissions: ['analytics:read'] },
  { href: '/recruiter/assistant', label: 'Ask HireHQ', icon: Sparkles, permissions: ['ai:assistant:use'] },
]

const CANDIDATE_NAV: NavItem[] = [
  { href: '/candidate/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/candidate/applications', label: 'Applications', icon: ClipboardList },
  { href: '/candidate/interviews', label: 'Interviews', icon: CalendarDays },
  { href: '/candidate/offers', label: 'Offers', icon: Gift },
  { href: '/jobs', label: 'Browse jobs', icon: Briefcase },
]

const ADMIN_NAV: NavItem[] = [
  { href: '/admin/dashboard', label: 'Overview', icon: LayoutDashboard },
  { href: '/admin/companies', label: 'Companies', icon: Building2 },
  { href: '/admin/users', label: 'Users', icon: Users },
  { href: '/admin/audit-logs', label: 'Audit logs', icon: ShieldCheck },
]

export function AppShell({
  children,
  variant = 'recruiter',
}: {
  children: React.ReactNode
  variant?: 'recruiter' | 'candidate' | 'admin'
}) {
  const pathname = usePathname()
  const { user, signOut, can } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)

  const nav = (
    variant === 'candidate' ? CANDIDATE_NAV : variant === 'admin' ? ADMIN_NAV : RECRUITER_NAV
  ).filter((item) => !item.permissions || can(...item.permissions))

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => {
    setMobileOpen(false)
  }, [pathname])

  return (
    <div className="flex min-h-full bg-ink-50">
      {/* --------------------------------------------------------- sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-60 shrink-0 border-r border-ink-200 bg-white transition-transform lg:static lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center justify-between border-b border-ink-200 px-4">
          <Logo />
          <button
            className="rounded-lg p-1.5 text-ink-500 hover:bg-ink-100 lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex flex-col gap-0.5 p-3">
          {nav.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  active
                    ? 'bg-ink-900 text-white'
                    : 'text-ink-600 hover:bg-ink-100 hover:text-ink-900',
                )}
              >
                <item.icon className="h-4 w-4 shrink-0" />
                {item.label}
              </Link>
            )
          })}
        </nav>

        {user?.company && (
          <div className="mx-3 mt-2 rounded-xl bg-ink-50 px-3 py-2.5">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              Company
            </p>
            <p className="mt-0.5 truncate text-sm font-medium text-ink-800">
              {user.company.name}
            </p>
          </div>
        )}
      </aside>

      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-ink-950/30 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* ------------------------------------------------------------ main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-4 border-b border-ink-200 bg-white/90 px-4 backdrop-blur-md sm:px-6">
          <button
            className="rounded-lg p-2 text-ink-600 hover:bg-ink-100 lg:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>

          <div className="flex-1" />

          <div className="flex items-center gap-1">
            <NotificationBell />
            <UserMenu onSignOut={signOut} />
          </div>
        </header>

        <main className="flex-1">{children}</main>
      </div>
    </div>
  )
}

function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const countQuery = useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: () => api.get<{ count: number }>('/notifications/unread-count'),
    refetchInterval: 60_000,
  })

  const listQuery = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () =>
      api.get<Page<Notification>>('/notifications', { query: { page_size: 8 } }),
    enabled: open,
  })

  useEffect(() => {
    if (!open) return
    function onClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const count = countQuery.data?.count ?? 0

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${count ? `, ${count} unread` : ''}`}
        className="relative rounded-lg p-2 text-ink-600 transition-colors hover:bg-ink-100"
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger-600 px-1 text-[10px] font-semibold text-white">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 animate-slide-up rounded-2xl border border-ink-200 bg-white shadow-popover">
          <div className="flex items-center justify-between border-b border-ink-200 px-4 py-3">
            <h3 className="text-sm font-semibold text-ink-900">Notifications</h3>
            {count > 0 && <Badge tone="danger">{count} new</Badge>}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {listQuery.isLoading ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="skeleton h-12" />
                ))}
              </div>
            ) : !listQuery.data?.items.length ? (
              <EmptyState icon={Bell} title="Nothing new" description="You are all caught up." />
            ) : (
              listQuery.data.items.map((item) => {
                const body = (
                  <>
                    <div className="flex items-start gap-2">
                      {!item.is_read && (
                        <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />
                      )}
                      <div className={cn('min-w-0', item.is_read && 'pl-3.5')}>
                        <p className="text-sm font-medium text-ink-900">{item.title}</p>
                        {item.body && (
                          <p className="mt-0.5 line-clamp-2 text-xs text-ink-600">{item.body}</p>
                        )}
                        <p className="mt-1 text-[11px] text-ink-400">
                          {formatRelative(item.created_at)}
                        </p>
                      </div>
                    </div>
                  </>
                )
                return item.action_url ? (
                  <Link
                    key={item.id}
                    href={item.action_url}
                    onClick={() => setOpen(false)}
                    className="block border-b border-ink-100 px-4 py-3 transition-colors last:border-0 hover:bg-ink-50"
                  >
                    {body}
                  </Link>
                ) : (
                  <div key={item.id} className="border-b border-ink-100 px-4 py-3 last:border-0">
                    {body}
                  </div>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function UserMenu({ onSignOut }: { onSignOut: () => void }) {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  if (!user) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-ink-100"
      >
        <Avatar name={user.full_name} src={user.avatar_url} size="sm" />
        <span className="hidden text-sm font-medium text-ink-800 sm:block">
          {user.first_name}
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-ink-400" />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-60 animate-slide-up rounded-2xl border border-ink-200 bg-white p-1.5 shadow-popover">
          <div className="border-b border-ink-100 px-3 py-2.5">
            <p className="truncate text-sm font-medium text-ink-900">{user.full_name}</p>
            <p className="truncate text-xs text-ink-500">{user.email}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <span
                  key={role.id}
                  className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                >
                  {role.name.replace(/_/g, ' ').toLowerCase()}
                </span>
              ))}
            </div>
          </div>

          <Link
            href="/settings/profile"
            onClick={() => setOpen(false)}
            className="mt-1 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-700 hover:bg-ink-100"
          >
            <Settings className="h-4 w-4 text-ink-400" />
            Profile settings
          </Link>

          <button
            onClick={() => {
              setOpen(false)
              onSignOut()
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-danger-600 hover:bg-danger-50"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/** Consistent page header for authenticated pages. */
export function PageHeader({
  title,
  description,
  actions,
  children,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <div className="border-b border-ink-200 bg-white">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <h1 className="text-title-lg font-semibold tracking-tight text-ink-900">{title}</h1>
            {description && <p className="mt-1 text-sm text-ink-600">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
        </div>
        {children}
      </div>
    </div>
  )
}

export function PageBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('mx-auto max-w-7xl px-4 py-6 sm:px-6', className)}>{children}</div>
}

'use client'

import Link from 'next/link'
import { Menu, X } from 'lucide-react'
import { useState } from 'react'

import { useAuth, homeFor } from '@/lib/auth'
import { cn } from '@/lib/utils'

import { Button } from './ui'

export function Logo({ className, compact }: { className?: string; compact?: boolean }) {
  return (
    <Link href="/" className={cn('inline-flex items-center gap-2', className)}>
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-ink-900 text-sm font-bold text-white">
        H
      </span>
      {!compact && (
        <span className="text-[15px] font-semibold tracking-tight text-ink-900">HireHQ</span>
      )}
    </Link>
  )
}

/** Public site header. Adapts to whether the visitor is signed in. */
export function PublicHeader() {
  const { user, loading } = useAuth()
  const [open, setOpen] = useState(false)

  const links = [
    { href: '/jobs', label: 'Browse jobs' },
    { href: '/#how-it-works', label: 'How it works' },
    { href: '/#for-recruiters', label: 'For recruiters' },
  ]

  return (
    <header className="sticky top-0 z-40 border-b border-ink-200 bg-white/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex items-center gap-8">
          <Logo />
          <nav className="hidden items-center gap-1 md:flex">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-lg px-3 py-2 text-sm text-ink-600 transition-colors hover:bg-ink-100 hover:text-ink-900"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="hidden items-center gap-2 md:flex">
          {loading ? (
            <div className="h-9 w-32 animate-pulse rounded-xl bg-ink-100" />
          ) : user ? (
            <Link href={homeFor(user)}>
              <Button size="sm">Go to dashboard</Button>
            </Link>
          ) : (
            <>
              <Link href="/login">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/register">
                <Button size="sm">Create account</Button>
              </Link>
            </>
          )}
        </div>

        <button
          className="rounded-lg p-2 text-ink-600 hover:bg-ink-100 md:hidden"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {open && (
        <div className="animate-slide-up border-t border-ink-200 bg-white px-4 py-3 md:hidden">
          <nav className="flex flex-col gap-1">
            {links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="rounded-lg px-3 py-2.5 text-sm text-ink-700 hover:bg-ink-100"
              >
                {link.label}
              </Link>
            ))}
            <div className="mt-2 flex gap-2 border-t border-ink-200 pt-3">
              {user ? (
                <Link href={homeFor(user)} className="flex-1">
                  <Button className="w-full" size="sm">
                    Dashboard
                  </Button>
                </Link>
              ) : (
                <>
                  <Link href="/login" className="flex-1">
                    <Button variant="secondary" className="w-full" size="sm">
                      Sign in
                    </Button>
                  </Link>
                  <Link href="/register" className="flex-1">
                    <Button className="w-full" size="sm">
                      Create account
                    </Button>
                  </Link>
                </>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  )
}

export function PublicFooter() {
  return (
    <footer className="border-t border-ink-200 bg-white">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-center">
          <div>
            <Logo />
            <p className="mt-2 max-w-xs text-sm text-ink-500">
              From application to hire — automated, with people still making the decisions.
            </p>
          </div>
          <nav className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-600">
            <Link href="/jobs" className="hover:text-ink-900">
              Browse jobs
            </Link>
            <Link href="/track" className="hover:text-ink-900">
              Track application
            </Link>
            <Link href="/login" className="hover:text-ink-900">
              Sign in
            </Link>
          </nav>
        </div>
        <p className="mt-8 border-t border-ink-200 pt-6 text-xs text-ink-400">
          © {new Date().getFullYear()} HireHQ. AI features assist recruiters; hiring decisions
          remain with authorised humans.
        </p>
      </div>
    </footer>
  )
}

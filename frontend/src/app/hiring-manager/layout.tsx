'use client'

import { AppShell } from '@/components/app-shell'
import { Skeleton } from '@/components/ui'
import { useRequireAuth } from '@/lib/auth'

export default function HiringManagerLayout({ children }: { children: React.ReactNode }) {
  const { loading } = useRequireAuth({
    roles: ['HIRING_MANAGER', 'RECRUITER', 'COMPANY_ADMIN', 'SUPER_ADMIN'],
  })

  if (loading) {
    return (
      <div className="min-h-full bg-ink-50 p-6">
        <div className="mx-auto max-w-7xl space-y-4">
          <Skeleton className="h-10 w-64" />
          <div className="grid gap-4 sm:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-80" />
        </div>
      </div>
    )
  }

  return <AppShell variant="recruiter">{children}</AppShell>
}

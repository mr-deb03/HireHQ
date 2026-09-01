'use client'

import { AppShell } from '@/components/app-shell'
import { Skeleton } from '@/components/ui'
import { useRequireAuth } from '@/lib/auth'

export default function RecruiterLayout({ children }: { children: React.ReactNode }) {
  // Any staff role can reach this area; individual pages gate their own actions on
  // finer-grained permissions, and the server enforces all of it regardless.
  const { loading } = useRequireAuth({
    roles: ['COMPANY_ADMIN', 'RECRUITER', 'HIRING_MANAGER', 'INTERVIEWER', 'SUPER_ADMIN'],
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

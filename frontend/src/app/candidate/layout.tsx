'use client'

import { AppShell } from '@/components/app-shell'
import { Skeleton } from '@/components/ui'
import { useRequireAuth } from '@/lib/auth'

export default function CandidateLayout({ children }: { children: React.ReactNode }) {
  const { loading } = useRequireAuth()

  if (loading) {
    return (
      <div className="min-h-full bg-ink-50 p-6">
        <div className="mx-auto max-w-5xl space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  return <AppShell variant="candidate">{children}</AppShell>
}

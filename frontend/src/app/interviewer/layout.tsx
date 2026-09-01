'use client'

import { AppShell } from '@/components/app-shell'
import { Skeleton } from '@/components/ui'
import { useRequireAuth } from '@/lib/auth'

export default function InterviewerLayout({ children }: { children: React.ReactNode }) {
  // Shares the staff shell: its navigation is filtered by permission, so an interviewer
  // sees only interviews and the candidates they are assigned to.
  const { loading } = useRequireAuth({
    roles: ['INTERVIEWER', 'HIRING_MANAGER', 'RECRUITER', 'COMPANY_ADMIN', 'SUPER_ADMIN'],
  })

  if (loading) {
    return (
      <div className="min-h-full bg-ink-50 p-6">
        <div className="mx-auto max-w-7xl space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-80" />
        </div>
      </div>
    )
  }

  return <AppShell variant="recruiter">{children}</AppShell>
}

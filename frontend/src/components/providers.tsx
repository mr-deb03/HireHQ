'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { Toaster } from 'sonner'

import { ApiError } from '@/lib/api'
import { AuthProvider } from '@/lib/auth'

export function Providers({ children }: { children: React.ReactNode }) {
  // Created in state so the client is stable across re-renders but not shared between
  // users during SSR.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Never retry a request the server has definitively rejected - retrying a
              // 403 just burns rate limit and delays the error the user needs to see.
              if (error instanceof ApiError && error.status < 500 && error.status !== 429) {
                return false
              }
              return failureCount < 2
            },
          },
          mutations: { retry: false },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            className: 'rounded-xl border border-ink-200 shadow-popover text-sm',
            duration: 4000,
          }}
        />
      </AuthProvider>
    </QueryClientProvider>
  )
}

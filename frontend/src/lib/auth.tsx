'use client'

import { useRouter } from 'next/navigation'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { ApiError, api, tokens } from './api'
import type { AuthenticatedUser, TokenPair } from './types'

interface AuthContextValue {
  user: AuthenticatedUser | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<AuthenticatedUser>
  signOut: () => Promise<void>
  refresh: () => Promise<void>
  /** Permission check used to gate UI. The server enforces the same rules. */
  can: (...permissions: string[]) => boolean
  hasRole: (...roles: string[]) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

/** Where each role lands after signing in. */
export function homeFor(user: AuthenticatedUser | null): string {
  if (!user) return '/login'
  const roles = new Set(user.roles.map((r) => r.name))
  if (roles.has('SUPER_ADMIN')) return '/admin/dashboard'
  if (roles.has('COMPANY_ADMIN') || roles.has('RECRUITER')) return '/recruiter/dashboard'
  if (roles.has('HIRING_MANAGER')) return '/hiring-manager/dashboard'
  if (roles.has('INTERVIEWER')) return '/interviewer/dashboard'
  return '/candidate/dashboard'
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  const loadUser = useCallback(async () => {
    if (!tokens.access()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      setUser(await api.get<AuthenticatedUser>('/auth/me'))
    } catch (error) {
      // A 401 here means the stored token is dead; anything else is transient and
      // should not silently sign the user out.
      if (error instanceof ApiError && error.status === 401) {
        tokens.clear()
        setUser(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUser()
  }, [loadUser])

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.post<{ tokens: TokenPair; user: AuthenticatedUser }>(
      '/auth/login',
      { email, password },
      { auth: false },
    )
    tokens.set(result.tokens.access_token, result.tokens.refresh_token)
    setUser(result.user)
    return result.user
  }, [])

  const signOut = useCallback(async () => {
    const refreshToken = tokens.refresh()
    try {
      if (refreshToken) await api.post('/auth/logout', { refresh_token: refreshToken })
    } catch {
      // Signing out locally must succeed even if the server call does not.
    }
    tokens.clear()
    setUser(null)
    router.push('/login')
  }, [router])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      refresh: loadUser,
      can: (...permissions) =>
        Boolean(user) && permissions.some((p) => user!.permissions.includes(p)),
      hasRole: (...roles) => {
        if (!user) return false
        const held = new Set(user.roles.map((r) => r.name))
        return roles.some((r) => held.has(r))
      },
    }),
    [user, loading, signIn, signOut, loadUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}

/**
 * Redirects to sign-in when the user is not authenticated, or to their own home when
 * they lack the required permission. Returns loading state so the caller can render a
 * skeleton rather than flashing protected content.
 */
export function useRequireAuth(options: { permission?: string; roles?: string[] } = {}) {
  const { user, loading, can, hasRole } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (loading) return
    if (!user) {
      const next = typeof window !== 'undefined' ? window.location.pathname : '/'
      router.replace(`/login?next=${encodeURIComponent(next)}`)
      return
    }
    if (options.permission && !can(options.permission)) {
      router.replace(homeFor(user))
      return
    }
    if (options.roles?.length && !hasRole(...options.roles)) {
      router.replace(homeFor(user))
    }
  }, [user, loading, router, options.permission, options.roles, can, hasRole])

  return { user, loading: loading || !user }
}

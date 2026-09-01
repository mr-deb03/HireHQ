/**
 * Typed API client for the HireHQ backend.
 *
 * Everything goes through one `request` function so token attachment, the response
 * envelope, error shaping and refresh-on-401 are handled in exactly one place.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

const ACCESS_TOKEN_KEY = 'hirehq.access_token'
const REFRESH_TOKEN_KEY = 'hirehq.refresh_token'

// ------------------------------------------------------------------ envelope
export interface ApiSuccess<T> {
  success: true
  data: T
  message?: string | null
}

export interface ApiErrorBody {
  success: false
  error: { code: string; message: string; details?: Record<string, unknown> }
  request_id?: string
}

export interface PageMeta {
  page: number
  page_size: number
  total_items: number
  total_pages: number
  has_next: boolean
  has_previous: boolean
}

export interface Page<T> {
  items: T[]
  meta: PageMeta
}

/** A failed request, carrying the backend's stable error code. */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly details?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** Field-level validation messages, when the backend supplied them. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details?.fields
    if (!Array.isArray(fields)) return {}
    return Object.fromEntries(
      fields
        .filter((f): f is { field: string; message: string } =>
          Boolean(f && typeof f === 'object' && 'field' in f && 'message' in f),
        )
        .map((f) => [f.field, f.message]),
    )
  }
}

// --------------------------------------------------------------------- tokens
export const tokens = {
  access: () => (typeof window === 'undefined' ? null : localStorage.getItem(ACCESS_TOKEN_KEY)),
  refresh: () => (typeof window === 'undefined' ? null : localStorage.getItem(REFRESH_TOKEN_KEY)),
  set(access: string, refresh: string) {
    if (typeof window === 'undefined') return
    localStorage.setItem(ACCESS_TOKEN_KEY, access)
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  },
  clear() {
    if (typeof window === 'undefined') return
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}

// A single in-flight refresh shared by every concurrent 401, so a page that fires six
// requests at once does not start six refreshes and invalidate its own rotated token.
let refreshInFlight: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokens.refresh()
  if (!refresh) return false

  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      })
      if (!response.ok) {
        tokens.clear()
        return false
      }
      const body = (await response.json()) as ApiSuccess<{
        access_token: string
        refresh_token: string
      }>
      tokens.set(body.data.access_token, body.data.refresh_token)
      return true
    } catch {
      tokens.clear()
      return false
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

// -------------------------------------------------------------------- request
interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  /** Set false for public endpoints so a stale token cannot cause a spurious refresh. */
  auth?: boolean
  query?: Record<string, string | number | boolean | undefined | null | string[]>
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${API_URL}${path}`, 'http://placeholder')
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === '') continue
      if (Array.isArray(value)) {
        // Repeated keys, which is what FastAPI expects for list query parameters.
        value.forEach((v) => url.searchParams.append(key, String(v)))
      } else {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return `${API_URL}${path}${url.search}`
}

async function request<T>(path: string, options: RequestOptions = {}, retry = true): Promise<T> {
  const { body, auth = true, query, headers, ...rest } = options

  const isFormData = body instanceof FormData
  const requestHeaders: Record<string, string> = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...((headers as Record<string, string>) ?? {}),
  }

  if (auth) {
    const token = tokens.access()
    if (token) requestHeaders.Authorization = `Bearer ${token}`
  }

  const response = await fetch(buildUrl(path, query), {
    ...rest,
    headers: requestHeaders,
    body: isFormData ? body : body !== undefined ? JSON.stringify(body) : undefined,
  })

  // Try once to refresh, then replay. Only for authenticated calls that had a token.
  if (response.status === 401 && retry && auth && tokens.refresh()) {
    if (await refreshAccessToken()) {
      return request<T>(path, options, false)
    }
    tokens.clear()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`
    }
  }

  if (response.status === 204) return undefined as T

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ApiError(
      'INVALID_RESPONSE',
      `The server returned a non-JSON response (${response.status})`,
      response.status,
    )
  }

  if (!response.ok) {
    const error = (payload as ApiErrorBody).error
    throw new ApiError(
      error?.code ?? 'UNKNOWN_ERROR',
      error?.message ?? `Request failed with status ${response.status}`,
      response.status,
      error?.details,
    )
  }

  return (payload as ApiSuccess<T>).data
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

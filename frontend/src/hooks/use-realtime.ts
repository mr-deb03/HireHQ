'use client'

/**
 * Live updates over server-sent events.
 *
 * Events are treated as *hints to refetch*, never as data. The server says "an
 * application arrived"; this hook invalidates the relevant queries and TanStack Query
 * fetches the authoritative version through the normal, permission-checked endpoints. A
 * missed event during a reconnect therefore costs a slightly stale number rather than a
 * wrong one, and nothing sensitive has to travel on the stream.
 *
 * The browser's `EventSource` cannot set request headers, which would force the access
 * token into the query string where it would land in access logs, proxy logs and browser
 * history (§47: never log tokens). So the stream is read with `fetch` instead and parsed
 * here — the token stays in an Authorization header, exactly like every other request.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { tokens } from '@/lib/api'

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'

/** Reconnect backoff, capped so a long outage does not spin. */
const RETRY_BASE_MS = 2_000
const RETRY_MAX_MS = 30_000

export interface RealtimeEvent {
  type: string
  label: string
  entity_type: string
  entity_id: string
  at: string
  job_id?: string | null
  candidate_name?: string | null
}

/** Which cached queries each event type makes stale. */
const INVALIDATES: Record<string, string[][]> = {
  APPLICATION_CREATED: [['applications'], ['kanban'], ['dashboard'], ['job-stats']],
  ATS_SCORE_GENERATED: [['applications'], ['kanban'], ['ranking'], ['ats']],
  APPLICATION_STATUS_CHANGED: [['applications'], ['kanban'], ['dashboard'], ['timeline']],
  INTERVIEW_SCHEDULED: [['interviews'], ['calendar'], ['dashboard']],
  FEEDBACK_SUBMITTED: [['interviews'], ['feedback'], ['dashboard']],
  OFFER_ACCEPTED: [['offers'], ['applications'], ['dashboard']],
  OFFER_REJECTED: [['offers'], ['applications'], ['dashboard']],
  EMAIL_RECEIVED: [['email-threads'], ['email-messages']],
}

export type RealtimeStatus = 'connecting' | 'live' | 'offline'

/** Splits an SSE wire chunk into its `event:` / `data:` fields. */
function parseFrame(frame: string): { event: string; data: string } | null {
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue // comment / keep-alive
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  return data.length ? { event, data: data.join('\n') } : null
}

/**
 * Subscribes to the company's event stream while the component is mounted.
 *
 * Returns a connection status so the UI can be honest about it: "Live" only when the
 * stream is genuinely open, never as decoration.
 */
export function useRealtime(
  options: { enabled?: boolean; onEvent?: (event: RealtimeEvent) => void } = {},
) {
  const { enabled = true, onEvent } = options
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<RealtimeStatus>('connecting')
  const [lastEvent, setLastEvent] = useState<RealtimeEvent | null>(null)

  // Held in a ref so a caller passing an inline arrow does not tear down and rebuild the
  // connection on every render.
  const handlerRef = useRef(onEvent)
  handlerRef.current = onEvent

  const dispatch = useCallback(
    (payload: RealtimeEvent) => {
      setLastEvent(payload)
      handlerRef.current?.(payload)
      for (const key of INVALIDATES[payload.type] ?? []) {
        void queryClient.invalidateQueries({ queryKey: key })
      }
    },
    [queryClient],
  )

  useEffect(() => {
    if (!enabled) return

    const controller = new AbortController()
    let attempt = 0
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    async function connect() {
      const token = tokens.access()
      if (!token) {
        setStatus('offline')
        return
      }

      try {
        setStatus((current) => (current === 'live' ? 'connecting' : current))
        const response = await fetch(`${API_URL}/realtime/stream`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
          signal: controller.signal,
        })

        // A 401/403 will not fix itself by retrying; stop rather than hammer the server.
        if (response.status === 401 || response.status === 403) {
          setStatus('offline')
          return
        }
        if (!response.ok || !response.body) throw new Error(`stream ${response.status}`)

        setStatus('live')
        attempt = 0

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (!stopped) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // Frames are separated by a blank line; keep any partial tail for next time.
          let split: number
          while ((split = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, split)
            buffer = buffer.slice(split + 2)
            const parsed = parseFrame(frame)
            if (!parsed || parsed.event !== 'update') continue
            try {
              dispatch(JSON.parse(parsed.data) as RealtimeEvent)
            } catch {
              // A malformed frame is not worth breaking the stream over.
            }
          }
        }
      } catch {
        // Aborted on unmount, or the connection dropped. Either way, fall through to
        // the retry below; the abort check stops it from scheduling one.
      }

      if (stopped || controller.signal.aborted) return
      setStatus('connecting')
      attempt += 1
      timer = setTimeout(connect, Math.min(RETRY_BASE_MS * 2 ** (attempt - 1), RETRY_MAX_MS))
    }

    void connect()

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      controller.abort()
    }
  }, [enabled, dispatch])

  return { status, lastEvent }
}

'use client'

import { useMutation, useQuery } from '@tanstack/react-query'
import { Info, Send, Sparkles, Wrench } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { PageBody, PageHeader } from '@/components/app-shell'
import { Badge, Button, Card, CardBody } from '@/components/ui'
import { ApiError, api } from '@/lib/api'
import type { AiStatus, AssistantAnswer } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  engine?: string
  tools?: { name: string }[]
  data?: Record<string, unknown> | null
}

export default function AssistantPage() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const statusQuery = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/ai/status'),
  })

  const askMutation = useMutation({
    mutationFn: (question: string) =>
      api.post<AssistantAnswer>('/ai/ask', {
        question,
        // Only prior conversational turns are replayed, not tool payloads.
        history: turns.slice(-8).map((t) => ({ role: t.role, content: t.content })),
      }),
    onSuccess: (answer) => {
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: answer.answer,
          engine: answer.engine,
          tools: answer.tool_calls,
          data: answer.data,
        },
      ])
    },
    onError: (error) => {
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          content:
            error instanceof ApiError
              ? `I could not answer that: ${error.message}`
              : 'Something went wrong reaching the assistant.',
        },
      ])
    },
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, askMutation.isPending])

  function send(question: string) {
    const trimmed = question.trim()
    if (!trimmed || askMutation.isPending) return
    setTurns((prev) => [...prev, { role: 'user', content: trimmed }])
    setInput('')
    askMutation.mutate(trimmed)
  }

  const suggestions = [
    'Show me the top candidates for Senior React Developer',
    'Which candidates are waiting for interview feedback?',
    'How many applications did we receive this week?',
    'Show candidates with ATS score above 85',
    'What are the interviews today?',
  ]

  return (
    <>
      <PageHeader
        title="Ask HireHQ"
        description="Questions about your jobs, candidates, pipeline and interviews."
        actions={
          statusQuery.data && (
            <Badge tone={statusQuery.data.is_language_model ? 'brand' : 'neutral'}>
              <Sparkles className="h-3 w-3" />
              {statusQuery.data.is_language_model
                ? (statusQuery.data.model ?? statusQuery.data.provider)
                : 'Built-in engine'}
            </Badge>
          )
        }
      />

      <PageBody className="max-w-3xl">
        {statusQuery.data && !statusQuery.data.is_language_model && (
          <Card className="mb-4 border-info-100 bg-info-50">
            <CardBody className="flex items-start gap-3">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-info-600" />
              <p className="text-sm leading-relaxed text-info-700">
                {statusQuery.data.message}
              </p>
            </CardBody>
          </Card>
        )}

        <Card className="flex h-[calc(100vh-16rem)] flex-col">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
            {turns.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50">
                  <Sparkles className="h-6 w-6 text-brand-600" />
                </span>
                <h3 className="mt-4 text-sm font-semibold text-ink-900">
                  Ask about your hiring data
                </h3>
                <p className="mt-1.5 max-w-md text-sm leading-relaxed text-ink-500">
                  The assistant can only read data you are authorised to see — it has no direct
                  database access, just a fixed set of tools scoped to your permissions.
                </p>
                <div className="mt-6 flex flex-col gap-2">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => send(suggestion)}
                      className="rounded-xl border border-ink-200 px-3.5 py-2 text-left text-sm text-ink-700 transition-colors hover:border-brand-300 hover:bg-brand-50"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((turn, index) => (
                <div
                  key={index}
                  className={cn('flex', turn.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-4 py-3',
                      turn.role === 'user'
                        ? 'bg-ink-900 text-white'
                        : 'bg-ink-100 text-ink-800',
                    )}
                  >
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.content}</p>

                    {turn.role === 'assistant' && (
                      <>
                        {Array.isArray(turn.data?.items) && turn.data.items.length > 0 && (
                          <ul className="mt-3 space-y-1 border-t border-ink-200 pt-3">
                            {(turn.data.items as Record<string, unknown>[])
                              .slice(0, 8)
                              .map((item, i) => (
                                <li key={i} className="text-xs text-ink-700">
                                  •{' '}
                                  {String(
                                    item.label ?? item.name ?? item.title ?? JSON.stringify(item),
                                  )}
                                </li>
                              ))}
                          </ul>
                        )}

                        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-ink-200 pt-2">
                          {turn.engine && (
                            <span className="text-[10px] text-ink-500">via {turn.engine}</span>
                          )}
                          {turn.tools?.map((tool) => (
                            <span
                              key={tool.name}
                              className="inline-flex items-center gap-1 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-ink-600"
                            >
                              <Wrench className="h-2.5 w-2.5" />
                              {tool.name}
                            </span>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}

            {askMutation.isPending && (
              <div className="flex justify-start">
                <div className="rounded-2xl bg-ink-100 px-4 py-3">
                  <div className="flex gap-1">
                    {[0, 150, 300].map((delay) => (
                      <span
                        key={delay}
                        className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-400"
                        style={{ animationDelay: `${delay}ms` }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              send(input)
            }}
            className="flex gap-2 border-t border-ink-200 p-4"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about candidates, jobs or your pipeline"
              aria-label="Your question"
              className="input flex-1"
              disabled={askMutation.isPending}
            />
            <Button type="submit" disabled={!input.trim()} loading={askMutation.isPending}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </Card>

        <p className="mt-3 text-center text-xs text-ink-400">
          Answers come from HireHQ data you are authorised to see. Verify before acting —
          hiring decisions remain yours.
        </p>
      </PageBody>
    </>
  )
}

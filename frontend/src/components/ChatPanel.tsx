'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { AgentOutputCard } from './AgentOutputCard'
import { useWorkspace } from './WorkspaceProvider'
import { IconSend, IconSpark, IconStop } from './icons'
import { Badge, Button, Card, ErrorBanner, cx } from './ui'
import { api } from '@/lib/api'
import { AGENT_LABEL, INTENT_LABEL, dateTime } from '@/lib/format'
import { streamChat } from '@/lib/sse'
import type { AgentOutput, ConversationSummary, StreamEvent } from '@/lib/types'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  outputs: AgentOutput[]
  intent?: string
  agents?: string[]
  planId?: number | null
  traceUrl?: string | null
  createdAt?: string
}

interface LiveState {
  steps: Array<{ node: string; detail: string }>
  outputs: AgentOutput[]
  startedAt: number
}

const PRESETS = [
  '帮我制定从现在到考试的复习计划',
  '复盘一下我现在的复习进度和风险',
  '数学的极限为什么总是算不对',
  '各科目该用什么资料，真题怎么刷',
]

export function ChatPanel() {
  const { userId, refresh, error: workspaceError, setError } = useWorkspace()

  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [live, setLive] = useState<LiveState | null>(null)
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [sending, setSending] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const loadConversations = useCallback(async () => {
    if (userId === null) {
      return
    }
    try {
      setConversations(await api.listConversations(userId, 15))
    } catch {
      // 历史列表失败不影响主流程
    }
  }, [userId])

  useEffect(() => {
    void loadConversations()
  }, [loadConversations])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, live])

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || userId === null || sending) {
      return
    }

    setLocalError(null)
    setError(null)
    setInput('')
    setSending(true)
    setTurns((current) => [...current, { role: 'user', content: message, outputs: [] }])
    setLive({ steps: [], outputs: [], startedAt: Date.now() })

    const controller = new AbortController()
    abortRef.current = controller

    let outputs: AgentOutput[] = []
    let reply = ''
    let intent = ''
    let agents: string[] = []
    let planId: number | null = null
    let traceUrl: string | null = null

    const handle = (event: StreamEvent) => {
      switch (event.type) {
        case 'start':
          setConversationId(event.conversation_id)
          break
        case 'progress':
          setLive((current) =>
            current
              ? { ...current, steps: [...current.steps, { node: event.node, detail: event.detail }] }
              : current,
          )
          break
        case 'output':
          outputs = [...outputs, event.output]
          setLive((current) => (current ? { ...current, outputs } : current))
          break
        case 'done':
          reply = event.reply
          intent = event.intent
          agents = event.agents
          planId = event.plan_id
          traceUrl = event.trace_url
          break
        case 'error':
          setLocalError(event.message)
          break
      }
    }

    try {
      await streamChat(
        { user_id: userId, message, conversation_id: conversationId, enable_review: false },
        handle,
        controller.signal,
      )

      if (reply || outputs.length > 0) {
        setTurns((current) => [
          ...current,
          {
            role: 'assistant',
            content: reply,
            outputs,
            intent,
            agents,
            planId,
            traceUrl,
            createdAt: new Date().toISOString(),
          },
        ])
      }
      if (planId) {
        await refresh()
      }
      void loadConversations()
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError')) {
        setLocalError(cause instanceof Error ? cause.message : '对话失败')
      }
    } finally {
      abortRef.current = null
      setLive(null)
      setSending(false)
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    setSending(false)
  }

  const openConversation = async (id: number) => {
    try {
      const detail = await api.getConversation(id)
      setConversationId(detail.id)
      setTurns(
        detail.messages.flatMap<Turn>((message) => {
          const payload = message.payload as { outputs?: AgentOutput[] }
          const meta = message.meta as {
            intent?: string
            agents?: string[]
            plan_id?: number | null
          }
          return [
            {
              role: message.role === 'user' ? 'user' : 'assistant',
              content: message.content,
              outputs: Array.isArray(payload.outputs) ? payload.outputs : [],
              intent: meta.intent,
              agents: meta.agents,
              planId: meta.plan_id ?? null,
              createdAt: message.created_at,
            },
          ]
        }),
      )
      setLocalError(null)
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : '加载会话失败')
    }
  }

  const startNew = () => {
    setConversationId(null)
    setTurns([])
    setLocalError(null)
  }

  return (
    <div className="grid gap-3.5 lg:grid-cols-[1fr_250px]">
      <Card
        padded={false}
        title="多智能体对话"
        subtitle="调度协调者先判断意图，再分发给规划 / 拆解 / 答疑 / 复盘 / 资料 / 督学智能体协作"
        action={
          <div className="flex items-center gap-2">
            {conversationId && <Badge tone="indigo">会话 #{conversationId}</Badge>}
            <Button variant="ghost" onClick={startNew}>
              新对话
            </Button>
          </div>
        }
      >
        <div className="flex h-[62vh] min-h-[420px] flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
            {(workspaceError || localError) && (
              <ErrorBanner message={localError ?? workspaceError ?? ''} />
            )}

            {turns.length === 0 && !live && (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent">
                  <IconSpark size={19} />
                </span>
                <div>
                  <p className="text-[13px] font-medium text-ink">描述你的备考问题</p>
                  <p className="mt-1 text-xs text-ink-muted">
                    智能体将结合你的档案、计划与知识库给出可执行建议
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => void send(preset)}
                      className="rounded-full border border-line-strong px-3 py-1.5 text-[11px] text-ink-soft transition-colors hover:border-accent hover:bg-accent-soft hover:text-accent"
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((turn, index) =>
              turn.role === 'user' ? (
                <div key={index} className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-[13px] leading-relaxed text-white">
                    {turn.content}
                  </div>
                </div>
              ) : (
                <div key={index} className="space-y-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {turn.intent && (
                      <Badge tone="indigo">{INTENT_LABEL[turn.intent] ?? turn.intent}</Badge>
                    )}
                    {(turn.agents ?? []).map((agent) => (
                      <Badge key={agent} tone="sky">
                        {AGENT_LABEL[agent] ?? agent}
                      </Badge>
                    ))}
                    {turn.createdAt && (
                      <span className="ml-auto text-[11px] text-ink-muted">
                        {dateTime(turn.createdAt)}
                      </span>
                    )}
                  </div>

                  {turn.outputs.map((output, position) => (
                    <AgentOutputCard key={position} output={output} />
                  ))}

                  {!turn.outputs.length && turn.content && (
                    <div className="surface whitespace-pre-wrap px-3.5 py-3 text-[13px] leading-relaxed text-ink-soft">
                      {turn.content}
                    </div>
                  )}

                  {turn.planId && (
                    <div className="flex items-center gap-2 text-[11px] text-emerald-700">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                      学习计划已入库（计划 #{turn.planId}），已同步到「学习计划」页
                    </div>
                  )}
                  {turn.traceUrl && (
                    <a
                      href={turn.traceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[11px] text-ink-muted underline underline-offset-2 hover:text-ink-soft"
                    >
                      在 LangFuse 查看本次协作链路
                    </a>
                  )}
                </div>
              ),
            )}

            {live && <LiveIndicator live={live} />}
            <div ref={bottomRef} />
          </div>

          <div className="border-t border-line px-3.5 py-3">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    void send(input)
                  }
                }}
                rows={2}
                placeholder="例如：我的数学拖后腿，帮我调整接下来一个月的安排"
                className="control max-h-36 flex-1 resize-none"
              />
              {sending ? (
                <Button variant="danger" onClick={stop} className="py-2">
                  <IconStop size={14} />
                  停止
                </Button>
              ) : (
                <Button
                  onClick={() => void send(input)}
                  disabled={!input.trim()}
                  className="py-2"
                >
                  <IconSend size={14} />
                  发送
                </Button>
              )}
            </div>
            <p className="mt-2 text-[11px] text-ink-muted">
              Enter 发送 · Shift + Enter 换行 · 支持 SSE 流式输出
            </p>
          </div>
        </div>
      </Card>

      <Card title="对话历史" subtitle={`最近 ${conversations.length} 条`} className="h-fit">
        {conversations.length === 0 ? (
          <p className="text-xs text-ink-muted">暂无历史会话</p>
        ) : (
          <ul className="space-y-1">
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <button
                  type="button"
                  onClick={() => void openConversation(conversation.id)}
                  className={cx(
                    'w-full rounded-lg px-2.5 py-2 text-left transition-colors',
                    conversation.id === conversationId
                      ? 'bg-accent-soft'
                      : 'hover:bg-slate-100',
                  )}
                >
                  <p
                    className={cx(
                      'truncate text-xs font-medium',
                      conversation.id === conversationId ? 'text-accent' : 'text-ink',
                    )}
                  >
                    {conversation.title || `会话 #${conversation.id}`}
                  </p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-muted">
                    <span>{conversation.message_count} 条消息</span>
                    <span>·</span>
                    <span>{dateTime(conversation.created_at)}</span>
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

function LiveIndicator({ live }: { live: LiveState }) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-blue-200 bg-accent-soft px-3.5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />
          <span className="text-xs font-medium text-accent">智能体协作中…</span>
          <span className="ml-auto text-[11px] text-ink-muted">
            {live.steps.length} 个步骤 · {live.outputs.length} 个产出
          </span>
        </div>
        <ul className="mt-2 space-y-1">
          {live.steps.map((step, index) => (
            <li key={index} className="flex items-center gap-2 text-[11px] text-ink-soft">
              <span className="font-mono text-ink-muted">{step.node}</span>
              <span className="truncate">{step.detail}</span>
            </li>
          ))}
          {live.steps.length === 0 && (
            <li className="text-[11px] text-ink-muted">正在准备上下文…</li>
          )}
        </ul>
      </div>

      {live.outputs.map((output, index) => (
        <AgentOutputCard key={index} output={output} />
      ))}
    </div>
  )
}

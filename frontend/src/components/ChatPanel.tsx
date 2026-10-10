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
          const meta = message.meta as { intent?: string; agents?: string[]; plan_id?: number | null }
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
    <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
      <Card
        padded={false}
        title="多智能体对话"
        subtitle="调度协调者会先判断意图，再分发给规划 / 拆解 / 答疑 / 复盘 / 资料 / 督学智能体协作"
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
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {(workspaceError || localError) && (
              <ErrorBanner message={localError ?? workspaceError ?? ''} />
            )}

            {turns.length === 0 && !live && (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-indigo-500/12 text-indigo-300">
                  <IconSpark size={20} />
                </span>
                <div>
                  <p className="text-sm font-medium text-slate-200">描述你的备考问题</p>
                  <p className="mt-1 text-xs text-slate-500">
                    智能体将结合你的档案、计划与知识库给出可执行建议
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  {PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => void send(preset)}
                      className="rounded-full border border-white/10 px-3 py-1.5 text-[11px] text-slate-300 hover:border-indigo-400/40 hover:bg-indigo-500/8 hover:text-indigo-200"
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
                  <div className="max-w-[80%] rounded-2xl rounded-br-md bg-indigo-500/15 px-4 py-2.5 text-[13px] leading-relaxed text-indigo-100 ring-1 ring-inset ring-indigo-400/20">
                    {turn.content}
                  </div>
                </div>
              ) : (
                <div key={index} className="space-y-2.5">
                  <div className="flex items-center gap-2">
                    {turn.intent && (
                      <Badge tone="indigo">{INTENT_LABEL[turn.intent] ?? turn.intent}</Badge>
                    )}
                    {(turn.agents ?? []).map((agent) => (
                      <Badge key={agent} tone="sky">
                        {AGENT_LABEL[agent] ?? agent}
                      </Badge>
                    ))}
                    {turn.createdAt && (
                      <span className="ml-auto text-[11px] text-slate-600">
                        {dateTime(turn.createdAt)}
                      </span>
                    )}
                  </div>

                  {turn.outputs.map((output, position) => (
                    <AgentOutputCard key={position} output={output} />
                  ))}

                  {!turn.outputs.length && turn.content && (
                    <div className="whitespace-pre-wrap rounded-2xl border border-white/8 bg-white/[0.02] px-4 py-3 text-[13px] leading-relaxed text-slate-300">
                      {turn.content}
                    </div>
                  )}

                  {turn.planId && (
                    <div className="flex items-center gap-2 text-[11px] text-emerald-300">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      学习计划已入库（计划 #{turn.planId}），已同步到「学习计划」页
                    </div>
                  )}
                  {turn.traceUrl && (
                    <a
                      href={turn.traceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[11px] text-slate-500 underline underline-offset-2 hover:text-slate-300"
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

          <div className="border-t border-white/6 px-4 py-3">
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
                className="max-h-36 flex-1 resize-none rounded-xl border border-white/10 bg-slate-950/50 px-3.5 py-2.5 text-[13px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/15"
              />
              {sending ? (
                <Button variant="danger" onClick={stop} className="h-10">
                  <IconStop size={15} />
                  停止
                </Button>
              ) : (
                <Button onClick={() => void send(input)} disabled={!input.trim()} className="h-10">
                  <IconSend size={15} />
                  发送
                </Button>
              )}
            </div>
            <p className="mt-2 text-[11px] text-slate-600">
              Enter 发送 · Shift + Enter 换行 · 支持 SSE 流式输出
            </p>
          </div>
        </div>
      </Card>

      <Card title="对话历史" subtitle={`最近 ${conversations.length} 条`} className="h-fit">
        {conversations.length === 0 ? (
          <p className="text-xs text-slate-500">暂无历史会话</p>
        ) : (
          <ul className="space-y-1.5">
            {conversations.map((conversation) => (
              <li key={conversation.id}>
                <button
                  type="button"
                  onClick={() => void openConversation(conversation.id)}
                  className={cx(
                    'w-full rounded-xl px-3 py-2 text-left transition-colors',
                    conversation.id === conversationId
                      ? 'bg-indigo-500/12 ring-1 ring-inset ring-indigo-400/20'
                      : 'hover:bg-white/5',
                  )}
                >
                  <p className="truncate text-xs font-medium text-slate-200">
                    {conversation.title || `会话 #${conversation.id}`}
                  </p>
                  <p className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
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
      <div className="rounded-2xl border border-indigo-400/20 bg-indigo-500/6 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse-soft rounded-full bg-indigo-400" />
          <span className="text-xs font-medium text-indigo-200">智能体协作中…</span>
          <span className="ml-auto text-[11px] text-slate-500">
            {live.steps.length} 个步骤 · {live.outputs.length} 个产出
          </span>
        </div>
        <ul className="mt-2.5 space-y-1">
          {live.steps.map((step, index) => (
            <li key={index} className="flex items-center gap-2 text-[11px] text-slate-400">
              <span className="font-mono text-slate-600">{step.node}</span>
              <span className="truncate">{step.detail}</span>
            </li>
          ))}
          {live.steps.length === 0 && (
            <li className="text-[11px] text-slate-500">正在准备上下文…</li>
          )}
        </ul>
      </div>

      {live.outputs.map((output, index) => (
        <AgentOutputCard key={index} output={output} />
      ))}
    </div>
  )
}

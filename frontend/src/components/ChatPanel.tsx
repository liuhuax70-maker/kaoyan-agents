'use client'

import { useEffect, useRef, useState } from 'react'

import { AgentAnswer } from './AgentAnswer'
import { useWorkspace } from './WorkspaceProvider'
import { IconArrowUp, IconBulb, IconCopy, IconGlobe, IconStop } from './icons'
import { Badge, IconButton, Spinner, TogglePill, cx } from './ui'
import { INTENT_LABEL, TOOL_LABEL } from '@/lib/format'
import { streamChat } from '@/lib/sse'
import type { AgentOutput, ChatTurn, StreamEvent, ToolCallRecord } from '@/lib/types'

const PRESETS = [
  '帮我制定从现在到考试的复习计划',
  '把没做完的任务往后挪三天',
  '复盘一下我现在的复习进度和风险',
  '数学的极限为什么总是算不对',
]

const SUMMARY_AGENT = 'chat_agent'

interface LiveState {
  steps: Array<{ node: string; detail: string }>
  tools: ToolCallRecord[]
  outputs: AgentOutput[]
}

export function ChatPanel() {
  const {
    userId,
    turns,
    appendTurn,
    bindConversation,
    activeConversationId,
    reloadConversations,
    refresh,
    error: workspaceError,
    setError,
  } = useWorkspace()

  const [input, setInput] = useState('')
  const [live, setLive] = useState<LiveState | null>(null)
  const [sending, setSending] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [enableReview, setEnableReview] = useState(false)
  const [enableRetrieval, setEnableRetrieval] = useState(true)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, live])

  const resizeTextarea = () => {
    const element = textareaRef.current
    if (!element) {
      return
    }
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  }

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || userId === null || sending) {
      return
    }

    setLocalError(null)
    setError(null)
    setInput('')
    setSending(true)
    appendTurn({ role: 'user', content: message, outputs: [] })
    setLive({ steps: [], tools: [], outputs: [] })
    requestAnimationFrame(resizeTextarea)

    const controller = new AbortController()
    abortRef.current = controller

    let outputs: AgentOutput[] = []
    let toolCalls: ToolCallRecord[] = []
    let reply = ''
    let intent = ''
    let agents: string[] = []
    let planId: number | null = null
    let traceUrl: string | null = null

    const handle = (event: StreamEvent) => {
      switch (event.type) {
        case 'start':
          bindConversation(event.conversation_id)
          break
        case 'progress':
          setLive((current) => {
            if (!current) {
              return current
            }
            const steps = [...current.steps, { node: event.node, detail: event.detail }]
            // 工具调用事件以工具名作为 node，据此实时拼出调用链
            const tools = TOOL_LABEL[event.node]
              ? [...current.tools, { name: event.node, agent: event.agent ?? '', label: '' }]
              : current.tools
            return { ...current, steps, tools }
          })
          break
        case 'output':
          outputs = [...outputs, event.output]
          setLive((current) => (current ? { ...current, outputs } : current))
          break
        case 'done':
          reply = event.reply
          intent = event.intent
          agents = event.agents
          toolCalls = event.tool_calls ?? []
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
        {
          user_id: userId,
          message,
          // 续接当前会话；仅在尚未绑定会话时（首次发送）才由后端新建
          conversation_id: activeConversationId,
          enable_review: enableReview,
          enable_retrieval: enableRetrieval,
        },
        handle,
        controller.signal,
      )

      if (reply || outputs.length > 0) {
        appendTurn({
          role: 'assistant',
          content: reply,
          outputs,
          toolCalls,
          intent,
          agents,
          planId,
          traceUrl,
          createdAt: new Date().toISOString(),
        })
      }
      if (planId) {
        await refresh()
      }
      await reloadConversations()
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

  const copyTurn = async (turn: ChatTurn, index: number) => {
    const text = [
      turn.content,
      ...turn.outputs.map(
        (output) => `${output.title}\n${output.summary}\n${output.highlights.join('\n')}`,
      ),
    ]
      .filter(Boolean)
      .join('\n\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopiedIndex(index)
      window.setTimeout(() => setCopiedIndex(null), 1500)
    } catch {
      setLocalError('复制失败，请手动选择文本')
    }
  }

  const empty = turns.length === 0 && !live

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[720px] px-5 py-6">
          {(workspaceError || localError) && (
            <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-xs text-rose-700">
              {localError ?? workspaceError}
            </div>
          )}

          {empty ? (
            <div className="flex min-h-[52vh] flex-col items-center justify-center gap-7 text-center">
              <div>
                <h1 className="text-[26px] font-semibold tracking-tight text-ink">
                  嗨，我是你的备考督导台
                </h1>
                <p className="mx-auto mt-2.5 max-w-lg text-[13.5px] leading-relaxed text-ink-muted">
                  我是你唯一的对话入口。需要规划、拆解、答疑、复盘、资料或督促时，
                  我会调用对应的专业子智能体，再把结果整理成一份完整答复给你。
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => void send(preset)}
                    className="rounded-full border border-line-strong bg-surface px-3.5 py-2 text-[12.5px] text-ink-soft transition-colors hover:bg-slate-50 hover:text-ink"
                  >
                    {preset}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-7">
              {turns.map((turn, index) =>
                turn.role === 'user' ? (
                  <div key={index} className="flex justify-end">
                    <div className="max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-surface-muted px-4 py-2.5 text-[14px] leading-[1.7] text-ink">
                      {turn.content}
                    </div>
                  </div>
                ) : (
                  <AssistantTurn
                    key={index}
                    turn={turn}
                    copied={copiedIndex === index}
                    onCopy={() => void copyTurn(turn, index)}
                  />
                ),
              )}

              {live && <LiveTurn live={live} />}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 px-5 pb-5">
        <div className="mx-auto w-full max-w-[720px]">
          <div className="rounded-composer border border-line bg-surface px-3.5 py-3 shadow-[0_2px_14px_rgba(16,24,40,0.07)]">
            <textarea
              ref={textareaRef}
              value={input}
              rows={1}
              onChange={(event) => {
                setInput(event.target.value)
                resizeTextarea()
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void send(input)
                }
              }}
              placeholder="给备考督导台发送消息"
              className="control-bare max-h-40"
            />

            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="flex flex-wrap gap-2">
                <TogglePill
                  active={enableReview}
                  onClick={() => setEnableReview((value) => !value)}
                  icon={<IconBulb size={14} />}
                  label="深度思考"
                  title="触发 CrewAI 多角色计划评审"
                />
                <TogglePill
                  active={enableRetrieval}
                  onClick={() => setEnableRetrieval((value) => !value)}
                  icon={<IconGlobe size={14} />}
                  label="联网搜索"
                  title="启用知识库检索增强"
                />
              </div>

              {sending ? (
                <IconButton
                  type="button"
                  onClick={stop}
                  title="停止生成"
                  className="bg-slate-700 text-white hover:bg-slate-800"
                >
                  <IconStop size={14} />
                </IconButton>
              ) : (
                <IconButton
                  type="button"
                  onClick={() => void send(input)}
                  disabled={!input.trim()}
                  title="发送"
                  className={cx(
                    input.trim()
                      ? 'bg-accent text-white hover:bg-accent-hover'
                      : 'bg-slate-200 text-white',
                  )}
                >
                  <IconArrowUp size={16} />
                </IconButton>
              )}
            </div>
          </div>

          <p className="mt-2.5 text-center text-[11px] text-ink-muted">
            答由聊天 Agent 汇总子智能体结果生成，请结合自身情况甄别
          </p>
        </div>
      </div>
    </div>
  )
}

/** 助手回答：先给统一总结，再按需展开子智能体的详细产出。 */
function AssistantTurn({
  turn,
  copied,
  onCopy,
}: {
  turn: ChatTurn
  copied: boolean
  onCopy: () => void
}) {
  const details = turn.outputs.filter((output) => output.agent !== SUMMARY_AGENT)

  return (
    <div className="flex gap-3.5">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        {turn.content && (
          <div className="answer-body whitespace-pre-wrap text-[14px] leading-[1.75] text-ink">
            {turn.content}
          </div>
        )}

        <ToolChain calls={turn.toolCalls ?? []} />

        {details.length > 0 && (
          <details className="group surface">
            <summary className="cursor-pointer list-none px-3.5 py-2.5 text-[12.5px] text-ink-soft hover:text-ink">
              查看 {details.length} 个子智能体的详细产出
              <span className="ml-1 text-ink-muted group-open:hidden">展开</span>
            </summary>
            <div className="space-y-4 border-t border-line px-3.5 py-3.5">
              {details.map((output, index) => (
                <AgentAnswer key={index} output={output} />
              ))}
            </div>
          </details>
        )}

        {turn.planId && (
          <div className="flex items-center gap-2 text-[12px] text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            学习计划已更新（计划 #{turn.planId}），已同步到「学习计划」页
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={onCopy}
            title="复制"
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11.5px] text-ink-muted transition-colors hover:bg-slate-100 hover:text-ink"
          >
            <IconCopy size={13} />
            {copied ? '已复制' : '复制'}
          </button>

          {turn.intent && <Badge tone="indigo">{INTENT_LABEL[turn.intent] ?? turn.intent}</Badge>}

          {turn.traceUrl && (
            <a
              href={turn.traceUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[11.5px] text-ink-muted underline underline-offset-2 hover:text-ink-soft"
            >
              LangFuse 链路
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

/** 调用链：展示聊天 Agent 本次调起了哪些子智能体。 */
function ToolChain({ calls }: { calls: ToolCallRecord[] }) {
  if (calls.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11.5px] text-ink-muted">调用</span>
      {calls.map((call, index) => (
        <span
          key={`${call.name}-${index}`}
          className="inline-flex items-center gap-1 rounded-md bg-surface-muted px-2 py-0.5 text-[11.5px]"
        >
          <span className="font-medium text-ink">{TOOL_LABEL[call.name] ?? call.name}</span>
          {call.label && <span className="text-ink-muted">· {call.label}</span>}
        </span>
      ))}
    </div>
  )
}

function LiveTurn({ live }: { live: LiveState }) {
  const lastStep = live.steps[live.steps.length - 1]
  const details = live.outputs.filter((output) => output.agent !== SUMMARY_AGENT)
  const summary = live.outputs.find((output) => output.agent === SUMMARY_AGENT)

  return (
    <div className="flex gap-3.5">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2 text-[13px] text-ink-muted">
          <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />
          <span className="text-ink-soft">
            {live.tools.length > 0 ? '子智能体执行中…' : '正在理解你的诉求…'}
          </span>
          {lastStep && <span className="truncate">· {lastStep.detail}</span>}
        </div>

        <ToolChain calls={live.tools} />

        {details.map((output, index) => (
          <AgentAnswer key={index} output={output} />
        ))}

        {summary && <AgentAnswer output={summary} />}

        {live.outputs.length === 0 && live.steps.length === 0 && (
          <Spinner label="正在准备上下文" />
        )}
      </div>
    </div>
  )
}

function AssistantAvatar() {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-[12px] font-semibold text-white">
      考
    </span>
  )
}

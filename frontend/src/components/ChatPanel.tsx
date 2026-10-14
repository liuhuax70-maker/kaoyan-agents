'use client'

import { useEffect, useRef, useState } from 'react'

import { AgentAnswer } from './AgentAnswer'
import { ConfirmationCard } from './ConfirmationCard'
import { Markdown } from './Markdown'
import { useWorkspace } from './WorkspaceProvider'
import { IconArrowUp, IconBulb, IconCopy, IconGlobe, IconStop } from './icons'
import { IconButton, Spinner, TogglePill, cx } from './ui'
import { TOOL_LABEL } from '@/lib/format'
import { api } from '@/lib/api'
import { streamChat } from '@/lib/sse'
import type { AgentOutput, ChatTurn, StreamEvent, ToolCallRecord } from '@/lib/types'

const PRESETS = [
  '帮我制定从现在到考试的复习计划',
  '把没做完的任务往后挪三天',
  '复盘一下我现在的复习进度和风险',
  '数学的极限为什么总是算不对',
]

interface LiveState {
  steps: Array<{ node: string; detail: string }>
  tools: ToolCallRecord[]
  outputs: AgentOutput[]
  /** 聊天 Agent 的最终回答，由 `token` 事件逐段追加而来 */
  reply: string
}

export function ChatPanel() {
  const {
    userId,
    turns,
    appendTurn,
    patchTurn,
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
  const [resolving, setResolving] = useState(false)
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
    setLive({ steps: [], tools: [], outputs: [], reply: '' })
    requestAnimationFrame(resizeTextarea)

    const controller = new AbortController()
    abortRef.current = controller

    let outputs: AgentOutput[] = []
    let toolCalls: ToolCallRecord[] = []
    let reply = ''
    let agents: string[] = []
    let planId: number | null = null
    let traceUrl: string | null = null
    // 收尾走两条路：跑完发 done，停在确认闸门上发 awaiting_confirmation
    let pending: ChatTurn | null = null

    // 知识点：自定义流在客户端的形态 —— token 增量不是一次响应，而是一串增量帧，
//   因此这里累积拼接而不是覆盖；拼起来的正文应恰好等于收尾帧里的 reply
//   （第5章 LangGraph·流式）
    const handle = (event: StreamEvent) => {
      switch (event.type) {
        case 'start':
          bindConversation(event.conversation_id)
          break
        case 'progress':
          setLive((current) =>
            current
              ? { ...current, steps: [...current.steps, { node: event.node, detail: event.detail }] }
              : current,
          )
          break
        case 'tool_call':
          setLive((current) =>
            current
              ? {
                  ...current,
                  tools: [
                    ...current.tools,
                    { name: event.name, agent: event.agent, label: event.label },
                  ],
                }
              : current,
          )
          break
        case 'output':
          outputs = [...outputs, event.output]
          setLive((current) => (current ? { ...current, outputs } : current))
          break
        case 'token':
          // 逐段追加：既写进实时气泡，也留到最后作为这一轮的正文
          reply += event.text
          setLive((current) => (current ? { ...current, reply } : current))
          break
        case 'done':
          reply = event.reply || reply
          agents = event.agents
          toolCalls = event.tool_calls ?? []
          planId = event.plan_id
          traceUrl = event.trace_url
          break
        case 'awaiting_confirmation':
          // 这一轮没有完成，也没有写库：把待确认内容挂成一轮助手消息，
          // 让 ConfirmationCard 就地渲染，答复后它的结果另起一轮
          reply = event.reply || reply
          agents = event.agents
          toolCalls = event.tool_calls ?? []
          traceUrl = event.trace_url
          pending = {
            role: 'assistant',
            content: reply,
            outputs,
            toolCalls,
            agents,
            confirmation: event.confirmation,
            traceUrl,
            createdAt: new Date().toISOString(),
          }
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

      if (pending) {
        appendTurn(pending)
      } else if (reply || outputs.length > 0) {
        appendTurn({
          role: 'assistant',
          content: reply,
          outputs,
          toolCalls,
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

  // 知识点：interrupt 的恢复 —— 第二次请求带回的是「答复」而不是新输入，
//   后端以 Command(resume=…) 让图从暂停点原地继续，不重跑已完成的节点
//   （第5章 LangGraph·人工确认）
  /**
   * 答复一次待确认的计划。
   *
   * 第一次答复才真正触发落库；答复后立刻把该轮上的卡片摘掉，
   * 免得同一个确认被点第二次（后端也有会话状态兜底，重复提交会返回 404）。
   */
  const resolveConfirmation = async (
    index: number,
    approve: boolean,
    feedback: string,
  ) => {
    if (activeConversationId === null || resolving) {
      return
    }
    setResolving(true)
    setLocalError(null)
    try {
      const result = await api.confirmPlan(activeConversationId, approve, feedback)
      patchTurn(index, { confirmation: null })
      appendTurn({
        role: 'assistant',
        content: result.reply,
        outputs: result.outputs,
        toolCalls: result.tool_calls,
        agents: result.agents,
        planId: result.plan_id,
        traceUrl: result.trace_url,
        createdAt: new Date().toISOString(),
      })
      if (result.plan_id) {
        await refresh()
      }
      await reloadConversations()
    } catch (cause) {
      setLocalError(cause instanceof Error ? cause.message : '确认失败')
    } finally {
      setResolving(false)
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
                    resolving={resolving}
                    onResolve={(approve, feedback) =>
                      void resolveConfirmation(index, approve, feedback)
                    }
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
                  title="计划产出后触发一轮独立评审"
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

/** 助手回答：正文在前，待确认的计划、调用链与子智能体产出依次跟在下面。 */
function AssistantTurn({
  turn,
  copied,
  onCopy,
  resolving,
  onResolve,
}: {
  turn: ChatTurn
  copied: boolean
  onCopy: () => void
  resolving: boolean
  onResolve: (approve: boolean, feedback: string) => void
}) {
  return (
    <div className="flex gap-3.5">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        {turn.content && <Markdown>{turn.content}</Markdown>}

        {turn.confirmation && (
          <ConfirmationCard
            confirmation={turn.confirmation}
            busy={resolving}
            onResolve={onResolve}
          />
        )}

        <ToolChain calls={turn.toolCalls ?? []} />

        {turn.outputs.length > 0 && (
          <details className="group surface">
            <summary className="cursor-pointer list-none px-3.5 py-2.5 text-[12.5px] text-ink-soft hover:text-ink">
              查看 {turn.outputs.length} 个子智能体的详细产出
              <span className="ml-1 text-ink-muted group-open:hidden">展开</span>
            </summary>
            <div className="space-y-4 border-t border-line px-3.5 py-3.5">
              {turn.outputs.map((output, index) => (
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
          <span className="font-medium text-ink">
            {call.label || TOOL_LABEL[call.name] || call.name}
          </span>
        </span>
      ))}
    </div>
  )
}

function LiveTurn({ live }: { live: LiveState }) {
  const lastStep = live.steps[live.steps.length - 1]
  const streaming = live.reply.length > 0

  return (
    <div className="flex gap-3.5">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 space-y-3">
        {streaming ? (
          // 正文开始逐 token 到达后就不再展示执行进度，避免与正文争夺注意力
          <Markdown className="streaming-caret">{live.reply}</Markdown>
        ) : (
          <div className="flex items-center gap-2 text-[13px] text-ink-muted">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />
            <span className="text-ink-soft">
              {live.tools.length > 0 ? '子智能体执行中…' : '正在理解你的诉求…'}
            </span>
            {lastStep && <span className="truncate">· {lastStep.detail}</span>}
          </div>
        )}

        <ToolChain calls={live.tools} />

        {live.outputs.map((output, index) => (
          <AgentAnswer key={index} output={output} />
        ))}

        {live.outputs.length === 0 && live.steps.length === 0 && !streaming && (
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

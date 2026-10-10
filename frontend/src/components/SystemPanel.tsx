'use client'

import { useCallback, useEffect, useState } from 'react'

import { IconRefresh, IconSpark, IconSystem } from './icons'
import { Badge, Button, Card, EmptyState, ErrorBanner, Input, Spinner } from './ui'
import { api } from '@/lib/api'
import { INTENT_LABEL } from '@/lib/format'
import type { KnowledgeHit, KnowledgeStats, OverviewRead } from '@/lib/types'

export function SystemPanel() {
  const [overview, setOverview] = useState<OverviewRead | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [ingesting, setIngesting] = useState(false)
  const [query, setQuery] = useState('英语真题怎么刷')
  const [searching, setSearching] = useState(false)
  const [hits, setHits] = useState<KnowledgeHit[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [data, stats] = await Promise.all([api.overview(), api.knowledgeStats()])
      setOverview(data)
      setKnowledge(stats)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载系统信息失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const ingest = async () => {
    setIngesting(true)
    setError(null)
    try {
      setKnowledge(await api.ingestKnowledge(true))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '写入知识库失败')
    } finally {
      setIngesting(false)
    }
  }

  const search = async () => {
    if (!query.trim()) {
      return
    }
    setSearching(true)
    setError(null)
    try {
      setHits(await api.searchKnowledge(query.trim(), 5))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '检索失败')
    } finally {
      setSearching(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <Spinner label="正在读取系统配置…" />
      </Card>
    )
  }

  if (!overview) {
    return (
      <Card>
        <EmptyState
          title="无法读取系统配置"
          description="请确认后端服务已启动。"
          action={<Button onClick={() => void load()}>重试</Button>}
        />
        {error && (
          <div className="mt-3.5">
            <ErrorBanner message={error} />
          </div>
        )}
      </Card>
    )
  }

  const { capability } = overview

  return (
    <div className="flex flex-col gap-3.5">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card
        title="运行能力"
        subtitle="未配置密钥时全部走离线兜底，因此本地可完整跑通全流程"
        action={
          <Button variant="outline" onClick={() => void load()}>
            <IconRefresh size={14} />
            刷新
          </Button>
        }
      >
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <Capability
            label="大模型"
            value={capability.llm_provider}
            ok={capability.llm_ready}
            hint={capability.llm_ready ? '配置完整' : '未配置密钥，使用离线桩'}
          />
          <Capability
            label="向量化"
            value={capability.embedding}
            ok={capability.embedding !== 'stub'}
            hint={capability.embedding === 'stub' ? '离线哈希向量' : '真实语义向量'}
          />
          <Capability
            label="向量库"
            value={capability.vector_backend}
            ok={capability.vector_backend === 'milvus'}
            hint={capability.vector_backend === 'milvus' ? 'Milvus 服务端' : '本地 JSON 兜底'}
          />
          <Capability
            label="协作与督促"
            value={`CrewAI ${capability.crew_enabled ? '开' : '关'} · 提醒 ${
              capability.reminders_enabled ? '开' : '关'
            }`}
            ok={capability.crew_enabled && capability.reminders_enabled}
            hint={`知识库检索 ${capability.knowledge_enabled ? '已启用' : '已停用'}`}
          />
        </div>
      </Card>

      <div className="grid gap-3.5 lg:grid-cols-[1.2fr_1fr]">
        <Card title="智能体角色" subtitle={`共 ${overview.roles.length} 个角色`}>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {overview.roles.map((role) => (
              <div key={role.key} className="surface-muted px-3.5 py-3">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-soft text-accent">
                    <IconSystem size={14} />
                  </span>
                  <span className="text-[13px] font-medium text-ink">{role.name}</span>
                  <span className="ml-auto font-mono text-[10px] text-ink-muted">{role.key}</span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-ink-soft">{role.mission}</p>
                {role.capabilities.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {role.capabilities.map((item) => (
                      <Badge key={item} tone="neutral">
                        {item}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card title="工作流拓扑" subtitle="LangGraph 状态机 · Send 动态扇出">
          <ol className="space-y-1.5">
            {overview.workflow.edges.map((edge, index) => (
              <li
                key={index}
                className="surface-muted flex items-center gap-2 px-3 py-2 text-[12px]"
              >
                <span className="font-mono text-ink-soft">{edge.from}</span>
                <span className="text-ink-muted">→</span>
                <span className="font-mono text-ink-soft">{edge.to}</span>
                <span className="ml-auto text-[10px] text-ink-muted">{edge.kind}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-[11px] text-ink-muted">
            入口节点：<span className="font-mono text-ink-soft">{overview.workflow.entry}</span>
          </p>
        </Card>
      </div>

      <div className="grid gap-3.5 lg:grid-cols-2">
        <Card title="提示词任务" subtitle="每个任务与结构化输出 Schema 一一绑定">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="text-[11px] text-ink-muted">
                  <th className="border-b border-line pb-2 pr-3 font-medium">任务</th>
                  <th className="border-b border-line pb-2 pr-3 font-medium">角色</th>
                  <th className="border-b border-line pb-2 font-medium">必需变量</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {overview.prompts.map((prompt) => (
                  <tr key={prompt.task}>
                    <td className="py-2 pr-3 font-mono text-[11px] text-ink-soft">{prompt.task}</td>
                    <td className="py-2 pr-3 text-ink-soft">{prompt.role_name}</td>
                    <td className="py-2 text-[11px] text-ink-muted">
                      {prompt.required_variables.join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="定时督促计划" subtitle="Celery Beat 调度">
          <ul className="space-y-1.5">
            {overview.schedule.map((job) => (
              <li key={job.name} className="surface-muted flex items-center gap-3 px-3.5 py-2.5">
                <span className="font-mono text-[11px] text-ink-soft">{job.task}</span>
                <span className="ml-auto font-mono text-[11px] text-ink">{job.schedule}</span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.entries(INTENT_LABEL).map(([key, label]) => (
              <Badge key={key} tone="sky">
                {label}
              </Badge>
            ))}
          </div>
        </Card>
      </div>

      <Card
        title="知识库检索"
        subtitle={
          knowledge
            ? `${knowledge.backend} · ${knowledge.embedding} · ${knowledge.dimension} 维 · ${knowledge.chunks} 个片段`
            : '未就绪'
        }
        action={
          <Button onClick={ingest} loading={ingesting}>
            <IconSpark size={14} />
            写入内置语料
          </Button>
        }
      >
        <div className="flex flex-wrap gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                void search()
              }
            }}
            placeholder="输入检索问题，例如：数学怎么提高计算准确率"
            className="max-w-md flex-1"
          />
          <Button variant="outline" onClick={() => void search()} loading={searching}>
            检索
          </Button>
        </div>

        {hits.length > 0 && (
          <ul className="mt-3 space-y-2">
            {hits.map((hit) => (
              <li key={hit.id} className="surface-muted px-3.5 py-3">
                <div className="flex items-center gap-2">
                  <Badge tone="emerald">{hit.subject || '通用'}</Badge>
                  <span className="text-[11px] text-ink-soft">{hit.source}</span>
                  <span className="ml-auto text-[11px] tabular-nums text-ink-muted">
                    相似度 {hit.score.toFixed(3)}
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-ink-soft">{hit.text}</p>
              </li>
            ))}
          </ul>
        )}
        {hits.length === 0 && (
          <p className="mt-3 text-[11px] text-ink-muted">
            尚无检索结果。首次使用可先点击「写入内置语料」。
          </p>
        )}
      </Card>
    </div>
  )
}

function Capability({
  label,
  value,
  ok,
  hint,
}: {
  label: string
  value: string
  ok: boolean
  hint: string
}) {
  return (
    <div className="surface-muted px-3.5 py-3">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-500' : 'bg-amber-500'}`} />
        <p className="text-[11px] text-ink-muted">{label}</p>
      </div>
      <p className="mt-1.5 truncate font-mono text-[12px] text-ink">{value}</p>
      <p className="mt-1 text-[11px] text-ink-muted">{hint}</p>
    </div>
  )
}

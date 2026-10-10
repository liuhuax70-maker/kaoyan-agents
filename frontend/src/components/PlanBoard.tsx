'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { IconCheck, IconPlan, IconRefresh, IconSpark } from './icons'
import { Badge, Button, Card, EmptyState, ErrorBanner, ProgressBar, Spinner, cx } from './ui'
import { api } from '@/lib/api'
import {
  PRIORITY_LABEL,
  TASK_STATUS_LABEL,
  TASK_TYPE_LABEL,
  percent,
  priorityTone,
  shortDate,
  statusTone,
} from '@/lib/format'
import type { PlanRead, TaskRead, TaskStatus } from '@/lib/types'

type Filter = 'all' | TaskStatus

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '待开始' },
  { key: 'doing', label: '进行中' },
  { key: 'done', label: '已完成' },
  { key: 'skipped', label: '已跳过' },
]

export function PlanBoard() {
  const { userId, refresh } = useWorkspace()

  const [plan, setPlan] = useState<PlanRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (userId === null) {
      return
    }
    setLoading(true)
    try {
      const plans = await api.listPlans(userId, 1)
      setPlan(plans[0] ?? null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载计划失败')
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  const stats = useMemo(() => {
    const tasks = plan?.stages.flatMap((stage) => stage.tasks) ?? []
    const done = tasks.filter((task) => task.status === 'done').length
    return {
      total: tasks.length,
      done,
      rate: tasks.length ? done / tasks.length : 0,
    }
  }, [plan])

  const generate = async () => {
    if (userId === null) {
      return
    }
    setGenerating(true)
    setError(null)
    try {
      const result = await api.generatePlan(userId, '', false)
      if (!result.plan_id) {
        setError('未能生成可入库的计划，请先设置备考目标与科目')
      }
      await load()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成计划失败')
    } finally {
      setGenerating(false)
    }
  }

  const checkIn = async (task: TaskRead, status: TaskStatus) => {
    setBusyTaskId(task.id)
    setError(null)
    try {
      await api.updateTask(task.id, {
        status,
        actual_minutes: status === 'done' ? task.duration_minutes : 0,
      })
      await load()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '打卡失败')
    } finally {
      setBusyTaskId(null)
    }
  }

  if (loading) {
    return (
      <Card>
        <Spinner label="正在加载学习计划…" />
      </Card>
    )
  }

  if (!plan) {
    return (
      <Card>
        <EmptyState
          title="还没有学习计划"
          description="点击下方按钮，规划智能体会依据你的档案与目标划分阶段、拆解任务并排期。"
          action={
            <Button onClick={generate} loading={generating}>
              <IconSpark size={15} />
              生成学习计划
            </Button>
          }
        />
        {error && <div className="mt-4">{<ErrorBanner message={error} />}</div>}
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card
        title={plan.title}
        subtitle={plan.goal}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void load()}>
              <IconRefresh size={15} />
              刷新
            </Button>
            <Button onClick={generate} loading={generating}>
              <IconSpark size={15} />
              重新生成
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          {plan.strategy && (
            <p className="text-[13px] leading-relaxed text-slate-400">{plan.strategy}</p>
          )}

          <div className="grid gap-3 sm:grid-cols-4">
            <Meta label="计划周期" value={`${plan.horizon_days} 天`} />
            <Meta label="起止日期" value={`${shortDate(plan.start_date)} - ${shortDate(plan.end_date)}`} />
            <Meta label="阶段 / 任务" value={`${plan.stages.length} / ${stats.total}`} />
            <Meta label="生成来源" value={plan.generated_by || '—'} />
          </div>

          <div>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>
                已完成 {stats.done} / {stats.total}
              </span>
              <span className="tabular-nums text-slate-300">{percent(stats.rate)}</span>
            </div>
            <ProgressBar value={stats.rate} tone="emerald" className="mt-2" />
          </div>
        </div>
      </Card>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setFilter(item.key)}
            className={cx(
              'rounded-full px-3 py-1.5 text-[11px] font-medium transition-colors',
              filter === item.key
                ? 'bg-indigo-500/15 text-indigo-200 ring-1 ring-inset ring-indigo-400/25'
                : 'text-slate-400 hover:bg-white/5 hover:text-slate-200',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {plan.stages.map((stage) => {
        const tasks = stage.tasks.filter((task) => filter === 'all' || task.status === filter)
        if (tasks.length === 0) {
          return null
        }
        return (
          <Card
            key={stage.id}
            title={stage.name}
            subtitle={stage.focus}
            action={
              <div className="flex items-center gap-3">
                <Badge tone="indigo">第 {stage.order_index + 1} 阶段</Badge>
                <span className="text-[11px] text-slate-500">
                  {shortDate(stage.start_date)} - {shortDate(stage.end_date)} · {stage.target_hours}h
                </span>
              </div>
            }
          >
            <div className="mb-3 flex items-center gap-3">
              <ProgressBar value={stage.completion_rate} className="flex-1" />
              <span className="text-[11px] tabular-nums text-slate-400">
                {percent(stage.completion_rate)}
              </span>
            </div>

            <ul className="space-y-2">
              {tasks.map((task) => (
                <li
                  key={task.id}
                  className="flex flex-wrap items-start gap-3 rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cx(
                          'rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
                          statusTone(task.status),
                        )}
                      >
                        {TASK_STATUS_LABEL[task.status]}
                      </span>
                      <span
                        className={cx(
                          'rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset',
                          priorityTone(task.priority),
                        )}
                      >
                        {PRIORITY_LABEL[task.priority]}优先
                      </span>
                      <Badge tone="neutral">{TASK_TYPE_LABEL[task.task_type]}</Badge>
                      <span className="text-[11px] text-slate-500">
                        {shortDate(task.planned_date)} · {task.duration_minutes} 分钟
                      </span>
                    </div>

                    <p className="mt-2 text-[13px] font-medium text-slate-200">{task.title}</p>
                    {task.description && (
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                        {task.description}
                      </p>
                    )}
                    {task.resource_hint && (
                      <p className="mt-1 text-[11px] text-slate-600">
                        资料建议：{task.resource_hint}
                      </p>
                    )}
                  </div>

                  <div className="flex shrink-0 items-center gap-2">
                    {task.status !== 'doing' && task.status !== 'done' && (
                      <Button
                        variant="outline"
                        loading={busyTaskId === task.id}
                        onClick={() => void checkIn(task, 'doing')}
                      >
                        开始
                      </Button>
                    )}
                    {task.status !== 'done' && (
                      <Button
                        loading={busyTaskId === task.id}
                        onClick={() => void checkIn(task, 'done')}
                      >
                        <IconCheck size={15} />
                        完成
                      </Button>
                    )}
                    {task.status === 'done' && (
                      <span className="flex items-center gap-1.5 text-[11px] text-emerald-300">
                        <IconCheck size={14} />
                        已打卡
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )
      })}

      {plan.stages.every((stage) => stage.tasks.filter((task) => filter === 'all' || task.status === filter).length === 0) && (
        <Card>
          <EmptyState
            title="当前筛选下没有任务"
            description="切换筛选条件查看其它状态的任务。"
            action={
              <Button variant="outline" onClick={() => setFilter('all')}>
                <IconPlan size={15} />
                查看全部任务
              </Button>
            }
          />
        </Card>
      )}
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-2.5">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 truncate text-[13px] font-medium text-slate-200">{value}</p>
    </div>
  )
}

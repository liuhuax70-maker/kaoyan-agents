'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { IconCheck, IconPlan, IconPlus, IconRefresh, IconSpark } from './icons'
import { Badge, Button, Card, EmptyState, ErrorBanner, Input, ProgressBar, Select, Spinner, Textarea, cx } from './ui'
import { api } from '@/lib/api'
import {
  PRIORITY_LABEL,
  TASK_STATUS_LABEL,
  TASK_TYPE_LABEL,
  percent,
  priorityTone,
  shortDate,
  statusTone,
  todayISO,
} from '@/lib/format'
import type { PlanRead, Priority, TaskRead, TaskStatus } from '@/lib/types'

type Filter = 'all' | TaskStatus

const FILTERS: Array<{ key: Filter; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '待开始' },
  { key: 'doing', label: '进行中' },
  { key: 'done', label: '已完成' },
  { key: 'skipped', label: '已跳过' },
]

const PRIORITIES: Priority[] = ['high', 'medium', 'low']

interface TaskForm {
  title: string
  description: string
  planned_date: string
  duration_minutes: number
  priority: Priority
}

interface PlanForm {
  title: string
  goal: string
  strategy: string
}

const EMPTY_TASK: TaskForm = {
  title: '',
  description: '',
  planned_date: todayISO(),
  duration_minutes: 60,
  priority: 'medium',
}

export function PlanBoard() {
  const { userId, refresh } = useWorkspace()

  const [plan, setPlan] = useState<PlanRead | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [error, setError] = useState<string | null>(null)

  const [editingTaskId, setEditingTaskId] = useState<number | null>(null)
  const [taskForm, setTaskForm] = useState<TaskForm>(EMPTY_TASK)
  const [addingStageId, setAddingStageId] = useState<number | null>(null)
  const [newTask, setNewTask] = useState<TaskForm>(EMPTY_TASK)
  const [editingPlan, setEditingPlan] = useState(false)
  const [planForm, setPlanForm] = useState<PlanForm>({ title: '', goal: '', strategy: '' })

  const load = useCallback(async () => {
    if (userId === null) {
      return
    }
    setLoading(true)
    try {
      const plans = await api.listPlans(userId, 1)
      const latest = plans[0] ?? null
      setPlan(latest)
      if (latest) {
        setPlanForm({ title: latest.title, goal: latest.goal, strategy: latest.strategy })
      }
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
    return { total: tasks.length, done, rate: tasks.length ? done / tasks.length : 0 }
  }, [plan])

  const run = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusy(key)
    setError(null)
    try {
      await action()
      await load()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : message)
    } finally {
      setBusy(null)
    }
  }

  const generate = async () => {
    if (userId === null) {
      return
    }
    setGenerating(true)
    setError(null)
    try {
      const result = await api.generatePlan(userId, '', false)
      if (!result.plan_id) {
        throw new Error('未能生成可入库的计划，请先设置备考目标与科目')
      }
      await load()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成计划失败')
    } finally {
      setGenerating(false)
    }
  }

  const checkIn = (task: TaskRead, status: TaskStatus) =>
    run(
      `task-${task.id}`,
      () =>
        api.updateTask(task.id, {
          status,
          actual_minutes: status === 'done' ? task.duration_minutes : 0,
        }),
      '打卡失败',
    )

  const startEdit = (task: TaskRead) => {
    setEditingTaskId(task.id)
    setTaskForm({
      title: task.title,
      description: task.description,
      planned_date: task.planned_date,
      duration_minutes: task.duration_minutes,
      priority: task.priority,
    })
  }

  const saveTask = (task: TaskRead) =>
    run(
      `task-${task.id}`,
      async () => {
        if (taskForm.title.trim().length < 2) {
          throw new Error('任务标题至少 2 个字符')
        }
        await api.updateTask(task.id, {
          title: taskForm.title.trim(),
          description: taskForm.description.trim(),
          planned_date: taskForm.planned_date,
          duration_minutes: taskForm.duration_minutes,
          priority: taskForm.priority,
        })
        setEditingTaskId(null)
      },
      '保存任务失败',
    )

  const removeTask = (task: TaskRead) =>
    run(`task-${task.id}`, () => api.deleteTask(task.id), '删除任务失败')

  const submitNewTask = (stageId: number, stageName: string) =>
    run(
      `add-${stageId}`,
      async () => {
        if (newTask.title.trim().length < 2) {
          throw new Error('任务标题至少 2 个字符')
        }
        await api.createTask(plan!.id, {
          title: newTask.title.trim(),
          description: newTask.description.trim(),
          stage_name: stageName,
          planned_date: newTask.planned_date,
          duration_minutes: newTask.duration_minutes,
          priority: newTask.priority,
        })
        setAddingStageId(null)
        setNewTask(EMPTY_TASK)
      },
      '新增任务失败',
    )

  const savePlan = () =>
    run(
      'plan',
      async () => {
        await api.updatePlan(plan!.id, {
          title: planForm.title.trim(),
          goal: planForm.goal.trim(),
          strategy: planForm.strategy.trim(),
        })
        setEditingPlan(false)
      },
      '保存计划信息失败',
    )

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
          description="可以点击下方按钮让规划智能体生成，也可以先在对话里描述你的目标。"
          action={
            <Button onClick={() => void generate()} loading={generating}>
              <IconSpark size={14} />
              生成学习计划
            </Button>
          }
        />
        {error && (
          <div className="mt-3.5">
            <ErrorBanner message={error} />
          </div>
        )}
      </Card>
    )
  }

  const visibleStages = plan.stages.filter((stage) =>
    stage.tasks.some((task) => filter === 'all' || task.status === filter),
  )

  return (
    <div className="flex flex-col gap-3.5">
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      <Card
        title={
          editingPlan ? (
            <Input
              value={planForm.title}
              onChange={(event) => setPlanForm((c) => ({ ...c, title: event.target.value }))}
              className="max-w-md"
            />
          ) : (
            plan.title
          )
        }
        subtitle={editingPlan ? '修改计划信息后保存' : plan.goal}
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => void load()}>
              <IconRefresh size={14} />
              刷新
            </Button>
            {editingPlan ? (
              <>
                <Button variant="ghost" onClick={() => setEditingPlan(false)}>
                  取消
                </Button>
                <Button loading={busy === 'plan'} onClick={() => void savePlan()}>
                  保存
                </Button>
              </>
            ) : (
              <>
                <Button variant="outline" onClick={() => setEditingPlan(true)}>
                  编辑计划
                </Button>
                <Button onClick={() => void generate()} loading={generating}>
                  <IconSpark size={14} />
                  重新生成
                </Button>
              </>
            )}
          </div>
        }
      >
        <div className="space-y-3">
          {editingPlan ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5 sm:col-span-2">
                <span className="text-xs font-medium text-ink-soft">计划目标</span>
                <Input
                  value={planForm.goal}
                  onChange={(event) => setPlanForm((c) => ({ ...c, goal: event.target.value }))}
                />
              </label>
              <label className="flex flex-col gap-1.5 sm:col-span-2">
                <span className="text-xs font-medium text-ink-soft">备考策略</span>
                <Textarea
                  rows={2}
                  value={planForm.strategy}
                  onChange={(event) =>
                    setPlanForm((c) => ({ ...c, strategy: event.target.value }))
                  }
                />
              </label>
            </div>
          ) : (
            plan.strategy && <p className="text-[13px] leading-relaxed text-ink-soft">{plan.strategy}</p>
          )}

          <div className="grid gap-2.5 sm:grid-cols-4">
            <Meta label="计划周期" value={`${plan.horizon_days} 天`} />
            <Meta
              label="起止日期"
              value={`${shortDate(plan.start_date)} - ${shortDate(plan.end_date)}`}
            />
            <Meta label="阶段 / 任务" value={`${plan.stages.length} / ${stats.total}`} />
            <Meta label="生成来源" value={plan.generated_by || '—'} />
          </div>

          <div>
            <div className="flex items-center justify-between text-xs text-ink-soft">
              <span>
                已完成 {stats.done} / {stats.total}
              </span>
              <span className="tabular-nums">{percent(stats.rate)}</span>
            </div>
            <ProgressBar value={stats.rate} tone="emerald" className="mt-2" />
          </div>
        </div>
      </Card>

      <div className="flex flex-wrap gap-1">
        {FILTERS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setFilter(item.key)}
            className={cx(
              'rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors',
              filter === item.key
                ? 'bg-accent-soft text-accent'
                : 'text-ink-soft hover:bg-slate-100 hover:text-ink',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {visibleStages.map((stage) => {
        const tasks = stage.tasks.filter((task) => filter === 'all' || task.status === filter)
        return (
          <Card
            key={stage.id}
            title={stage.name}
            subtitle={stage.focus}
            action={
              <div className="flex items-center gap-3">
                <Badge tone="indigo">第 {stage.order_index + 1} 阶段</Badge>
                <span className="hidden text-[11px] text-ink-muted sm:inline">
                  {shortDate(stage.start_date)} - {shortDate(stage.end_date)} · {stage.target_hours}h
                </span>
              </div>
            }
          >
            <div className="mb-3 flex items-center gap-3">
              <ProgressBar value={stage.completion_rate} className="flex-1" />
              <span className="text-[11px] tabular-nums text-ink-muted">
                {percent(stage.completion_rate)}
              </span>
            </div>

            <ul className="space-y-2">
              {tasks.map((task) => (
                <li key={task.id} className="surface-muted px-3.5 py-3">
                  {editingTaskId === task.id ? (
                    <div className="space-y-2.5">
                      <Input
                        value={taskForm.title}
                        onChange={(event) =>
                          setTaskForm((c) => ({ ...c, title: event.target.value }))
                        }
                        placeholder="任务标题"
                      />
                      <Textarea
                        rows={2}
                        value={taskForm.description}
                        onChange={(event) =>
                          setTaskForm((c) => ({ ...c, description: event.target.value }))
                        }
                        placeholder="任务说明与验收标准"
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          type="date"
                          value={taskForm.planned_date}
                          onChange={(event) =>
                            setTaskForm((c) => ({ ...c, planned_date: event.target.value }))
                          }
                          className="max-w-40"
                        />
                        <Input
                          type="number"
                          min={5}
                          max={480}
                          step={5}
                          value={taskForm.duration_minutes}
                          onChange={(event) =>
                            setTaskForm((c) => ({
                              ...c,
                              duration_minutes: Number(event.target.value),
                            }))
                          }
                          className="max-w-28"
                        />
                        <Select
                          value={taskForm.priority}
                          onChange={(event) =>
                            setTaskForm((c) => ({ ...c, priority: event.target.value as Priority }))
                          }
                          className="max-w-24"
                        >
                          {PRIORITIES.map((item) => (
                            <option key={item} value={item}>
                              {PRIORITY_LABEL[item]}优先
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button loading={busy === `task-${task.id}`} onClick={() => void saveTask(task)}>
                          保存
                        </Button>
                        <Button variant="ghost" onClick={() => setEditingTaskId(null)}>
                          取消
                        </Button>
                        <button
                          type="button"
                          onClick={() => void removeTask(task)}
                          className="ml-auto text-[11.5px] text-ink-muted hover:text-rose-600"
                        >
                          删除任务
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-wrap items-start gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span
                            className={cx(
                              'rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset',
                              statusTone(task.status),
                            )}
                          >
                            {TASK_STATUS_LABEL[task.status]}
                          </span>
                          <span
                            className={cx(
                              'rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset',
                              priorityTone(task.priority),
                            )}
                          >
                            {PRIORITY_LABEL[task.priority]}优先
                          </span>
                          <Badge tone="neutral">{TASK_TYPE_LABEL[task.task_type]}</Badge>
                          <span className="text-[11px] text-ink-muted">
                            {shortDate(task.planned_date)} · {task.duration_minutes} 分钟
                          </span>
                        </div>

                        <p className="mt-1.5 text-[13px] font-medium text-ink">{task.title}</p>
                        {task.description && (
                          <p className="mt-1 text-[11px] leading-relaxed text-ink-soft">
                            {task.description}
                          </p>
                        )}
                        {task.resource_hint && (
                          <p className="mt-1 text-[11px] text-ink-muted">
                            资料建议：{task.resource_hint}
                          </p>
                        )}
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {task.status !== 'doing' && task.status !== 'done' && (
                          <Button
                            variant="outline"
                            loading={busy === `task-${task.id}`}
                            onClick={() => void checkIn(task, 'doing')}
                          >
                            开始
                          </Button>
                        )}
                        {task.status !== 'done' ? (
                          <Button
                            loading={busy === `task-${task.id}`}
                            onClick={() => void checkIn(task, 'done')}
                          >
                            <IconCheck size={14} />
                            完成
                          </Button>
                        ) : (
                          <span className="flex items-center gap-1.5 text-[11px] text-emerald-700">
                            <IconCheck size={13} />
                            已打卡
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => startEdit(task)}
                          className="rounded-lg px-2 py-1 text-[11.5px] text-ink-muted transition-colors hover:bg-slate-100 hover:text-ink"
                        >
                          编辑
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>

            {addingStageId === stage.id ? (
              <div className="mt-2.5 rounded-xl border border-dashed border-line-strong px-3.5 py-3">
                <div className="space-y-2.5">
                  <Input
                    value={newTask.title}
                    onChange={(event) => setNewTask((c) => ({ ...c, title: event.target.value }))}
                    placeholder="新任务标题，例如：数学第三章习题 20 道"
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      type="date"
                      value={newTask.planned_date}
                      onChange={(event) =>
                        setNewTask((c) => ({ ...c, planned_date: event.target.value }))
                      }
                      className="max-w-40"
                    />
                    <Input
                      type="number"
                      min={5}
                      max={480}
                      step={5}
                      value={newTask.duration_minutes}
                      onChange={(event) =>
                        setNewTask((c) => ({ ...c, duration_minutes: Number(event.target.value) }))
                      }
                      className="max-w-28"
                    />
                    <Select
                      value={newTask.priority}
                      onChange={(event) =>
                        setNewTask((c) => ({ ...c, priority: event.target.value as Priority }))
                      }
                      className="max-w-24"
                    >
                      {PRIORITIES.map((item) => (
                        <option key={item} value={item}>
                          {PRIORITY_LABEL[item]}优先
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      loading={busy === `add-${stage.id}`}
                      onClick={() => void submitNewTask(stage.id, stage.name)}
                    >
                      添加
                    </Button>
                    <Button variant="ghost" onClick={() => setAddingStageId(null)}>
                      取消
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setAddingStageId(stage.id)
                  setNewTask(EMPTY_TASK)
                }}
                className="mt-2.5 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] text-ink-soft transition-colors hover:bg-slate-100 hover:text-ink"
              >
                <IconPlus size={13} />
                在本阶段添加任务
              </button>
            )}
          </Card>
        )
      })}

      {visibleStages.length === 0 && (
        <Card>
          <EmptyState
            title="当前筛选下没有任务"
            description="切换筛选条件查看其它状态的任务。"
            action={
              <Button variant="outline" onClick={() => setFilter('all')}>
                <IconPlan size={14} />
                查看全部任务
              </Button>
            }
          />
        </Card>
      )}

      <p className="text-center text-[11px] text-ink-muted">
        计划表既可以在本页直接编辑，也可以在对话里让我调用计划修订师调整（例如「把没做完的任务往后挪三天」）
      </p>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface-muted px-3.5 py-2.5">
      <p className="text-[11px] text-ink-muted">{label}</p>
      <p className="mt-0.5 truncate text-[13px] font-medium text-ink">{value}</p>
    </div>
  )
}

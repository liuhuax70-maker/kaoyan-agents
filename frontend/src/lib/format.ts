import type { Priority, TaskStatus, TaskType } from './types'

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function shortDate(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return `${parsed.getMonth() + 1}月${parsed.getDate()}日`
}

export function dateTime(value: string | null | undefined): string {
  if (!value) {
    return '—'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(
    parsed.getHours(),
  )}:${pad(parsed.getMinutes())}`
}

export function todayISO(): string {
  const now = new Date()
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function addDaysISO(days: number): string {
  const target = new Date()
  target.setDate(target.getDate() + days)
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}`
}

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  todo: '待开始',
  doing: '进行中',
  done: '已完成',
  skipped: '已跳过',
}

export const TASK_TYPE_LABEL: Record<TaskType, string> = {
  learn: '学习',
  practice: '练习',
  review: '复盘',
  mock: '模考',
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

export const INTENT_LABEL: Record<string, string> = {
  plan: '制定计划',
  breakdown: '任务拆解',
  tutor: '答疑讲解',
  review: '复盘诊断',
  resource: '资料推荐',
  nudge: '督促提醒',
  chat: '综合咨询',
}

export const AGENT_LABEL: Record<string, string> = {
  coordinator: '调度协调者',
  planner: '备考规划师',
  breakdown: '任务拆解师',
  tutor: '答疑讲师',
  reviewer: '复盘诊断师',
  resource: '资料规划师',
  coach: '督学教练',
}

export const REMINDER_TYPE_LABEL: Record<string, string> = {
  daily: '每日提醒',
  overdue: '逾期催办',
  idle: '断签预警',
  weekly: '周报复盘',
  custom: '自定义',
}

export function statusTone(status: TaskStatus): string {
  switch (status) {
    case 'done':
      return 'bg-emerald-500/12 text-emerald-300 ring-emerald-500/25'
    case 'doing':
      return 'bg-sky-500/12 text-sky-300 ring-sky-500/25'
    case 'skipped':
      return 'bg-slate-500/12 text-slate-400 ring-slate-500/25'
    default:
      return 'bg-slate-500/12 text-slate-300 ring-slate-500/25'
  }
}

export function priorityTone(priority: Priority): string {
  switch (priority) {
    case 'high':
      return 'bg-rose-500/12 text-rose-300 ring-rose-500/25'
    case 'medium':
      return 'bg-amber-500/12 text-amber-300 ring-amber-500/25'
    default:
      return 'bg-slate-500/12 text-slate-300 ring-slate-500/25'
  }
}

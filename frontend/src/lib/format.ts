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

export const AGENT_LABEL: Record<string, string> = {
  chat_agent: '备考督导助手',
  coordinator: '调度协调者',
  planner: '备考规划师',
  breakdown: '任务拆解师',
  tutor: '答疑讲师',
  reviewer: '复盘诊断师',
  resource: '资料规划师',
  coach: '督学教练',
  plan_editor: '计划修订师',
  school_advisor: '择校参谋',
}

export const TOOL_LABEL: Record<string, string> = {
  generate_plan: '制定学习计划',
  breakdown_tasks: '拆解任务',
  explain_concept: '讲解知识点',
  review_progress: '复盘进度',
  recommend_resources: '推荐资料',
  send_nudge: '督促提醒',
  revise_plan: '修改计划表',
  advise_schools: '择校参谋',
}

export const REMINDER_TYPE_LABEL: Record<string, string> = {
  daily: '每日提醒',
  overdue: '逾期催办',
  idle: '断签预警',
  weekly: '周报复盘',
  school_brief: '院校简报',
  custom: '自定义',
}

/**
 * 按时间远近把条目分组，用于侧边栏的「今天 / 7 天内 / 30 天内 / 更早」。
 * 空分组会被剔除。
 */
export function groupByRecency<T>(
  items: T[],
  getDate: (item: T) => string,
): Array<{ label: string; items: T[] }> {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const day = 86_400_000

  const buckets = [
    { label: '今天', min: startOfToday, max: Number.POSITIVE_INFINITY },
    { label: '7 天内', min: startOfToday - 6 * day, max: startOfToday },
    { label: '30 天内', min: startOfToday - 29 * day, max: startOfToday - 6 * day },
    { label: '更早', min: Number.NEGATIVE_INFINITY, max: startOfToday - 29 * day },
  ]

  return buckets
    .map((bucket) => ({
      label: bucket.label,
      items: items.filter((item) => {
        const parsed = new Date(getDate(item)).getTime()
        if (Number.isNaN(parsed)) {
          return false
        }
        return parsed >= bucket.min && parsed < bucket.max
      }),
    }))
    .filter((bucket) => bucket.items.length > 0)
}

export function statusTone(status: TaskStatus): string {
  switch (status) {
    case 'done':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    case 'doing':
      return 'bg-blue-50 text-blue-700 ring-blue-200'
    case 'skipped':
      return 'bg-slate-100 text-slate-500 ring-slate-200'
    default:
      return 'bg-slate-100 text-slate-600 ring-slate-200'
  }
}

export function priorityTone(priority: Priority): string {
  switch (priority) {
    case 'high':
      return 'bg-rose-50 text-rose-700 ring-rose-200'
    case 'medium':
      return 'bg-amber-50 text-amber-700 ring-amber-200'
    default:
      return 'bg-slate-100 text-slate-600 ring-slate-200'
  }
}

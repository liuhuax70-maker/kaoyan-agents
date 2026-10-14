/**
 * 课表的纯逻辑：周网格与今日目标。
 *
 * 这里是时段与周次的**唯一**定义处 —— 网格、今日目标、表单下拉都从这一份导出取词。
 * 三处各写一份字符串是课表最常见的漂移来源：多一个字，就有一行永远匹配不上任务，
 * 而界面上只会表现为「这一格莫名是空的」。
 *
 * 逻辑刻意与视图分开：验收标准里「最右侧小格子列出今日要达成的目标」是一条
 * 可计算的口径，放在纯函数里才能被测试，也才能保证「当时算的」与「界面上看到的」
 * 不可能不一致。
 */
import type { TaskRead } from './types'

export const SLOTS = ['上午', '下午', '晚上'] as const

export const UNSCHEDULED = '未定时段'

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export interface GridDay {
  iso: string
  label: string
}

export interface GridRow {
  slot: string
  cells: TaskRead[][]
}

export interface TimetableGrid {
  days: GridDay[]
  rows: GridRow[]
}

export interface TodayGoal {
  subject: string
  minutes: number
}

/** 把 ISO 日期解析成「本地当天」，避免 `new Date('2026-10-15')` 被当成 UTC 午夜而错一天。 */
function parseDay(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function formatDay(value: Date): string {
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}

/** 返回所在周的周一。`getDay()` 里周日是 0，先折成 7 才能算出「距周一几天」。 */
export function weekStart(iso: string): string {
  const date = parseDay(iso)
  const offset = (date.getDay() + 6) % 7
  date.setDate(date.getDate() - offset)
  return formatDay(date)
}

export function addDays(iso: string, days: number): string {
  const date = parseDay(iso)
  date.setDate(date.getDate() + days)
  return formatDay(date)
}

/**
 * 把任务铺进「周一~周日 × 上午/下午/晚上」的网格。
 *
 * 没有时段（或时段不在词表内）的任务单独成行，而不是塞进某一格：课表的价值就在于
 * 位置说明安排，硬塞会让用户以为那是他计划好的时段。
 */
export function buildGrid(tasks: TaskRead[], weekStartIso: string): TimetableGrid {
  const days: GridDay[] = Array.from({ length: 7 }, (_, index) => ({
    iso: addDays(weekStartIso, index),
    label: WEEKDAY_LABELS[index],
  }))
  const columnOf = new Map(days.map((day, position) => [day.iso, position]))

  const rows: GridRow[] = SLOTS.map((slot) => ({
    slot,
    cells: days.map(() => [] as TaskRead[]),
  }))
  const unscheduled: TaskRead[][] = days.map(() => [])

  for (const task of tasks) {
    const column = columnOf.get(task.planned_date)
    if (column === undefined) {
      continue
    }
    const row = task.slot ? rows.find((item) => item.slot === task.slot) : undefined
    if (row) {
      row.cells[column].push(task)
    } else {
      unscheduled[column].push(task)
    }
  }

  if (unscheduled.some((cell) => cell.length > 0)) {
    rows.push({ slot: UNSCHEDULED, cells: unscheduled })
  }

  return { days, rows }
}

/**
 * 今日要达成的目标：按科目汇总今天还没做完的任务时长。
 *
 * 口径在这里钉死（验收标准 3 的「最右侧小格子」）：只看今天、只算未完成
 * （已完成与已跳过都不算）、科目为空归到「其他」、按分钟数从多到少排。
 */
export function todayGoals(tasks: TaskRead[], todayIso: string): TodayGoal[] {
  const totals = new Map<string, number>()

  for (const task of tasks) {
    if (task.planned_date !== todayIso || task.status === 'done' || task.status === 'skipped') {
      continue
    }
    const key = task.subject.trim() || '其他'
    totals.set(key, (totals.get(key) ?? 0) + task.duration_minutes)
  }

  return [...totals.entries()]
    .map(([subject, minutes]) => ({ subject, minutes }))
    .sort((left, right) => right.minutes - left.minutes)
}

/** 把分钟折成「2h」「45m」「1h 30m」，今日目标格用。 */
export function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) {
    return `${rest}m`
  }
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}

'use client'

import { useMemo, useState } from 'react'

import { Button, Card, cx } from './ui'
import { statusTone } from '@/lib/format'
import { addDays, buildGrid, formatMinutes, todayGoals, weekStart } from '@/lib/timetable'
import type { TaskRead } from '@/lib/types'

/**
 * 周课表：周一~周日 × 上午/下午/晚上，最右一列是今天要达成的目标。
 *
 * 所有取值与聚合都来自 `@/lib/timetable`，组件本身不拼时段字符串 —— 见该模块的说明。
 */
export function Timetable({
  tasks,
  todayIso,
  weekStartIso,
}: {
  tasks: TaskRead[]
  todayIso: string
  weekStartIso: string
}) {
  const [weekOffset, setWeekOffset] = useState(0)

  const anchor = useMemo(
    () => weekStart(addDays(weekStartIso, weekOffset * 7)),
    [weekStartIso, weekOffset],
  )
  const grid = useMemo(() => buildGrid(tasks, anchor), [tasks, anchor])
  const goals = useMemo(() => todayGoals(tasks, todayIso), [tasks, todayIso])
  const scheduled = grid.rows.reduce((total, row) => total + row.cells.flat().length, 0)

  return (
    <Card
      title="周课表"
      subtitle="按周查看安排；最右一列是今天要达成的目标"
      action={
        <div className="flex items-center gap-1.5">
          <Button variant="outline" onClick={() => setWeekOffset((value) => value - 1)}>
            上一周
          </Button>
          <Button
            variant="outline"
            disabled={weekOffset === 0}
            onClick={() => setWeekOffset(0)}
          >
            本周
          </Button>
          <Button variant="outline" onClick={() => setWeekOffset((value) => value + 1)}>
            下一周
          </Button>
        </div>
      }
      padded={false}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2 text-[11px] text-ink-muted">
        <span className="tabular-nums">
          {anchor} ~ {addDays(anchor, 6)}
        </span>
        <span>本周共 {scheduled} 个任务</span>
      </div>

      <div className="overflow-x-auto px-4 py-3.5">
        <table className="w-full min-w-[760px] border-separate border-spacing-1">
          <thead>
            <tr>
              <th className="w-14" />
              {grid.days.map((day) => (
                <th
                  key={day.iso}
                  className={cx(
                    'rounded-md px-1 py-1.5 text-[11px] font-medium',
                    day.iso === todayIso ? 'bg-accent-soft text-accent' : 'text-ink-soft',
                  )}
                >
                  {day.label}
                  <span className="mt-0.5 block text-[10px] font-normal tabular-nums opacity-70">
                    {day.iso.slice(5)}
                  </span>
                </th>
              ))}
              <th className="w-32 rounded-md bg-slate-100 px-1 py-1.5 text-[11px] font-medium text-slate-600">
                今日目标
              </th>
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row, rowIndex) => (
              <tr key={row.slot}>
                <th
                  className={cx(
                    'rounded-md px-1 py-2 text-[11px] font-medium align-top',
                    row.slot === '未定时段' ? 'text-ink-muted' : 'text-ink-soft',
                  )}
                >
                  {row.slot}
                </th>
                {row.cells.map((cell, column) => (
                  <td
                    key={grid.days[column].iso}
                    className="rounded-md bg-slate-50/70 p-1 align-top"
                  >
                    <div className="flex min-h-11 flex-col gap-1">
                      {cell.map((task) => (
                        <TaskChip key={task.id} task={task} />
                      ))}
                    </div>
                  </td>
                ))}
                {rowIndex === 0 && (
                  <td
                    rowSpan={grid.rows.length}
                    className="rounded-md bg-slate-100 p-2 align-top"
                  >
                    {goals.length === 0 ? (
                      <p className="text-[11px] text-ink-muted">今天没有待办任务</p>
                    ) : (
                      <ul className="flex flex-col gap-1.5">
                        {goals.map((goal) => (
                          <li key={goal.subject} className="text-[11.5px] text-ink">
                            <span className="font-semibold tabular-nums text-accent">
                              {formatMinutes(goal.minutes)}
                            </span>{' '}
                            {goal.subject}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="border-t border-line px-4 py-2.5 text-[11.5px] leading-relaxed text-ink-muted">
        计划不必严格执行，可以随时调整：某天没做完，把任务挪到明天就好，节奏比强度更重要。
      </p>
    </Card>
  )
}

function TaskChip({ task }: { task: TaskRead }) {
  return (
    <div
      className={cx('rounded-md px-1.5 py-1 text-[11px] leading-snug ring-1 ring-inset', statusTone(task.status))}
      title={task.title}
    >
      <p className="line-clamp-2 font-medium">{task.title}</p>
      <p className="mt-0.5 text-[10px] tabular-nums opacity-80">
        {task.subject || '通用'} · {task.duration_minutes}m
      </p>
    </div>
  )
}

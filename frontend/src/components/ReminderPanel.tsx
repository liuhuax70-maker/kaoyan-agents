'use client'

import { useCallback, useEffect, useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { IconBell, IconRefresh } from './icons'
import { Badge, Button, Card, EmptyState, ErrorBanner, Spinner } from './ui'
import { api } from '@/lib/api'
import { REMINDER_TYPE_LABEL, dateTime } from '@/lib/format'
import type { ReminderRead } from '@/lib/types'

const KINDS: Array<{ key: 'daily' | 'overdue' | 'idle' | 'weekly'; label: string; hint: string }> = [
  { key: 'daily', label: '每日提醒', hint: '今天有待办任务时触发' },
  { key: 'overdue', label: '逾期催办', hint: '仅针对存在逾期任务的考生' },
  { key: 'idle', label: '断签预警', hint: '连续未学习达到阈值时触发' },
  { key: 'weekly', label: '周报复盘', hint: '汇总本周表现与下周重点' },
]

export function ReminderPanel() {
  const { userId, refresh } = useWorkspace()

  const [reminders, setReminders] = useState<ReminderRead[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (userId === null) {
      return
    }
    setLoading(true)
    try {
      setReminders(await api.listReminders(userId, 30))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '加载提醒失败')
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  const trigger = async (kind: 'daily' | 'overdue' | 'idle' | 'weekly') => {
    setRunning(kind)
    setNotice(null)
    setError(null)
    try {
      const payload = (await api.runReminders(kind)) as {
        generated?: number
        delivered?: number
        skipped?: number
      }
      setNotice(
        `已执行：生成 ${payload.generated ?? 0} 条，投递 ${payload.delivered ?? 0} 条，跳过 ${
          payload.skipped ?? 0
        } 位考生`,
      )
      await load()
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '触发提醒失败')
    } finally {
      setRunning(null)
    }
  }

  return (
    <Card
      title="提醒督促"
      subtitle="生产环境由 Celery Beat 定时触发，这里可手动执行查看效果"
      action={
        <Button variant="outline" onClick={() => void load()}>
          <IconRefresh size={15} />
          刷新
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} onRetry={() => void load()} />}
        {notice && (
          <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/8 px-4 py-3 text-xs text-emerald-200">
            {notice}
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {KINDS.map((kind) => (
            <button
              key={kind.key}
              type="button"
              disabled={running !== null}
              onClick={() => void trigger(kind.key)}
              className="rounded-xl border border-white/10 bg-white/[0.02] px-3.5 py-3 text-left transition-colors hover:border-indigo-400/35 hover:bg-indigo-500/6 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="flex items-center gap-1.5 text-[12px] font-medium text-slate-200">
                <IconBell size={14} />
                {kind.label}
                {running === kind.key && (
                  <span className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-indigo-400 border-t-transparent" />
                )}
              </span>
              <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">
                {kind.hint}
              </span>
            </button>
          ))}
        </div>

        {loading ? (
          <Spinner label="正在加载提醒…" />
        ) : reminders.length === 0 ? (
          <EmptyState
            title="暂无提醒记录"
            description="点击上方任一类型即可立即生成一条督促提醒。"
          />
        ) : (
          <ul className="space-y-2.5">
            {reminders.map((reminder) => (
              <li key={reminder.id} className="rounded-xl border border-white/8 bg-white/[0.02] p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="indigo">
                    {REMINDER_TYPE_LABEL[reminder.reminder_type] ?? reminder.reminder_type}
                  </Badge>
                  <Badge
                    tone={
                      reminder.status === 'sent'
                        ? 'emerald'
                        : reminder.status === 'failed'
                          ? 'rose'
                          : 'amber'
                    }
                  >
                    {reminder.status === 'sent'
                      ? '已发送'
                      : reminder.status === 'failed'
                        ? '发送失败'
                        : '待发送'}
                  </Badge>
                  <Badge tone="neutral">{reminder.channel}</Badge>
                  <span className="ml-auto text-[11px] text-slate-600">
                    {dateTime(reminder.created_at)}
                  </span>
                </div>
                <p className="mt-2 text-[13px] font-medium text-slate-200">{reminder.title}</p>
                <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-slate-500">
                  {reminder.content}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}

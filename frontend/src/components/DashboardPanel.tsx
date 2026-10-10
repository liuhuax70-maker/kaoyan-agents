'use client'

import Link from 'next/link'
import { useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { IconChart, IconPlan, IconSpark } from './icons'
import { Badge, Button, Card, EmptyState, ErrorBanner, ProgressBar, Stat } from './ui'
import { api } from '@/lib/api'
import { REMINDER_TYPE_LABEL, percent, shortDate } from '@/lib/format'

export function DashboardPanel() {
  const { userId, user, target, dashboard, refresh, setError, error } = useWorkspace()
  const [generating, setGenerating] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  if (!dashboard || userId === null) {
    return <EmptyState title="暂无数据" description="请先完成考生档案与备考目标设置。" />
  }

  const stats = dashboard.task_stats

  const generate = async () => {
    setGenerating(true)
    setNotice(null)
    setError(null)
    try {
      const result = await api.generatePlan(userId, '', false)
      if (result.plan_id) {
        setNotice(`已生成计划并入库（计划 #${result.plan_id}），可在「学习计划」查看任务`)
      } else if (result.reply) {
        setNotice('本次未生成可入库的计划，请确认已设置备考目标与科目')
      }
      await refresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '生成计划失败')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <ErrorBanner message={error} />}
      {notice && (
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/8 px-4 py-3 text-xs text-emerald-200">
          {notice}
        </div>
      )}

      {!target && (
        <Card>
          <EmptyState
            title="还没有备考目标"
            description="设置目标院校、考试日期与科目后，规划智能体才能生成贴合你节奏的学习计划。"
            action={
              <Link
                href="/plan"
                className="rounded-xl bg-indigo-500 px-3.5 py-2 text-[13px] font-medium text-white hover:bg-indigo-400"
              >
                去设置备考目标
              </Link>
            }
          />
        </Card>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="任务总数" value={stats.total} hint={`已完成 ${stats.done}`} />
        <Stat
          label="整体完成度"
          value={percent(stats.completion)}
          tone="emerald"
          hint={`进行中 ${stats.doing} · 待开始 ${stats.todo}`}
        />
        <Stat
          label="逾期任务"
          value={stats.overdue}
          tone={stats.overdue > 0 ? 'rose' : 'emerald'}
          hint={stats.overdue > 0 ? '建议优先后处理' : '节奏正常'}
        />
        <Stat
          label="距考试"
          value={dashboard.days_left != null ? `${dashboard.days_left} 天` : '—'}
          tone="amber"
          hint={dashboard.exam_date ? shortDate(dashboard.exam_date) : '未设置考试日期'}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
        <Card
          title="当前学习计划"
          subtitle={dashboard.plan_title || '尚未生成计划'}
          action={
            <Button onClick={generate} loading={generating}>
              <IconSpark size={15} />
              生成计划
            </Button>
          }
        >
          {dashboard.plan_id ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span>计划完成度</span>
                <span className="tabular-nums text-slate-300">
                  {percent(dashboard.plan_progress)}
                </span>
              </div>
              <ProgressBar value={dashboard.plan_progress} tone="emerald" />
              <div className="flex flex-wrap gap-2 pt-1">
                <Link
                  href="/plan"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs text-slate-200 hover:border-white/25 hover:bg-white/5"
                >
                  <IconPlan size={14} />
                  查看任务看板
                </Link>
                <Link
                  href="/chat"
                  className="inline-flex items-center gap-1.5 rounded-xl border border-white/12 px-3 py-1.5 text-xs text-slate-200 hover:border-white/25 hover:bg-white/5"
                >
                  <IconChart size={14} />
                  找智能体复盘
                </Link>
              </div>
            </div>
          ) : (
            <p className="text-xs leading-relaxed text-slate-500">
              点击右上角「生成计划」，规划智能体会依据你的基础、目标与剩余天数划分阶段并拆解任务。
            </p>
          )}
        </Card>

        <Card title="最近提醒" subtitle={`待发送 ${dashboard.pending_reminders} 条`}>
          {dashboard.recent_reminders.length === 0 ? (
            <p className="text-xs leading-relaxed text-slate-500">
              暂无提醒。可在「学习计划」页手动触发一轮提醒查看效果。
            </p>
          ) : (
            <ul className="space-y-3">
              {dashboard.recent_reminders.map((reminder) => (
                <li key={reminder.id} className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
                  <div className="flex items-center gap-2">
                    <Badge tone="indigo">{REMINDER_TYPE_LABEL[reminder.reminder_type] ?? reminder.reminder_type}</Badge>
                    <Badge tone={reminder.status === 'sent' ? 'emerald' : 'amber'}>
                      {reminder.status === 'sent' ? '已发送' : '待发送'}
                    </Badge>
                    <span className="ml-auto text-[11px] text-slate-600">
                      {shortDate(reminder.created_at)}
                    </span>
                  </div>
                  <p className="mt-2 text-xs font-medium text-slate-200">{reminder.title}</p>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-slate-500">
                    {reminder.content}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="考生档案摘要">
        <div className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <Summary label="备考目标" value={dashboard.target_title || '未设置'} />
          <Summary label="每日可投入" value={`${user?.profile?.daily_hours ?? '—'} 小时`} />
          <Summary label="单次专注" value={`${user?.profile?.attention_span ?? '—'} 分钟`} />
          <Summary label="自律程度" value={`${user?.profile?.self_discipline ?? '—'}/5`} />
        </div>
      </Card>
    </div>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-2.5">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className="mt-1 truncate text-[13px] font-medium text-slate-200">{value}</p>
    </div>
  )
}

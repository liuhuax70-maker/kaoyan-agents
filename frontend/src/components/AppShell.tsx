'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { ConnectGate } from './ConnectGate'
import { useWorkspace } from './WorkspaceProvider'
import { IconChat, IconDashboard, IconPlan, IconRefresh, IconSystem } from './icons'
import { Badge, Button, Spinner, cx } from './ui'

const NAV = [
  { href: '/', label: '工作台', Icon: IconDashboard },
  { href: '/chat', label: '多智能体对话', Icon: IconChat },
  { href: '/plan', label: '学习计划', Icon: IconPlan },
  { href: '/system', label: '系统总览', Icon: IconSystem },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const { userId, user, target, dashboard, booting, busy, refresh, disconnect } = useWorkspace()

  if (booting) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="正在连接后端…" />
      </div>
    )
  }

  if (userId === null) {
    return <main className="mx-auto w-full max-w-6xl px-5 py-10">{<ConnectGate />}</main>
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1400px] gap-6 px-4 py-5 lg:px-6">
      <aside className="hidden w-60 shrink-0 flex-col lg:flex">
        <div className="flex items-center gap-2.5 px-2 py-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 text-sm font-bold text-white">
            考
          </span>
          <div className="leading-tight">
            <p className="text-[13px] font-semibold text-slate-100">备考督导台</p>
            <p className="text-[11px] text-slate-500">多智能体协作</p>
          </div>
        </div>

        <nav className="mt-6 flex flex-col gap-1">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                className={cx(
                  'flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors',
                  active
                    ? 'bg-indigo-500/12 text-indigo-200 ring-1 ring-inset ring-indigo-400/20'
                    : 'text-slate-400 hover:bg-white/5 hover:text-slate-200',
                )}
              >
                <Icon size={17} />
                {label}
              </Link>
            )
          })}
        </nav>

        <div className="mt-auto rounded-2xl border border-white/8 bg-white/[0.02] p-4">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">当前考生</p>
          <p className="mt-1.5 truncate text-sm font-medium text-slate-100">
            {user?.nickname ?? '—'}
          </p>
          <p className="mt-0.5 truncate text-[11px] text-slate-500">@{user?.username}</p>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {target ? (
              <Badge tone="indigo">{target.title}</Badge>
            ) : (
              <Badge tone="amber">未设置目标</Badge>
            )}
            {dashboard?.days_left != null && (
              <Badge tone="sky">剩余 {dashboard.days_left} 天</Badge>
            )}
          </div>

          <Button
            variant="ghost"
            className="mt-3 w-full"
            onClick={disconnect}
            title="退出当前考生"
          >
            切换考生
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/8 bg-white/[0.025] px-4 py-3 backdrop-blur-sm">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 text-sm font-bold text-white lg:hidden">
              考
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-100">
                {dashboard?.target_title || user?.nickname || '工作台'}
              </p>
              <p className="truncate text-[11px] text-slate-500">
                {dashboard?.plan_title
                  ? `当前计划：${dashboard.plan_title}`
                  : '尚未生成学习计划'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {dashboard && (
              <>
                <Badge tone="emerald">完成度 {(dashboard.task_stats.completion * 100).toFixed(0)}%</Badge>
                {dashboard.task_stats.overdue > 0 && (
                  <Badge tone="rose">逾期 {dashboard.task_stats.overdue}</Badge>
                )}
                {dashboard.pending_reminders > 0 && (
                  <Badge tone="amber">待发提醒 {dashboard.pending_reminders}</Badge>
                )}
              </>
            )}
            <Button variant="outline" onClick={refresh} loading={busy}>
              <IconRefresh size={15} />
              刷新
            </Button>
          </div>
        </header>

        <nav className="flex gap-1.5 overflow-x-auto lg:hidden">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === '/' ? pathname === '/' : pathname.startsWith(href)
            return (
              <Link
                key={href}
                href={href}
                className={cx(
                  'flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium transition-colors',
                  active
                    ? 'bg-indigo-500/12 text-indigo-200 ring-1 ring-inset ring-indigo-400/20'
                    : 'text-slate-400 hover:bg-white/5',
                )}
              >
                <Icon size={15} />
                {label}
              </Link>
            )
          })}
        </nav>

        <main className="min-w-0 flex-1 pb-10">{children}</main>
      </div>
    </div>
  )
}

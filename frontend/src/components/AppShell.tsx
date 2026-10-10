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

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-[13px] font-semibold text-white">
        考
      </span>
      <div className="leading-tight">
        <p className="text-[13px] font-semibold text-ink">备考督导台</p>
        <p className="text-[11px] text-ink-muted">多智能体协作</p>
      </div>
    </div>
  )
}

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

  const isActive = (href: string) => (href === '/' ? pathname === '/' : pathname.startsWith(href))

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1400px] gap-6 px-4 py-5 lg:px-6">
      <aside className="hidden w-56 shrink-0 flex-col lg:flex">
        <div className="px-1 py-1">
          <Brand />
        </div>

        <nav className="mt-7 flex flex-col gap-0.5">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={cx(
                'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors',
                isActive(href)
                  ? 'bg-accent-soft text-accent'
                  : 'text-ink-soft hover:bg-slate-100 hover:text-ink',
              )}
            >
              <Icon size={16} />
              {label}
            </Link>
          ))}
        </nav>

        <div className="surface mt-auto p-3.5">
          <p className="text-[11px] text-ink-muted">当前考生</p>
          <p className="mt-1 truncate text-[13px] font-medium text-ink">
            {user?.nickname ?? '—'}
          </p>
          <p className="truncate text-[11px] text-ink-muted">@{user?.username}</p>

          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {target ? <Badge tone="indigo">{target.title}</Badge> : <Badge tone="amber">未设置目标</Badge>}
            {dashboard?.days_left != null && <Badge tone="sky">剩余 {dashboard.days_left} 天</Badge>}
          </div>

          <Button variant="outline" className="mt-3 w-full" onClick={disconnect}>
            切换考生
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col gap-3.5">
        <header className="surface flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-[13px] font-semibold text-white lg:hidden">
              考
            </span>
            <div className="min-w-0">
              <p className="truncate text-[13.5px] font-semibold text-ink">
                {dashboard?.target_title || user?.nickname || '工作台'}
              </p>
              <p className="truncate text-[11px] text-ink-muted">
                {dashboard?.plan_title ? `当前计划：${dashboard.plan_title}` : '尚未生成学习计划'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {dashboard && (
              <>
                <Badge tone="emerald">
                  完成度 {(dashboard.task_stats.completion * 100).toFixed(0)}%
                </Badge>
                {dashboard.task_stats.overdue > 0 && (
                  <Badge tone="rose">逾期 {dashboard.task_stats.overdue}</Badge>
                )}
                {dashboard.pending_reminders > 0 && (
                  <Badge tone="amber">待发提醒 {dashboard.pending_reminders}</Badge>
                )}
              </>
            )}
            <Button variant="outline" onClick={refresh} loading={busy}>
              <IconRefresh size={14} />
              刷新
            </Button>
          </div>
        </header>

        <nav className="flex gap-1 overflow-x-auto lg:hidden">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={cx(
                'flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors',
                isActive(href)
                  ? 'bg-accent-soft text-accent'
                  : 'text-ink-soft hover:bg-slate-100',
              )}
            >
              <Icon size={14} />
              {label}
            </Link>
          ))}
        </nav>

        <main className="min-w-0 flex-1 pb-10">{children}</main>
      </div>
    </div>
  )
}

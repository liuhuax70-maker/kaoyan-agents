'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'

import { ConnectGate } from './ConnectGate'
import { useWorkspace } from './WorkspaceProvider'
import { IconChat, IconDashboard, IconPlan, IconPlus, IconRefresh } from './icons'
import { Badge, Button, Spinner, cx } from './ui'
import { groupByRecency } from '@/lib/format'

const NAV = [
  { href: '/', label: '工作台', Icon: IconDashboard },
  { href: '/chat', label: '多智能体对话', Icon: IconChat },
  { href: '/plan', label: '学习计划', Icon: IconPlan },
] as const

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const {
    userId,
    user,
    dashboard,
    booting,
    busy,
    refresh,
    disconnect,
    conversations,
    activeConversationId,
    openConversation,
    startNewChat,
  } = useWorkspace()

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
  const isChat = pathname.startsWith('/chat')
  const groups = groupByRecency(conversations, (item) => item.created_at)

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ---------- 侧边栏 ---------- */}
      <aside className="hidden w-[272px] shrink-0 flex-col border-r border-line bg-sidebar lg:flex">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-[13px] font-semibold text-white">
            考
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-ink">备考督导台</span>
        </div>

        <nav className="flex flex-col gap-0.5 px-2">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={cx(
                'flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-[13.5px] font-medium transition-colors',
                isActive(href)
                  ? 'bg-accent-soft text-accent'
                  : 'text-ink-soft hover:bg-slate-100 hover:text-ink',
              )}
            >
              <Icon size={17} />
              {label}
            </Link>
          ))}
        </nav>

        <div className="px-3 pt-4">
          <button
            type="button"
            onClick={startNewChat}
            className="flex w-full items-center gap-2 rounded-full border border-line-strong bg-surface px-3.5 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-slate-50"
          >
            <IconPlus size={15} />
            开启新对话
          </button>
        </div>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {groups.length === 0 ? (
            <p className="px-2.5 py-2 text-[12px] text-ink-muted">还没有对话记录</p>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="mb-2">
                <p className="px-2.5 py-1.5 text-[11px] font-medium text-ink-muted">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.items.map((conversation) => (
                    <li key={conversation.id}>
                      <button
                        type="button"
                        onClick={() => void openConversation(conversation.id)}
                        title={conversation.title || `会话 #${conversation.id}`}
                        className={cx(
                          'w-full truncate rounded-xl px-2.5 py-2 text-left text-[13px] transition-colors',
                          conversation.id === activeConversationId
                            ? 'bg-surface text-ink shadow-[0_1px_2px_rgba(16,24,40,0.06)]'
                            : 'text-ink-soft hover:bg-slate-100',
                        )}
                      >
                        {conversation.title || `会话 #${conversation.id}`}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>

        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[13px] font-semibold text-accent">
              {(user?.nickname ?? '考').slice(0, 1)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-ink">{user?.nickname ?? '—'}</p>
              <p className="truncate text-[11px] text-ink-muted">@{user?.username}</p>
            </div>
            <button
              type="button"
              onClick={disconnect}
              className="shrink-0 rounded-lg px-2 py-1 text-[11px] text-ink-muted transition-colors hover:bg-slate-100 hover:text-ink"
            >
              切换
            </button>
          </div>
        </div>
      </aside>

      {/* ---------- 主区域 ---------- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-[13px] font-semibold text-white lg:hidden">
              考
            </span>
            <div className="min-w-0">
              <p className="truncate text-[14px] font-semibold text-ink">
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
              </>
            )}
            <Button variant="ghost" onClick={refresh} loading={busy} title="刷新">
              <IconRefresh size={15} />
            </Button>
          </div>
        </header>

        <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-line px-3 py-2 lg:hidden">
          {NAV.map(({ href, label, Icon }) => (
            <Link
              key={href}
              href={href}
              className={cx(
                'flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors',
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

        <main
          className={cx('min-h-0 flex-1', isChat ? 'overflow-hidden' : 'overflow-y-auto p-5')}
        >
          {children}
        </main>
      </div>
    </div>
  )
}

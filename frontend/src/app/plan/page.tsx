'use client'

import { useState } from 'react'

import { PlanBoard } from '@/components/PlanBoard'
import { ProfilePanel } from '@/components/ProfilePanel'
import { ReminderPanel } from '@/components/ReminderPanel'
import { cx } from '@/components/ui'

const TABS = [
  { key: 'plan', label: '任务看板' },
  { key: 'profile', label: '档案与目标' },
  { key: 'reminder', label: '提醒督促' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function PlanPage() {
  const [tab, setTab] = useState<TabKey>('plan')

  return (
    <div className="flex flex-col gap-3.5">
      <nav className="surface inline-flex w-fit gap-1 p-1">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={cx(
              'rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors',
              tab === item.key
                ? 'bg-accent-soft text-accent'
                : 'text-ink-soft hover:bg-slate-100 hover:text-ink',
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === 'plan' && <PlanBoard />}
      {tab === 'profile' && <ProfilePanel />}
      {tab === 'reminder' && <ReminderPanel />}
    </div>
  )
}

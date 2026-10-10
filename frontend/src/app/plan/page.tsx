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
    <div className="flex flex-col gap-4">
      <nav className="flex gap-1.5">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={cx(
              'rounded-xl px-3.5 py-2 text-[13px] font-medium transition-colors',
              tab === item.key
                ? 'bg-indigo-500/12 text-indigo-200 ring-1 ring-inset ring-indigo-400/20'
                : 'text-slate-400 hover:bg-white/5 hover:text-slate-200',
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

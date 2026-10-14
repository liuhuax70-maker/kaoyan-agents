'use client'

import { useState } from 'react'

import { Button, cx } from './ui'
import { IconCheck } from './icons'
import type { PlanConfirmation } from '@/lib/types'

const KIND_LABEL: Record<PlanConfirmation['kind'], string> = {
  plan_draft: '整份重排',
  plan_revision: '局部修订',
}

// 知识点：人工确认闸门在 UI 上的形态 —— 暂停期间数据库是干净的，
//   卡片展示的只是草稿；用户点头之前不存在「已写进去再回滚」这一步
//   （第5章 LangGraph·人工确认）
/**
 * 计划落库前的人工确认卡片。
 *
 * 后端在写库前把图暂停（LangGraph `interrupt`），此时下发的是**尚未写库**的草稿；
 * 用户在这里点「确认落库」才会真正写进计划表。因此这张卡片不是提示，
 * 而是这道闸门的唯一开关——所以它必须把待确认的要点逐条列出来，
 * 否则「确认」只是让用户盲签一个字。
 */
export function ConfirmationCard({
  confirmation,
  busy,
  onResolve,
}: {
  confirmation: PlanConfirmation
  busy: boolean
  onResolve: (approve: boolean, feedback: string) => void
}) {
  const [feedback, setFeedback] = useState('')

  return (
    <div className="rounded-card border border-amber-200 bg-amber-50/60 px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center rounded-md bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
          {KIND_LABEL[confirmation.kind]}
        </span>
        <span className="text-[13px] font-semibold text-ink">计划待确认，尚未写库</span>
      </div>

      {confirmation.title && (
        <p className="mt-2 text-[13.5px] font-medium text-ink">{confirmation.title}</p>
      )}
      {confirmation.summary && (
        <p className="mt-1 text-[13px] leading-[1.7] text-ink-soft">{confirmation.summary}</p>
      )}

      {confirmation.items.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {confirmation.items.map((item, index) => (
            <li key={index} className="flex gap-2.5 text-[13px] leading-[1.7] text-ink-soft">
              <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-amber-500" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}

      <textarea
        value={feedback}
        onChange={(event) => setFeedback(event.target.value)}
        rows={2}
        disabled={busy}
        placeholder="想调整什么？写在这里，驳回后我重新拟一版（可留空）"
        className={cx('control mt-3', busy && 'opacity-60')}
      />

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          loading={busy}
          onClick={() => onResolve(true, feedback.trim())}
          className="bg-emerald-600 text-white hover:bg-emerald-700"
        >
          <IconCheck size={13} />
          确认落库
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => onResolve(false, feedback.trim())}
        >
          先不要
        </Button>
        <span className="text-[11.5px] text-ink-muted">
          确认前不会改动你的计划表
        </span>
      </div>
    </div>
  )
}
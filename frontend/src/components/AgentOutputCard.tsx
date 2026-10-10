'use client'

import type { AgentOutput, Reference } from '@/lib/types'

import { Badge, Card, cx, type BadgeTone } from './ui'

// 显式声明为 BadgeTone：否则索引结果会被推断为不含 neutral 的联合类型，
// 后续 `?? 'neutral'` 会被 TypeScript 判定为无意义比较。
const AGENT_TONE: Record<string, BadgeTone> = {
  coordinator: 'indigo',
  planner: 'indigo',
  breakdown: 'sky',
  tutor: 'emerald',
  reviewer: 'amber',
  resource: 'sky',
  coach: 'rose',
}

interface PlanStagePreview {
  name?: unknown
  focus?: unknown
  tasks?: unknown
}

interface ReviewIssue {
  severity?: 'low' | 'medium' | 'high'
  category?: string
  detail?: string
  suggestion?: string
}

interface ReviewPayload {
  approved?: boolean
  score?: number
  issues?: unknown
}

/** 智能体产出卡片：把结构化 payload 中的关键信息渲染出来，而不是只显示一段文本。 */
export function AgentOutputCard({ output }: { output: AgentOutput }) {
  const tone: BadgeTone = (AGENT_TONE as Record<string, BadgeTone | undefined>)[output.agent] ?? 'neutral'
  const references = extractReferences(output.payload)
  const stages = extractStages(output.payload)
  const review = extractReview(output.payload)

  return (
    <Card
      className="animate-fade-up"
      title={
        <span className="flex items-center gap-2">
          <Badge tone={tone}>{output.name}</Badge>
          <span className="text-slate-300">{output.title}</span>
        </span>
      }
    >
      <div className="space-y-3">
        {output.summary && (
          <p className="text-[13px] leading-relaxed text-slate-300">{output.summary}</p>
        )}

        {output.highlights.length > 0 && (
          <ul className="space-y-1.5">
            {output.highlights.map((line, index) => (
              <li key={index} className="flex gap-2 text-xs leading-relaxed text-slate-400">
                <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-indigo-400/70" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        )}

        {stages.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {stages.map((stage, index) => (
              <span
                key={index}
                className="rounded-lg border border-white/8 bg-white/[0.03] px-2.5 py-1.5 text-[11px] text-slate-300"
              >
                <span className="font-medium text-slate-200">{stage.name}</span>
                {stage.taskCount > 0 && (
                  <span className="ml-1.5 text-slate-500">{stage.taskCount} 个任务</span>
                )}
              </span>
            ))}
          </div>
        )}

        {review && (
          <div className="rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-3">
            <div className="flex items-center gap-2">
              <Badge tone={review.approved ? 'emerald' : 'amber'}>
                {review.approved ? '评审通过' : '需修订'}
              </Badge>
              <span className="text-[11px] text-slate-400">质量评分 {review.score}</span>
              <span className="text-[11px] text-slate-600">· {review.reviewer}</span>
            </div>
            {review.issues.length > 0 && (
              <ul className="mt-2.5 space-y-1.5">
                {review.issues.map((issue, index) => (
                  <li key={index} className="text-[11px] leading-relaxed text-slate-400">
                    <span
                      className={cx(
                        'mr-1.5 rounded px-1 py-px text-[10px]',
                        issue.severity === 'high'
                          ? 'bg-rose-500/15 text-rose-300'
                          : issue.severity === 'medium'
                            ? 'bg-amber-500/15 text-amber-300'
                            : 'bg-slate-500/15 text-slate-400',
                      )}
                    >
                      {issue.severity === 'high' ? '高' : issue.severity === 'medium' ? '中' : '低'}
                    </span>
                    {issue.category && <span className="text-slate-300">{issue.category}：</span>}
                    {issue.detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {references.length > 0 && (
          <details className="group rounded-xl border border-white/8 bg-white/[0.02] px-3.5 py-2.5">
            <summary className="cursor-pointer list-none text-[11px] text-slate-400 hover:text-slate-300">
              引用知识库片段 {references.length} 条
              <span className="ml-1 text-slate-600 group-open:hidden">展开</span>
            </summary>
            <ul className="mt-2.5 space-y-2">
              {references.map((item) => (
                <li key={item.id} className="text-[11px] leading-relaxed text-slate-500">
                  <span className="text-slate-400">
                    [{item.subject || '通用'}] {item.source || item.id}
                  </span>
                  <span className="ml-1.5 text-slate-600">相似度 {item.score.toFixed(2)}</span>
                  <p className="mt-0.5 line-clamp-3">{item.text}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Card>
  )
}

function extractStages(payload: Record<string, unknown>): Array<{ name: string; taskCount: number }> {
  const raw = payload.stages
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return []
    }
    const stage = item as PlanStagePreview
    const tasks = Array.isArray(stage.tasks) ? stage.tasks.length : 0
    return [{ name: String(stage.name ?? '阶段'), taskCount: tasks }]
  })
}

function extractReview(
  payload: Record<string, unknown>,
): { approved: boolean; score: number; reviewer: string; issues: ReviewIssue[] } | null {
  const candidate = payload as ReviewPayload
  if (candidate.approved === undefined && candidate.score === undefined) {
    return null
  }
  const issues = Array.isArray(candidate.issues) ? (candidate.issues as ReviewIssue[]) : []
  return {
    approved: Boolean(candidate.approved),
    score: Number(candidate.score ?? 0),
    reviewer: String(payload.reviewer ?? '—'),
    issues,
  }
}

function extractReferences(payload: Record<string, unknown>): Reference[] {
  const raw = payload.references
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return []
    }
    const record = item as Record<string, unknown>
    return [
      {
        id: String(record.id ?? ''),
        text: String(record.text ?? ''),
        score: Number(record.score ?? 0),
        source: String(record.source ?? ''),
        subject: String(record.subject ?? ''),
      },
    ]
  })
}

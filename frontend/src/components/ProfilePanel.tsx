'use client'

import { useEffect, useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { Button, Card, ErrorBanner, Field, Input, Select, Textarea } from './ui'
import { addDaysISO } from '@/lib/format'
import type { ProfileInput } from '@/lib/types'

interface SubjectRow {
  name: string
  is_weak: boolean
  score_weight: number
}

interface TargetForm {
  title: string
  target_school: string
  target_major: string
  exam_date: string
  description: string
  subjects: SubjectRow[]
}

const EMPTY_PROFILE: ProfileInput = {
  education: '',
  major: '',
  base_level: '一般',
  daily_hours: 5,
  weekly_days: 6,
  attention_span: 50,
  self_discipline: 3,
  preferred_slots: [],
  notes: '',
}

const EMPTY_TARGET: TargetForm = {
  title: '',
  target_school: '',
  target_major: '',
  exam_date: addDaysISO(150),
  description: '',
  subjects: [
    { name: '政治', is_weak: false, score_weight: 0.2 },
    { name: '英语', is_weak: false, score_weight: 0.2 },
    { name: '数学', is_weak: true, score_weight: 0.3 },
    { name: '专业课', is_weak: false, score_weight: 0.3 },
  ],
}

export function ProfilePanel() {
  const { user, target, saveProfile, saveTarget, busy, error, setError } = useWorkspace()

  const [profile, setProfile] = useState<ProfileInput>(EMPTY_PROFILE)
  const [slots, setSlots] = useState('')
  const [targetForm, setTargetForm] = useState<TargetForm>(EMPTY_TARGET)
  const [notice, setNotice] = useState<string | null>(null)

  // 档案与目标落库后同步回表单
  useEffect(() => {
    if (user?.profile) {
      const { id: _id, user_id: _uid, ...rest } = user.profile
      void _id
      void _uid
      setProfile(rest)
      setSlots(rest.preferred_slots.join('、'))
    }
  }, [user])

  useEffect(() => {
    if (target) {
      setTargetForm({
        title: target.title,
        target_school: target.target_school,
        target_major: target.target_major,
        exam_date: target.exam_date,
        description: target.description,
        subjects: target.subjects.map((item) => ({
          name: item.name,
          is_weak: item.is_weak,
          score_weight: item.score_weight,
        })),
      })
    }
  }, [target])

  const updateSubject = (index: number, patch: Partial<SubjectRow>) => {
    setTargetForm((current) => ({
      ...current,
      subjects: current.subjects.map((item, position) =>
        position === index ? { ...item, ...patch } : item,
      ),
    }))
  }

  const submitProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setNotice(null)
    setError(null)
    try {
      await saveProfile({
        ...profile,
        preferred_slots: slots
          .split(/[、,，\s]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      })
      setNotice('学习档案已保存')
    } catch {
      // 错误已由上下文写入
    }
  }

  const submitTarget = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setNotice(null)
    setError(null)

    const subjects = targetForm.subjects.filter((item) => item.name.trim())
    if (subjects.length === 0) {
      setError('至少需要一门考试科目')
      return
    }
    if (!targetForm.title.trim()) {
      setError('请填写备考目标名称')
      return
    }

    try {
      await saveTarget({
        title: targetForm.title.trim(),
        target_school: targetForm.target_school.trim(),
        target_major: targetForm.target_major.trim(),
        exam_date: targetForm.exam_date,
        description: targetForm.description.trim(),
        subjects,
      })
      setNotice('备考目标已保存，可在「学习计划」页生成学习计划')
    } catch {
      // 错误已由上下文写入
    }
  }

  return (
    <div className="flex flex-col gap-3.5">
      {error && <ErrorBanner message={error} />}
      {notice && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs text-emerald-800">
          {notice}
        </div>
      )}

      <Card title="备考目标与科目" subtitle="决定计划周期与任务分配权重">
        <form onSubmit={submitTarget} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="目标名称">
              <Input
                value={targetForm.title}
                onChange={(event) =>
                  setTargetForm((current) => ({ ...current, title: event.target.value }))
                }
                placeholder="例如：复旦计算机 408"
              />
            </Field>
            <Field label="考试日期">
              <Input
                type="date"
                value={targetForm.exam_date}
                onChange={(event) =>
                  setTargetForm((current) => ({ ...current, exam_date: event.target.value }))
                }
              />
            </Field>
            <Field label="目标院校">
              <Input
                value={targetForm.target_school}
                onChange={(event) =>
                  setTargetForm((current) => ({ ...current, target_school: event.target.value }))
                }
                placeholder="例如：复旦大学"
              />
            </Field>
            <Field label="目标专业">
              <Input
                value={targetForm.target_major}
                onChange={(event) =>
                  setTargetForm((current) => ({ ...current, target_major: event.target.value }))
                }
                placeholder="例如：计算机科学与技术"
              />
            </Field>
          </div>

          <Field label="补充说明" hint="可写明分数线目标、跨考情况等，会一并进入智能体上下文">
            <Textarea
              rows={2}
              value={targetForm.description}
              onChange={(event) =>
                setTargetForm((current) => ({ ...current, description: event.target.value }))
              }
              placeholder="例如：目标是总分 380，数学是薄弱科目"
            />
          </Field>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-medium text-ink-soft">考试科目</span>
              <button
                type="button"
                onClick={() =>
                  setTargetForm((current) => ({
                    ...current,
                    subjects: [
                      ...current.subjects,
                      { name: '', is_weak: false, score_weight: 0.1 },
                    ],
                  }))
                }
                className="text-[11px] font-medium text-accent hover:text-accent-hover"
              >
                + 添加科目
              </button>
            </div>
            <div className="space-y-2">
              {targetForm.subjects.map((subject, index) => (
                <div key={index} className="surface-muted flex flex-wrap items-center gap-2 px-2.5 py-2">
                  <Input
                    value={subject.name}
                    onChange={(event) => updateSubject(index, { name: event.target.value })}
                    placeholder="科目名称"
                    className="max-w-40 flex-1"
                  />
                  <Select
                    value={String(subject.score_weight)}
                    onChange={(event) =>
                      updateSubject(index, { score_weight: Number(event.target.value) })
                    }
                    className="max-w-28"
                  >
                    <option value="0.1">占比 10%</option>
                    <option value="0.2">占比 20%</option>
                    <option value="0.3">占比 30%</option>
                    <option value="0.4">占比 40%</option>
                    <option value="0.5">占比 50%</option>
                  </Select>
                  <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-ink-soft">
                    <input
                      type="checkbox"
                      checked={subject.is_weak}
                      onChange={(event) => updateSubject(index, { is_weak: event.target.checked })}
                      className="h-3.5 w-3.5 accent-blue-600"
                    />
                    薄弱科目
                  </label>
                  {targetForm.subjects.length > 1 && (
                    <button
                      type="button"
                      onClick={() =>
                        setTargetForm((current) => ({
                          ...current,
                          subjects: current.subjects.filter((_, position) => position !== index),
                        }))
                      }
                      className="text-[11px] text-ink-muted hover:text-rose-600"
                    >
                      删除
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          <Button type="submit" loading={busy}>
            {target ? '更新备考目标' : '保存备考目标'}
          </Button>
        </form>
      </Card>

      <Card title="学习档案" subtitle="智能体据此判断任务粒度与每日强度">
        <form onSubmit={submitProfile} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="学历">
              <Input
                value={profile.education}
                onChange={(event) =>
                  setProfile((current) => ({ ...current, education: event.target.value }))
                }
                placeholder="例如：本科大三"
              />
            </Field>
            <Field label="专业">
              <Input
                value={profile.major}
                onChange={(event) =>
                  setProfile((current) => ({ ...current, major: event.target.value }))
                }
                placeholder="例如：软件工程"
              />
            </Field>
            <Field label="基础水平">
              <Select
                value={profile.base_level}
                onChange={(event) =>
                  setProfile((current) => ({ ...current, base_level: event.target.value }))
                }
              >
                <option value="零基础">零基础</option>
                <option value="一般">一般</option>
                <option value="较好">较好</option>
                <option value="优秀">优秀</option>
              </Select>
            </Field>
            <Field label="每日可投入（小时）">
              <Input
                type="number"
                min={0.5}
                max={16}
                step={0.5}
                value={profile.daily_hours}
                onChange={(event) =>
                  setProfile((current) => ({ ...current, daily_hours: Number(event.target.value) }))
                }
              />
            </Field>
            <Field label="每周学习天数">
              <Input
                type="number"
                min={1}
                max={7}
                value={profile.weekly_days}
                onChange={(event) =>
                  setProfile((current) => ({ ...current, weekly_days: Number(event.target.value) }))
                }
              />
            </Field>
            <Field label="单次专注时长（分钟）" hint="超过该时长的任务会被拆解">
              <Input
                type="number"
                min={10}
                max={240}
                step={5}
                value={profile.attention_span}
                onChange={(event) =>
                  setProfile((current) => ({
                    ...current,
                    attention_span: Number(event.target.value),
                  }))
                }
              />
            </Field>
            <Field label="自律程度（1-5）" hint="越低，督促语气越严格">
              <Select
                value={String(profile.self_discipline)}
                onChange={(event) =>
                  setProfile((current) => ({
                    ...current,
                    self_discipline: Number(event.target.value),
                  }))
                }
              >
                {[1, 2, 3, 4, 5].map((value) => (
                  <option key={value} value={value}>
                    {value}
                    {value <= 2 ? '（需严格督促）' : value >= 4 ? '（自律良好）' : ''}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="偏好学习时段" hint="用顿号或逗号分隔">
              <Input
                value={slots}
                onChange={(event) => setSlots(event.target.value)}
                placeholder="例如：上午、晚上"
              />
            </Field>
          </div>

          <Field label="备注">
            <Textarea
              rows={2}
              value={profile.notes}
              onChange={(event) =>
                setProfile((current) => ({ ...current, notes: event.target.value }))
              }
              placeholder="例如：在职备考，工作日只能晚上学习"
            />
          </Field>

          <Button type="submit" loading={busy}>
            保存学习档案
          </Button>
        </form>
      </Card>
    </div>
  )
}

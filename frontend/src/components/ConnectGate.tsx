'use client'

import { useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { Button, ErrorBanner, Field, Input } from './ui'
import { API_BASE } from '@/lib/api'

/**
 * 进入工作台前的「登录」入口。
 *
 * 系统未引入账号体系：输入用户名即可进入，
 * 用户名已存在则直接登录，不存在则自动注册一个带默认档案的账号。
 */
export function ConnectGate() {
  const { connect, busy, error, setError } = useWorkspace()
  const [username, setUsername] = useState('')

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = username.trim()
    if (trimmed.length < 2) {
      setError('用户名至少 2 个字符')
      return
    }
    try {
      await connect(trimmed)
    } catch {
      // connect 内部已经写入 error，这里无需重复处理
    }
  }

  return (
    <div className="mx-auto flex min-h-[70vh] w-full max-w-lg flex-col justify-center gap-6">
      <div className="text-center">
        <p className="text-[11px] font-medium uppercase tracking-[0.32em] text-indigo-400">
          Kaoyan Agents
        </p>
        <h1 className="mt-3 text-2xl font-semibold text-slate-100">
          考研考证学习规划与督促系统
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-400">
          多智能体协作生成学习计划、拆解任务、跟踪进度并定时督促
        </p>
      </div>

      <form
        onSubmit={submit}
        className="rounded-2xl border border-white/8 bg-white/[0.025] p-6 backdrop-blur-sm"
      >
        <Field label="考生标识" hint="同一用户名会进入同一份学习档案，换名字即新建账号">
          <Input
            value={username}
            onChange={(event) => {
              setUsername(event.target.value)
              setError(null)
            }}
            placeholder="例如：xiaoyan"
            autoComplete="off"
            maxLength={32}
          />
        </Field>

        {error && (
          <div className="mt-4">
            <ErrorBanner message={error} />
          </div>
        )}

        <Button type="submit" loading={busy} className="mt-5 w-full">
          进入工作台
        </Button>

        <p className="mt-4 text-center text-[11px] text-slate-600">
          后端地址 <span className="font-mono text-slate-500">{API_BASE}</span>
        </p>
      </form>
    </div>
  )
}

'use client'

import { useState } from 'react'

import { useWorkspace } from './WorkspaceProvider'
import { Button, ErrorBanner, Field, Input } from './ui'
import { API_BASE } from '@/lib/api'

/**
 * 进入系统前的「登录」入口。
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
    <div className="mx-auto flex min-h-[70vh] w-full max-w-md flex-col justify-center gap-6">
      <div>
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-sm font-semibold text-white">
          考
        </span>
        <h1 className="mt-4 text-xl font-semibold text-ink">考研考证学习规划与督促系统</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">
          多智能体协作生成学习计划、拆解任务、跟踪进度并定时督促
        </p>
      </div>

      <form onSubmit={submit} className="surface p-5">
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
          <div className="mt-3.5">
            <ErrorBanner message={error} />
          </div>
        )}

        <Button type="submit" loading={busy} className="mt-4 w-full py-2">
          进入系统
        </Button>

        <p className="mt-3.5 text-center text-[11px] text-ink-muted">
          后端地址 <span className="font-mono">{API_BASE}</span>
        </p>
      </form>
    </div>
  )
}

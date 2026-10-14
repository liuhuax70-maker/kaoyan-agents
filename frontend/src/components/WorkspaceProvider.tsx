'use client'

import { useRouter } from 'next/navigation'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError, api, toTurns, type CreateTargetPayload } from '@/lib/api'
import type {
  ChatTurn,
  ConversationSummary,
  DashboardRead,
  ProfileInput,
  TargetRead,
  UserRead,
} from '@/lib/types'

const STORAGE_KEY = 'kaoyan-agents.userId'
const CONVERSATION_PAGE_SIZE = 30

interface WorkspaceValue {
  userId: number | null
  user: UserRead | null
  target: TargetRead | null
  dashboard: DashboardRead | null
  booting: boolean
  busy: boolean
  error: string | null
  setError: (message: string | null) => void
  /** 按用户名登录；不存在则自动注册 */
  connect: (username: string, nickname?: string) => Promise<void>
  disconnect: () => void
  refresh: () => Promise<void>
  saveProfile: (payload: Partial<ProfileInput>) => Promise<void>
  saveTarget: (payload: Omit<CreateTargetPayload, 'user_id'>) => Promise<void>

  /** ---- 会话：侧边栏与对话页共享 ---- */
  conversations: ConversationSummary[]
  reloadConversations: () => Promise<void>
  activeConversationId: number | null
  /** 加载指定会话的消息并跳转到对话页 */
  openConversation: (conversationId: number) => Promise<void>
  turns: ChatTurn[]
  turnsLoading: boolean
  appendTurn: (turn: ChatTurn) => void
  /** 就地改写某一轮，用于答复确认后把卡片从该轮上摘掉 */
  patchTurn: (index: number, patch: Partial<ChatTurn>) => void
  /** 把服务端返回的会话 id 绑定到当前对话 */
  bindConversation: (conversationId: number) => void
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const router = useRouter()

  const [userId, setUserId] = useState<number | null>(null)
  const [user, setUser] = useState<UserRead | null>(null)
  const [target, setTarget] = useState<TargetRead | null>(null)
  const [dashboard, setDashboard] = useState<DashboardRead | null>(null)
  const [booting, setBooting] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [turnsLoading, setTurnsLoading] = useState(false)

  const load = useCallback(async (id: number) => {
    const [loadedUser, targets, board] = await Promise.all([
      api.getUser(id),
      api.listTargets(id),
      api.dashboard(id),
    ])
    setUser(loadedUser)
    setTarget(targets[0] ?? null)
    setDashboard(board)
  }, [])

  const reloadConversations = useCallback(async () => {
    if (userId === null) {
      setConversations([])
      return
    }
    try {
      setConversations(await api.listConversations(userId, CONVERSATION_PAGE_SIZE))
    } catch {
      // 历史列表属于辅助信息，失败不影响主流程
    }
  }, [userId])

  // 首次挂载：尝试用本地记录的 userId 恢复会话
  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (!stored) {
      setBooting(false)
      return
    }

    const parsed = Number(stored)
    if (!Number.isInteger(parsed) || parsed <= 0) {
      window.localStorage.removeItem(STORAGE_KEY)
      setBooting(false)
      return
    }

    setUserId(parsed)
    load(parsed)
      .catch((cause: unknown) => {
        // 后端换了库或记录已失效，清掉本地缓存让用户重新登录
        window.localStorage.removeItem(STORAGE_KEY)
        setUserId(null)
        setError(cause instanceof Error ? cause.message : '恢复会话失败')
      })
      .finally(() => setBooting(false))
  }, [load])

  useEffect(() => {
    void reloadConversations()
  }, [reloadConversations])

  const connect = useCallback(
    async (username: string, nickname?: string) => {
      setBusy(true)
      setError(null)
      try {
        let resolved: UserRead
        try {
          resolved = await api.lookupUser(username)
        } catch (cause) {
          if (cause instanceof ApiError && cause.status === 404) {
            resolved = await api.createUser({
              username,
              nickname: nickname?.trim() || username,
              profile: {
                daily_hours: 5,
                weekly_days: 6,
                attention_span: 50,
                self_discipline: 3,
                base_level: '一般',
              },
            })
          } else {
            throw cause
          }
        }

        window.localStorage.setItem(STORAGE_KEY, String(resolved.id))
        setUserId(resolved.id)
        setUser(resolved)
        await load(resolved.id)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '登录失败')
        throw cause
      } finally {
        setBusy(false)
      }
    },
    [load],
  )

  const disconnect = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY)
    setUserId(null)
    setUser(null)
    setTarget(null)
    setDashboard(null)
    setError(null)
    setConversations([])
    setActiveConversationId(null)
    setTurns([])
  }, [])

  const refresh = useCallback(async () => {
    if (userId === null) {
      return
    }
    try {
      await load(userId)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '刷新失败')
    }
  }, [load, userId])

  const saveProfile = useCallback(
    async (payload: Partial<ProfileInput>) => {
      if (userId === null) {
        return
      }
      setBusy(true)
      setError(null)
      try {
        const updated = await api.updateUser(userId, { profile: payload })
        setUser(updated)
        await load(userId)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '保存档案失败')
        throw cause
      } finally {
        setBusy(false)
      }
    },
    [load, userId],
  )

  const saveTarget = useCallback(
    async (payload: Omit<CreateTargetPayload, 'user_id'>) => {
      if (userId === null) {
        return
      }
      setBusy(true)
      setError(null)
      try {
        await api.createTarget({ ...payload, user_id: userId })
        await load(userId)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '保存备考目标失败')
        throw cause
      } finally {
        setBusy(false)
      }
    },
    [load, userId],
  )

  const openConversation = useCallback(
    async (conversationId: number) => {
      setTurnsLoading(true)
      try {
        const detail = await api.getConversation(conversationId)
        setTurns(toTurns(detail))
        setActiveConversationId(detail.id)
        setError(null)
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '加载会话失败')
      } finally {
        setTurnsLoading(false)
        router.push('/chat')
      }
    },
    [router],
  )

  const appendTurn = useCallback((turn: ChatTurn) => {
    setTurns((current) => [...current, turn])
  }, [])

  const patchTurn = useCallback((index: number, patch: Partial<ChatTurn>) => {
    setTurns((current) =>
      current.map((turn, position) => (position === index ? { ...turn, ...patch } : turn)),
    )
  }, [])

  const bindConversation = useCallback((conversationId: number) => {
    setActiveConversationId(conversationId)
  }, [])

  const value = useMemo<WorkspaceValue>(
    () => ({
      userId,
      user,
      target,
      dashboard,
      booting,
      busy,
      error,
      setError,
      connect,
      disconnect,
      refresh,
      saveProfile,
      saveTarget,
      conversations,
      reloadConversations,
      activeConversationId,
      openConversation,
      turns,
      turnsLoading,
      appendTurn,
      patchTurn,
      bindConversation,
    }),
    [
      userId,
      user,
      target,
      dashboard,
      booting,
      busy,
      error,
      connect,
      disconnect,
      refresh,
      saveProfile,
      saveTarget,
      conversations,
      reloadConversations,
      activeConversationId,
      openConversation,
      turns,
      turnsLoading,
      appendTurn,
      patchTurn,
      bindConversation,
    ],
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext)
  if (value === null) {
    throw new Error('useWorkspace 必须在 WorkspaceProvider 内使用')
  }
  return value
}

import type {
  ChatResponse,
  ConversationRead,
  ConversationSummary,
  DashboardRead,
  KnowledgeHit,
  KnowledgeStats,
  OverviewRead,
  PlanRead,
  ProfileInput,
  ReminderRead,
  StageRead,
  TargetRead,
  TaskProgressRead,
  TaskRead,
  TaskStatus,
  UserRead,
} from './types'

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000').replace(
  /\/$/,
  '',
)

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      cache: 'no-store',
    })
  } catch {
    throw new ApiError(0, `无法连接后端 ${API_BASE}，请确认服务已启动`)
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readError(response))
  }

  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    const detail = payload.detail
    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg)
          }
          return JSON.stringify(item)
        })
        .join('；')
    }
  } catch {
    // 忽略解析失败，回落到状态码描述
  }
  return `请求失败（HTTP ${response.status}）`
}

export interface CreateUserPayload {
  username: string
  nickname?: string
  email?: string | null
  profile?: Partial<ProfileInput>
}

export interface CreateTargetPayload {
  user_id: number
  title: string
  exam_type?: string
  target_school?: string
  target_major?: string
  exam_date: string
  description?: string
  subjects?: Array<{
    name: string
    category?: string
    score_weight?: number
    difficulty?: number
    current_level?: number
    is_weak?: boolean
  }>
}

export interface UpdateTaskPayload {
  status?: TaskStatus
  planned_date?: string
  duration_minutes?: number
  actual_minutes?: number
  score?: number
  note?: string
}

export const api = {
  base: API_BASE,

  // ---- 用户与档案 ----
  createUser: (payload: CreateUserPayload) =>
    request<UserRead>('/api/users', { method: 'POST', body: JSON.stringify(payload) }),

  getUser: (userId: number) => request<UserRead>(`/api/users/${userId}`),

  lookupUser: (username: string) =>
    request<UserRead>(`/api/users/lookup?username=${encodeURIComponent(username)}`),

  updateUser: (userId: number, payload: { nickname?: string; profile?: Partial<ProfileInput> }) =>
    request<UserRead>(`/api/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // ---- 备考目标 ----
  listTargets: (userId: number) => request<TargetRead[]>(`/api/targets?user_id=${userId}`),

  createTarget: (payload: CreateTargetPayload) =>
    request<TargetRead>('/api/targets', { method: 'POST', body: JSON.stringify(payload) }),

  // ---- 学习计划 ----
  generatePlan: (userId: number, goal = '', enableReview = false) =>
    request<ChatResponse>('/api/plans/generate', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, goal, enable_review: enableReview }),
    }),

  listPlans: (userId: number, limit = 10) =>
    request<PlanRead[]>(`/api/plans?user_id=${userId}&limit=${limit}`),

  getPlan: (planId: number) => request<PlanRead>(`/api/plans/${planId}`),

  // ---- 任务 ----
  listTasks: (userId: number, status?: TaskStatus) =>
    request<TaskRead[]>(
      `/api/tasks?user_id=${userId}${status ? `&status=${status}` : ''}`,
    ),

  updateTask: (taskId: number, payload: UpdateTaskPayload) =>
    request<TaskRead>(`/api/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  listTaskProgress: (taskId: number) =>
    request<TaskProgressRead[]>(`/api/tasks/${taskId}/progress`),

  // ---- 对话 ----
  chat: (userId: number, message: string, conversationId?: number | null, enableReview = false) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        message,
        conversation_id: conversationId ?? null,
        enable_review: enableReview,
      }),
    }),

  listConversations: (userId: number, limit = 20) =>
    request<ConversationSummary[]>(`/api/chat/conversations?user_id=${userId}&limit=${limit}`),

  getConversation: (conversationId: number) =>
    request<ConversationRead>(`/api/chat/conversations/${conversationId}`),

  // ---- 提醒 ----
  listReminders: (userId: number, limit = 20) =>
    request<ReminderRead[]>(`/api/reminders?user_id=${userId}&limit=${limit}`),

  runReminders: (kind: 'daily' | 'overdue' | 'idle' | 'weekly') =>
    request<Record<string, unknown>>(`/api/reminders/run?kind=${kind}`, { method: 'POST' }),

  // ---- 看板与系统 ----
  dashboard: (userId: number) => request<DashboardRead>(`/api/dashboard?user_id=${userId}`),

  overview: () => request<OverviewRead>('/api/overview'),

  health: () => request<Record<string, unknown>>('/api/health'),

  // ---- 知识库 ----
  knowledgeStats: () => request<KnowledgeStats>('/api/knowledge/stats'),

  ingestKnowledge: (reset = false) =>
    request<KnowledgeStats>('/api/knowledge/ingest', {
      method: 'POST',
      body: JSON.stringify({ reset, use_builtin: true }),
    }),

  searchKnowledge: (query: string, topK = 5) =>
    request<KnowledgeHit[]>('/api/knowledge/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK }),
    }),
}

/** 计划中的全部任务（用于看板统计） */
export function flattenTasks(stages: StageRead[]): TaskRead[] {
  return stages.flatMap((stage) => stage.tasks)
}

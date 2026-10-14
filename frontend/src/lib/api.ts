import type {
  AgentOutput,
  ChatResponse,
  ChatTurn,
  ConversationRead,
  ConversationSummary,
  DashboardRead,
  PlanConfirmation,
  PlanRead,
  Priority,
  ProfileInput,
  ReminderRead,
  StageRead,
  TargetRead,
  TaskProgressRead,
  TaskRead,
  TaskStatus,
  TaskType,
  ToolCallRecord,
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
  title?: string
  description?: string
  status?: TaskStatus
  planned_date?: string
  duration_minutes?: number
  priority?: Priority
  slot?: string
  actual_minutes?: number
  score?: number
  note?: string
}

export interface CreateTaskPayload {
  title: string
  description?: string
  stage_name?: string
  subject?: string
  planned_date?: string
  duration_minutes?: number
  priority?: Priority
  task_type?: TaskType
  slot?: string
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
  /**
   * 计划页的「生成计划」。
   *
   * 显式关掉 `confirm_commit`：落库前的人工确认是为**对话里顺手改计划**设的闸门，
   * 而这里用户点按钮本身就是明确的确认动作，再问一遍只是把同一次同意问两次。
   */
  generatePlan: (userId: number, goal = '', enableReview = false) =>
    request<ChatResponse>('/api/plans/generate', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        goal,
        enable_review: enableReview,
        confirm_commit: false,
      }),
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

  /** 用户直接在学习计划里新增任务 */
  createTask: (planId: number, payload: CreateTaskPayload) =>
    request<TaskRead>(`/api/plans/${planId}/tasks`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteTask: (taskId: number) =>
    request<void>(`/api/tasks/${taskId}`, { method: 'DELETE' }),

  updatePlan: (planId: number, payload: { title?: string; goal?: string; strategy?: string }) =>
    request<PlanRead>(`/api/plans/${planId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

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

  /** 答复对话中被暂停的计划确认；答复后才真正落库。 */
  confirmPlan: (conversationId: number, approve: boolean, feedback = '') =>
    request<ChatResponse>('/api/chat/confirm', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: conversationId,
        approve,
        feedback,
      }),
    }),

  // ---- 提醒 ----
  listReminders: (userId: number, limit = 20) =>
    request<ReminderRead[]>(`/api/reminders?user_id=${userId}&limit=${limit}`),

  runReminders: (kind: 'daily' | 'overdue' | 'idle' | 'weekly' | 'school_brief') =>
    request<Record<string, unknown>>(`/api/reminders/run?kind=${kind}`, { method: 'POST' }),

  // ---- 看板 ----
  dashboard: (userId: number) => request<DashboardRead>(`/api/dashboard?user_id=${userId}`),

  health: () => request<Record<string, unknown>>('/api/health'),
}

/** 计划中的全部任务（用于看板统计） */
export function flattenTasks(stages: StageRead[]): TaskRead[] {
  return stages.flatMap((stage) => stage.tasks)
}

/** 把持久化的会话消息还原为对话页所需的轮次。 */
export function toTurns(detail: ConversationRead): ChatTurn[] {
  return detail.messages.map((message) => {
    const payload = message.payload as { outputs?: AgentOutput[] }
    const meta = message.meta as {
      agents?: string[]
      tool_calls?: ToolCallRecord[]
      plan_id?: number | null
      trace_url?: string | null
      pending_confirmation?: PlanConfirmation | null
    }
    return {
      role: message.role === 'user' ? 'user' : 'assistant',
      content: message.content,
      outputs: Array.isArray(payload.outputs) ? payload.outputs : [],
      toolCalls: Array.isArray(meta.tool_calls) ? meta.tool_calls : [],
      agents: meta.agents,
      planId: meta.plan_id ?? null,
      traceUrl: meta.trace_url ?? null,
      // 刷新页面后仍要把未答复的确认卡片放回去，否则用户没法回答那个待确认的计划
      confirmation: meta.pending_confirmation ?? null,
      createdAt: message.created_at,
    }
  })
}

/**
 * 与后端 `app/schemas/api.py` 保持一致的接口类型。
 * 后端字段一旦调整，这里必须同步，否则类型检查会立刻报错。
 */

export type ExamType = 'postgraduate' | 'certificate'
export type TargetStatus = 'preparing' | 'achieved' | 'abandoned'
export type PlanStatus = 'draft' | 'active' | 'completed' | 'archived'
export type TaskStatus = 'todo' | 'doing' | 'done' | 'skipped'
export type TaskType = 'learn' | 'practice' | 'review' | 'mock'
export type Priority = 'low' | 'medium' | 'high'
export type StageType = 'foundation' | 'enhancement' | 'sprint' | 'mock'
export type ReminderType = 'daily' | 'overdue' | 'idle' | 'weekly' | 'custom'
export type ReminderStatus = 'pending' | 'sent' | 'failed' | 'cancelled'

export interface ProfileInput {
  education: string
  major: string
  base_level: string
  daily_hours: number
  weekly_days: number
  attention_span: number
  self_discipline: number
  preferred_slots: string[]
  notes: string
}

export interface ProfileRead extends ProfileInput {
  id: number
  user_id: number
}

export interface UserRead {
  id: number
  username: string
  nickname: string
  email: string | null
  is_active: boolean
  timezone: string
  created_at: string
  profile: ProfileRead | null
}

export interface SubjectRead {
  id: number
  order_index: number
  name: string
  category: string
  score_weight: number
  difficulty: number
  current_level: number
  is_weak: boolean
}

export interface TargetRead {
  id: number
  user_id: number
  exam_type: ExamType
  title: string
  target_school: string
  target_major: string
  exam_date: string
  target_score: number | null
  status: TargetStatus
  is_primary: boolean
  description: string
  subjects: SubjectRead[]
}

export interface TaskRead {
  id: number
  plan_id: number
  stage_id: number | null
  subject_id: number | null
  title: string
  description: string
  task_type: TaskType
  planned_date: string
  duration_minutes: number
  priority: Priority
  status: TaskStatus
  difficulty: number
  resource_hint: string
  order_index: number
  depends_on_task_id: number | null
}

export interface StageRead {
  id: number
  plan_id: number
  name: string
  stage_type: StageType
  order_index: number
  start_date: string
  end_date: string
  focus: string
  target_hours: number
  completion_rate: number
  tasks: TaskRead[]
}

export interface PlanRead {
  id: number
  user_id: number
  target_id: number
  title: string
  goal: string
  strategy: string
  horizon_days: number
  start_date: string
  end_date: string
  total_hours: number
  status: PlanStatus
  version: number
  generated_by: string
  created_at: string
  stages: StageRead[]
}

export interface TaskProgressRead {
  id: number
  task_id: number
  status: TaskStatus
  actual_minutes: number
  completion_rate: number
  score: number | null
  note: string
  created_at: string
}

export interface ReminderRead {
  id: number
  user_id: number
  plan_id: number | null
  task_id: number | null
  reminder_type: ReminderType
  channel: string
  title: string
  content: string
  scheduled_at: string
  sent_at: string | null
  status: ReminderStatus
  retry_count: number
  created_at: string
}

export interface PlanReviewIssue {
  severity: 'low' | 'medium' | 'high'
  category: string
  detail: string
  suggestion: string
}

export interface PlanReviewResult {
  approved: boolean
  score: number
  summary: string
  issues: PlanReviewIssue[]
  improvements: string[]
  reviewer: string
}

export interface AgentOutput {
  agent: string
  name: string
  title: string
  summary: string
  highlights: string[]
  payload: Record<string, unknown>
}

export interface Reference {
  id: string
  text: string
  score: number
  source: string
  subject: string
}

/** 聊天 Agent 的一次子智能体工具调用。 */
export interface ToolCallRecord {
  name: string
  agent: string
  label: string
}

/** 计划落库前的人工确认请求。后端暂停时随 `awaiting_confirmation` 一起下发。 */
export interface PlanConfirmation {
  kind: 'plan_draft' | 'plan_revision'
  title: string
  summary: string
  items: string[]
  plan_id: number | null
  thread_id: string
}

export interface ChatResponse {
  conversation_id: number
  message_id: number | null
  agents: string[]
  tool_calls: ToolCallRecord[]
  outputs: AgentOutput[]
  reply: string
  plan_id: number | null
  plan_review: PlanReviewResult | null
  /** 非空表示本次停在确认闸门上、尚未写库。 */
  confirmation: PlanConfirmation | null
  errors: string[]
  trace_id: string | null
  trace_url: string | null
}

/** 对话页渲染用的单轮消息，由历史消息或流式结果归一化而来。 */
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  outputs: AgentOutput[]
  toolCalls?: ToolCallRecord[]
  agents?: string[]
  planId?: number | null
  traceUrl?: string | null
  /** 该轮停在计划确认上时携带待确认内容，由 `ConfirmationCard` 渲染。 */
  confirmation?: PlanConfirmation | null
  createdAt?: string
}

export interface ChatMessageRead {
  id: number
  conversation_id: number
  role: string
  agent_name: string
  content: string
  payload: Record<string, unknown>
  meta: Record<string, unknown>
  created_at: string
}

export interface ConversationSummary {
  id: number
  user_id: number
  target_id: number | null
  title: string
  workflow: string
  status: string
  message_count: number
  created_at: string
}

export interface ConversationRead extends ConversationSummary {
  messages: ChatMessageRead[]
}

export interface TaskStatsRead {
  total: number
  todo: number
  doing: number
  done: number
  overdue: number
  completion: number
}

export interface DashboardRead {
  user_id: number
  nickname: string
  target_id: number | null
  target_title: string
  exam_date: string | null
  days_left: number | null
  task_stats: TaskStatsRead
  plan_id: number | null
  plan_title: string
  plan_progress: number
  pending_reminders: number
  recent_reminders: ReminderRead[]
}

/**
 * 对话流式事件。
 *
 * `token` 与 `done` / `awaiting_confirmation` 是两条收尾路径：正常跑完发 `done`；
 * 停在计划确认闸门上时发 `awaiting_confirmation` 并就此结束，不会再有 `done`。
 */
export type StreamEvent =
  | { type: 'start'; conversation_id: number }
  | { type: 'progress'; node: string; agent?: string; status: string; detail: string }
  | { type: 'output'; output: AgentOutput }
  | { type: 'token'; text: string }
  /** 聊天 Agent 开始执行某个子智能体工具；调用链的权威来源 */
  | { type: 'tool_call'; name: string; agent: string; label: string }
  | {
      type: 'done'
      conversation_id: number
      message_id: number | null
      agents: string[]
      tool_calls: ToolCallRecord[]
      reply: string
      plan_id: number | null
      errors: string[]
      trace_id: string | null
      trace_url: string | null
    }
  | {
      type: 'awaiting_confirmation'
      conversation_id: number
      message_id: number | null
      reply: string
      agents: string[]
      tool_calls: ToolCallRecord[]
      confirmation: PlanConfirmation | null
      trace_id: string | null
      trace_url: string | null
    }
  | { type: 'error'; message: string }

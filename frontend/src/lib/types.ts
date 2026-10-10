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

export interface ChatResponse {
  conversation_id: number
  message_id: number | null
  intent: string
  agents: string[]
  outputs: AgentOutput[]
  reply: string
  plan_id: number | null
  plan_review: PlanReviewResult | null
  errors: string[]
  trace_id: string | null
  trace_url: string | null
}

/** 对话页渲染用的单轮消息，由历史消息或流式结果归一化而来。 */
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  outputs: AgentOutput[]
  intent?: string
  agents?: string[]
  planId?: number | null
  traceUrl?: string | null
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

export interface RoleInfo {
  key: string
  name: string
  mission: string
  capabilities: string[]
}

export interface PromptInfo {
  task: string
  role: string
  role_name: string
  required_variables: string[]
}

export interface WorkflowEdge {
  from: string
  to: string
  kind: string
}

export interface WorkflowInfo {
  entry: string
  nodes: string[]
  edges: WorkflowEdge[]
}

export interface ScheduleJob {
  name: string
  task: string
  schedule: string
}

export interface CapabilityInfo {
  llm_provider: string
  llm_ready: boolean
  embedding: string
  vector_backend: string
  knowledge_enabled: boolean
  crew_enabled: boolean
  reminders_enabled: boolean
}

export interface OverviewRead {
  roles: RoleInfo[]
  prompts: PromptInfo[]
  workflow: WorkflowInfo
  schedule: ScheduleJob[]
  knowledge: Record<string, unknown>
  observability: Record<string, unknown>
  capability: CapabilityInfo
}

export interface KnowledgeStats {
  backend: string
  collection: string
  embedding: string
  dimension: number
  chunks: number
}

export interface KnowledgeHit extends Reference {}

/** 对话流式事件 */
export type StreamEvent =
  | { type: 'start'; conversation_id: number }
  | { type: 'progress'; node: string; agent?: string; status: string; detail: string }
  | { type: 'output'; output: AgentOutput }
  | {
      type: 'done'
      conversation_id: number
      message_id: number | null
      intent: string
      agents: string[]
      reply: string
      plan_id: number | null
      errors: string[]
      trace_id: string | null
      trace_url: string | null
    }
  | { type: 'error'; message: string }

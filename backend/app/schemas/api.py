"""HTTP 接口的数据模型。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import (
    ExamType,
    PlanStatus,
    Priority,
    ReminderChannel,
    ReminderStatus,
    ReminderType,
    StageType,
    TargetStatus,
    TaskStatus,
    TaskType,
)
from app.schemas.review import PlanReviewResult
from app.schemas.workflow import AgentOutput, PlanConfirmation, ToolCallRecord


class ProfileInput(BaseModel):
    """学习档案输入。"""

    education: str = Field(default="", max_length=64)
    major: str = Field(default="", max_length=64)
    base_level: str = Field(default="一般", max_length=32)
    daily_hours: float = Field(default=4.0, gt=0, le=24)
    weekly_days: int = Field(default=6, ge=1, le=7)
    attention_span: int = Field(default=50, ge=10, le=240)
    self_discipline: int = Field(default=3, ge=1, le=5)
    preferred_slots: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)


class ProfileRead(ProfileInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int


class UserCreate(BaseModel):
    """创建用户。"""

    username: str = Field(min_length=2, max_length=64)
    nickname: str = Field(default="考生", max_length=64)
    email: str | None = Field(default=None, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", max_length=32)
    profile: ProfileInput | None = None


class UserUpdate(BaseModel):
    """更新用户基本信息。"""

    nickname: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    timezone: str | None = Field(default=None, max_length=32)
    profile: ProfileInput | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    email: str | None
    is_active: bool
    timezone: str
    created_at: datetime
    profile: ProfileRead | None = None


class SubjectInput(BaseModel):
    """考试科目输入。"""

    name: str = Field(min_length=1, max_length=64)
    category: str = Field(default="公共课", max_length=32)
    score_weight: float = Field(default=0.0, ge=0, le=1)
    difficulty: int = Field(default=3, ge=1, le=5)
    current_level: int = Field(default=2, ge=1, le=5)
    is_weak: bool = False


class SubjectRead(SubjectInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int = 0


class TargetCreate(BaseModel):
    """创建备考目标。"""

    user_id: int
    exam_type: ExamType = ExamType.POSTGRADUATE
    title: str = Field(min_length=1, max_length=128)
    target_school: str = Field(default="", max_length=128)
    target_major: str = Field(default="", max_length=128)
    exam_date: date
    target_score: float | None = None
    description: str = Field(default="", max_length=1000)
    subjects: list[SubjectInput] = Field(default_factory=list)
    make_primary: bool = True


class TargetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    exam_type: ExamType
    title: str
    target_school: str
    target_major: str
    exam_date: date
    target_score: float | None
    status: TargetStatus
    is_primary: bool
    description: str
    subjects: list[SubjectRead] = Field(default_factory=list)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    stage_id: int | None
    subject_id: int | None
    title: str
    description: str
    task_type: TaskType
    planned_date: date
    duration_minutes: int
    priority: Priority
    status: TaskStatus
    difficulty: int
    resource_hint: str
    order_index: int
    depends_on_task_id: int | None


class StageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    name: str
    stage_type: StageType
    order_index: int
    start_date: date
    end_date: date
    focus: str
    target_hours: float
    completion_rate: float
    tasks: list[TaskRead] = Field(default_factory=list)


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    target_id: int
    title: str
    goal: str
    strategy: str
    horizon_days: int
    start_date: date
    end_date: date
    total_hours: float
    status: PlanStatus
    version: int
    generated_by: str
    created_at: datetime
    stages: list[StageRead] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    """任务打卡与调整。"""

    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: TaskStatus | None = None
    planned_date: date | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    priority: Priority | None = None
    note: str = Field(default="", max_length=1000)
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)
    score: float | None = Field(default=None, ge=0, le=200)


class TaskCreate(BaseModel):
    """用户在学习计划里直接新增任务。"""

    title: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    stage_name: str = Field(default="", max_length=40, description="所属阶段名称，可留空")
    subject: str = Field(default="", max_length=32, description="所属科目名称，可留空")
    planned_date: date | None = Field(default=None, description="留空则落在计划开始日")
    duration_minutes: int = Field(default=60, ge=5, le=480)
    priority: Priority = Priority.MEDIUM
    task_type: TaskType = TaskType.LEARN


class PlanUpdate(BaseModel):
    """计划信息调整。"""

    title: str | None = Field(default=None, min_length=2, max_length=80)
    goal: str | None = Field(default=None, max_length=300)
    strategy: str | None = Field(default=None, max_length=600)


class TaskProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: TaskStatus
    actual_minutes: int
    completion_rate: float
    score: float | None
    note: str
    created_at: datetime


class ReminderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    plan_id: int | None
    task_id: int | None
    reminder_type: ReminderType
    channel: ReminderChannel
    title: str
    content: str
    scheduled_at: datetime
    sent_at: datetime | None
    status: ReminderStatus
    retry_count: int
    created_at: datetime


class ChatRequest(BaseModel):
    """多智能体对话请求。"""

    user_id: int
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    provider: str | None = Field(default=None, description="覆盖默认大模型提供方")
    enable_review: bool | None = Field(default=None, description="是否触发计划评审协作")
    enable_retrieval: bool | None = Field(
        default=None, description="是否启用知识库检索增强，缺省读取全局配置"
    )
    confirm_commit: bool | None = Field(
        default=None, description="计划是否等人工确认后才落库，缺省读取全局配置"
    )


class ChatConfirmRequest(BaseModel):
    """计划落库前的人工确认答复。"""

    conversation_id: int
    approve: bool = Field(description="true 则写入计划，false 则本次不写库")
    feedback: str = Field(default="", max_length=1000, description="补充意见，可留空")


class PlanGenerateRequest(BaseModel):
    """生成学习计划请求。"""

    user_id: int
    goal: str = Field(default="", max_length=500, description="补充目标描述，可留空")
    provider: str | None = None
    enable_review: bool | None = None
    confirm_commit: bool | None = Field(
        default=None, description="生成后是否等人工确认才落库，缺省读取全局配置"
    )


class ChatResponse(BaseModel):
    """多智能体对话响应。"""

    conversation_id: int
    message_id: int | None = None
    agents: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(
        default_factory=list, description="聊天 Agent 调起的子智能体工具"
    )
    outputs: list[AgentOutput] = Field(default_factory=list)
    reply: str = ""
    plan_id: int | None = None
    plan_review: PlanReviewResult | None = None
    confirmation: PlanConfirmation | None = Field(
        default=None, description="待人工确认的落库内容；非空时本次尚未写库"
    )
    errors: list[str] = Field(default_factory=list)
    trace_id: str | None = Field(default=None, description="LangFuse 追踪 ID")
    trace_url: str | None = Field(default=None, description="LangFuse 追踪链接")


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    agent_name: str
    content: str
    payload: dict
    meta: dict
    created_at: datetime


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    target_id: int | None
    title: str
    workflow: str
    status: str
    message_count: int
    created_at: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class TaskStatsRead(BaseModel):
    """任务统计。"""

    total: int = 0
    todo: int = 0
    doing: int = 0
    done: int = 0
    overdue: int = 0
    completion: float = Field(default=0.0, ge=0, le=1)


class DashboardRead(BaseModel):
    """工作台概览。"""

    user_id: int
    nickname: str
    target_id: int | None = None
    target_title: str = ""
    exam_date: date | None = None
    days_left: int | None = None
    task_stats: TaskStatsRead = Field(default_factory=TaskStatsRead)
    plan_id: int | None = None
    plan_title: str = ""
    plan_progress: float = Field(default=0.0, ge=0, le=1)
    pending_reminders: int = 0
    recent_reminders: list[ReminderRead] = Field(default_factory=list)


class RoleInfo(BaseModel):
    """智能体角色信息。"""

    key: str
    name: str
    mission: str
    capabilities: list[str] = Field(default_factory=list)


class PromptInfo(BaseModel):
    """提示词配置信息。"""

    task: str
    role: str
    role_name: str
    required_variables: list[str] = Field(default_factory=list)


class CapabilityInfo(BaseModel):
    """后端能力开关，便于前端与排障。"""

    llm_provider: str
    llm_ready: bool
    embedding: str
    vector_backend: str
    knowledge_enabled: bool
    review_enabled: bool
    reminders_enabled: bool


class OverviewRead(BaseModel):
    """系统总览：角色、提示词、工作流、定时计划与知识库状态。"""

    roles: list[RoleInfo] = Field(default_factory=list)
    prompts: list[PromptInfo] = Field(default_factory=list)
    workflow: dict = Field(default_factory=dict)
    schedule: list[dict] = Field(default_factory=list)
    knowledge: dict = Field(default_factory=dict)
    observability: dict = Field(default_factory=dict)
    capability: CapabilityInfo


class KnowledgeIngestRequest(BaseModel):
    """写入知识库请求。"""

    reset: bool = Field(default=False, description="是否先清空集合")
    use_builtin: bool = Field(default=True, description="是否写入内置语料")


class KnowledgeStatsRead(BaseModel):
    backend: str
    collection: str
    embedding: str
    dimension: int
    chunks: int


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=6, ge=1, le=30)

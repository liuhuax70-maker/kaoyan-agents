"""数据模型使用的枚举定义。"""

from enum import StrEnum


class ExamType(StrEnum):
    """备考类型。"""

    POSTGRADUATE = "postgraduate"
    """考研。"""

    CERTIFICATE = "certificate"
    """职业资格考试。"""


class TargetStatus(StrEnum):
    """备考目标状态。"""

    PREPARING = "preparing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PlanStatus(StrEnum):
    """学习计划状态。"""

    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class StageType(StrEnum):
    """阶段类型。"""

    FOUNDATION = "foundation"
    """基础夯实。"""

    ENHANCEMENT = "enhancement"
    """强化提升。"""

    SPRINT = "sprint"
    """真题冲刺。"""

    MOCK = "mock"
    """模考复盘。"""


class TaskType(StrEnum):
    """任务类型。"""

    LEARN = "learn"
    """知识点学习。"""

    PRACTICE = "practice"
    """习题训练。"""

    REVIEW = "review"
    """错题与复盘。"""

    MEMORIZE = "memorize"
    """背诵记忆。"""

    MOCK = "mock"
    """整卷模考。"""


class TaskStatus(StrEnum):
    """任务状态。"""

    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    SKIPPED = "skipped"


class Priority(StrEnum):
    """优先级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReminderType(StrEnum):
    """提醒类型。"""

    DAILY = "daily"
    """每日任务提醒。"""

    WEEKLY = "weekly"
    """周报复盘。"""

    OVERDUE = "overdue"
    """逾期催办。"""

    COUNTDOWN = "countdown"
    """考试倒计时。"""

    IDLE = "idle"
    """连续未学习预警。"""


class ReminderChannel(StrEnum):
    """提醒渠道。"""

    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


class ReminderStatus(StrEnum):
    """提醒发送状态。"""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    """会话消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

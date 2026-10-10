"""ORM 数据模型集合。

所有模型必须在此处导入，保证 Alembic 能读取到完整的 metadata。
"""

from app.db.models.conversation import AgentConversation, AgentMessage
from app.db.models.enums import (
    ExamType,
    MessageRole,
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
from app.db.models.plan import PlanStage, StudyPlan, StudyTask, TaskProgress
from app.db.models.reminder import Reminder, StudyStreak
from app.db.models.target import ExamTarget, Subject
from app.db.models.user import LearnerProfile, User

__all__ = [
    "AgentConversation",
    "AgentMessage",
    "ExamTarget",
    "ExamType",
    "LearnerProfile",
    "MessageRole",
    "PlanStage",
    "PlanStatus",
    "Priority",
    "Reminder",
    "ReminderChannel",
    "ReminderStatus",
    "ReminderType",
    "StageType",
    "StudyPlan",
    "StudyStreak",
    "StudyTask",
    "Subject",
    "TargetStatus",
    "TaskProgress",
    "TaskStatus",
    "TaskType",
    "User",
]

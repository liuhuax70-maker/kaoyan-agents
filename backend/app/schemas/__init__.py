"""智能体输入快照与结构化输出模型。"""

from app.schemas.common import (
    LearnerSnapshot,
    PlanSnapshot,
    ProgressSnapshot,
    ReminderSnapshot,
    SubjectSnapshot,
    TaskSnapshot,
)
from app.schemas.diagnosis import DiagnosisReport, RiskItem
from app.schemas.nudge import NudgeMessage, WeeklyDigest
from app.schemas.plan import PlanDraft, StageDraft, TaskBreakdown, TaskDraft
from app.schemas.resource import ResourceItem, ResourcePlan
from app.schemas.review import PlanReviewIssue, PlanReviewResult
from app.schemas.routing import IntentDecision
from app.schemas.tutoring import TutoringAnswer

__all__ = [
    "DiagnosisReport",
    "IntentDecision",
    "LearnerSnapshot",
    "NudgeMessage",
    "PlanDraft",
    "PlanReviewIssue",
    "PlanReviewResult",
    "PlanSnapshot",
    "ProgressSnapshot",
    "ReminderSnapshot",
    "ResourceItem",
    "ResourcePlan",
    "RiskItem",
    "StageDraft",
    "SubjectSnapshot",
    "TaskBreakdown",
    "TaskDraft",
    "TaskSnapshot",
    "TutoringAnswer",
    "WeeklyDigest",
]

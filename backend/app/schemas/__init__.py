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
from app.schemas.revision import PlanRevision, PlanRevisionOp, RevisionAction
from app.schemas.school import (
    SchoolAdvisorAnswer,
    SchoolBrief,
    SchoolCandidate,
    TrackedSchoolSnapshot,
)
from app.schemas.subagent import SubagentReply, envelope_for
from app.schemas.tutoring import TutoringAnswer

__all__ = [
    "DiagnosisReport",
    "LearnerSnapshot",
    "NudgeMessage",
    "PlanDraft",
    "PlanReviewIssue",
    "PlanReviewResult",
    "PlanRevision",
    "PlanRevisionOp",
    "PlanSnapshot",
    "ProgressSnapshot",
    "ReminderSnapshot",
    "ResourceItem",
    "ResourcePlan",
    "RevisionAction",
    "RiskItem",
    "SchoolAdvisorAnswer",
    "SchoolBrief",
    "SchoolCandidate",
    "StageDraft",
    "SubagentReply",
    "SubjectSnapshot",
    "TaskBreakdown",
    "TaskDraft",
    "TaskSnapshot",
    "TrackedSchoolSnapshot",
    "TutoringAnswer",
    "WeeklyDigest",
    "envelope_for",
]

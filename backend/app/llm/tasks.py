"""智能体任务定义。

任务标识是提示词、结构化输出 Schema 与离线桩之间的契约：
新增任务时只需在此登记，提示词与桩实现会同步约束。
"""

from enum import StrEnum

from pydantic import BaseModel

from app.schemas import (
    ChatSummary,
    DiagnosisReport,
    IntentDecision,
    NudgeMessage,
    PlanDraft,
    PlanReviewResult,
    PlanRevision,
    ResourcePlan,
    TaskBreakdown,
    TutoringAnswer,
    WeeklyDigest,
)


class AgentTask(StrEnum):
    """系统内的全部模型调用任务。"""

    INTENT_ROUTING = "intent_routing"
    PLAN_DRAFT = "plan_draft"
    TASK_BREAKDOWN = "task_breakdown"
    TUTORING = "tutoring"
    DIAGNOSIS = "diagnosis"
    RESOURCE_PLAN = "resource_plan"
    NUDGE = "nudge"
    WEEKLY_DIGEST = "weekly_digest"
    PLAN_REVIEW = "plan_review"
    PLAN_REVISION = "plan_revision"
    CHAT_SUMMARY = "chat_summary"


TASK_SCHEMAS: dict[AgentTask, type[BaseModel]] = {
    AgentTask.INTENT_ROUTING: IntentDecision,
    AgentTask.PLAN_DRAFT: PlanDraft,
    AgentTask.TASK_BREAKDOWN: TaskBreakdown,
    AgentTask.TUTORING: TutoringAnswer,
    AgentTask.DIAGNOSIS: DiagnosisReport,
    AgentTask.RESOURCE_PLAN: ResourcePlan,
    AgentTask.NUDGE: NudgeMessage,
    AgentTask.WEEKLY_DIGEST: WeeklyDigest,
    AgentTask.PLAN_REVIEW: PlanReviewResult,
    AgentTask.PLAN_REVISION: PlanRevision,
    AgentTask.CHAT_SUMMARY: ChatSummary,
}


def schema_for(task: AgentTask) -> type[BaseModel]:
    """返回任务对应的结构化输出模型。"""

    try:
        return TASK_SCHEMAS[task]
    except KeyError as exc:  # pragma: no cover - 仅在登记遗漏时触发
        raise KeyError(f"任务 {task} 未登记结构化输出模型") from exc

"""智能体任务定义。

任务标识是提示词、结构化输出 Schema 与假模型之间的契约：
新增任务时只需在此登记，提示词与测试夹具会同步约束。
"""

from enum import StrEnum

from pydantic import BaseModel

from app.schemas import (
    DiagnosisReport,
    NudgeMessage,
    PlanDraft,
    PlanReviewResult,
    PlanRevision,
    ResourcePlan,
    SchoolAdvisorAnswer,
    SchoolBrief,
    SubagentReply,
    TaskBreakdown,
    TutoringAnswer,
    WeeklyDigest,
    envelope_for,
)


class AgentTask(StrEnum):
    """系统内的全部模型调用任务。"""

    PLAN_DRAFT = "plan_draft"
    TASK_BREAKDOWN = "task_breakdown"
    TUTORING = "tutoring"
    DIAGNOSIS = "diagnosis"
    RESOURCE_PLAN = "resource_plan"
    NUDGE = "nudge"
    WEEKLY_DIGEST = "weekly_digest"
    PLAN_REVIEW = "plan_review"
    PLAN_REVISION = "plan_revision"
    SCHOOL_ADVISOR = "school_advisor"
    SCHOOL_BRIEF = "school_brief"


TASK_SCHEMAS: dict[AgentTask, type[BaseModel]] = {
    AgentTask.PLAN_DRAFT: PlanDraft,
    AgentTask.TASK_BREAKDOWN: TaskBreakdown,
    AgentTask.TUTORING: TutoringAnswer,
    AgentTask.DIAGNOSIS: DiagnosisReport,
    AgentTask.RESOURCE_PLAN: ResourcePlan,
    AgentTask.NUDGE: NudgeMessage,
    AgentTask.WEEKLY_DIGEST: WeeklyDigest,
    AgentTask.PLAN_REVIEW: PlanReviewResult,
    AgentTask.PLAN_REVISION: PlanRevision,
    AgentTask.SCHOOL_ADVISOR: SchoolAdvisorAnswer,
    AgentTask.SCHOOL_BRIEF: SchoolBrief,
}


SUBAGENT_TASKS: frozenset[AgentTask] = frozenset(
    {
        AgentTask.PLAN_DRAFT,
        AgentTask.TASK_BREAKDOWN,
        AgentTask.TUTORING,
        AgentTask.DIAGNOSIS,
        AgentTask.RESOURCE_PLAN,
        AgentTask.NUDGE,
        AgentTask.PLAN_REVISION,
        AgentTask.SCHOOL_ADVISOR,
    }
)
"""由聊天 Agent 通过工具调起的任务，与 ``agents/tools.py`` 的八个工具一一对应。

``SCHOOL_BRIEF`` 刻意**不在**此列：它与 ``WEEKLY_DIGEST`` 同形，只由 Celery 定时任务
消费，只要结构化数据、不要面向用户的正文通道，套上信封反而多解析一层。

这些任务走双轨产出：同一次调用既给出面向用户的正文，也给出结构化产物。
图节点任务（如计划评审）不在此列——它们的产出由节点自己渲染，不需要正文通道。
"""


def schema_for(task: AgentTask) -> type[BaseModel]:
    """返回任务对应的业务结构化输出模型。"""

    try:
        return TASK_SCHEMAS[task]
    except KeyError as exc:  # pragma: no cover - 仅在登记遗漏时触发
        raise KeyError(f"任务 {task} 未登记结构化输出模型") from exc


# 知识点：提示词契约与解析契约同源 —— 输出结构只登记一处，模板渲染与结果解析
#   都从这里取，格式与解析逻辑不可能各自漂移（第2章 LangChain核心组件·结构化输出）
def output_model_for(task: AgentTask) -> type[BaseModel]:
    """返回任务在提示词与解析阶段实际使用的输出模型。

    子智能体任务在外面套一层双轨信封，其余任务直接用业务 Schema。
    提示词渲染与结果解析都走这个函数，因此「模型被要求的格式」与
    「代码按什么格式解析」不可能不同步。
    """

    schema = schema_for(task)
    if task in SUBAGENT_TASKS:
        return envelope_for(schema)
    return schema


__all__ = [
    "SUBAGENT_TASKS",
    "TASK_SCHEMAS",
    "AgentTask",
    "SubagentReply",
    "output_model_for",
    "schema_for",
]
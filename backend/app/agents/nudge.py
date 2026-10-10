"""督促提醒与周报的单智能体能力。

工作流节点与 Celery 定时任务都需要生成督促文案，
因此抽成独立能力层，避免两处重复维护提示词与离线上下文。
"""

from typing import Any

from app.llm import AgentTask, invoke_agent_task
from app.prompts import build_messages, render_learner, render_plan, render_reminder
from app.schemas import (
    LearnerSnapshot,
    NudgeMessage,
    PlanSnapshot,
    ReminderSnapshot,
    WeeklyDigest,
)


def nudge_stub_context(
    learner: LearnerSnapshot, reminder: ReminderSnapshot
) -> dict[str, Any]:
    """离线桩生成督促文案所需的上下文。"""

    return {
        "self_discipline": learner.self_discipline,
        "days_left": learner.days_left,
        "idle_days": reminder.idle_days,
        "due_tasks": list(reminder.due_tasks),
        "overdue_tasks": list(reminder.overdue_tasks),
        "completion_rate": reminder.completion_rate,
    }


def digest_stub_context(learner: LearnerSnapshot) -> dict[str, Any]:
    """离线桩生成周报所需的上下文。"""

    progress = learner.progress
    return {
        "completion_rate": progress.completion_rate,
        "done_tasks": progress.done_tasks,
        "total_tasks": progress.total_tasks,
        "recent_minutes": progress.recent_minutes,
    }


async def compose_nudge(
    learner: LearnerSnapshot,
    reminder: ReminderSnapshot,
    provider: str | None = None,
) -> NudgeMessage:
    """生成一条有分寸的督促提醒。"""

    messages = build_messages(
        AgentTask.NUDGE,
        learner_context=render_learner(learner),
        reminder_context=render_reminder(reminder),
    )
    return await invoke_agent_task(
        AgentTask.NUDGE.value,
        messages,
        NudgeMessage,
        provider=provider,
        stub_context=nudge_stub_context(learner, reminder),
    )


async def compose_weekly_digest(
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    provider: str | None = None,
) -> WeeklyDigest:
    """生成一周学习复盘。"""

    messages = build_messages(
        AgentTask.WEEKLY_DIGEST,
        learner_context=render_learner(learner),
        plan_context=render_plan(plan),
    )
    return await invoke_agent_task(
        AgentTask.WEEKLY_DIGEST.value,
        messages,
        WeeklyDigest,
        provider=provider,
        stub_context=digest_stub_context(learner),
    )

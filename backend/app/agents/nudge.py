"""督促提醒与周报的单智能体能力。

工作流节点与 Celery 定时任务都需要生成督促文案，
因此抽成独立能力层，避免两处重复维护提示词。

同一个 NUDGE 任务有两种消费方式：聊天 Agent 派发时既要正文也要结构化数据，
定时提醒只需要结构化的 ``NudgeMessage``。因此以 ``compose_nudge_reply`` 为主实现，
``compose_nudge`` 只是丢掉正文的薄封装。
"""

# 知识点：结构化输出的双轨信封 —— 同一个任务被两条链路消费时，主实现产出「正文 + 数据」，
#   只取数据的调用方做一次解包，避免为两条链路各写一套提示词（第2章 LangChain核心组件·结构化输出）
from app.llm import AgentTask, invoke_agent_task, invoke_subagent_task
from app.prompts import build_messages, render_learner, render_plan, render_reminder
from app.schemas import LearnerSnapshot, NudgeMessage, PlanSnapshot, ReminderSnapshot, WeeklyDigest


async def compose_nudge_reply(
    learner: LearnerSnapshot,
    reminder: ReminderSnapshot,
    provider: str | None = None,
) -> tuple[str, NudgeMessage]:
    """生成督促提醒，返回 ``(面向用户的正文, 结构化提醒)``。"""

    messages = build_messages(
        AgentTask.NUDGE,
        learner_context=render_learner(learner),
        reminder_context=render_reminder(reminder),
    )
    return await invoke_subagent_task(AgentTask.NUDGE, messages, NudgeMessage, provider=provider)


async def compose_nudge(
    learner: LearnerSnapshot,
    reminder: ReminderSnapshot,
    provider: str | None = None,
) -> NudgeMessage:
    """生成一条有分寸的督促提醒（定时提醒链路，只要结构化结果）。"""

    _, message = await compose_nudge_reply(learner, reminder, provider)
    return message


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
        AgentTask.WEEKLY_DIGEST.value, messages, WeeklyDigest, provider=provider
    )
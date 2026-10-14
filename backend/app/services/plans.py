"""把智能体产出的计划草稿落库。

草稿中的日期使用相对天数（day_offset），由这里换算成真实日期：
让模型专注于「几天做什么」，日期计算交给确定性代码，避免模型算错日期。
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.timeutil import utc_today
from app.db.models import (
    LearnerProfile,
    PlanStage,
    PlanStatus,
    StudyPlan,
    StudyTask,
    Subject,
    TaskStatus,
)
from app.schemas import PlanDraft
from app.services.scheduling import DEFAULT_ATTENTION_SPAN, assign_slots

logger = get_logger(__name__)


async def persist_plan_draft(
    session: AsyncSession,
    *,
    user_id: int,
    target_id: int,
    draft: PlanDraft,
    generated_by: str = "plan_generation",
    today: date | None = None,
) -> StudyPlan:
    """把计划草稿写入数据库，返回已 flush 的计划对象。"""

    start = today or utc_today()
    horizon = max(draft.horizon_days, 1)

    await _archive_active_plans(session, user_id=user_id, target_id=target_id)
    version = await _next_version(session, user_id=user_id, target_id=target_id)

    plan = StudyPlan(
        user_id=user_id,
        target_id=target_id,
        title=draft.title,
        goal=draft.goal,
        strategy=draft.strategy,
        horizon_days=horizon,
        start_date=start,
        end_date=start + timedelta(days=horizon),
        total_hours=round(sum(stage.target_hours for stage in draft.stages), 1),
        status=PlanStatus.ACTIVE,
        version=version,
        generated_by=generated_by,
        meta={"notes": draft.notes, "daily_hours": draft.daily_hours},
    )
    session.add(plan)
    await session.flush()

    subjects = await _subject_index(session, target_id)
    preferred, attention_span = await _slot_preferences(session, user_id)
    task_count = 0

    for index, stage_draft in enumerate(draft.stages):
        stage = PlanStage(
            plan_id=plan.id,
            name=stage_draft.name,
            stage_type=stage_draft.stage_type,
            order_index=index,
            start_date=start + timedelta(days=stage_draft.start_offset),
            end_date=start + timedelta(days=stage_draft.end_offset),
            focus=stage_draft.focus,
            target_hours=stage_draft.target_hours,
        )
        session.add(stage)
        await session.flush()

        ordered = sorted(stage_draft.tasks, key=lambda item: (item.day_offset, item.title))
        # 时段在落库前补齐：模型留空的按用户偏好做水线填充，模型给了的就照用
        assign_slots(ordered, preferred, attention_span=attention_span)
        created: list[StudyTask] = []

        for order, task_draft in enumerate(ordered):
            task = StudyTask(
                plan_id=plan.id,
                stage_id=stage.id,
                subject_id=subjects.get(task_draft.subject),
                user_id=user_id,
                title=task_draft.title,
                description=task_draft.description,
                task_type=task_draft.task_type,
                planned_date=start + timedelta(days=task_draft.day_offset),
                duration_minutes=task_draft.duration_minutes,
                priority=task_draft.priority,
                status=TaskStatus.TODO,
                difficulty=task_draft.difficulty,
                resource_hint=task_draft.resource_hint,
                order_index=order,
                slot=task_draft.slot,
            )
            session.add(task)
            created.append(task)

        await session.flush()

        # 前置依赖需要等任务拿到主键后再回填
        for order, task_draft in enumerate(ordered):
            index_ref = task_draft.depends_on_index
            if index_ref is not None and 0 <= index_ref < order:
                created[order].depends_on_task_id = created[index_ref].id

        task_count += len(created)

    await session.flush()
    logger.info(
        "计划已落库 plan_id=%s，阶段 %d 个，任务 %d 个",
        plan.id,
        len(draft.stages),
        task_count,
    )
    return plan


async def _archive_active_plans(
    session: AsyncSession, *, user_id: int, target_id: int
) -> int:
    """归档同一目标下仍在生效的旧计划。

    重新规划意味着旧计划作废。若不归档，同一目标会同时存在多个 ACTIVE 计划，
    进度统计会把已作废任务一并计入，完成度被稀释。
    """

    previous = list(
        await session.scalars(
            select(StudyPlan).where(
                StudyPlan.user_id == user_id,
                StudyPlan.target_id == target_id,
                StudyPlan.status == PlanStatus.ACTIVE,
            )
        )
    )
    for item in previous:
        item.status = PlanStatus.ARCHIVED

    if previous:
        await session.flush()
        logger.info(
            "已归档 %d 个旧计划（user=%s target=%s）", len(previous), user_id, target_id
        )
    return len(previous)


async def _next_version(session: AsyncSession, *, user_id: int, target_id: int) -> int:
    """返回该目标下计划的下一个版本号。"""

    latest = await session.scalar(
        select(func.max(StudyPlan.version)).where(
            StudyPlan.user_id == user_id, StudyPlan.target_id == target_id
        )
    )
    return int(latest or 0) + 1


async def _subject_index(session: AsyncSession, target_id: int) -> dict[str, int]:
    """返回科目名称到主键的映射。"""

    rows = await session.execute(
        select(Subject.name, Subject.id).where(Subject.target_id == target_id)
    )
    return dict(rows.all())


async def _slot_preferences(session: AsyncSession, user_id: int) -> tuple[list[str], int]:
    """读取用户的偏好时段与单次专注时长，供时段分配使用。

    刻意在这里按 ``user_id`` 现查一次，而不是把 learner 穿进 ``CommitContext``：
    那个结构在「恢复人工确认」的路径上拿不到 learner，塞进去等于让它携带一个假值，
    而假值造成的错误是静默的。
    """

    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.user_id == user_id)
    )
    if profile is None:
        return [], DEFAULT_ATTENTION_SPAN
    return list(profile.preferred_slots or []), profile.attention_span

"""进度跟踪服务：打卡记录与完成度刷新。

打卡不只是改一个状态字段：
- 写入 TaskProgress 保留历史（用于复盘与时长统计）；
- 刷新阶段完成度；
- 更新连续学习统计（用于断签预警与督促）。
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.timeutil import utc_now, utc_today
from app.db.models import PlanStage, StudyStreak, StudyTask, TaskProgress, TaskStatus

logger = get_logger(__name__)


async def record_check_in(
    session: AsyncSession,
    task: StudyTask,
    *,
    status: TaskStatus,
    actual_minutes: int = 0,
    completion_rate: float | None = None,
    score: float | None = None,
    note: str = "",
) -> TaskProgress:
    """记录一次打卡。"""

    if completion_rate is None:
        completion_rate = 1.0 if status == TaskStatus.DONE else 0.5

    progress = TaskProgress(
        task_id=task.id,
        user_id=task.user_id,
        status=status,
        actual_minutes=actual_minutes,
        completion_rate=completion_rate,
        score=score,
        note=note,
        started_at=utc_now(),
        finished_at=utc_now() if status == TaskStatus.DONE else None,
    )
    session.add(progress)

    task.status = status
    await session.flush()

    await refresh_stage_completion(session, task.plan_id)

    if status == TaskStatus.DONE:
        await touch_streak(session, task.user_id, minutes=actual_minutes)

    return progress


async def refresh_stage_completion(session: AsyncSession, plan_id: int) -> None:
    """按任务完成情况刷新各阶段完成度。"""

    stages = list(await session.scalars(select(PlanStage).where(PlanStage.plan_id == plan_id)))
    rows = (
        await session.execute(
            select(StudyTask.stage_id, StudyTask.status).where(StudyTask.plan_id == plan_id)
        )
    ).all()

    grouped: dict[int | None, list[TaskStatus]] = {}
    for stage_id, status in rows:
        grouped.setdefault(stage_id, []).append(status)

    for stage in stages:
        statuses = grouped.get(stage.id) or []
        if not statuses:
            continue
        done = sum(1 for item in statuses if item == TaskStatus.DONE)
        stage.completion_rate = round(done / len(statuses), 4)

    await session.flush()


def _as_date(value: datetime | date | None) -> date | None:
    """把可能带时间的字段统一成日期。"""

    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


async def touch_streak(
    session: AsyncSession,
    user_id: int,
    *,
    minutes: int = 0,
    today: date | None = None,
) -> StudyStreak:
    """更新连续学习统计。

    规则：同一天重复打卡不重复计数；昨天学过则累加；否则重新从 1 开始。
    """

    reference = today or utc_today()
    streak = await session.scalar(select(StudyStreak).where(StudyStreak.user_id == user_id))
    if streak is None:
        streak = StudyStreak(user_id=user_id, current_streak=0, longest_streak=0, total_days=0)
        session.add(streak)
        await session.flush()

    last_date = _as_date(streak.last_study_date)

    if last_date == reference:
        pass
    elif last_date is not None and (reference - last_date).days == 1:
        streak.current_streak += 1
        streak.total_days += 1
    else:
        streak.current_streak = 1
        streak.total_days += 1

    streak.longest_streak = max(streak.longest_streak, streak.current_streak)
    streak.total_minutes += max(minutes, 0)
    streak.last_study_date = utc_now()
    streak.last_check_date = utc_now()

    await session.flush()
    logger.info(
        "更新连续学习 user=%s current=%d longest=%d",
        user_id,
        streak.current_streak,
        streak.longest_streak,
    )
    return streak

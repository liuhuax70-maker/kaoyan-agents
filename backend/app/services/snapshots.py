"""从数据库构建智能体所需的快照。

智能体只依赖快照而非 ORM：这样提示词与工作流可以脱离数据库单测，
表结构调整也不会渗透进智能体逻辑。
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.timeutil import days_ago, utc_today
from app.db.models import (
    ExamTarget,
    StudyPlan,
    StudyStreak,
    StudyTask,
    TargetStatus,
    TaskProgress,
    TaskStatus,
    User,
)
from app.schemas import (
    LearnerSnapshot,
    PlanSnapshot,
    ProgressSnapshot,
    SubjectSnapshot,
    TaskSnapshot,
)

RECENT_WINDOW_DAYS = 7
ACTIVE_TASK_STATES = (TaskStatus.TODO, TaskStatus.DOING)


async def load_primary_target(session: AsyncSession, user_id: int) -> ExamTarget | None:
    """返回用户的主备考目标：优先主目标，其次最早创建的那个。"""

    statement = (
        select(ExamTarget)
        .where(ExamTarget.user_id == user_id, ExamTarget.status == TargetStatus.PREPARING)
        .order_by(ExamTarget.is_primary.desc(), ExamTarget.id.asc())
        .limit(1)
    )
    return await session.scalar(statement)


async def collect_progress(
    session: AsyncSession,
    user_id: int,
    *,
    today: date | None = None,
) -> ProgressSnapshot:
    """统计任务完成度、近 7 天学习时长与连续学习情况。"""

    reference = today or utc_today()

    rows = (
        await session.execute(
            select(StudyTask.status, StudyTask.planned_date).where(StudyTask.user_id == user_id)
        )
    ).all()

    total = len(rows)
    done = sum(1 for status, _ in rows if status == TaskStatus.DONE)
    doing = sum(1 for status, _ in rows if status == TaskStatus.DOING)
    overdue = sum(
        1
        for status, planned in rows
        if status in ACTIVE_TASK_STATES and planned is not None and planned < reference
    )

    recent_minutes = await session.scalar(
        select(func.coalesce(func.sum(TaskProgress.actual_minutes), 0)).where(
            TaskProgress.user_id == user_id,
            TaskProgress.created_at >= days_ago(RECENT_WINDOW_DAYS),
        )
    )

    streak = await session.scalar(select(StudyStreak).where(StudyStreak.user_id == user_id))

    return ProgressSnapshot(
        total_tasks=total,
        done_tasks=done,
        doing_tasks=doing,
        overdue_tasks=overdue,
        completion_rate=round(done / total, 4) if total else 0.0,
        recent_minutes=int(recent_minutes or 0),
        current_streak=streak.current_streak if streak else 0,
        longest_streak=streak.longest_streak if streak else 0,
        idle_days=_idle_days(streak, reference),
    )


def _idle_days(streak: StudyStreak | None, reference: date) -> int:
    """计算连续未学习天数。"""

    if streak is None or streak.last_study_date is None:
        return 0
    last_study = streak.last_study_date
    last_date = last_study.date() if hasattr(last_study, "date") else last_study
    return max((reference - last_date).days, 0)


async def load_learner_snapshot(
    session: AsyncSession,
    user_id: int,
    *,
    today: date | None = None,
) -> LearnerSnapshot | None:
    """构建考生完整画像。"""

    reference = today or utc_today()
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        return None

    target = await load_primary_target(session, user_id)
    profile = user.profile
    progress = await collect_progress(session, user_id, today=reference)

    return LearnerSnapshot(
        nickname=user.nickname or user.username,
        exam_type=target.exam_type.value if target else "postgraduate",
        target_title=target.title if target else "",
        target_school=target.target_school if target else "",
        target_major=target.target_major if target else "",
        exam_date=target.exam_date if target else None,
        days_left=(target.exam_date - reference).days if target else None,
        base_level=profile.base_level if profile else "一般",
        daily_hours=profile.daily_hours if profile else 4.0,
        weekly_days=profile.weekly_days if profile else 6,
        attention_span=profile.attention_span if profile else 50,
        self_discipline=profile.self_discipline if profile else 3,
        preferred_slots=list(profile.preferred_slots) if profile else [],
        notes=profile.notes if profile else "",
        subjects=[
            SubjectSnapshot(
                name=item.name,
                category=item.category,
                score_weight=item.score_weight,
                difficulty=item.difficulty,
                current_level=item.current_level,
                is_weak=item.is_weak,
            )
            for item in (target.subjects if target else [])
        ],
        progress=progress,
    )


def _task_snapshot(task: StudyTask) -> TaskSnapshot:
    """把任务 ORM 转为快照。"""

    return TaskSnapshot(
        id=task.id,
        title=task.title,
        subject=task.subject.name if task.subject else "",
        stage=task.stage.name if task.stage else "",
        task_type=task.task_type.value,
        planned_date=task.planned_date,
        duration_minutes=task.duration_minutes,
        priority=task.priority.value,
        status=task.status.value,
    )


async def load_plan_snapshot(session: AsyncSession, plan_id: int) -> PlanSnapshot | None:
    """构建计划快照，含任务明细。"""

    plan = await session.scalar(select(StudyPlan).where(StudyPlan.id == plan_id))
    if plan is None:
        return None

    tasks = list(
        await session.scalars(
            select(StudyTask)
            .where(StudyTask.plan_id == plan_id)
            .options(selectinload(StudyTask.subject), selectinload(StudyTask.stage))
            .order_by(StudyTask.planned_date, StudyTask.order_index, StudyTask.id)
        )
    )

    return PlanSnapshot(
        id=plan.id,
        title=plan.title,
        goal=plan.goal,
        status=plan.status.value,
        start_date=plan.start_date,
        end_date=plan.end_date,
        horizon_days=plan.horizon_days,
        tasks=[_task_snapshot(task) for task in tasks],
    )


async def load_latest_plan_snapshot(
    session: AsyncSession,
    user_id: int,
) -> PlanSnapshot | None:
    """构建用户最新计划的快照。"""

    plan_id = await session.scalar(
        select(StudyPlan.id)
        .where(StudyPlan.user_id == user_id)
        .order_by(StudyPlan.id.desc())
        .limit(1)
    )
    if plan_id is None:
        return None
    return await load_plan_snapshot(session, plan_id)


async def collect_user_tasks(
    session: AsyncSession,
    user_id: int,
    *,
    today: date | None = None,
) -> tuple[list[StudyTask], list[StudyTask]]:
    """返回 (今日待完成, 已逾期) 两组任务。"""

    reference = today or utc_today()
    tasks = list(
        await session.scalars(
            select(StudyTask)
            .where(StudyTask.user_id == user_id, StudyTask.status.in_(ACTIVE_TASK_STATES))
            .order_by(StudyTask.planned_date, StudyTask.order_index, StudyTask.id)
        )
    )

    due = [task for task in tasks if task.planned_date == reference]
    overdue = [
        task for task in tasks if task.planned_date is not None and task.planned_date < reference
    ]
    return due, overdue


async def active_user_ids(session: AsyncSession) -> list[int]:
    """返回存在进行中备考目标的用户 ID。"""

    rows = await session.scalars(
        select(ExamTarget.user_id)
        .where(ExamTarget.status == TargetStatus.PREPARING)
        .distinct()
        .order_by(ExamTarget.user_id)
    )
    return [int(value) for value in rows]

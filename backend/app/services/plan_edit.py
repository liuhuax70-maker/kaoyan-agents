"""计划表编辑。

两个入口共用这一套底层能力：

- **聊天 Agent**：``revise_plan`` 工具产出修订提案，对话结束后由
  :func:`apply_plan_revision` 统一落库。图谱本身不碰数据库。
- **用户直接编辑**：前端计划看板调用 :func:`create_task` /
  :func:`update_task_fields` / :func:`delete_task` / :func:`update_plan_fields`。

无论走哪条路，改动都会刷新阶段完成度，保证看板与统计口径一致。
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import (
    PlanStage,
    Priority,
    StudyPlan,
    StudyTask,
    Subject,
    TaskStatus,
    TaskType,
)
from app.schemas import PlanRevision, PlanRevisionOp, RevisionAction
from app.services.progress import refresh_stage_completion

logger = get_logger(__name__)

TITLE_MATCH_MIN = 2
"""标题模糊匹配的最短长度，太短容易误伤。"""

PENDING_STATES = (TaskStatus.TODO, TaskStatus.DOING)


@dataclass(slots=True)
class RevisionOutcome:
    """计划修订的执行结果。"""

    applied: int = 0
    skipped: int = 0
    details: list[str] = field(default_factory=list)

    def note(self, message: str, *, ok: bool = True) -> None:
        """记录一条执行说明。"""

        if ok:
            self.applied += 1
        else:
            self.skipped += 1
        self.details.append(message)


async def load_plan(session: AsyncSession, plan_id: int) -> StudyPlan | None:
    """读取计划（阶段与任务会随关系自动加载）。"""

    return await session.scalar(select(StudyPlan).where(StudyPlan.id == plan_id))


async def _find_subject(session: AsyncSession, target_id: int, name: str) -> Subject | None:
    """按名称取科目对象；名称留空或对不上时返回 ``None``。"""

    needle = name.strip()
    if not needle:
        return None
    return await session.scalar(
        select(Subject).where(Subject.target_id == target_id, Subject.name == needle)
    )


def match_task(plan: StudyPlan, title: str) -> StudyTask | None:
    """按标题片段定位任务：先精确匹配，再退化为包含匹配。"""

    needle = title.strip()
    if len(needle) < TITLE_MATCH_MIN:
        return None
    for task in plan.tasks:
        if task.title == needle:
            return task
    for task in plan.tasks:
        if needle in task.title or task.title in needle:
            return task
    return None


def match_stage(plan: StudyPlan, name: str) -> PlanStage | None:
    """按名称片段定位阶段，未指定或找不到时退回第一个阶段。"""

    needle = name.strip()
    if needle:
        for stage in plan.stages:
            if needle in stage.name or stage.name in needle:
                return stage
    return plan.stages[0] if plan.stages else None


async def create_task(
    session: AsyncSession,
    *,
    plan: StudyPlan,
    title: str,
    description: str = "",
    stage_name: str = "",
    subject: str = "",
    planned_date: date | None = None,
    duration_minutes: int = 60,
    priority: Priority = Priority.MEDIUM,
    task_type: TaskType = TaskType.LEARN,
    slot: str | None = None,
) -> StudyTask:
    """在计划中新增一个任务。"""

    stage = match_stage(plan, stage_name)
    subject_row = await _find_subject(session, plan.target_id, subject)
    resolved_date = planned_date or plan.start_date

    same_day = await session.scalar(
        select(func.count())
        .select_from(StudyTask)
        .where(StudyTask.plan_id == plan.id, StudyTask.planned_date == resolved_date)
    )

    task = StudyTask(
        plan_id=plan.id,
        stage_id=stage.id if stage else None,
        # 直接挂对象而不是写 subject_id：这样新建出来的任务立刻就有科目名，
        # 接口返回时不必为了一行响应再查一次
        subject=subject_row,
        user_id=plan.user_id,
        title=title.strip(),
        description=description.strip(),
        task_type=task_type,
        planned_date=resolved_date,
        duration_minutes=duration_minutes,
        priority=priority,
        status=TaskStatus.TODO,
        order_index=int(same_day or 0),
        slot=slot,
    )
    session.add(task)
    await session.flush()
    await refresh_stage_completion(session, plan.id)
    logger.info("新增任务 plan=%s task=%s", plan.id, task.id)
    return task


async def update_task_fields(
    session: AsyncSession,
    *,
    task: StudyTask,
    title: str | None = None,
    description: str | None = None,
    planned_date: date | None = None,
    duration_minutes: int | None = None,
    priority: Priority | None = None,
    status: TaskStatus | None = None,
) -> StudyTask:
    """按传入的非空字段更新任务，未传入的字段保持不变。"""

    if title is not None:
        task.title = title.strip()
    if description is not None:
        task.description = description.strip()
    if planned_date is not None:
        task.planned_date = planned_date
    if duration_minutes is not None:
        task.duration_minutes = duration_minutes
    if priority is not None:
        task.priority = priority
    if status is not None:
        task.status = status

    await session.flush()
    await refresh_stage_completion(session, task.plan_id)
    return task


async def delete_task(session: AsyncSession, task: StudyTask) -> None:
    """删除任务并刷新阶段完成度。"""

    plan_id = task.plan_id
    await session.delete(task)
    await session.flush()
    await refresh_stage_completion(session, plan_id)
    logger.info("删除任务 plan=%s task=%s", plan_id, task.id)


async def reschedule_pending_tasks(
    session: AsyncSession, *, plan: StudyPlan, shift_days: int
) -> int:
    """把未完成任务的计划日期整体平移。"""

    if shift_days == 0:
        return 0

    moved = 0
    for task in plan.tasks:
        if task.status in PENDING_STATES:
            task.planned_date = task.planned_date + timedelta(days=shift_days)
            moved += 1

    if moved:
        await session.flush()
    return moved


async def update_plan_fields(
    session: AsyncSession,
    *,
    plan: StudyPlan,
    title: str | None = None,
    goal: str | None = None,
    strategy: str | None = None,
) -> StudyPlan:
    """更新计划标题、目标与策略。"""

    if title is not None and title.strip():
        plan.title = title.strip()
    if goal is not None and goal.strip():
        plan.goal = goal.strip()
    if strategy is not None and strategy.strip():
        plan.strategy = strategy.strip()

    await session.flush()
    return plan


def _resolve_date(plan: StudyPlan, op: PlanRevisionOp) -> date:
    """把相对天数换算成绝对日期。"""

    return plan.start_date + timedelta(days=max(op.day_offset, 0))


async def _apply_op(
    session: AsyncSession, plan: StudyPlan, op: PlanRevisionOp
) -> tuple[str, bool]:
    """执行单条修订操作，返回说明与是否生效。"""

    if op.action is RevisionAction.ADD_TASK:
        if not op.title.strip():
            return "新增任务缺少标题，已跳过", False
        task = await create_task(
            session,
            plan=plan,
            title=op.title,
            description=op.description,
            stage_name=op.stage_name,
            subject=op.subject,
            planned_date=_resolve_date(plan, op),
            duration_minutes=op.duration_minutes,
            priority=op.priority,
            task_type=op.task_type,
        )
        return f"新增任务「{task.title}」（{task.planned_date}）", True

    if op.action is RevisionAction.UPDATE_TASK:
        task = match_task(plan, op.task_title)
        if task is None:
            return f"未找到任务「{op.task_title}」，已跳过", False
        await update_task_fields(
            session,
            task=task,
            title=op.new_title or None,
            planned_date=(
                plan.start_date + timedelta(days=op.new_day_offset)
                if op.new_day_offset is not None
                else None
            ),
            duration_minutes=op.new_duration_minutes,
            priority=op.new_priority,
            status=op.new_status,
        )
        return f"调整任务「{task.title}」", True

    if op.action is RevisionAction.REMOVE_TASK:
        task = match_task(plan, op.task_title)
        if task is None:
            return f"未找到任务「{op.task_title}」，已跳过", False
        removed = task.title
        await delete_task(session, task)
        return f"删除任务「{removed}」", True

    if op.action is RevisionAction.SHIFT_TASKS:
        moved = await reschedule_pending_tasks(session, plan=plan, shift_days=op.shift_days)
        direction = "后移" if op.shift_days >= 0 else "前移"
        return f"未完成任务整体{direction} {abs(op.shift_days)} 天（{moved} 个）", moved > 0

    updated = await update_plan_fields(
        session,
        plan=plan,
        title=op.plan_title or None,
        goal=op.plan_goal or None,
        strategy=op.plan_strategy or None,
    )
    return f"更新计划信息「{updated.title}」", True


async def apply_plan_revision(
    session: AsyncSession,
    *,
    plan_id: int,
    revision: PlanRevision,
) -> RevisionOutcome:
    """把聊天 Agent 提出的修订提案落库。"""

    outcome = RevisionOutcome()
    plan = await load_plan(session, plan_id)
    if plan is None:
        outcome.note(f"计划 {plan_id} 不存在，修订未执行", ok=False)
        return outcome

    if not revision.ops:
        outcome.note("修订提案为空，计划未改动", ok=False)
        return outcome

    for op in revision.ops:
        message, ok = await _apply_op(session, plan, op)
        outcome.note(message, ok=ok)

    logger.info(
        "计划修订完成 plan=%s 生效 %d 条，跳过 %d 条",
        plan_id,
        outcome.applied,
        outcome.skipped,
    )
    return outcome

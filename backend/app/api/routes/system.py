"""系统能力总览与工作台概览接口。"""

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.db.models import Reminder, ReminderStatus
from app.knowledge import get_knowledge_base
from app.prompts import ROLES, describe_prompts
from app.schemas.api import (
    CapabilityInfo,
    DashboardRead,
    OverviewRead,
    PromptInfo,
    ReminderRead,
    RoleInfo,
    TaskStatsRead,
)
from app.services.snapshots import (
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_primary_target,
)
from app.tasks import describe_schedule
from app.workflows import describe_workflow

router = APIRouter(tags=["system"])

RECENT_REMINDER_LIMIT = 5


async def _knowledge_stats() -> dict[str, Any]:
    """知识库状态，失败时返回错误信息而不是让总览接口整体失败。"""

    try:
        return await get_knowledge_base().stats()
    except Exception as exc:  # noqa: BLE001 - 总览接口需要尽力返回
        return {"error": str(exc)}


@router.get("/overview", response_model=OverviewRead, summary="系统能力总览")
async def overview() -> OverviewRead:
    """返回角色、提示词、工作流拓扑、定时计划与知识库状态。

    这个接口是给前端渲染「系统是怎么工作的」用的，也便于答辩演示与排障。
    """

    settings = get_settings()

    return OverviewRead(
        roles=[
            RoleInfo(
                key=role.key,
                name=role.name,
                mission=role.mission,
                capabilities=list(role.capabilities),
            )
            for role in ROLES.values()
        ],
        prompts=[
            PromptInfo(
                task=str(item["task"]),
                role=str(item["role"]),
                role_name=str(item["role_name"]),
                required_variables=list(item["required_variables"]),  # type: ignore[arg-type]
            )
            for item in describe_prompts()
        ],
        workflow=describe_workflow(),
        schedule=describe_schedule(),
        knowledge=await _knowledge_stats(),
        capability=CapabilityInfo(
            llm_provider=settings.llm.default_provider,
            llm_ready=settings.llm.is_ready(),
            embedding=settings.embedding.provider,
            vector_backend=settings.vector.backend,
            knowledge_enabled=settings.knowledge.enabled,
            crew_enabled=settings.workflow.enable_plan_review,
            reminders_enabled=settings.reminder.enabled,
        ),
    )


@router.get("/dashboard", response_model=DashboardRead, summary="工作台概览")
async def dashboard(user_id: int, session: SessionDep) -> DashboardRead:
    """汇总用户的目标、进度、计划与提醒，供前端首屏使用。"""

    learner = await load_learner_snapshot(session, user_id)
    if learner is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    target = await load_primary_target(session, user_id)
    plan = await load_latest_plan_snapshot(session, user_id)

    plan_progress = 0.0
    if plan and plan.tasks:
        done = sum(1 for task in plan.tasks if task.status == "done")
        plan_progress = round(done / len(plan.tasks), 4)

    reminders = list(
        await session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .order_by(Reminder.id.desc())
            .limit(RECENT_REMINDER_LIMIT)
        )
    )
    pending = await session.scalar(
        select(func.count())
        .select_from(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == ReminderStatus.PENDING)
    )

    progress = learner.progress
    return DashboardRead(
        user_id=user_id,
        nickname=learner.nickname,
        target_id=target.id if target else None,
        target_title=learner.target_title,
        exam_date=learner.exam_date,
        days_left=learner.days_left,
        task_stats=TaskStatsRead(
            total=progress.total_tasks,
            todo=max(progress.total_tasks - progress.done_tasks - progress.doing_tasks, 0),
            doing=progress.doing_tasks,
            done=progress.done_tasks,
            overdue=progress.overdue_tasks,
            completion=progress.completion_rate,
        ),
        plan_id=plan.id if plan else None,
        plan_title=plan.title if plan else "",
        plan_progress=plan_progress,
        pending_reminders=int(pending or 0),
        recent_reminders=[
            ReminderRead.model_validate(item, from_attributes=True) for item in reminders
        ],
    )

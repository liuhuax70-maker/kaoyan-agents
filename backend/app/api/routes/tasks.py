"""学习任务与打卡接口。"""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import StudyTask, TaskProgress, TaskStatus
from app.schemas.api import TaskProgressRead, TaskRead, TaskUpdate
from app.services.plan_edit import delete_task
from app.services.progress import record_check_in
from app.services.scheduling import order_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead], summary="查询学习任务")
async def list_tasks(
    user_id: int,
    session: SessionDep,
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    plan_id: int | None = None,
    limit: int = 200,
) -> list[StudyTask]:
    """按用户（可选状态与计划）查询任务。"""

    statement = select(StudyTask).where(StudyTask.user_id == user_id)
    if status_filter is not None:
        statement = statement.where(StudyTask.status == status_filter)
    if plan_id is not None:
        statement = statement.where(StudyTask.plan_id == plan_id)

    return list(await session.scalars(order_tasks(statement).limit(limit)))


@router.get("/{task_id}", response_model=TaskRead, summary="查询任务详情")
async def get_task(task_id: int, session: SessionDep) -> StudyTask:
    """读取任务详情。"""

    task = await session.get(StudyTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.patch("/{task_id}", response_model=TaskRead, summary="任务打卡与调整")
async def update_task(task_id: int, payload: TaskUpdate, session: SessionDep) -> StudyTask:
    """更新任务。

    当传入 ``status`` 时会写入一条打卡记录，并连带刷新阶段完成度与连续学习统计。
    """

    task = await session.get(StudyTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    fields = payload.model_dump(
        exclude_unset=True, exclude={"note", "actual_minutes", "score", "status"}
    )
    for field, value in fields.items():
        if value is not None:
            setattr(task, field, value)

    if payload.status is not None:
        await record_check_in(
            session,
            task,
            status=payload.status,
            actual_minutes=payload.actual_minutes or 0,
            score=payload.score,
            note=payload.note,
        )
    else:
        await session.flush()

    updated = await session.get(StudyTask, task_id)
    if updated is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="任务更新失败")
    return updated


@router.delete("/{task_id}", status_code=204, summary="删除任务")
async def remove_task(task_id: int, session: SessionDep) -> None:
    """删除任务；打卡记录随任务一并移除。"""

    task = await session.get(StudyTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    await delete_task(session, task)


@router.get(
    "/{task_id}/progress",
    response_model=list[TaskProgressRead],
    summary="查询任务打卡记录",
)
async def list_task_progress(task_id: int, session: SessionDep) -> list[TaskProgress]:
    """返回任务的全部打卡历史。"""

    return list(
        await session.scalars(
            select(TaskProgress)
            .where(TaskProgress.task_id == task_id)
            .order_by(TaskProgress.id.desc())
        )
    )

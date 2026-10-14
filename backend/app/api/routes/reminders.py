"""提醒督促接口。"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import Reminder, ReminderStatus
from app.schemas.api import ReminderRead
from app.services.reminders import (
    ReminderResult,
    send_daily_reminders,
    send_idle_warnings,
    send_overdue_nudges,
    send_school_briefs,
    send_weekly_digests,
)

router = APIRouter(prefix="/reminders", tags=["reminders"])

Runner = Callable[..., Awaitable[ReminderResult]]

RUNNERS: dict[str, Runner] = {
    "daily": send_daily_reminders,
    "overdue": send_overdue_nudges,
    "idle": send_idle_warnings,
    "weekly": send_weekly_digests,
    "school_brief": send_school_briefs,
}


@router.get("", response_model=list[ReminderRead], summary="查询提醒")
async def list_reminders(
    user_id: int,
    session: SessionDep,
    status_filter: ReminderStatus | None = Query(default=None, alias="status"),
    limit: int = 50,
) -> list[Reminder]:
    """列出用户的提醒记录。"""

    statement = select(Reminder).where(Reminder.user_id == user_id)
    if status_filter is not None:
        statement = statement.where(Reminder.status == status_filter)

    return list(
        await session.scalars(statement.order_by(Reminder.id.desc()).limit(limit))
    )


@router.post("/run", summary="手动触发一轮提醒（调试与演示）")
async def run_reminders(
    session: SessionDep,
    kind: str = Query(
        default="daily", description="daily / overdue / idle / weekly / school_brief"
    ),
) -> dict[str, Any]:
    """立即执行一次提醒生成与投递。

    生产环境由 Celery Beat 定时触发，这个端点用于联调与演示。
    """

    runner = RUNNERS.get(kind)
    if runner is None:
        raise HTTPException(status_code=400, detail=f"不支持的提醒类型：{kind}")

    result = await runner(session)
    return {"kind": kind, **result.as_dict()}

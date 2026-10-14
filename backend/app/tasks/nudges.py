"""提醒督促定时任务。

Celery 任务是同步函数而业务层是异步实现，因此统一用 ``asyncio.run`` 包一层。
配合 SQLite 的 NullPool（连接随用随关），连接不会跨事件循环被复用。
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.db.session import db
from app.observability import get_observability
from app.services.reminders import (
    ReminderResult,
    send_daily_reminders,
    send_idle_warnings,
    send_overdue_nudges,
    send_school_briefs,
    send_weekly_digests,
)
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)

Handler = Callable[..., Awaitable[ReminderResult]]


async def _run_with_session(handler: Handler) -> ReminderResult:
    async with db.session() as session:
        return await handler(session)


def _execute(name: str, handler: Handler) -> dict[str, Any]:
    """在同步上下文中执行异步业务逻辑。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:  # pragma: no cover - 仅在错误调用方式下触发
        raise RuntimeError(
            f"定时任务 {name} 检测到运行中的事件循环，请通过 Celery worker 或同步上下文调用"
        )

    observability = get_observability()
    with observability.trace(
        f"reminder.{name}",
        tags=["celery", "reminder"],
        input=name,
        metadata={"task": name},
    ) as handle:
        result = asyncio.run(_run_with_session(handler))
        payload = result.as_dict()
        handle.update(output=payload)

    logger.info("定时任务 %s 完成：%s", name, payload)
    return payload


@celery_app.task(name="kaoyan.daily_reminder")
def daily_reminder() -> dict[str, Any]:
    """每日任务提醒：今天有待办就推一条。"""

    return _execute("daily_reminder", send_daily_reminders)


@celery_app.task(name="kaoyan.overdue_nudge")
def overdue_nudge() -> dict[str, Any]:
    """逾期催办：只针对存在逾期任务的用户。"""

    return _execute("overdue_nudge", send_overdue_nudges)


@celery_app.task(name="kaoyan.idle_warning")
def idle_warning() -> dict[str, Any]:
    """断签预警：连续未学习达到阈值时触发。"""

    return _execute("idle_warning", send_idle_warnings)


@celery_app.task(name="kaoyan.weekly_digest")
def weekly_digest() -> dict[str, Any]:
    """周报复盘：汇总本周表现并给出下周重点。"""

    return _execute("weekly_digest", send_weekly_digests)


@celery_app.task(name="kaoyan.school_brief")
def school_brief() -> dict[str, Any]:
    """每日院校简报：目标院校与专业的动向 + 官方核验入口。"""

    return _execute("school_brief", send_school_briefs)

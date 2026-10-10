"""Celery 应用与定时计划。"""

from typing import Any

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()
reminder = settings.reminder

celery_app = Celery(
    "kaoyan",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
    include=["app.tasks.nudges"],
)

celery_app.conf.update(
    timezone=settings.celery.timezone,
    enable_utc=False,
    task_always_eager=settings.celery.task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    beat_schedule={
        "daily-reminder": {
            "task": "kaoyan.daily_reminder",
            "schedule": crontab(hour=reminder.daily_hour, minute=0),
        },
        "overdue-nudge": {
            "task": "kaoyan.overdue_nudge",
            "schedule": crontab(hour=reminder.overdue_hour, minute=0),
        },
        "idle-warning": {
            "task": "kaoyan.idle_warning",
            "schedule": crontab(hour=reminder.idle_hour, minute=30),
        },
        "weekly-digest": {
            "task": "kaoyan.weekly_digest",
            "schedule": crontab(
                day_of_week=reminder.weekly_digest_weekday,
                hour=reminder.weekly_digest_hour,
                minute=0,
            ),
        },
    },
)


def describe_schedule() -> list[dict[str, str]]:
    """返回可读的定时计划，供文档与调试接口使用。"""

    schedule: dict[str, dict[str, Any]] = celery_app.conf.beat_schedule
    return [
        {
            "name": name,
            "task": str(config.get("task", "")),
            "schedule": str(config.get("schedule", "")),
        }
        for name, config in schedule.items()
    ]

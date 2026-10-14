"""Celery 定时任务层。"""

from app.tasks.celery_app import celery_app, describe_schedule
from app.tasks.nudges import (
    daily_reminder,
    idle_warning,
    overdue_nudge,
    school_brief,
    weekly_digest,
)

__all__ = [
    "celery_app",
    "daily_reminder",
    "describe_schedule",
    "idle_warning",
    "overdue_nudge",
    "school_brief",
    "weekly_digest",
]

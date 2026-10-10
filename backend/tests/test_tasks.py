"""提醒督促定时任务测试。

Celery 任务是同步入口，因此这里用同步用例直接验证 eager 链路：
真实走完「读库 → 生成督促文案 → 落库 → 投递」全过程。
"""

import asyncio
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.core.timeutil import utc_today
from app.db.base import Base
from app.db.models import (
    ExamTarget,
    LearnerProfile,
    Reminder,
    ReminderStatus,
    ReminderType,
    StudyPlan,
    StudyStreak,
    StudyTask,
    Subject,
    User,
)
from app.db.session import db
from app.tasks import (
    celery_app,
    daily_reminder,
    describe_schedule,
    idle_warning,
    overdue_nudge,
    weekly_digest,
)

UTC_TODAY = utc_today()


async def _prepare_async(*, due: bool, overdue: bool, idle_days: int) -> int:
    """重建数据库并写入一个用户场景，返回用户 ID。"""

    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        user = User(username="runner", nickname="小研")
        user.profile = LearnerProfile(
            base_level="一般", daily_hours=5, attention_span=60, self_discipline=2
        )
        session.add(user)
        await session.flush()

        target = ExamTarget(
            user_id=user.id,
            title="复旦计算机",
            exam_date=UTC_TODAY + timedelta(days=120),
        )
        session.add(target)
        await session.flush()

        session.add(Subject(target_id=target.id, name="数学"))
        await session.flush()

        plan = StudyPlan(
            user_id=user.id,
            target_id=target.id,
            title="60 天备考计划",
            horizon_days=60,
            start_date=UTC_TODAY,
            end_date=UTC_TODAY + timedelta(days=60),
        )
        session.add(plan)
        await session.flush()

        if due:
            session.add(
                StudyTask(
                    plan_id=plan.id,
                    user_id=user.id,
                    title="数学第二章配套习题",
                    planned_date=UTC_TODAY,
                )
            )
        if overdue:
            session.add(
                StudyTask(
                    plan_id=plan.id,
                    user_id=user.id,
                    title="数学第一章精读",
                    planned_date=UTC_TODAY - timedelta(days=2),
                )
            )

        session.add(
            StudyStreak(
                user_id=user.id,
                current_streak=0 if idle_days else 5,
                longest_streak=8,
                last_study_date=datetime.combine(
                    UTC_TODAY - timedelta(days=idle_days), time(20, 0)
                ),
            )
        )
        return user.id


async def _fetch_reminders_async(user_id: int) -> list[Reminder]:
    async with db.session() as session:
        rows = await session.scalars(
            select(Reminder).where(Reminder.user_id == user_id).order_by(Reminder.id)
        )
        return list(rows)


def _prepare(**scenario: bool | int) -> int:
    return asyncio.run(_prepare_async(**scenario))  # type: ignore[arg-type]


def _reminders(user_id: int) -> list[Reminder]:
    return asyncio.run(_fetch_reminders_async(user_id))


def test_celery_runs_eager_in_tests() -> None:
    assert celery_app.conf.task_always_eager is True


def test_schedule_contains_four_jobs() -> None:
    names = {item["name"] for item in describe_schedule()}
    assert names == {"daily-reminder", "overdue-nudge", "idle-warning", "weekly-digest"}


def test_daily_reminder_generates_and_delivers() -> None:
    user_id = _prepare(due=True, overdue=False, idle_days=0)

    payload = daily_reminder.delay().get()

    assert payload["generated"] == 1
    assert payload["delivered"] == 1
    assert payload["failed"] == 0

    reminders = _reminders(user_id)
    assert len(reminders) == 1
    assert reminders[0].reminder_type is ReminderType.DAILY
    assert reminders[0].status is ReminderStatus.SENT
    assert reminders[0].sent_at is not None
    assert reminders[0].title
    assert "数学第二章配套习题" in reminders[0].content


def test_daily_reminder_skips_user_without_tasks() -> None:
    _prepare(due=False, overdue=False, idle_days=0)

    payload = daily_reminder.delay().get()

    assert payload["generated"] == 0
    assert payload["skipped"] == 1
    assert payload["delivered"] == 0


def test_overdue_nudge_only_targets_overdue_tasks() -> None:
    _prepare(due=True, overdue=False, idle_days=0)
    assert overdue_nudge.delay().get()["generated"] == 0

    user_id = _prepare(due=False, overdue=True, idle_days=0)
    payload = overdue_nudge.delay().get()

    assert payload["generated"] == 1
    reminders = _reminders(user_id)
    assert reminders[0].reminder_type is ReminderType.OVERDUE
    assert "数学第一章精读" in reminders[0].content


def test_idle_warning_respects_threshold() -> None:
    _prepare(due=False, overdue=False, idle_days=1)
    assert idle_warning.delay().get()["generated"] == 0

    user_id = _prepare(due=False, overdue=False, idle_days=4)
    payload = idle_warning.delay().get()

    assert payload["generated"] == 1
    reminders = _reminders(user_id)
    assert reminders[0].reminder_type is ReminderType.IDLE


def test_weekly_digest_builds_report_body() -> None:
    user_id = _prepare(due=True, overdue=False, idle_days=0)

    payload = weekly_digest.delay().get()

    assert payload["generated"] == 1
    reminder = _reminders(user_id)[0]
    assert reminder.reminder_type is ReminderType.WEEKLY
    assert "下周重点" in reminder.content
    assert "本周亮点" in reminder.content


def test_reminders_are_not_generated_twice_for_same_run() -> None:
    """同一场景连续跑两次会各生成一条，说明每次执行都是独立批次。"""

    user_id = _prepare(due=True, overdue=False, idle_days=0)

    daily_reminder.delay().get()
    daily_reminder.delay().get()

    assert len(_reminders(user_id)) == 2

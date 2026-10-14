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
    TaskProgress,
    TrackedSchool,
    TrackedSchoolStatus,
    User,
)
from app.db.session import db
from app.tasks import (
    celery_app,
    daily_reminder,
    describe_schedule,
    idle_warning,
    overdue_nudge,
    school_brief,
    weekly_digest,
)
from tests.fakes import message_text, recorded_requests

UTC_TODAY = utc_today()

PRESSURE_WORDS = ("必须", "再不学", "来不及", "已经落后", "赶紧")
"""施压措辞的黑名单：督促是邀请，不是催办。"""


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


async def _add_progress_async(
    user_id: int, *, days_ago: int = 0, minutes: int = 30
) -> None:
    """补一条打卡记录，``created_at`` 相对 UTC 今天往回推 ``days_ago`` 天。"""

    async with db.session() as session:
        task_id = await session.scalar(
            select(StudyTask.id).where(StudyTask.user_id == user_id).limit(1)
        )
        session.add(
            TaskProgress(
                task_id=task_id,
                user_id=user_id,
                actual_minutes=minutes,
                created_at=datetime.combine(
                    UTC_TODAY - timedelta(days=days_ago), time(20, 0)
                ),
            )
        )
        await session.commit()


def _add_progress(user_id: int, *, days_ago: int = 0, minutes: int = 30) -> None:
    asyncio.run(_add_progress_async(user_id, days_ago=days_ago, minutes=minutes))


def _prepare(**scenario: bool | int) -> int:
    return asyncio.run(_prepare_async(**scenario))  # type: ignore[arg-type]


async def _prepare_without_streak_async() -> int:
    """与 ``_prepare`` 相同，但不写 ``StudyStreak`` —— 模拟从未开始学的用户。"""

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

        session.add(
            StudyTask(
                plan_id=plan.id,
                user_id=user.id,
                title="数学第二章配套习题",
                planned_date=UTC_TODAY,
            )
        )
        await session.commit()
        return user.id


def _prepare_idle_without_streak() -> int:
    return asyncio.run(_prepare_without_streak_async())


async def _seed_tracked_school_async(
    user_id: int, *, name: str = "某某大学", major: str = "计算机技术"
) -> None:
    """给用户的目标下挂一所跟踪中的候选院校，供院校简报使用。"""

    async with db.session() as session:
        target_id = await session.scalar(
            select(ExamTarget.id).where(ExamTarget.user_id == user_id).limit(1)
        )
        session.add(
            TrackedSchool(
                user_id=user_id,
                target_id=target_id,
                name=name,
                major=major,
                status=TrackedSchoolStatus.CANDIDATE,
                snapshot={},
                order_index=0,
            )
        )
        await session.commit()


def _seed_tracked_school(user_id: int, **kwargs: str) -> None:
    asyncio.run(_seed_tracked_school_async(user_id, **kwargs))


def _reminders(user_id: int) -> list[Reminder]:
    return asyncio.run(_fetch_reminders_async(user_id))


def test_celery_runs_eager_in_tests() -> None:
    assert celery_app.conf.task_always_eager is True


def test_schedule_contains_five_jobs() -> None:
    names = {item["name"] for item in describe_schedule()}
    assert names == {
        "daily-reminder",
        "overdue-nudge",
        "idle-warning",
        "weekly-digest",
        "school-brief",
    }


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


def test_idle_warning_respects_consecutive_zero_days() -> None:
    """断签预警看「连续零投入」而不是「距上次学习多少天」。

    两天前有打卡、但 StudyStreak 记的上次学习是 5 天前：旧口径会误报（5 ≥ 3），
    新口径只看打卡，两天前投入过就不该打扰。
    """

    user_id = _prepare(due=True, overdue=False, idle_days=5)
    _add_progress(user_id, days_ago=2)
    assert idle_warning.delay().get()["generated"] == 0

    # 连续 4 天没有任何打卡 → 该预警
    user_id = _prepare(due=True, overdue=False, idle_days=4)
    payload = idle_warning.delay().get()
    assert payload["generated"] == 1
    reminders = _reminders(user_id)
    assert reminders[0].reminder_type is ReminderType.IDLE


def test_idle_warning_skips_never_started_users() -> None:
    """从未开始学（无 StudyStreak.last_study_date）的用户不该被打扰。"""

    _prepare_idle_without_streak()
    assert idle_warning.delay().get()["generated"] == 0


def test_school_brief_task_generates_and_delivers() -> None:
    """每日院校简报走完「找跟踪院校 → 生成 → 落库 → 投递」全链路。"""

    user_id = _prepare(due=False, overdue=False, idle_days=0)
    _seed_tracked_school(user_id)

    payload = school_brief.delay().get()

    assert payload["generated"] == 1
    assert payload["delivered"] == 1

    reminders = _reminders(user_id)
    assert len(reminders) == 1
    assert reminders[0].reminder_type is ReminderType.SCHOOL_BRIEF
    assert reminders[0].status is ReminderStatus.SENT
    assert "【核验入口】" in reminders[0].content
    # 链接是 markdown 语法而非死文本：站内信渲染成 Markdown 后可点击
    assert "](http" in reminders[0].content


def test_school_brief_falls_back_to_official_links_when_search_degraded() -> None:
    """联网搜索关着（默认）时简报照投，核验入口一条不少。"""

    user_id = _prepare(due=False, overdue=False, idle_days=0)
    _seed_tracked_school(user_id)

    payload = school_brief.delay().get()

    assert payload["generated"] == 1
    content = _reminders(user_id)[0].content
    # 研招网专业目录是不依赖搜索提供方的确定性入口，降级也必须在场
    assert "研招网 · 硕士专业目录" in content
    assert "yz.chsi.com.cn" in content


def test_overdue_nudge_language_is_invitational() -> None:
    """逾期提醒是邀请式表达：先说可以顺延，不施压。"""

    user_id = _prepare(due=False, overdue=True, idle_days=0)

    overdue_nudge.delay().get()

    content = _reminders(user_id)[0].content
    assert "顺延" in content
    assert not [word for word in PRESSURE_WORDS if word in content]

    # 提示词里也要明文给出「能顺延」这件事：否则提醒只描述了欠账，语气再客气也还是在催
    prompts = "\n".join(
        message_text(item) for messages in recorded_requests("nudge") for item in messages
    )
    assert "一键顺延到明天" in prompts


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

"""提醒督促服务：生成、落库与投递。

五类提醒对应五种督促场景：
- daily：今日任务提醒；
- overdue：逾期催办；
- idle：连续零投入预警；
- weekly：周报复盘；
- school_brief：每日院校简报（目标院校与专业的动向 + 官方核验入口）。

生成环节统一走 ``app.agents.compose_nudge`` / ``compose_weekly_digest`` /
``compose_school_brief``，提示词只有一份实现；定时链路只要结构化结果，
因此丢掉双轨信封里的正文一轨。
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import (
    compose_nudge,
    compose_school_brief,
    compose_weekly_digest,
    format_brief_content,
)
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.timeutil import utc_now, utc_today
from app.db.models import (
    ExamTarget,
    Reminder,
    ReminderChannel,
    ReminderStatus,
    ReminderType,
    StudyTask,
    TrackedSchool,
    TrackedSchoolStatus,
)
from app.schemas import LearnerSnapshot, ReminderSnapshot
from app.search.base import gather_school_intel
from app.services.snapshots import (
    active_user_ids,
    collect_user_tasks,
    consecutive_zero_days,
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_primary_target,
)
from app.services.targets import (
    list_tracked_schools,
    mark_briefed,
    tracked_schools_as_snapshots,
)

logger = get_logger(__name__)

TASK_TITLE_LIMIT = 5


@dataclass(slots=True)
class ReminderResult:
    """一轮提醒任务的执行结果。"""

    generated: int = 0
    delivered: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """转为可序列化结构，便于作为任务返回值。"""

        return {
            "generated": self.generated,
            "delivered": self.delivered,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors[:10],
        }


def _titles(tasks: list[StudyTask]) -> list[str]:
    return [task.title for task in tasks[:TASK_TITLE_LIMIT]]


def _plan_id(due: list[StudyTask], overdue: list[StudyTask]) -> int | None:
    for task in (*due, *overdue):
        if task.plan_id:
            return task.plan_id
    return None


async def _create_nudge_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    reminder_type: ReminderType,
    learner: LearnerSnapshot,
    due: list[StudyTask],
    overdue: list[StudyTask],
    provider: str | None = None,
) -> Reminder:
    """生成一条督促提醒并落库（状态为待发送）。"""

    snapshot = ReminderSnapshot(
        reminder_type=reminder_type.value,
        target_title=learner.target_title,
        due_tasks=_titles(due),
        overdue_tasks=_titles(overdue),
        days_left=learner.days_left,
        idle_days=learner.progress.idle_days,
        completion_rate=learner.progress.completion_rate,
    )
    nudge = await compose_nudge(learner, snapshot, provider)

    reminder = Reminder(
        user_id=user_id,
        plan_id=_plan_id(due, overdue),
        task_id=overdue[0].id if overdue else None,
        reminder_type=reminder_type,
        channel=ReminderChannel.IN_APP,
        title=nudge.title[:200],
        content=nudge.content,
        scheduled_at=utc_now(),
        status=ReminderStatus.PENDING,
    )
    session.add(reminder)
    await session.flush()
    return reminder


def _brief_query(school: str, major: str, tracked: list[TrackedSchool]) -> str:
    """构造每日院校简报的联网搜索词。

    优先搜用户已经拍板的那所（``target.target_school``），还没拍板时
    用最前面的几所候选一起搜——决策之前的跟踪期，恰恰是简报最有价值的时段。
    """

    if school:
        focus = " ".join(filter(None, [school, major]))
    else:
        names = " ".join(row.name for row in tracked[:3])
        focus = names
    return f"{focus} 考研 招生".strip()


# 知识点：增强能力的降级不中断主链路 —— 简报的联网情报失败时照常投递，核验入口由
#   ``official_entry_links`` 保证仍在，因此「没搜到」不等于「没简报」（第4章 RAG Agent·构建知识库）
async def _create_school_brief_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    learner: LearnerSnapshot,
    target: ExamTarget,
    tracked: list[TrackedSchool],
    search_enabled: bool,
    provider: str | None,
) -> Reminder:
    """生成一条每日院校简报并落库，随后把简报过的候选盖上时间戳。"""

    school = target.target_school or tracked[0].name
    major = target.target_major or tracked[0].major
    intel = await gather_school_intel(
        _brief_query(target.target_school, target.target_major, tracked),
        school=school,
        major=major,
        enabled=search_enabled,
    )

    brief = await compose_school_brief(
        learner,
        tracked=tracked_schools_as_snapshots(tracked),
        intel=intel,
        provider=provider,
    )
    content = format_brief_content(brief, intel.links)

    reminder = Reminder(
        user_id=user_id,
        reminder_type=ReminderType.SCHOOL_BRIEF,
        channel=ReminderChannel.IN_APP,
        title=(brief.title or "今日院校简报")[:200],
        content=content,
        scheduled_at=utc_now(),
        status=ReminderStatus.PENDING,
    )
    session.add(reminder)
    await session.flush()
    await mark_briefed(session, school_ids=[row.id for row in tracked])
    return reminder


async def _create_digest_reminder(
    session: AsyncSession,
    *,
    user_id: int,
    learner: LearnerSnapshot,
    provider: str | None = None,
) -> Reminder:
    """生成周报提醒并落库。"""

    plan = await load_latest_plan_snapshot(session, user_id)
    digest = await compose_weekly_digest(learner, plan, provider)

    content = "\n".join(
        [
            "【本周亮点】",
            *digest.highlights,
            "【存在问题】",
            *digest.problems,
            "【下周重点】",
            *digest.next_week_plan,
            digest.closing,
        ]
    )

    reminder = Reminder(
        user_id=user_id,
        plan_id=plan.id if plan else None,
        reminder_type=ReminderType.WEEKLY,
        channel=ReminderChannel.IN_APP,
        title=digest.title[:200],
        content=content,
        scheduled_at=utc_now(),
        status=ReminderStatus.PENDING,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def deliver(session: AsyncSession, reminder: Reminder) -> bool:
    """投递提醒。

    目前只实现站内信渠道：其他渠道标记为失败并记录原因，
    而不是把「未发送」伪装成「已发送」。
    """

    if reminder.channel != ReminderChannel.IN_APP:
        reminder.status = ReminderStatus.FAILED
        reminder.error_message = f"渠道 {reminder.channel} 尚未实现"
        reminder.retry_count += 1
        await session.flush()
        return False

    reminder.status = ReminderStatus.SENT
    reminder.sent_at = utc_now()
    reminder.error_message = ""
    await session.flush()
    logger.info("站内提醒已投递 user=%s title=%s", reminder.user_id, reminder.title)
    return True


async def _generate_for_users(
    session: AsyncSession,
    *,
    reminder_type: ReminderType,
    today: date,
    provider: str | None,
    require_overdue: bool = False,
) -> ReminderResult:
    """按用户批量生成并投递任务类提醒。"""

    result = ReminderResult()

    for user_id in await active_user_ids(session):
        learner = await load_learner_snapshot(session, user_id, today=today)
        if learner is None:
            result.skipped += 1
            continue

        due, overdue = await collect_user_tasks(session, user_id, today=today)
        if require_overdue:
            if not overdue:
                result.skipped += 1
                continue
        elif not due and not overdue:
            result.skipped += 1
            continue

        try:
            reminder = await _create_nudge_reminder(
                session,
                user_id=user_id,
                reminder_type=reminder_type,
                learner=learner,
                due=due,
                overdue=overdue,
                provider=provider,
            )
        except Exception as exc:  # noqa: BLE001 - 单个用户失败不应影响其他人
            result.failed += 1
            result.errors.append(f"user={user_id} 生成提醒失败：{exc}")
            continue

        result.generated += 1
        if await deliver(session, reminder):
            result.delivered += 1

    return result


async def send_daily_reminders(
    session: AsyncSession,
    *,
    today: date | None = None,
    provider: str | None = None,
) -> ReminderResult:
    """为今天有任务的用户生成每日提醒。"""

    return await _generate_for_users(
        session,
        reminder_type=ReminderType.DAILY,
        today=today or utc_today(),
        provider=provider,
    )


async def send_overdue_nudges(
    session: AsyncSession,
    *,
    today: date | None = None,
    provider: str | None = None,
) -> ReminderResult:
    """仅对存在逾期任务的用户催办。"""

    return await _generate_for_users(
        session,
        reminder_type=ReminderType.OVERDUE,
        today=today or utc_today(),
        provider=provider,
        require_overdue=True,
    )


async def send_idle_warnings(
    session: AsyncSession,
    *,
    today: date | None = None,
    provider: str | None = None,
) -> ReminderResult:
    """对连续多日「完全零投入」的用户下发预警。

    门槛用 ``consecutive_zero_days`` 而不是 ``progress.idle_days``：
    后者是「距上次学习多少天」的展示口径，自律度低的用户隔三差五不打卡是常态，
    只看它会写成催办。这里要求窗口内每一天都没有任何 ``actual_minutes > 0`` 的打卡，
    才真正叫「断了」，才值得轻轻提醒一句。
    """

    reference = today or utc_today()
    threshold = get_settings().reminder.idle_zero_days
    result = ReminderResult()

    for user_id in await active_user_ids(session):
        learner = await load_learner_snapshot(session, user_id, today=reference)
        zero_days = await consecutive_zero_days(session, user_id, today=reference)
        if learner is None or zero_days < threshold:
            result.skipped += 1
            continue

        due, overdue = await collect_user_tasks(session, user_id, today=reference)
        try:
            reminder = await _create_nudge_reminder(
                session,
                user_id=user_id,
                reminder_type=ReminderType.IDLE,
                learner=learner,
                due=due,
                overdue=overdue,
                provider=provider,
            )
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"user={user_id} 生成断签预警失败：{exc}")
            continue

        result.generated += 1
        if await deliver(session, reminder):
            result.delivered += 1

    return result


async def send_school_briefs(
    session: AsyncSession,
    *,
    today: date | None = None,
    provider: str | None = None,
) -> ReminderResult:
    """为跟踪着院校的用户生成并投递每日院校简报。

    逐用户 try/except：单个用户失败不拖垮整批。没有在跟踪的院校就跳过——
    简报要说的就是「跟踪中的那几所」的情况，没有 watch-list 就无简报可言。
    """

    reference = today or utc_today()
    search_enabled = get_settings().search.enabled
    result = ReminderResult()

    for user_id in await active_user_ids(session):
        learner = await load_learner_snapshot(session, user_id, today=reference)
        if learner is None:
            result.skipped += 1
            continue

        target = await load_primary_target(session, user_id)
        if target is None:
            result.skipped += 1
            continue

        tracked = [
            row
            for row in await list_tracked_schools(session, target_id=target.id)
            if row.status is not TrackedSchoolStatus.ARCHIVED
        ]
        if not tracked:
            result.skipped += 1
            continue

        try:
            reminder = await _create_school_brief_reminder(
                session,
                user_id=user_id,
                learner=learner,
                target=target,
                tracked=tracked,
                search_enabled=search_enabled,
                provider=provider,
            )
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"user={user_id} 生成院校简报失败：{exc}")
            continue

        result.generated += 1
        if await deliver(session, reminder):
            result.delivered += 1

    return result


async def send_weekly_digests(
    session: AsyncSession,
    *,
    today: date | None = None,
    provider: str | None = None,
) -> ReminderResult:
    """生成并投递周报复盘。"""

    reference = today or utc_today()
    result = ReminderResult()

    for user_id in await active_user_ids(session):
        learner = await load_learner_snapshot(session, user_id, today=reference)
        if learner is None:
            result.skipped += 1
            continue

        try:
            reminder = await _create_digest_reminder(
                session, user_id=user_id, learner=learner, provider=provider
            )
        except Exception as exc:  # noqa: BLE001
            result.failed += 1
            result.errors.append(f"user={user_id} 生成周报失败：{exc}")
            continue

        result.generated += 1
        if await deliver(session, reminder):
            result.delivered += 1

    return result

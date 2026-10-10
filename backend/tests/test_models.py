"""数据模型测试：建表、关系级联、枚举落库与约束。"""

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    AgentConversation,
    AgentMessage,
    ExamTarget,
    ExamType,
    LearnerProfile,
    MessageRole,
    PlanStage,
    PlanStatus,
    Priority,
    Reminder,
    ReminderStatus,
    ReminderType,
    StageType,
    StudyPlan,
    StudyStreak,
    StudyTask,
    Subject,
    TargetStatus,
    TaskProgress,
    TaskStatus,
    TaskType,
    User,
)

TODAY = date(2026, 10, 10)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """内存 SQLite 会话。

    使用 StaticPool 让所有会话共享同一个连接，否则每次连接都是新的空库；
    同时打开外键约束，确保关系与级联在测试中真实生效。
    """

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session

    await engine.dispose()


async def test_persist_full_learning_data(session: AsyncSession) -> None:
    """完整写入用户 → 目标 → 科目 → 计划 → 阶段 → 任务 → 打卡 → 提醒 → 会话。"""

    user = User(username="xiaoyan", nickname="小研", email="xiaoyan@example.com")
    user.profile = LearnerProfile(
        base_level="一般",
        daily_hours=6.0,
        preferred_slots=["上午", "晚上"],
        self_discipline=4,
    )
    session.add(user)
    await session.flush()

    target = ExamTarget(
        user_id=user.id,
        exam_type=ExamType.POSTGRADUATE,
        title="复旦计算机",
        target_school="复旦大学",
        target_major="计算机科学与技术",
        exam_date=TODAY + timedelta(days=200),
        status=TargetStatus.PREPARING,
    )
    session.add(target)
    await session.flush()

    math = Subject(
        target_id=target.id, name="数学", score_weight=0.3, is_weak=True, order_index=0
    )
    english = Subject(target_id=target.id, name="英语", score_weight=0.2, order_index=1)
    session.add_all([math, english])
    await session.flush()

    plan = StudyPlan(
        user_id=user.id,
        target_id=target.id,
        title="200 天备考规划",
        goal="数学从 60 分提升到 110 分",
        horizon_days=200,
        start_date=TODAY,
        end_date=TODAY + timedelta(days=200),
        total_hours=1200,
        status=PlanStatus.ACTIVE,
        generated_by="plan_generation",
    )
    session.add(plan)
    await session.flush()

    stage = PlanStage(
        plan_id=plan.id,
        name="基础夯实",
        stage_type=StageType.FOUNDATION,
        order_index=0,
        start_date=TODAY,
        end_date=TODAY + timedelta(days=80),
        target_hours=480,
    )
    session.add(stage)
    await session.flush()

    task = StudyTask(
        plan_id=plan.id,
        stage_id=stage.id,
        subject_id=math.id,
        user_id=user.id,
        title="高数第一章：函数与极限精读",
        task_type=TaskType.LEARN,
        planned_date=TODAY,
        duration_minutes=90,
        priority=Priority.HIGH,
        resource_hint="教材 + 基础讲义",
    )
    session.add(task)
    await session.flush()

    session.add_all(
        [
            TaskProgress(
                task_id=task.id,
                user_id=user.id,
                status=TaskStatus.DONE,
                actual_minutes=105,
                completion_rate=0.9,
                score=72.0,
                note="洛必达法则使用条件不熟",
            ),
            Reminder(
                user_id=user.id,
                plan_id=plan.id,
                task_id=task.id,
                reminder_type=ReminderType.DAILY,
                title="今日任务提醒",
                content="今天还有 2 个任务未完成",
                scheduled_at=datetime(2026, 10, 11, 8, 0),
            ),
            StudyStreak(user_id=user.id, current_streak=7, longest_streak=12, total_days=30),
        ]
    )

    conversation = AgentConversation(
        user_id=user.id, target_id=target.id, title="生成备考计划", workflow="plan_generation"
    )
    session.add(conversation)
    await session.flush()
    session.add(
        AgentMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            agent_name="planner",
            content="已生成 200 天四阶段计划",
            payload={"stages": ["基础夯实", "强化提升"]},
            tokens_in=820,
            tokens_out=1430,
            latency_ms=5200,
        )
    )
    await session.commit()

    loaded_task = await session.scalar(
        select(StudyTask)
        .where(StudyTask.id == task.id)
        .options(selectinload(StudyTask.subject), selectinload(StudyTask.stage))
    )
    assert loaded_task is not None
    assert loaded_task.status is TaskStatus.TODO
    assert loaded_task.priority is Priority.HIGH
    assert loaded_task.task_type is TaskType.LEARN
    assert loaded_task.subject is not None
    assert loaded_task.subject.name == "数学"
    assert loaded_task.stage is not None
    assert loaded_task.stage.name == "基础夯实"

    loaded_plan = await session.scalar(
        select(StudyPlan).where(StudyPlan.id == plan.id).options(selectinload(StudyPlan.user))
    )
    assert loaded_plan is not None
    assert loaded_plan.status is PlanStatus.ACTIVE
    assert loaded_plan.user.nickname == "小研"
    assert len(loaded_plan.stages) == 1
    assert len(loaded_plan.tasks) == 1
    assert loaded_plan.meta == {}

    loaded_target = await session.scalar(select(ExamTarget).where(ExamTarget.id == target.id))
    assert loaded_target is not None
    assert loaded_target.exam_type is ExamType.POSTGRADUATE
    assert [item.name for item in loaded_target.subjects] == ["数学", "英语"]

    loaded_user = await session.scalar(select(User).where(User.id == user.id))
    assert loaded_user is not None
    assert loaded_user.profile is not None
    assert loaded_user.profile.preferred_slots == ["上午", "晚上"]

    progress = await session.scalar(select(TaskProgress).where(TaskProgress.task_id == task.id))
    assert progress is not None
    assert progress.score == 72.0

    reminder = await session.scalar(select(Reminder).where(Reminder.user_id == user.id))
    assert reminder is not None
    assert reminder.status is ReminderStatus.PENDING
    assert reminder.is_pending is True

    loaded_conversation = await session.scalar(
        select(AgentConversation).where(AgentConversation.id == conversation.id)
    )
    assert loaded_conversation is not None
    assert loaded_conversation.message_count == 0
    assert len(loaded_conversation.messages) == 1
    assert loaded_conversation.messages[0].payload["stages"] == ["基础夯实", "强化提升"]


async def test_enum_is_stored_as_value(session: AsyncSession) -> None:
    """枚举列落库应保存 value 而非成员名，避免后续升级时取值不兼容。"""

    user = User(username="enum_check")
    session.add(user)
    await session.flush()

    target = ExamTarget(user_id=user.id, title="软考中级", exam_date=TODAY)
    session.add(target)
    await session.flush()

    plan = StudyPlan(
        user_id=user.id,
        target_id=target.id,
        title="计划",
        start_date=TODAY,
        end_date=TODAY + timedelta(days=30),
    )
    session.add(plan)
    await session.flush()

    task = StudyTask(
        plan_id=plan.id,
        user_id=user.id,
        title="整卷模考",
        planned_date=TODAY,
        task_type=TaskType.MOCK,
        priority=Priority.LOW,
    )
    session.add(task)
    await session.commit()

    raw_status = await session.scalar(
        text("SELECT status FROM study_tasks WHERE id = :task_id"), {"task_id": task.id}
    )
    raw_type = await session.scalar(
        text("SELECT task_type FROM study_tasks WHERE id = :task_id"), {"task_id": task.id}
    )
    assert raw_status == "todo"
    assert raw_type == "mock"


async def test_deleting_user_cascades_to_plan_and_tasks(session: AsyncSession) -> None:
    """删除用户应级联清理目标、计划与任务。"""

    user = User(username="cascade_user")
    session.add(user)
    await session.flush()

    target = ExamTarget(user_id=user.id, title="软考中级", exam_date=TODAY)
    session.add(target)
    await session.flush()

    plan = StudyPlan(
        user_id=user.id,
        target_id=target.id,
        title="计划",
        start_date=TODAY,
        end_date=TODAY + timedelta(days=30),
    )
    session.add(plan)
    await session.flush()

    session.add(
        StudyTask(plan_id=plan.id, user_id=user.id, title="任务", planned_date=TODAY)
    )
    await session.commit()

    await session.delete(user)
    await session.commit()

    assert await session.scalar(select(StudyTask)) is None
    assert await session.scalar(select(StudyPlan)) is None
    assert await session.scalar(select(ExamTarget)) is None


async def test_username_must_be_unique(session: AsyncSession) -> None:
    """登录名唯一约束应生效。"""

    session.add(User(username="duplicated"))
    await session.commit()

    session.add(User(username="duplicated"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

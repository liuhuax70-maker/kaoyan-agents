"""服务层测试：快照构建与计划落库。"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ExamTarget,
    ExamType,
    LearnerProfile,
    PlanStage,
    StudyStreak,
    StudyTask,
    Subject,
    TargetStatus,
    TaskStatus,
    User,
)
from app.schemas import PlanDraft
from app.services import (
    active_user_ids,
    collect_user_tasks,
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_plan_snapshot,
)
from app.services.plans import persist_plan_draft

TODAY = date(2026, 10, 10)


def _draft(horizon: int = 60) -> PlanDraft:
    return PlanDraft.model_validate(
        {
            "title": f"{horizon} 天备考计划",
            "goal": "系统完成数学与英语备考",
            "strategy": "分阶段推进，薄弱科目优先",
            "horizon_days": horizon,
            "daily_hours": 5,
            "stages": [
                {
                    "name": "基础夯实",
                    "stage_type": "foundation",
                    "focus": "打牢基础",
                    "start_offset": 0,
                    "end_offset": 30,
                    "target_hours": 120,
                    "tasks": [
                        {
                            "title": "数学第一章精读",
                            "subject": "数学",
                            "day_offset": 0,
                            "duration_minutes": 60,
                        },
                        {
                            "title": "数学第一章配套习题",
                            "subject": "数学",
                            "day_offset": 1,
                            "duration_minutes": 45,
                            "depends_on_index": 0,
                        },
                    ],
                },
                {
                    "name": "强化提升",
                    "stage_type": "enhancement",
                    "focus": "专题突破",
                    "start_offset": 30,
                    "end_offset": 60,
                    "target_hours": 100,
                    "tasks": [
                        {
                            "title": "英语真题阅读两篇",
                            "subject": "英语",
                            "day_offset": 30,
                            "duration_minutes": 50,
                        },
                        {
                            "title": "英语长难句整理",
                            "subject": "英语",
                            "day_offset": 31,
                            "duration_minutes": 40,
                        },
                    ],
                },
            ],
        }
    )


async def _seed(session: AsyncSession, *, idle_days: int = 0) -> dict[str, int]:
    user = User(username="xiaoyan", nickname="小研", email="xiaoyan@example.com")
    user.profile = LearnerProfile(
        base_level="一般", daily_hours=6.0, attention_span=60, self_discipline=4
    )
    session.add(user)
    await session.flush()

    target = ExamTarget(
        user_id=user.id,
        exam_type=ExamType.POSTGRADUATE,
        title="复旦计算机",
        target_school="复旦大学",
        exam_date=TODAY + timedelta(days=200),
        status=TargetStatus.PREPARING,
    )
    session.add(target)
    await session.flush()

    session.add_all(
        [
            Subject(target_id=target.id, name="数学", is_weak=True, order_index=0),
            Subject(target_id=target.id, name="英语", order_index=1),
        ]
    )
    session.add(
        StudyStreak(
            user_id=user.id,
            current_streak=5,
            longest_streak=9,
            last_study_date=datetime.combine(
                TODAY - timedelta(days=idle_days), datetime.min.time()
            ),
        )
    )
    await session.commit()
    return {"user": user.id, "target": target.id}


async def test_load_learner_snapshot_includes_target_and_subjects(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)

    learner = await load_learner_snapshot(app_db, ids["user"], today=TODAY)

    assert learner is not None
    assert learner.nickname == "小研"
    assert learner.target_title == "复旦计算机"
    assert learner.exam_type == "postgraduate"
    assert learner.days_left == 200
    assert learner.daily_hours == 6.0
    assert [item.name for item in learner.subjects] == ["数学", "英语"]
    assert learner.weak_subjects == ["数学"]
    assert learner.progress.current_streak == 5


async def test_load_learner_snapshot_returns_none_for_unknown_user(app_db: AsyncSession) -> None:
    assert await load_learner_snapshot(app_db, 999_999, today=TODAY) is None


async def test_collect_progress_counts_idle_days(app_db: AsyncSession) -> None:
    ids = await _seed(app_db, idle_days=3)

    learner = await load_learner_snapshot(app_db, ids["user"], today=TODAY)

    assert learner is not None
    assert learner.progress.idle_days == 3


async def test_active_user_ids_only_returns_preparing(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)

    assert await active_user_ids(app_db) == [ids["user"]]


async def test_persist_plan_draft_creates_stages_and_tasks(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)

    plan = await persist_plan_draft(
        app_db,
        user_id=ids["user"],
        target_id=ids["target"],
        draft=_draft(),
        today=TODAY,
    )
    await app_db.commit()

    snapshot = await load_plan_snapshot(app_db, plan.id)

    assert snapshot is not None
    assert snapshot.horizon_days == 60
    assert snapshot.start_date == TODAY
    assert snapshot.end_date == TODAY + timedelta(days=60)
    assert len(snapshot.tasks) == 4

    first = snapshot.tasks[0]
    assert first.planned_date == TODAY
    assert first.subject == "数学"
    assert first.stage == "基础夯实"
    assert first.status == "todo"


async def test_persist_plan_draft_resolves_task_dependencies(app_db: AsyncSession) -> None:
    """depends_on_index 应在任务拿到主键后回填为真实外键。"""

    ids = await _seed(app_db)
    plan = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(), today=TODAY
    )
    await app_db.commit()

    stages = list(
        await app_db.scalars(
            select(PlanStage).where(PlanStage.plan_id == plan.id).order_by(PlanStage.order_index)
        )
    )
    assert len(stages) == 2

    async def stage_tasks(stage_id: int) -> list[StudyTask]:
        return list(
            await app_db.scalars(
                select(StudyTask)
                .where(StudyTask.stage_id == stage_id)
                .order_by(StudyTask.order_index)
            )
        )

    first_stage = await stage_tasks(stages[0].id)
    assert len(first_stage) == 2
    assert first_stage[0].depends_on_task_id is None
    assert first_stage[1].depends_on_task_id == first_stage[0].id

    second_stage = await stage_tasks(stages[1].id)
    assert all(task.depends_on_task_id is None for task in second_stage)


async def test_collect_user_tasks_splits_due_and_overdue(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)
    plan = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(), today=TODAY
    )
    await app_db.commit()

    due, overdue = await collect_user_tasks(app_db, ids["user"], today=TODAY)

    assert [task.title for task in due] == ["数学第一章精读"]
    assert overdue == []

    # 把第一天任务挪到昨天，即变成逾期
    first = await app_db.scalar(
        select(StudyTask).where(StudyTask.plan_id == plan.id, StudyTask.planned_date == TODAY)
    )
    assert first is not None
    first.planned_date = TODAY - timedelta(days=1)
    await app_db.commit()

    due, overdue = await collect_user_tasks(app_db, ids["user"], today=TODAY)
    assert due == []
    assert [task.title for task in overdue] == ["数学第一章精读"]


async def test_load_latest_plan_snapshot_returns_newest(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)

    assert await load_latest_plan_snapshot(app_db, ids["user"]) is None

    await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(30), today=TODAY
    )
    second = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(90), today=TODAY
    )
    await app_db.commit()

    snapshot = await load_latest_plan_snapshot(app_db, ids["user"])
    assert snapshot is not None
    assert snapshot.id == second.id
    assert snapshot.horizon_days == 90


async def test_task_status_is_persisted_as_enum_value(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)
    plan = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(), today=TODAY
    )
    await app_db.commit()

    tasks = list(await app_db.scalars(select(StudyTask).where(StudyTask.plan_id == plan.id)))
    assert all(task.status is TaskStatus.TODO for task in tasks)

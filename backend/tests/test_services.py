"""服务层测试：快照构建与计划落库。"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentConversation,
    AgentMessage,
    ExamTarget,
    ExamType,
    LearnerProfile,
    MessageRole,
    PlanStage,
    PlanStatus,
    StudyPlan,
    StudyStreak,
    StudyTask,
    Subject,
    TargetStatus,
    TaskProgress,
    TaskStatus,
    User,
)
from app.schemas import PlanDraft, TaskDraft
from app.services import (
    active_user_ids,
    collect_progress,
    collect_user_tasks,
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_plan_snapshot,
)
from app.services.conversations import load_history
from app.services.plan_edit import defer_unfinished_tasks, load_plan
from app.services.plans import persist_plan_draft
from app.services.scheduling import SLOTS, assign_slots
from app.services.snapshots import consecutive_zero_days

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


async def _seed(
    session: AsyncSession, *, idle_days: int = 0, with_streak: bool = True
) -> dict[str, int]:
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
    if with_streak:
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


async def _add_progress(
    session: AsyncSession, user_id: int, target_id: int, *, days_ago: int, minutes: int = 30
) -> None:
    """补一条 ``days_ago`` 天前的打卡记录，供断签口径用例使用。"""

    plan = StudyPlan(
        user_id=user_id,
        target_id=target_id,
        title="打卡计划",
        horizon_days=60,
        start_date=TODAY - timedelta(days=30),
        end_date=TODAY + timedelta(days=30),
    )
    session.add(plan)
    await session.flush()

    task = StudyTask(
        plan_id=plan.id,
        user_id=user_id,
        title="每日打卡任务",
        planned_date=TODAY,
    )
    session.add(task)
    await session.flush()

    session.add(
        TaskProgress(
            task_id=task.id,
            user_id=user_id,
            actual_minutes=minutes,
            created_at=datetime.combine(TODAY - timedelta(days=days_ago), time(20, 0)),
        )
    )
    await session.commit()


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


# 知识点：断签触发口径 —— 触发用「连续零投入」而非展示用的「距上次学习天数」，
#   隔三差五不打卡是自律度低用户的常态，只看后者会把提醒写成催办（第3章 Agent进阶）
async def test_consecutive_zero_days_counts_actual_study_not_idle_gap(app_db: AsyncSession) -> None:
    """旧口径看「距上次学习 5 天」会误报；新口径看打卡，2 天前学过就只算 2 天断签。"""

    ids = await _seed(app_db, idle_days=5)
    await _add_progress(app_db, ids["user"], ids["target"], days_ago=2)

    assert await consecutive_zero_days(app_db, ids["user"], today=TODAY) == 2


async def test_consecutive_zero_days_reaches_tail_of_three(app_db: AsyncSession) -> None:
    """连续 3 天零投入（第 4 天有打卡）→ 返回 3，命中预警门槛。"""

    ids = await _seed(app_db, idle_days=3)
    await _add_progress(app_db, ids["user"], ids["target"], days_ago=3)

    assert await consecutive_zero_days(app_db, ids["user"], today=TODAY) == 3


async def test_consecutive_zero_days_skips_never_started(app_db: AsyncSession) -> None:
    """无 StudyStreak（从未开始学）返回 0，即不预警——不打扰还没起步的用户。"""

    ids = await _seed(app_db, with_streak=False)

    assert await consecutive_zero_days(app_db, ids["user"], today=TODAY) == 0


async def _seed_conversation(
    session: AsyncSession, user_id: int, turns: list[tuple[MessageRole, str]]
) -> tuple[int, int]:
    """建一个会话与若干条消息，返回 ``(会话 id, 最后一条消息 id)``。"""

    conversation = AgentConversation(user_id=user_id, title="数学答疑", workflow="multi_agent_chat")
    session.add(conversation)
    await session.flush()

    last_id = 0
    for role, content in turns:
        message = AgentMessage(conversation_id=conversation.id, role=role, content=content)
        session.add(message)
        await session.flush()
        last_id = message.id

    return conversation.id, last_id


async def test_load_history_returns_previous_turns_in_order(app_db: AsyncSession) -> None:
    """历史只含本次提问之前的往来正文，按时间正序返回。"""

    ids = await _seed(app_db)
    conversation_id, current_id = await _seed_conversation(
        app_db,
        ids["user"],
        [
            (MessageRole.USER, "第一问"),
            (MessageRole.ASSISTANT, "第一答"),
            (MessageRole.USER, "第二问"),
            (MessageRole.ASSISTANT, "第二答"),
            (MessageRole.USER, "第三问"),
        ],
    )

    history = await load_history(app_db, conversation_id, 20, before_id=current_id)

    # 当前提问（第三问）被排除在外，其余按时间正序
    assert [item["content"] for item in history] == ["第一问", "第一答", "第二问", "第二答"]
    assert {item["role"] for item in history} == {"user", "assistant"}


async def test_load_history_keeps_the_nearest_turns_and_drops_tool_rows(
    app_db: AsyncSession,
) -> None:
    """条数上限从最近的往回取；工具与系统消息不进上下文预算。"""

    ids = await _seed(app_db)
    conversation_id, current_id = await _seed_conversation(
        app_db,
        ids["user"],
        [
            (MessageRole.USER, "第一问"),
            (MessageRole.ASSISTANT, "第一答"),
            (MessageRole.TOOL, "工具中间结果不该进上下文"),
            (MessageRole.SYSTEM, "系统提示不该进上下文"),
            (MessageRole.USER, "第二问"),
            (MessageRole.ASSISTANT, "第二答"),
            (MessageRole.USER, "第三问"),
        ],
    )

    history = await load_history(app_db, conversation_id, limit=2, before_id=current_id)

    assert [item["content"] for item in history] == ["第二问", "第二答"]


async def test_load_history_is_empty_for_the_first_turn(app_db: AsyncSession) -> None:
    ids = await _seed(app_db)
    conversation_id, current_id = await _seed_conversation(
        app_db, ids["user"], [(MessageRole.USER, "第一问")]
    )

    assert await load_history(app_db, conversation_id, 20, before_id=current_id) == []


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


def test_slots_assigned_from_preferred_slots() -> None:
    """偏好时段决定课表行；模型已给时段的不覆盖，也不占水线。"""

    tasks = [
        TaskDraft(title="数学精读", day_offset=0, duration_minutes=60),
        TaskDraft(title="英语阅读", day_offset=0, duration_minutes=60),
        TaskDraft(title="政治背诵", day_offset=0, duration_minutes=60, slot="晚上"),
    ]

    filled = assign_slots(tasks, ["上午", "下午", "晚上"], attention_span=60)

    assert filled == 2
    assert {task.title: task.slot for task in tasks} == {
        "数学精读": "上午",
        "英语阅读": "下午",
        "政治背诵": "晚上",
    }


def test_assign_slots_uses_attention_span_as_water_line() -> None:
    """单次专注时长就是水线高度：一个时段堆满就换行，而不是全塞进上午。"""

    tasks = [
        TaskDraft(title=f"任务{index}", day_offset=0, duration_minutes=30) for index in range(4)
    ]

    assign_slots(tasks, ["上午", "下午"], attention_span=60)

    assert [task.slot for task in tasks] == ["上午", "上午", "下午", "下午"]


def test_assign_slots_falls_back_to_all_slots_without_preference() -> None:
    """偏好为空时按 上午/下午/晚上 的默认顺序分配，而不是留空。"""

    tasks = [TaskDraft(title="真题训练", day_offset=0, duration_minutes=120)]

    assert assign_slots(tasks, []) == 1
    assert tasks[0].slot == "上午"


async def test_persist_plan_draft_fills_missing_slots(app_db: AsyncSession) -> None:
    """模型没给时段的任务，落库时按用户偏好补齐。"""

    ids = await _seed(app_db)
    profile = await app_db.scalar(
        select(LearnerProfile).where(LearnerProfile.user_id == ids["user"])
    )
    assert profile is not None
    profile.preferred_slots = ["晚上"]
    await app_db.flush()

    await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(), today=TODAY
    )
    await app_db.commit()

    tasks = list(await app_db.scalars(select(StudyTask).where(StudyTask.user_id == ids["user"])))
    assert tasks
    # 偏好只有「晚上」，因此每个任务都该落在这一行；留空会说明分配根本没跑到
    assert {task.slot for task in tasks} == {"晚上"}
    assert set(SLOTS) >= {"晚上"}


async def test_defer_moves_only_overdue_unfinished(app_db: AsyncSession) -> None:
    """顺延只收拢「已逾期且未完成」的任务，不碰今天与未来，也不碰已完成的。"""

    ids = await _seed(app_db)
    created = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(), today=TODAY
    )
    await app_db.commit()

    # 重新查一次：persist_plan_draft 返回的对象的 tasks 集合没有加载，
    # 直接访问会触发异步会话里的懒加载（MissingGreenlet）
    plan = await load_plan(app_db, created.id)
    assert plan is not None

    tasks = list(
        await app_db.scalars(
            select(StudyTask).where(StudyTask.plan_id == plan.id).order_by(StudyTask.id)
        )
    )
    overdue_todo, overdue_done, today_todo, future_todo = tasks

    overdue_todo.planned_date = TODAY - timedelta(days=3)
    overdue_done.planned_date = TODAY - timedelta(days=1)
    overdue_done.status = TaskStatus.DONE
    today_todo.planned_date = TODAY
    future_todo.planned_date = TODAY + timedelta(days=5)
    await app_db.flush()

    moved = await defer_unfinished_tasks(app_db, plan=plan, target_date=TODAY)

    assert moved == 1
    assert overdue_todo.planned_date == TODAY
    assert overdue_done.planned_date == TODAY - timedelta(days=1)
    assert future_todo.planned_date == TODAY + timedelta(days=5)

    # 收拢之后当日的 order_index 必须重排，否则会与既有任务撞号
    same_day = list(
        await app_db.scalars(
            select(StudyTask).where(StudyTask.plan_id == plan.id, StudyTask.planned_date == TODAY)
        )
    )
    assert len(same_day) == 2
    assert sorted(task.order_index for task in same_day) == [0, 1]


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


async def test_persist_plan_draft_supersedes_previous_plan(app_db: AsyncSession) -> None:
    """重新规划应归档旧计划并递增版本号，保证同一目标下只有一个 ACTIVE 计划。"""

    ids = await _seed(app_db)

    first = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(30), today=TODAY
    )
    second = await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(90), today=TODAY
    )
    await app_db.commit()

    assert first.version == 1
    assert second.version == 2
    assert first.status is PlanStatus.ARCHIVED
    assert second.status is PlanStatus.ACTIVE

    active = list(
        await app_db.scalars(
            select(StudyPlan).where(
                StudyPlan.user_id == ids["user"],
                StudyPlan.status == PlanStatus.ACTIVE,
            )
        )
    )
    assert len(active) == 1
    assert active[0].id == second.id


async def test_collect_progress_ignores_archived_plan_tasks(app_db: AsyncSession) -> None:
    """旧计划被归档后，其任务不应再计入当前进度，否则完成度会被历史任务稀释。"""

    ids = await _seed(app_db)

    await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(30), today=TODAY
    )
    await app_db.commit()
    before = await collect_progress(app_db, ids["user"], today=TODAY)
    assert before.total_tasks > 0

    await persist_plan_draft(
        app_db, user_id=ids["user"], target_id=ids["target"], draft=_draft(30), today=TODAY
    )
    await app_db.commit()
    after = await collect_progress(app_db, ids["user"], today=TODAY)

    assert after.total_tasks == before.total_tasks
    assert after.completion_rate == before.completion_rate

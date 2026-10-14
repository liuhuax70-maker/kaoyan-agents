"""计划评审测试：条件边路由、评审节点产出与工作流集成。

评审原本由 CrewAI 承担，现在收敛为图上的一个节点：
生成与评审分成两次模型调用，路由由纯函数决定，因此可以逐层单独验证。
"""

from typing import Any

from app.schemas import LearnerSnapshot, PlanDraft, PlanReviewResult, SubjectSnapshot
from app.workflows import run_workflow
from app.workflows.graph import NODE_CONFIRM, NODE_REVIEW, route_after_chat
from app.workflows.nodes import GRAPH_REVIEWER, review_plan


def _learner(attention_span: int = 60) -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        target_title="复旦计算机",
        days_left=120,
        daily_hours=5,
        attention_span=attention_span,
        self_discipline=4,
        subjects=[
            SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True),
            SubjectSnapshot(name="英语", score_weight=0.2),
        ],
    )


def _draft(task_minutes: int = 45, stages: int = 3) -> PlanDraft:
    tasks = [
        {"title": "数学第一章精读", "subject": "数学", "duration_minutes": task_minutes},
        {"title": "英语真题阅读两篇", "subject": "英语", "duration_minutes": 40},
    ]
    stage_payloads = [
        {
            "name": name,
            "stage_type": stage_type,
            "start_offset": index * 40,
            "end_offset": (index + 1) * 40,
            "focus": f"{name}阶段重点",
            "tasks": tasks,
        }
        for index, (name, stage_type) in enumerate(
            [
                ("基础夯实", "foundation"),
                ("强化提升", "enhancement"),
                ("真题冲刺", "sprint"),
            ][:stages]
        )
    ]
    return PlanDraft.model_validate(
        {
            "title": "120 天备考计划",
            "goal": "系统完成数学与英语备考并进入模考状态",
            "strategy": "分阶段推进，薄弱科目优先",
            "horizon_days": 120,
            "daily_hours": 5,
            "stages": stage_payloads,
        }
    )


def _state(learner: LearnerSnapshot, draft: PlanDraft | None = None) -> dict[str, Any]:
    return {
        "learner": learner.model_dump(mode="json"),
        "plan_draft": draft.model_dump(mode="json") if draft else None,
    }


# --------------------------------------------------------------------------
# 条件边路由
# --------------------------------------------------------------------------


def test_route_takes_review_branch_when_plan_exists_and_review_enabled() -> None:
    state = {**_state(_learner(), _draft()), "enable_review": True}
    assert route_after_chat(state) == NODE_REVIEW


def test_route_skips_review_branch() -> None:
    """开关关闭、没有计划草稿、或开关缺省时都必须跳过评审。

    跳过评审不等于跳过确认：两条分支都汇到 ``confirm_plan``，
    评审只影响用户看到的内容，不改变「要不要人工确认落库」。
    """

    state = _state(_learner(), _draft())

    assert route_after_chat({**state, "enable_review": False}) == NODE_CONFIRM
    assert route_after_chat({**state, "plan_draft": None, "enable_review": True}) == NODE_CONFIRM
    assert route_after_chat(state) == NODE_CONFIRM


# --------------------------------------------------------------------------
# 评审节点
# --------------------------------------------------------------------------


async def test_review_node_is_noop_without_a_draft() -> None:
    """没有计划草稿时节点不产出任何字段，也不应调用模型。"""

    assert await review_plan(_state(_learner())) == {}


async def test_review_node_flags_oversized_task() -> None:
    """任务时长超过单次专注时长时，应给出 high 级问题并否决计划。"""

    fragment = await review_plan(_state(_learner(attention_span=60), _draft(task_minutes=120)))

    review = PlanReviewResult.model_validate(fragment["plan_review"])
    assert review.approved is False
    assert review.blocking_issues
    assert "任务粒度" in [item.category for item in review.issues]
    assert review.score < 100
    assert review.reviewer == GRAPH_REVIEWER


async def test_review_node_approves_reasonable_plan() -> None:
    fragment = await review_plan(_state(_learner(attention_span=90), _draft(task_minutes=45)))

    review = PlanReviewResult.model_validate(fragment["plan_review"])
    assert review.approved is True
    assert review.improvements
    assert fragment["outputs"][0]["agent"] == "reviewer"
    assert fragment["events"][0]["node"] == "review_plan"


# --------------------------------------------------------------------------
# 工作流集成
# --------------------------------------------------------------------------


async def test_workflow_reviews_plan_when_enabled() -> None:
    result = await run_workflow("帮我制定复习计划", _learner(), enable_review=True)

    assert result.plan_draft is not None
    assert isinstance(result.plan_review, PlanReviewResult)
    assert result.plan_review.reviewer == GRAPH_REVIEWER
    assert "review_plan" in [item.node for item in result.events]
    assert "reviewer" in [item.agent for item in result.outputs]


async def test_workflow_skips_review_when_disabled() -> None:
    result = await run_workflow("帮我制定复习计划", _learner(), enable_review=False)

    assert result.plan_draft is not None
    assert result.plan_review is None
    assert "review_plan" not in [item.node for item in result.events]


async def test_review_not_triggered_without_plan_draft() -> None:
    """答疑类请求不产出计划，自然也不该进入评审分支。"""

    result = await run_workflow("数学的极限为什么总是算不对", _learner(), enable_review=True)

    assert result.plan_draft is None
    assert result.plan_review is None
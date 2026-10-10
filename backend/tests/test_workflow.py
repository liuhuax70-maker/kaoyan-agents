"""LangGraph 工作流测试：意图路由、并行扇出、结果渲染与流式输出。"""

import pytest

from app.schemas import (
    LearnerSnapshot,
    PlanSnapshot,
    ProgressSnapshot,
    SubjectSnapshot,
    TaskSnapshot,
)
from app.workflows import describe_workflow, run_workflow, stream_workflow


def _learner(**overrides: object) -> LearnerSnapshot:
    payload: dict[str, object] = {
        "nickname": "小研",
        "target_title": "复旦计算机",
        "days_left": 120,
        "daily_hours": 5,
        "weekly_days": 6,
        "attention_span": 60,
        "self_discipline": 4,
        "subjects": [
            SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True, difficulty=5),
            SubjectSnapshot(name="英语", score_weight=0.2),
        ],
        "progress": ProgressSnapshot(total_tasks=20, done_tasks=6, completion_rate=0.3),
    }
    payload.update(overrides)
    return LearnerSnapshot.model_validate(payload)


def _plan() -> PlanSnapshot:
    return PlanSnapshot(
        title="120 天备考规划",
        horizon_days=120,
        status="active",
        tasks=[
            TaskSnapshot(title="高数第一章精读", subject="数学", status="done"),
            TaskSnapshot(title="英语真题阅读两篇", subject="英语", status="todo"),
        ],
    )


def test_workflow_topology_is_described() -> None:
    topology = describe_workflow()
    assert topology["entry"] == "prepare_context"
    assert "run_agent" in topology["nodes"]
    assert any(edge["kind"].startswith("fan-out") for edge in topology["edges"])


async def test_plan_request_fans_out_to_planner_and_breakdown() -> None:
    """计划类请求应由规划师与拆解师并行协作。"""

    result = await run_workflow("帮我制定从现在到考试的复习计划", _learner())

    assert result.intent == "plan"
    assert "planner" in result.agents
    assert result.plan_draft is not None
    assert result.plan_draft.horizon_days == 120
    assert result.plan_draft.total_tasks > 0

    agent_keys = [item.agent for item in result.outputs]
    assert "planner" in agent_keys
    assert len(agent_keys) == len(set(agent_keys))
    assert result.reply_text()


async def test_tutoring_request_routes_to_tutor() -> None:
    result = await run_workflow("数学的极限为什么总是算不对", _learner())

    assert result.intent == "tutor"
    assert result.tutoring is not None
    assert result.tutoring.steps
    assert result.plan_draft is None


async def test_review_request_uses_plan_snapshot() -> None:
    """复盘应读取当前计划数据，而不是凭空生成。"""

    result = await run_workflow("复盘一下我现在的复习进度和风险", _learner(), _plan())

    assert result.intent == "review"
    assert result.diagnosis is not None
    assert result.diagnosis.adjustments
    assert result.diagnosis.risks


async def test_resource_request_returns_plan() -> None:
    result = await run_workflow("数学和英语该用什么资料，真题怎么刷", _learner())

    assert result.intent == "resource"
    assert result.resource is not None
    assert result.resource.items


async def test_plan_draft_targets_are_used_in_plan() -> None:
    """计划任务应落在用户填写的科目上。"""

    result = await run_workflow("制定复习计划", _learner())
    assert result.plan_draft is not None

    subjects = {task.subject for stage in result.plan_draft.stages for task in stage.tasks}
    assert {"数学", "英语"} <= subjects


async def test_stream_workflow_emits_progress_then_result() -> None:
    chunks = [chunk async for chunk in stream_workflow("帮我制定复习计划", _learner())]

    types = [item["type"] for item in chunks]
    assert types[-1] == "result"
    assert "progress" in types
    assert "output" in types

    result = chunks[-1]["result"]
    assert result["plan_draft"] is not None
    assert result["agents"]


async def test_workflow_records_events_for_each_stage() -> None:
    result = await run_workflow("帮我制定复习计划", _learner())
    nodes = [item.node for item in result.events]

    assert "prepare_context" in nodes
    assert "route_intent" in nodes
    assert "finalize" in nodes
    assert result.errors == []


@pytest.mark.parametrize(
    "request_text",
    ["帮我制定复习计划", "数学极限为什么算不对", "复盘一下进度", "用什么资料"],
)
async def test_every_intent_produces_outputs(request_text: str) -> None:
    result = await run_workflow(request_text, _learner())
    assert result.outputs
    assert all(item.summary or item.highlights for item in result.outputs)

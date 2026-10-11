"""工作流测试：聊天 Agent 的工具调度、统一总结、流式输出与计划修订。"""

import pytest

from app.agents.tools import TOOLS, TOOLS_BY_NAME
from app.schemas import (
    LearnerSnapshot,
    PlanSnapshot,
    ProgressSnapshot,
    RevisionAction,
    SubjectSnapshot,
    TaskSnapshot,
)
from app.workflows import describe_workflow, run_workflow, stream_workflow
from app.workflows.nodes import AGENT_HANDLERS


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

    assert topology["pattern"] == "subagents"
    assert topology["entry"] == "prepare_context"
    assert "chat_agent" in topology["nodes"]
    assert len(topology["tools"]) == len(TOOLS)


def test_every_tool_maps_to_a_real_subagent() -> None:
    """工具注册表与执行器必须一一对应，否则调度会静默落空。"""

    assert len(TOOLS_BY_NAME) == len(TOOLS)
    for tool in TOOLS:
        assert tool.agent in AGENT_HANDLERS, f"工具 {tool.name} 没有对应的执行器"
    assert len(AGENT_HANDLERS) == len(TOOLS)


async def test_plan_request_calls_planner_and_breakdown_tools() -> None:
    """计划类请求应由聊天 Agent 调起规划师与拆解师，并统一总结。"""

    result = await run_workflow("帮我制定从现在到考试的复习计划", _learner())

    assert result.intent == "plan"
    assert "planner" in result.agents
    assert result.plan_draft is not None
    assert result.plan_draft.horizon_days == 120
    assert result.plan_draft.total_tasks > 0

    called = {item.name for item in result.tool_calls}
    assert {"generate_plan", "breakdown_tasks"} <= called

    agent_keys = [item.agent for item in result.outputs]
    assert "planner" in agent_keys
    assert len(agent_keys) == len(set(agent_keys))

    # 每个工具调用都应留下轨迹，最后是聊天 Agent 的统一总结
    assert result.summary is not None
    assert result.reply_text().startswith(result.summary.summary)
    node_names = [item.node for item in result.events]
    assert "chat_agent" in node_names
    assert "generate_plan" in node_names


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
    assert "chat_agent" in nodes
    assert "finalize" in nodes
    assert result.errors == []


async def test_chat_agent_always_produces_a_summary() -> None:
    """无论是否调起工具，聊天 Agent 都必须给出一份总结。"""

    for request_text in ("帮我制定复习计划", "数学极限为什么算不对", "你好"):
        result = await run_workflow(request_text, _learner())
        assert result.summary is not None
        assert result.summary.summary.strip()
        assert result.reply_text().strip()


async def test_revise_request_produces_plan_revision() -> None:
    """提到「往后挪」时，聊天 Agent 应调起计划修订师而不是重排整份计划。"""

    result = await run_workflow("把没做完的任务往后挪三天", _learner(), _plan())

    assert result.plan_draft is None, "局部修订不应触发整份重排"
    assert result.plan_revision is not None
    assert result.plan_revision.ops
    assert result.plan_revision.ops[0].action is RevisionAction.SHIFT_TASKS
    assert result.plan_revision.ops[0].shift_days == 3
    assert "revise_plan" in {item.name for item in result.tool_calls}


async def test_revision_cannot_be_derived_without_a_plan() -> None:
    """没有现有计划时不产出修订提案，避免凭空改动。"""

    result = await run_workflow("把没做完的任务往后挪三天", _learner(), None)
    assert result.plan_revision is None or not result.plan_revision.ops


@pytest.mark.parametrize(
    "request_text",
    ["帮我制定复习计划", "数学极限为什么算不对", "复盘一下进度", "用什么资料"],
)
async def test_every_intent_produces_outputs(request_text: str) -> None:
    result = await run_workflow(request_text, _learner())
    assert result.outputs
    assert all(item.summary or item.highlights for item in result.outputs)

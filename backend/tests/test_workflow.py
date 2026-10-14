"""工作流测试：聊天 Agent 的工具调度、回答质量、多轮记忆、流式输出与计划修订。"""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.tools import TOOLS, TOOLS_BY_NAME
from app.prompts import trim_history
from app.schemas import (
    LearnerSnapshot,
    PlanSnapshot,
    ProgressSnapshot,
    RevisionAction,
    SubjectSnapshot,
    TaskSnapshot,
)
from app.workflows import describe_workflow, run_workflow, stream_workflow
from app.workflows.chat_agent import CHAT_AGENT_TASK
from app.workflows.nodes import AGENT_HANDLERS
from tests.fakes import message_text, recorded_requests


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
    """计划类请求应由聊天 Agent 调起规划师与拆解师，并给出完整回答。"""

    result = await run_workflow("帮我制定从现在到考试的复习计划", _learner())

    # 调度权已交给聊天 Agent，因此断言工具调用而不是旧的意图标签
    called = {item.name for item in result.tool_calls}
    assert {"generate_plan", "breakdown_tasks"} <= called
    assert "planner" in result.agents
    assert result.plan_draft is not None
    assert result.plan_draft.horizon_days == 120
    assert result.plan_draft.total_tasks > 0

    agent_keys = [item.agent for item in result.outputs]
    assert "planner" in agent_keys
    assert len(agent_keys) == len(set(agent_keys))

    # 最终回答由聊天 Agent 自己组织，且两个子智能体的正文都原样进入回答
    reply = result.reply_text()
    assert reply.strip()
    assert "阶段安排" in reply  # 规划师正文
    assert "任务清单" in reply  # 拆解师正文
    node_names = [item.node for item in result.events]
    assert "chat_agent" in node_names
    assert "generate_plan" in node_names


async def test_tutoring_request_routes_to_tutor() -> None:
    result = await run_workflow("数学的极限为什么总是算不对", _learner())

    assert [item.name for item in result.tool_calls] == ["explain_concept"]
    assert result.tutoring is not None
    assert result.tutoring.steps
    assert result.plan_draft is None


async def test_review_request_uses_plan_snapshot() -> None:
    """复盘应读取当前计划数据，而不是凭空生成。"""

    result = await run_workflow("复盘一下我现在的复习进度和风险", _learner(), _plan())

    assert [item.name for item in result.tool_calls] == ["review_progress"]
    assert result.diagnosis is not None
    assert result.diagnosis.adjustments
    assert result.diagnosis.risks


async def test_resource_request_returns_plan() -> None:
    result = await run_workflow("数学和英语该用什么资料，真题怎么刷", _learner())

    assert [item.name for item in result.tool_calls] == ["recommend_resources"]
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


async def test_chat_agent_always_produces_a_reply() -> None:
    """无论是否调起工具，聊天 Agent 都必须给出一份完整回答。"""

    for request_text in ("帮我制定复习计划", "数学极限为什么算不对", "你好"):
        result = await run_workflow(request_text, _learner())
        assert result.reply.strip()
        assert result.reply_text().strip()


async def test_tutoring_reply_keeps_steps_and_pitfalls() -> None:
    """阶段 1 的验收点：答疑回答里必须能看到解题步骤与易错点原文。

    旧实现把子智能体产出摘要成三个字段，这两段在到达用户前就丢了。
    """

    result = await run_workflow("数学极限为什么算不对", _learner())
    answer = result.tutoring
    assert answer is not None and answer.steps and answer.pitfalls

    reply = result.reply_text()
    assert answer.steps[0] in reply
    assert answer.pitfalls[0] in reply
    assert answer.followups[0] in reply


async def test_first_turn_carries_no_history_messages() -> None:
    """没有历史时，聊天 Agent 的首轮消息就是「system + 本次输入」两条。"""

    await run_workflow("数学极限为什么算不对", _learner())

    messages = recorded_requests(CHAT_AGENT_TASK)[0]
    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    assert "数学极限为什么算不对" in message_text(messages[1])


async def test_followup_turn_sees_previous_question_and_answer() -> None:
    """阶段 2 的验收点：同会话追问时，上一轮的问与答都进了模型的输入。

    追问「第二点再展开」要能指代，前提是被指代的那条回答还在上下文里。
    """

    learner = _learner()
    first = await run_workflow("数学极限为什么算不对", learner)
    previous_answer = first.reply_text()

    await run_workflow(
        "第二点再展开",
        learner,
        history=[
            {"role": "user", "content": "数学极限为什么算不对"},
            {"role": "assistant", "content": previous_answer},
        ],
    )

    messages = recorded_requests(CHAT_AGENT_TASK)[-1]
    contents = [message_text(item) for item in messages]

    # system 之后紧跟上文：先上一轮提问，再上一轮回答，最后才是本次追问
    assert "数学极限为什么算不对" in contents[1]
    assert contents[2] == previous_answer
    assert any("第二点再展开" in text for text in contents[3:])


def test_trim_history_keeps_the_most_recent_turns() -> None:
    """预算不足时从最旧的一轮开始丢，最近一轮即使单独超预算也保留。"""

    turns = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 100},
        {"role": "user", "content": "c" * 100},
    ]

    kept = trim_history(turns, char_budget=250)
    assert [item["content"][0] for item in kept] == ["b", "c"]

    # 预算比最后一条还小：仍然留下它，否则追问就没有上文可指代
    assert trim_history(turns, char_budget=10) == [turns[-1]]
    assert trim_history(turns, char_budget=0) == []


def test_trim_history_skips_blank_turns_and_keeps_order() -> None:
    turns = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "   "},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]
    assert trim_history(turns, char_budget=1000) == [turns[0], turns[2], turns[3]]


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
async def test_every_request_kind_produces_outputs(request_text: str) -> None:
    """四类典型诉求都要落到某个子智能体上，不能出现「答了但没产出」。"""

    result = await run_workflow(request_text, _learner())
    assert result.outputs
    assert all(item.summary or item.highlights for item in result.outputs)

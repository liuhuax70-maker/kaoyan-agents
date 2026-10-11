"""聊天 Agent：统一受理用户诉求，按需调用子智能体工具，最后给出总结。

这是 Subagents 模式的入口节点：用户只和聊天 Agent 对话，
各板块的专业能力一律以「工具」形式暴露，由聊天 Agent 决定调用顺序与次数。

两条执行路径：

- **真实模型**：走原生 tool calling（``bind_tools`` + ``ToolMessage`` 回灌），
  模型自行决定调哪些工具、传什么指令。
- **离线桩**：没有密钥时无法做原生工具调用，改用关键词规则挑选工具，
  等价地完成同一套调用与总结。

两条路径产出的状态结构完全一致，下游落库、SSE 与前端无需区分。
"""

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.tools import TOOLS_BY_AGENT, TOOLS_BY_NAME, SubagentTool, tool_schemas
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm import build_chat_model
from app.prompts.catalog import CHAT_AGENT_ROLE
from app.prompts.context import render_learner, render_plan
from app.schemas import ChatSummary, IntentDecision
from app.workflows.nodes import (
    AGENT_HANDLERS,
    DEFAULT_AGENTS,
    MAX_AGENTS,
    compose_summary,
    decide_intent,
    learner_of,
    plan_of,
)
from app.workflows.render import render_summary
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 4
"""单轮对话内最多允许的模型-工具往返次数，防止无限调用。"""


def _tool_event(tool: SubagentTool, status: str, detail: str) -> dict[str, Any]:
    """构造工具调用事件，供 SSE 与前端调用链展示。"""

    return {
        "node": tool.name,
        "agent": tool.agent,
        "status": status,
        "detail": detail,
        "elapsed_ms": 0,
    }


def _to_request(state: WorkflowState, instruction: str) -> WorkflowState:
    """把工具指令作为该子智能体的本次请求。"""

    return {**state, "request": instruction or state.get("request", "")}


async def _invoke_tool(
    tool: SubagentTool, instruction: str, state: WorkflowState
) -> tuple[dict[str, Any], str]:
    """执行一个子智能体工具，返回状态片段与给模型看的简报。"""

    handler = AGENT_HANDLERS.get(tool.agent)
    if handler is None:
        return {"errors": [f"工具 {tool.name} 没有对应的子智能体"]}, ""

    try:
        fragment = await handler(_to_request(state, instruction))
    except Exception as exc:  # noqa: BLE001 - 单个工具失败不应中断整体协作
        logger.exception("工具 %s 执行失败", tool.name)
        return (
            {
                "errors": [f"{tool.label} 执行失败：{exc}"],
                "events": [_tool_event(tool, "failed", str(exc))],
            },
            "",
        )

    outputs = fragment.get("outputs") or []
    brief_lines = [
        f"{tool.label}｜{item.get('title', '')}：{item.get('summary', '')}" for item in outputs
    ]
    for item in outputs:
        brief_lines.extend(f"  - {line}" for line in (item.get("highlights") or [])[:3])

    fragment["events"] = [
        *_events_of(fragment),
        _tool_event(tool, "ok", instruction or tool.description),
    ]
    return fragment, "\n".join(line for line in brief_lines if line.strip())


def _events_of(fragment: dict[str, Any]) -> list[dict[str, Any]]:
    """取出片段里已有事件，避免覆盖 handler 自己产出的事件。"""

    return list(fragment.get("events") or [])


def _merge(
    fragments: list[dict[str, Any]],
    *,
    intent: str,
    confidence: float,
    reason: str,
    tools: list[SubagentTool],
    summary: ChatSummary,
    tool_results: str,
    extra_errors: list[str] | None = None,
) -> dict[str, Any]:
    """把各工具的状态片段合并成一个可写回图状态的结果。"""

    merged: dict[str, Any] = {
        "intent": intent,
        "confidence": confidence,
        "reason": reason,
        "agents": [tool.agent for tool in tools],
        "agents_used": [tool.agent for tool in tools],
        "tool_calls": [
            {"name": tool.name, "agent": tool.agent, "label": tool.label} for tool in tools
        ],
        "tool_results": tool_results,
        "summary": summary.model_dump(mode="json"),
        "outputs": [],
        "events": [],
        "errors": list(extra_errors or []),
    }

    for fragment in fragments:
        merged["outputs"].extend(fragment.get("outputs") or [])
        merged["events"].extend(fragment.get("events") or [])
        merged["errors"].extend(fragment.get("errors") or [])
        for key in (
            "plan_draft",
            "breakdown",
            "diagnosis",
            "resource",
            "tutoring",
            "nudge",
            "plan_revision",
        ):
            if fragment.get(key) is not None:
                merged[key] = fragment[key]

    # 调度决策在工具执行之前，插到轨迹最前面才符合时间顺序
    merged["events"].insert(
        0,
        {
            "node": "chat_agent",
            "agent": "chat_agent",
            "status": "ok",
            "detail": (
                f"调用 {len(tools)} 个子智能体工具：{'、'.join(tool.label for tool in tools)}"
                if tools
                else "无需调用工具，直接回答"
            ),
            "elapsed_ms": 0,
        },
    )

    title, summary_text, highlights = render_summary(summary)
    merged["outputs"].append(
        {
            "agent": "chat_agent",
            "name": CHAT_AGENT_ROLE.name,
            "title": title,
            "summary": summary_text,
            "highlights": highlights,
            "payload": summary.model_dump(mode="json"),
        }
    )
    return merged


def _tools_for_agents(agents: list[str]) -> list[SubagentTool]:
    """把智能体标识映射成工具，顺带过滤未知项。"""

    picked: list[SubagentTool] = []
    for agent in agents:
        tool = TOOLS_BY_AGENT.get(agent)
        if tool is not None and tool not in picked:
            picked.append(tool)
    return picked


async def _run_offline(
    state: WorkflowState, extra_errors: list[str] | None = None
) -> dict[str, Any]:
    """离线路径：用关键词规则挑选工具，等价完成工具调用与总结。"""

    decision = await decide_intent(state)
    agents = decision.normalized_agents(set(AGENT_HANDLERS)) or list(DEFAULT_AGENTS)
    tools = _tools_for_agents(agents[:MAX_AGENTS])

    fragments: list[dict[str, Any]] = []
    briefs: list[str] = []
    for tool in tools:
        fragment, brief = await _invoke_tool(tool, state.get("request", ""), state)
        fragments.append(fragment)
        if brief:
            briefs.append(brief)

    tool_results = "\n".join(briefs)
    summary = await compose_summary(state, tool_results)

    return _merge(
        fragments,
        intent=decision.intent,
        confidence=decision.confidence,
        reason=decision.reason,
        tools=tools,
        summary=summary,
        tool_results=tool_results,
        extra_errors=extra_errors,
    )


def _chat_messages(state: WorkflowState) -> list[BaseMessage]:
    """组装聊天 Agent 的首轮消息。"""

    human = (
        f"【考生画像】\n{render_learner(learner_of(state))}\n\n"
        f"【当前计划】\n{render_plan(plan_of(state))}\n\n"
        f"【用户输入】\n{state.get('request', '')}"
    )
    return [SystemMessage(content=CHAT_AGENT_ROLE.system_prompt), HumanMessage(content=human)]


async def _run_tool_calling(state: WorkflowState, provider: str) -> dict[str, Any]:
    """真实模型路径：让模型自行决定调用哪些工具。"""

    model = build_chat_model("chat_agent", provider).bind_tools(tool_schemas())
    messages = _chat_messages(state)

    fragments: list[dict[str, Any]] = []
    tools: list[SubagentTool] = []
    briefs: list[str] = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = await model.ainvoke(messages)
        messages.append(reply)

        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            break

        for call in calls:
            name = str(call.get("name", ""))
            tool = TOOLS_BY_NAME.get(name)
            if tool is None:
                messages.append(
                    ToolMessage(content=f"未知工具：{name}", tool_call_id=str(call.get("id", "")))
                )
                continue

            args = call.get("args") or {}
            instruction = str(args.get("instruction") or state.get("request", ""))
            fragment, brief = await _invoke_tool(tool, instruction, state)
            fragments.append(fragment)
            tools.append(tool)
            if brief:
                briefs.append(brief)

            messages.append(
                ToolMessage(
                    content=brief or "（该工具没有返回内容）",
                    tool_call_id=str(call.get("id", "")),
                )
            )
    else:
        logger.warning("工具调用达到上限 %d 轮，强制收尾", MAX_TOOL_ROUNDS)

    tool_results = "\n".join(briefs)
    summary = await compose_summary(state, tool_results)
    intent, confidence, reason = await _describe_intent(state, tools)

    return _merge(
        fragments,
        intent=intent,
        confidence=confidence,
        reason=reason,
        tools=tools,
        summary=summary,
        tool_results=tool_results,
    )


async def _describe_intent(
    state: WorkflowState, tools: list[SubagentTool]
) -> tuple[str, float, str]:
    """回填意图字段；工具为空时退回协调者判定。"""

    if not tools:
        decision: IntentDecision = await decide_intent(state)
        return decision.intent, decision.confidence, decision.reason

    names = "、".join(tool.label for tool in tools)
    return "chat", 0.8, f"聊天 Agent 调用了：{names}"


async def chat_agent(state: WorkflowState) -> dict[str, Any]:
    """聊天 Agent 节点：调度工具并产出统一总结。"""

    provider = state.get("provider") or get_settings().llm.default_provider
    if provider == "stub":
        return await _run_offline(state)

    try:
        return await _run_tool_calling(state, provider)
    except Exception as exc:  # noqa: BLE001 - 工具调用不可用时必须仍能给出回答
        logger.warning("原生工具调用失败，回退到离线调度：%s", exc)
        return await _run_offline(state, extra_errors=[f"工具调用降级：{exc}"])


def describe_chat_agent() -> dict[str, Any]:
    """返回聊天 Agent 的调度契约，供文档与自省接口使用。"""

    return {
        "role": CHAT_AGENT_ROLE.key,
        "name": CHAT_AGENT_ROLE.name,
        "max_tool_rounds": MAX_TOOL_ROUNDS,
        "max_tools_per_turn": MAX_AGENTS,
        "tools": [tool.name for tool in TOOLS_BY_NAME.values()],
    }

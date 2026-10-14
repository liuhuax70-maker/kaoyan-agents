# 知识点：Subagents 模式 —— 主 Agent 不实现任何专业能力，只持有「派给谁」的工具，
#   子智能体之间互不可见，上下文隔离靠工具边界而不是靠提示词约定（第3章 Agent进阶·Multi Agent）
"""聊天 Agent：统一受理用户诉求，按需调用子智能体工具，最终由它自己作答。

这是 Subagents 模式的入口节点：用户只和聊天 Agent 对话，
各板块的专业能力一律以「工具」形式暴露，由聊天 Agent 决定调用顺序与次数。

调用走原生 tool calling：模型返回 ``tool_calls`` → 本地执行 → 结果以 ``ToolMessage``
回灌 → 模型继续决策，直到不再请求工具为止。

最终回答取自模型自己的输出，不再另发一次请求做「总结」：子智能体已经给出完整正文，
再摘要一遍只会把内容压掉。
"""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.config import get_stream_writer

from app.agents.tools import TOOLS_BY_NAME, SubagentTool, tool_schemas
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm import build_chat_model, message_text
from app.prompts.catalog import CHAT_AGENT_ROLE
from app.prompts.context import render_learner, render_plan, trim_history
from app.workflows.nodes import AGENT_HANDLERS, SubagentOutcome, learner_of, plan_of
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

CHAT_AGENT_TASK = "chat_agent"
"""聊天 Agent 在模型适配层的任务标识，区别于需要结构化输出的子智能体任务。"""

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


# 知识点：错误回灌给 LLM —— 工具抛错不是流程中断信号，而是一条要交回模型的消息；
#   模型因此可以改派别的工具或如实告知用户，异常分层止步于工具边界（第3章 Agent进阶·工具可靠性）
async def _invoke_tool(
    tool: SubagentTool, instruction: str, state: WorkflowState
) -> SubagentOutcome:
    """执行一个子智能体工具，返回状态片段与回灌给模型的正文。

    单个工具失败不中断整体协作：失败信息本身也是一条要回灌给模型的消息，
    模型可以据此改派其他工具或直接向用户说明。
    """

    handler = AGENT_HANDLERS.get(tool.agent)
    if handler is None:
        return (
            {"errors": [f"工具 {tool.name} 没有对应的子智能体"]},
            f"{tool.label}不可用：没有登记对应的子智能体。",
        )

    try:
        return await handler(_to_request(state, instruction))
    except Exception as exc:  # noqa: BLE001 - 单个工具失败不应中断整体协作
        logger.exception("工具 %s 执行失败", tool.name)
        return (
            {
                "errors": [f"{tool.label} 执行失败：{exc}"],
                "events": [_tool_event(tool, "failed", str(exc))],
            },
            f"{tool.label}执行失败：{exc}。请改用其他方式回答用户，或如实说明该能力暂不可用。",
        )


def _events_of(fragment: dict[str, Any]) -> list[dict[str, Any]]:
    """取出片段里已有事件，避免覆盖 handler 自己产出的事件。"""

    return list(fragment.get("events") or [])


def _merge(
    fragments: list[dict[str, Any]],
    *,
    tools: list[SubagentTool],
    reply: str,
) -> dict[str, Any]:
    # 知识点：状态字段的 reducer 契约 —— 带 Annotated[list, operator.add] 的字段由节点
    #   返回「增量」，节点只给本回合新增的部分，累加交给 reducer（第5章 LangGraph·基本概念）
    """把各工具的状态片段合并成一个可写回图状态的结果。"""

    merged: dict[str, Any] = {
        # intent / confidence 已随 Orchestrator 一起删除：调用链的权威来源是
        # tool_calls（含工具名与智能体标识），再由它派生一个字段只会两处漂移。
        "reason": (
            f"聊天 Agent 调用了：{'、'.join(tool.label for tool in tools)}"
            if tools
            else "无需调用工具，直接回答"
        ),
        "agents": [tool.agent for tool in tools],
        "agents_used": [tool.agent for tool in tools],
        "tool_calls": [
            {"name": tool.name, "agent": tool.agent, "label": tool.label} for tool in tools
        ],
        "reply": reply,
        "outputs": [],
        "events": [],
        "errors": [],
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
            "school_advice",
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
    return merged


def _history_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    """把历史轮次还原成对话消息。

    历史以真实的消息序列插入，而不是塞进一段文本块：模型对「谁说的」
    有原生区分能力，追问时的指代才稳得住。
    """

    restored: list[BaseMessage] = []
    for item in history:
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        if str(item.get("role") or "").lower() == "assistant":
            restored.append(AIMessage(content=text))
        else:
            restored.append(HumanMessage(content=text))
    return restored


# 知识点：对话记忆的注入位置 —— system 定人格、历史给上文、human 是本次输入，
#   三者顺序固定；历史被裁剪但最近一轮永远保留（第3章 Agent进阶·记忆）
def _chat_messages(state: WorkflowState) -> list[BaseMessage]:
    """组装聊天 Agent 的首轮消息：system → 历史轮次 → 本次输入。"""

    human = (
        f"【考生画像】\n{render_learner(learner_of(state))}\n\n"
        f"【当前计划】\n{render_plan(plan_of(state))}\n\n"
        f"【用户输入】\n{state.get('request', '')}"
    )
    history = trim_history(
        state.get("history") or [],
        get_settings().workflow.history_char_budget,
    )
    return [
        SystemMessage(content=CHAT_AGENT_ROLE.system_prompt),
        *_history_messages(history),
        HumanMessage(content=human),
    ]


# 知识点：自定义流 —— 节点内部的增量不走 State，而是通过 get_stream_writer 直接
#   推给调用方；State 仍只在节点边界整块更新，两条通道互不干扰（第5章 LangGraph·流式）
def _stream_writer() -> Callable[[Any], None]:
    """取到 langgraph 的自定义流写入器，取不到时退化成空操作。

    非流式入口（``ainvoke``）下 ``get_stream_writer`` 返回的已是空操作函数；
    只有在脱离图运行上下文直接调用本模块处理器时它才会抛错，这里兜住那一层。
    """

    try:
        return get_stream_writer()
    except RuntimeError:
        return lambda _payload: None


async def _stream_answer(
    model: Any, messages: list[BaseMessage], write: Callable[[Any], None]
) -> tuple[BaseMessage, str]:
    """流式索取一次模型输出：边收增量边推 token 事件。

    返回完整消息与其正文投影：消息（含 ``tool_calls``）要回填进对话历史，
    正文只是给用户看的那部分。
    """

    accumulated: BaseMessage | None = None
    parts: list[str] = []

    async for chunk in model.astream(messages):
        accumulated = chunk if accumulated is None else accumulated + chunk
        delta = message_text(chunk)
        if delta:
            parts.append(delta)
            write({"type": "token", "text": delta})

    if accumulated is None:  # pragma: no cover - 空流说明提供方行为异常
        raise RuntimeError("模型流式输出为空，无法继续本轮对话")

    return accumulated, "".join(parts).strip()


# 知识点：自主循环的硬边界 —— Agent 自己决定循环何时结束，就必须由代码兜住
#   「模型永远不停」这一情况，触边后降级为不带工具的一次调用（第3章 Agent进阶·Multi Agent）
async def _force_final_answer(
    model: Any, messages: list[BaseMessage], write: Callable[[Any], None]
) -> str:
    """轮次耗尽时再要一次纯文本回答。

    此时已经不再给模型新信息，只是明确告知「不允许再调工具」。
    模型若仍执意请求工具，就返回空串，由 ``WorkflowResult.reply_text`` 兜底拼接各子智能体产出。
    """

    nudge = HumanMessage(
        content="工具调用已达轮次上限。请立即基于以上结果直接输出面向用户的完整回答，不要再请求工具。"
    )
    _, text = await _stream_answer(model, [*messages, nudge], write)
    return text


async def _run_tool_calling(state: WorkflowState, provider: str) -> dict[str, Any]:
    # 知识点：bind_tools + ToolMessage 回灌 —— 工具调用是「模型出参数、本地执行、
    #   结果再作为一条消息回到历史」，模型据此继续决策，循环由轮次上限兜底
    #   （第2章 LangChain核心组件·工具调用）
    """让模型自行决定调用哪些工具，直到它不再请求工具为止。

    每一轮都走流式：工具轮通常没有正文，因此不会往外推 token；
    模型真正开口的那一轮，用户就能逐字看到回答。
    """

    write = _stream_writer()
    model = build_chat_model(CHAT_AGENT_TASK, provider).bind_tools(tool_schemas())
    messages = _chat_messages(state)

    fragments: list[dict[str, Any]] = []
    tools: list[SubagentTool] = []
    reply_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        current, text = await _stream_answer(model, messages, write)
        messages.append(current)

        calls = getattr(current, "tool_calls", None) or []
        if not calls:
            # 模型自己开口了：这就是最终回答
            reply_text = text
            break

        for call in calls:
            name = str(call.get("name", ""))
            tool_call_id = str(call.get("id", ""))
            tool = TOOLS_BY_NAME.get(name)
            if tool is None:
                messages.append(
                    ToolMessage(content=f"未知工具：{name}", tool_call_id=tool_call_id)
                )
                continue

            # 调用链直接由这里给出，前端不必再拿事件里的 node 名去猜调了哪个工具
            write(
                {
                    "type": "tool_call",
                    "name": tool.name,
                    "agent": tool.agent,
                    "label": tool.label,
                }
            )

            args = call.get("args") or {}
            instruction = str(args.get("instruction") or state.get("request", ""))
            fragment, narrative = await _invoke_tool(tool, instruction, state)
            fragments.append(fragment)
            tools.append(tool)

            fragment["events"] = [
                *_events_of(fragment),
                _tool_event(tool, "ok", instruction or tool.description),
            ]
            # 回灌的是子智能体的完整正文而非摘要：模型据此作答时能看到解题步骤与易错点原文
            body = narrative.strip() or "（该工具没有返回内容）"
            messages.append(
                ToolMessage(content=f"【{tool.label}】\n{body}", tool_call_id=tool_call_id)
            )
    else:
        logger.warning("工具调用达到上限 %d 轮，强制收尾", MAX_TOOL_ROUNDS)
        reply_text = await _force_final_answer(model, messages, write)

    return _merge(fragments, tools=tools, reply=reply_text)


async def chat_agent(state: WorkflowState) -> dict[str, Any]:
    """聊天 Agent 节点：调度工具并给出最终回答。

    模型不可用时直接抛出：宁可让请求失败并暴露配置问题，
    也不要用一份看起来正常的假回答掩盖故障。
    """

    provider = state.get("provider") or get_settings().llm.default_provider
    return await _run_tool_calling(state, provider)


def describe_chat_agent() -> dict[str, Any]:
    """返回聊天 Agent 的调度契约，供文档与自省接口使用。"""

    return {
        "role": CHAT_AGENT_ROLE.key,
        "name": CHAT_AGENT_ROLE.name,
        "max_tool_rounds": MAX_TOOL_ROUNDS,
        "tools": [tool.name for tool in TOOLS_BY_NAME.values()],
    }
"""LangGraph 工作流装配。

拓扑：prepare_context → chat_agent → finalize

聊天 Agent 是唯一的调度者，各板块的专业能力以「工具」形式暴露给它：
调用哪些工具、按什么顺序、各调用几次，都由聊天 Agent 在节点内部决定，
图本身保持线性，不再用 Send 做静态扇出。
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.tools import describe_tools
from app.workflows.chat_agent import MAX_TOOL_ROUNDS, chat_agent
from app.workflows.nodes import finalize, prepare_context
from app.workflows.state import WorkflowState


def build_workflow() -> CompiledStateGraph:
    """构建并编译聊天 Agent 工作流。"""

    builder = StateGraph(WorkflowState)
    builder.add_node("prepare_context", prepare_context)
    builder.add_node("chat_agent", chat_agent)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "prepare_context")
    builder.add_edge("prepare_context", "chat_agent")
    builder.add_edge("chat_agent", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


@lru_cache(maxsize=1)
def get_workflow() -> CompiledStateGraph:
    """返回进程内复用的编译结果。"""

    return build_workflow()


def describe_workflow() -> dict[str, Any]:
    """返回工作流拓扑与可用工具，供文档与自省接口使用。"""

    return {
        "pattern": "subagents",
        "entry": "prepare_context",
        "nodes": ["prepare_context", "chat_agent", "finalize"],
        "edges": [
            {"from": "prepare_context", "to": "chat_agent", "kind": "sequential"},
            {"from": "chat_agent", "to": "finalize", "kind": "sequential"},
            {"from": "finalize", "to": "END", "kind": "sequential"},
        ],
        "tools": describe_tools(),
        "max_tool_rounds": MAX_TOOL_ROUNDS,
    }

"""LangGraph 工作流装配。

拓扑：prepare_context → route_intent →（Send 并行分发）→ run_agent × N → finalize
使用 Send 实现动态扇出：由协调者决定本轮有哪几个智能体参与，而不是固定流水线。
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.workflows.nodes import finalize, prepare_context, route_intent, run_agent
from app.workflows.state import WorkflowState

DEFAULT_AGENTS = ("tutor",)


def dispatch_agents(state: WorkflowState) -> list[Send]:
    """按调度结果把本轮请求分发给多个智能体并行执行。"""

    agents = state.get("agents") or list(DEFAULT_AGENTS)
    payload: dict[str, Any] = {
        "request": state.get("request", ""),
        "learner": state.get("learner") or {},
        "plan": state.get("plan"),
        "intent": state.get("intent", "chat"),
        "provider": state.get("provider"),
    }
    return [Send("run_agent", {**payload, "agent_key": key}) for key in agents]


def build_workflow() -> CompiledStateGraph:
    """构建并编译多智能体协作图。"""

    builder = StateGraph(WorkflowState)
    builder.add_node("prepare_context", prepare_context)
    builder.add_node("route_intent", route_intent)
    builder.add_node("run_agent", run_agent)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "prepare_context")
    builder.add_edge("prepare_context", "route_intent")
    builder.add_conditional_edges("route_intent", dispatch_agents, ["run_agent"])
    builder.add_edge("run_agent", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


@lru_cache(maxsize=1)
def get_workflow() -> CompiledStateGraph:
    """返回进程内复用的编译结果。"""

    return build_workflow()


def describe_workflow() -> dict[str, Any]:
    """返回工作流拓扑描述，供文档与调试使用。"""

    return {
        "entry": "prepare_context",
        "nodes": ["prepare_context", "route_intent", "run_agent", "finalize"],
        "edges": [
            {"from": "prepare_context", "to": "route_intent", "kind": "sequential"},
            {"from": "route_intent", "to": "run_agent", "kind": "fan-out (Send)"},
            {"from": "run_agent", "to": "finalize", "kind": "fan-in"},
            {"from": "finalize", "to": "END", "kind": "sequential"},
        ],
    }

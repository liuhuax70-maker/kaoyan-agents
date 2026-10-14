# 知识点：StateGraph 装配与条件边 —— add_conditional_edges 把「下一步走哪」抽成纯函数，
#   图结构因此是静态可画的，分支逻辑可单独测试（第5章 LangGraph·基本概念）
"""LangGraph 工作流装配。

拓扑：prepare_context → chat_agent ─┬→ review_plan → confirm_plan → finalize
                                    └→ confirm_plan → finalize

聊天 Agent 是唯一的调度者，各板块的专业能力以「工具」形式暴露给它：
调用哪些工具、按什么顺序、各调用几次，都由聊天 Agent 在节点内部决定，
图本身只保留「要不要评审」这一处分支，以及落库前的确认闸门。
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.tools import describe_tools
from app.workflows.chat_agent import MAX_TOOL_ROUNDS, chat_agent
from app.workflows.checkpoint import get_checkpointer
from app.workflows.nodes import confirm_plan, finalize, prepare_context, review_plan
from app.workflows.state import WorkflowState

NODE_PREPARE = "prepare_context"
NODE_CHAT = "chat_agent"
NODE_REVIEW = "review_plan"
NODE_CONFIRM = "confirm_plan"
NODE_FINALIZE = "finalize"


def route_after_chat(state: WorkflowState) -> str:
    """聊天 Agent 之后是否走评审分支。

    只做一件事：读状态判断该走哪条边。判定函数写成纯函数，
    既不调模型也不碰数据库，因此可以直接单测。

    两条分支都汇到 ``confirm_plan``：评审只影响用户看到的内容，
    不改变「要不要人工确认」这件事。
    """

    if state.get("enable_review") and state.get("plan_draft"):
        return NODE_REVIEW
    return NODE_CONFIRM


def build_workflow(checkpointer: Any = None) -> CompiledStateGraph:
    """构建并编译聊天 Agent 工作流。

    传 ``checkpointer`` 时图具备「暂停—恢复」能力；不传则是一次直跑，
    代价是不需要任何持久化，绝大多数单测走的都是这条路。
    """

    builder = StateGraph(WorkflowState)
    builder.add_node(NODE_PREPARE, prepare_context)
    builder.add_node(NODE_CHAT, chat_agent)
    builder.add_node(NODE_REVIEW, review_plan)
    builder.add_node(NODE_CONFIRM, confirm_plan)
    builder.add_node(NODE_FINALIZE, finalize)

    builder.add_edge(START, NODE_PREPARE)
    builder.add_edge(NODE_PREPARE, NODE_CHAT)
    builder.add_conditional_edges(
        NODE_CHAT,
        route_after_chat,
        {NODE_REVIEW: NODE_REVIEW, NODE_CONFIRM: NODE_CONFIRM},
    )
    builder.add_edge(NODE_REVIEW, NODE_CONFIRM)
    builder.add_edge(NODE_CONFIRM, NODE_FINALIZE)
    builder.add_edge(NODE_FINALIZE, END)

    return builder.compile(checkpointer=checkpointer)


@lru_cache(maxsize=1)
def get_workflow() -> CompiledStateGraph:
    """返回进程内复用的编译结果（无检查点）。"""

    return build_workflow()


# 知识点：Checkpointer 与 thread_id —— 检查点让「暂停—恢复」跨请求成立：中断时状态按
#   thread_id 归档，恢复请求只要带上同一个 thread_id 就能从断点续跑
#   （第5章 LangGraph·人工确认）
async def get_checkpointed_workflow() -> CompiledStateGraph:
    """返回挂了检查点的编译结果，供需要人工确认的调用方使用。

    刻意不做进程级缓存：编译本身只是搭对象，相比一次模型调用可以忽略，
    而缓存会让「检查点实现被替换」（测试注入）留下一个指向旧实现的编译结果。
    """

    return build_workflow(await get_checkpointer())


def describe_workflow() -> dict[str, Any]:
    """返回工作流拓扑与可用工具，供文档与自省接口使用。"""

    return {
        "pattern": "subagents",
        "entry": NODE_PREPARE,
        "nodes": [NODE_PREPARE, NODE_CHAT, NODE_REVIEW, NODE_CONFIRM, NODE_FINALIZE],
        "edges": [
            {"from": NODE_PREPARE, "to": NODE_CHAT, "kind": "sequential"},
            {"from": NODE_CHAT, "to": NODE_REVIEW, "kind": "conditional"},
            {"from": NODE_CHAT, "to": NODE_CONFIRM, "kind": "conditional"},
            {"from": NODE_REVIEW, "to": NODE_CONFIRM, "kind": "sequential"},
            {"from": NODE_CONFIRM, "to": NODE_FINALIZE, "kind": "sequential"},
            {"from": NODE_FINALIZE, "to": "END", "kind": "sequential"},
        ],
        "tools": describe_tools(),
        "max_tool_rounds": MAX_TOOL_ROUNDS,
    }
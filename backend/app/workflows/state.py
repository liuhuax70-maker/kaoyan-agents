# 知识点：State + Reducer —— 状态是节点之间唯一的通信通道；同一字段被多个分支写入时，
#   合并规则由字段上的 Annotated[type, reducer] 决定，而不是由写入方决定
#   （第5章 LangGraph·基本概念）
"""LangGraph 工作流状态定义。

状态刻意保持纯净：只承载数据，不做数据库读写。
落库由服务层在图执行完成后统一处理，这样工作流本身可脱离数据库单测。

字段取舍遵循「下游需要就存、能推导就不存」：输出类字段一律带累加 reducer，
节点只需返回自己新增的那部分，不必读改写整份列表。
"""

import operator
from typing import Annotated, Any, TypedDict


class WorkflowState(TypedDict, total=False):
    """多智能体协作的状态。"""

    # ---- 输入 ----
    request: str
    """用户本次输入。"""

    learner: dict[str, Any]
    """LearnerSnapshot 的序列化结果。"""

    plan: dict[str, Any] | None
    """PlanSnapshot 的序列化结果。"""

    provider: str | None
    """覆盖默认大模型提供方，缺省读取配置。"""

    enable_retrieval: bool
    """本次请求是否启用知识库检索增强。"""

    enable_review: bool
    """本次请求是否在计划产出后触发评审。"""

    confirm_commit: bool
    """本次请求是否在计划落库前暂停等待人工确认。

    与 ``enable_review`` 一样是**写进状态的显式开关**：确认节点只读状态，
    不回头查配置，这样同一份状态回放出来的路径永远一致。
    """

    # 知识点：对话记忆的载体 —— 多轮上文是一份「状态输入」而不是节点的私有缓存：
#   由调用方从会话记录里取好再喂进来，图本身不读数据库，记忆有无都能脱离库单测
#   （第3章 Agent进阶·记忆）
    history: list[dict[str, str]]
    """同一会话中被裁剪后的历史轮次，按时间正序，每项形如 ``{"role": ..., "content": ...}``。

    只放「用户与助手」的往来正文，不放工具调用与中间产出：
    追问需要的是上文说过什么，而不是当时调了哪些工具。
    """

    # ---- 调度决策 ----
    agents: list[str]
    reason: str

    reply: str
    """聊天 Agent 面向用户的最终回答正文。"""

    # ---- 工具调用轨迹 ----
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    """聊天 Agent 依次调起的子智能体工具，供前端展示调用链。"""

    agents_used: Annotated[list[str], operator.add]
    """实际执行过的子智能体标识，按调用顺序累加。"""

    # ---- 子智能体产物 ----
    plan_draft: dict[str, Any] | None
    breakdown: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    resource: dict[str, Any] | None
    tutoring: dict[str, Any] | None
    nudge: dict[str, Any] | None
    plan_revision: dict[str, Any] | None
    plan_review: dict[str, Any] | None
    """PlanReviewResult 的序列化结果。"""

    # ---- 汇总输出（按 reducer 合并）----
    outputs: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]
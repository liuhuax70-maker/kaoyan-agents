"""LangGraph 工作流状态定义。

状态刻意保持纯净：只承载数据，不做数据库读写。
落库由服务层在图执行完成后统一处理，这样工作流本身可脱离数据库单测。

拓扑已从「Send 并行扇出」改为「聊天 Agent 串行调用子智能体工具」，
因此这里记录的是工具调用轨迹与统一总结，而不是各分支的独立产物键。
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

    # ---- 调度决策 ----
    intent: str
    agents: list[str]
    confidence: float
    reason: str

    # ---- 工具调用轨迹 ----
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    """聊天 Agent 依次调起的子智能体工具，供前端展示调用链。"""

    tool_results: str
    """子智能体产出的可读汇总，作为总结环节的输入。"""

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

    # ---- 统一总结 ----
    summary: dict[str, Any] | None
    """ChatSummary 的序列化结果。"""

    # ---- 汇总输出（按 reducer 合并）----
    outputs: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]

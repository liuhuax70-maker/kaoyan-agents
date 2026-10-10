"""LangGraph 工作流状态定义。

状态刻意保持纯净：只承载数据，不做数据库读写。
落库由服务层在图执行完成后统一处理，这样工作流本身可脱离数据库单测。
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

    # ---- 各智能体产物 ----
    agent_key: str
    """当前分支正在执行的智能体，用于 Send 分发。"""

    plan_draft: dict[str, Any] | None
    breakdown: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    resource: dict[str, Any] | None
    tutoring: dict[str, Any] | None
    nudge: dict[str, Any] | None

    # ---- 汇总输出（多分支按 reducer 合并）----
    outputs: Annotated[list[dict[str, Any]], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]

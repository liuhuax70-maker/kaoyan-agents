"""工作流编排的输入输出模型。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.diagnosis import DiagnosisReport
from app.schemas.nudge import NudgeMessage, WeeklyDigest
from app.schemas.plan import PlanDraft, TaskBreakdown
from app.schemas.resource import ResourcePlan
from app.schemas.review import PlanReviewResult
from app.schemas.revision import PlanRevision
from app.schemas.school import SchoolAdvisorAnswer
from app.schemas.tutoring import TutoringAnswer


class ToolCallRecord(BaseModel):
    """聊天 Agent 的一次工具调用，用于前端展示调用链。"""

    name: str
    agent: str
    label: str = ""


class AgentOutput(BaseModel):
    """单个智能体的展示结果，供前端直接渲染。"""

    agent: str
    name: str
    title: str
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict, description="结构化原始结果")


class WorkflowEvent(BaseModel):
    """工作流执行轨迹，用于前端进度展示与问题排查。"""

    node: str
    agent: str = ""
    status: str = "ok"
    detail: str = ""
    elapsed_ms: int = 0


class PlanConfirmation(BaseModel):
    """计划落库前的人工确认请求。

    它同时也是 ``interrupt()`` 的载荷：图暂停时交出的就是这份内容，
    用户答复后由同一个 thread 恢复。
    """

    kind: Literal["plan_draft", "plan_revision"] = Field(description="待确认的产物类型")
    title: str = ""
    summary: str = ""
    items: list[str] = Field(default_factory=list, description="变更要点，供用户逐条核对")
    plan_id: int | None = Field(default=None, description="修订类产物对应的既有计划 ID")
    thread_id: str = Field(default="", description="恢复该次中断所需的检查点线程标识")


class WorkflowResult(BaseModel):
    """一次多智能体协作的完整结果。"""

    agents: list[str] = Field(default_factory=list)
    outputs: list[AgentOutput] = Field(default_factory=list)

    tool_calls: list[ToolCallRecord] = Field(
        default_factory=list, description="聊天 Agent 依次调起的子智能体工具"
    )
    reply: str = Field(default="", description="聊天 Agent 面向用户的最终回答正文")

    plan_draft: PlanDraft | None = None
    breakdown: TaskBreakdown | None = None
    diagnosis: DiagnosisReport | None = None
    resource: ResourcePlan | None = None
    tutoring: TutoringAnswer | None = None
    nudge: NudgeMessage | None = None
    digest: WeeklyDigest | None = None
    plan_revision: PlanRevision | None = None
    school_advice: SchoolAdvisorAnswer | None = None
    plan_review: PlanReviewResult | None = None

    confirmation: PlanConfirmation | None = Field(
        default=None, description="图在落库前暂停时交出的待确认内容"
    )

    errors: list[str] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)
    trace_id: str | None = Field(default=None, description="LangFuse 追踪 ID")
    trace_url: str | None = Field(default=None, description="LangFuse 追踪链接")

    @property
    def awaiting_confirmation(self) -> bool:
        """本次执行是否停在人工确认上、尚未写库。"""

        return self.confirmation is not None

    @property
    def has_plan(self) -> bool:
        """是否产出了可落库的学习计划。"""

        return self.plan_draft is not None

    @property
    def has_plan_revision(self) -> bool:
        """是否产出了可落库的计划修订。"""

        return self.plan_revision is not None and bool(self.plan_revision.ops)

    # 知识点：LLM 节点的输出即最终产物 —— 模型用自然语言给出的回答不该被确定性代码
    #   再压缩一遍，代码只在模型没开口时兜底，而不是替模型组织语言（第2章 LangChain核心组件·模型）
    def reply_text(self) -> str:
        """生成回复正文。

        以聊天 Agent 自己的输出为准；模型没有给出正文时（例如调用被中断），
        退回逐段拼接各子智能体的产出，保证用户总能看到内容。
        """

        if self.reply.strip():
            return self.reply

        if not self.outputs:
            return "暂时无法生成建议，请补充更具体的备考问题。"

        parts = []
        if len(self.outputs) > 1:
            names = "、".join(f"「{item.name}」" for item in self.outputs)
            parts.append(f"已调度 {names} 协同处理你的问题。")

        for item in self.outputs:
            parts.append(f"### {item.name}｜{item.title}")
            if item.summary:
                parts.append(item.summary)
            parts.extend(f"- {line}" for line in item.highlights)

        return "\n\n".join(parts)

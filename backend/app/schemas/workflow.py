"""工作流编排的输入输出模型。"""

from pydantic import BaseModel, Field

from app.schemas.diagnosis import DiagnosisReport
from app.schemas.nudge import NudgeMessage, WeeklyDigest
from app.schemas.plan import PlanDraft, TaskBreakdown
from app.schemas.resource import ResourcePlan
from app.schemas.review import PlanReviewResult
from app.schemas.revision import ChatSummary, PlanRevision
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


class WorkflowResult(BaseModel):
    """一次多智能体协作的完整结果。"""

    intent: str = "chat"
    confidence: float = Field(default=0.0, ge=0, le=1)
    agents: list[str] = Field(default_factory=list)
    outputs: list[AgentOutput] = Field(default_factory=list)

    tool_calls: list[ToolCallRecord] = Field(
        default_factory=list, description="聊天 Agent 依次调起的子智能体工具"
    )
    summary: ChatSummary | None = Field(default=None, description="聊天 Agent 的统一总结")

    plan_draft: PlanDraft | None = None
    breakdown: TaskBreakdown | None = None
    diagnosis: DiagnosisReport | None = None
    resource: ResourcePlan | None = None
    tutoring: TutoringAnswer | None = None
    nudge: NudgeMessage | None = None
    digest: WeeklyDigest | None = None
    plan_revision: PlanRevision | None = None
    plan_review: PlanReviewResult | None = None

    errors: list[str] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)
    trace_id: str | None = Field(default=None, description="LangFuse 追踪 ID")
    trace_url: str | None = Field(default=None, description="LangFuse 追踪链接")

    @property
    def has_plan(self) -> bool:
        """是否产出了可落库的学习计划。"""

        return self.plan_draft is not None

    @property
    def has_plan_revision(self) -> bool:
        """是否产出了可落库的计划修订。"""

        return self.plan_revision is not None and bool(self.plan_revision.ops)

    def reply_text(self) -> str:
        """生成回复正文。

        聊天 Agent 模式下以统一总结为准；没有总结时退回逐段拼接各智能体产出。
        """

        if self.summary is not None:
            parts = [self.summary.summary]
            parts.extend(f"- {line}" for line in self.summary.key_points)
            if self.summary.next_actions:
                parts.append("**建议下一步**")
                parts.extend(f"- {line}" for line in self.summary.next_actions)
            text = "\n\n".join(part for part in parts if part.strip())
            if text.strip():
                return text

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

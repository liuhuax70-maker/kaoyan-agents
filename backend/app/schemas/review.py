"""计划评审协作的结构化输出。"""

from typing import Literal

from pydantic import BaseModel, Field

IssueSeverity = Literal["low", "medium", "high"]


class PlanReviewIssue(BaseModel):
    """评审发现的问题。"""

    severity: IssueSeverity = "medium"
    category: str = Field(default="", max_length=32, description="问题类别，如 任务粒度 / 时间分配")
    detail: str = Field(min_length=2, max_length=300, description="问题描述，须引用具体数据")
    suggestion: str = Field(default="", max_length=300, description="可执行的修改建议")


class PlanReviewResult(BaseModel):
    """计划评审结论。

    由工作流的 ``review_plan`` 节点独立产出：生成与评审分成两次模型调用，
    避免模型在同一段上下文里既当作者又当裁判。
    """

    approved: bool = Field(default=False, description="是否可以直接执行")
    score: int = Field(default=60, ge=0, le=100, description="计划质量评分")
    summary: str = Field(default="", max_length=300, description="一句话评审结论")
    issues: list[PlanReviewIssue] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list, description="修订后的改进要点")
    reviewer: str = Field(default="", max_length=64, description="产出该结论的协作模式")

    @property
    def blocking_issues(self) -> list[PlanReviewIssue]:
        """阻断性问题。"""

        return [item for item in self.issues if item.severity == "high"]

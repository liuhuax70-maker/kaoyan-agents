"""复盘诊断智能体的结构化输出。"""

from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]


class RiskItem(BaseModel):
    """识别出的备考风险。"""

    level: RiskLevel = "medium"
    title: str = Field(min_length=2, max_length=60)
    detail: str = Field(default="", max_length=300, description="风险依据，需引用具体数据")
    suggestion: str = Field(default="", max_length=300, description="可立即执行的调整动作")


class DiagnosisReport(BaseModel):
    """备考体检报告。"""

    summary: str = Field(min_length=2, max_length=400, description="一句话结论")
    completion_rate: float = Field(default=0.0, ge=0, le=1, description="当前整体完成度")
    discipline_score: int = Field(default=3, ge=1, le=5, description="执行稳定性评分")
    findings: list[str] = Field(default_factory=list, description="客观发现，每条须带数据")
    risks: list[RiskItem] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list, description="本周具体调整动作")
    encouragement: str = Field(default="", max_length=200, description="一句鼓励，避免空泛")

    @property
    def high_risks(self) -> list[RiskItem]:
        """高风险项。"""

        return [item for item in self.risks if item.level == "high"]

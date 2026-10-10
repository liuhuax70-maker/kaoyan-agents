"""答疑讲解智能体的结构化输出。"""

from pydantic import BaseModel, Field


class TutoringAnswer(BaseModel):
    """知识点讲解与解题路径。"""

    subject: str = Field(default="通用", max_length=32)
    question_summary: str = Field(
        default="", max_length=200, description="对问题的复述，确认理解一致"
    )
    key_points: list[str] = Field(default_factory=list, description="必须先掌握的关键概念")
    steps: list[str] = Field(default_factory=list, description="有序解题步骤，每步可独立验证")
    pitfalls: list[str] = Field(default_factory=list, description="该题型的常见错误")
    followups: list[str] = Field(default_factory=list, description="引导学生自检的追问")
    related_practice: list[str] = Field(default_factory=list, description="建议配套练习方向")

    @property
    def is_actionable(self) -> bool:
        """是否给出了可执行的步骤。"""

        return len(self.steps) >= 2

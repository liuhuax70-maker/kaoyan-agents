"""资料规划智能体的结构化输出。"""

from pydantic import BaseModel, Field


class ResourceItem(BaseModel):
    """一份具体资料及其用法。"""

    subject: str = Field(default="", max_length=32, description="适用科目")
    stage: str = Field(default="基础", max_length=32, description="适用阶段")
    name: str = Field(min_length=2, max_length=120, description="资料类型或名称")
    usage: str = Field(default="", max_length=300, description="使用方式与刷法")
    priority: int = Field(default=2, ge=1, le=3, description="优先级 1 最高")


class ResourcePlan(BaseModel):
    """资料组合建议。"""

    summary: str = Field(default="", max_length=300)
    items: list[ResourceItem] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list, description="选资料与用资料的原则")

    def for_subject(self, subject: str) -> list[ResourceItem]:
        """按科目筛选资料。"""

        return [item for item in self.items if item.subject == subject]

"""督促提醒智能体的结构化输出。"""

from typing import Literal

from pydantic import BaseModel, Field

NudgeTone = Literal["gentle", "neutral", "firm"]


class NudgeMessage(BaseModel):
    """一条督促提醒文案。

    语气由工作流依据自律程度与逾期情况决定，避免对自律度低的用户过度施压。
    """

    title: str = Field(min_length=2, max_length=60, description="提醒标题")
    content: str = Field(min_length=2, max_length=400, description="提醒正文，具体到任务")
    tone: NudgeTone = Field(default="neutral", description="语气：温和 / 中性 / 严格")
    actions: list[str] = Field(default_factory=list, description="建议立即执行的动作，最多 3 条")
    streak_hint: str = Field(default="", max_length=120, description="连续学习或断签提示")


class WeeklyDigest(BaseModel):
    """周报复盘文案。"""

    title: str = Field(default="本周学习周报", max_length=60)
    highlights: list[str] = Field(default_factory=list, description="本周亮点，需带具体数字")
    problems: list[str] = Field(default_factory=list)
    next_week_plan: list[str] = Field(default_factory=list, description="下周重点，控制在 3 条内")
    closing: str = Field(default="", max_length=200)

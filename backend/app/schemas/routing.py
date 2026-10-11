"""协调者意图识别的结构化输出。"""

from typing import Literal

from pydantic import BaseModel, Field

IntentType = Literal[
    "revise",
    "plan",
    "breakdown",
    "tutor",
    "review",
    "resource",
    "nudge",
    "chat",
]


class IntentDecision(BaseModel):
    """用户请求的意图判定与协作编排建议。"""

    intent: IntentType = Field(default="chat", description="主意图")
    confidence: float = Field(default=0.5, ge=0, le=1, description="判定置信度")
    agents: list[str] = Field(
        default_factory=list,
        description="建议参与的智能体 key，按执行顺序排列，数量 1-3",
    )
    reason: str = Field(default="", max_length=200, description="判定依据")

    def normalized_agents(self, allowed: set[str]) -> list[str]:
        """过滤掉未知智能体并去重，保证编排安全。"""

        result: list[str] = []
        for key in self.agents:
            if key in allowed and key not in result:
                result.append(key)
        return result

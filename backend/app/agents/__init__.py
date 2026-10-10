"""单智能体能力层。

与 ``app.crews`` 的区别：
- 这里封装「一次模型调用即可完成」的能力（如督促文案、周报），供工作流与定时任务复用；
- ``app.crews`` 封装需要多角色对抗与多轮协商的 CrewAI 协作。
"""

from app.agents.nudge import (
    compose_nudge,
    compose_weekly_digest,
    digest_stub_context,
    nudge_stub_context,
)

__all__ = [
    "compose_nudge",
    "compose_weekly_digest",
    "digest_stub_context",
    "nudge_stub_context",
]

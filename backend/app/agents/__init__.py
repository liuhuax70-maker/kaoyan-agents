"""单智能体能力层。

这里封装「一次模型调用即可完成」的能力（如督促文案、周报），
供工作流节点与 Celery 定时任务复用。

需要多角色协作的场景一律由图节点编排，不再引入第二个编排框架。
"""

from app.agents.nudge import compose_nudge, compose_nudge_reply, compose_weekly_digest
from app.agents.school import compose_school_brief, format_brief_content

__all__ = [
    "compose_nudge",
    "compose_nudge_reply",
    "compose_school_brief",
    "compose_weekly_digest",
    "format_brief_content",
]
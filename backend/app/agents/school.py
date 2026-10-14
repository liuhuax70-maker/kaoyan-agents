"""院校简报的单智能体能力。

与 ``agents/nudge.py`` 的 ``compose_weekly_digest`` 同形：只有定时任务消费，
只要结构化数据、不要面向用户的正文通道。因此这里走 ``invoke_agent_task``
而不是 ``invoke_subagent_task``——``SCHOOL_BRIEF`` 不在 ``SUBAGENT_TASKS``
里，输出模型就是 ``SchoolBrief`` 本体，不套双轨信封。
"""

from app.llm import AgentTask, invoke_agent_task
from app.prompts import (
    build_messages,
    render_learner,
    render_tracked_schools,
    render_web_intel,
)
from app.schemas import LearnerSnapshot, SchoolBrief, TrackedSchoolSnapshot
from app.search.types import OfficialLink, SchoolIntel


# 知识点：结构化输出 —— 双轨信封只对 ``SUBAGENT_TASKS`` 生效，单轨任务直接以业务
#   Schema 作为输出模型；简报只需结构化数据，因此走 ``invoke_agent_task`` 而非其双子
#   （第2章 LangChain核心组件·结构化输出）
async def compose_school_brief(
    learner: LearnerSnapshot,
    *,
    tracked: list[TrackedSchoolSnapshot],
    intel: SchoolIntel,
    provider: str | None = None,
) -> SchoolBrief:
    """生成一条每日院校简报。

    ``tracked`` 是用户还没放弃的候选院校（含已拍板的那所），
    ``intel`` 是联网搜索结果 + 官方核验入口。简报只描述动向，不替用户做取舍。
    """

    messages = build_messages(
        AgentTask.SCHOOL_BRIEF,
        learner_context=render_learner(learner),
        tracked_context=render_tracked_schools(tracked),
        retrieved_context=render_web_intel(intel),
    )
    return await invoke_agent_task(
        AgentTask.SCHOOL_BRIEF.value, messages, SchoolBrief, provider=provider
    )


# 知识点：幻觉抑制的工程手段 —— 可核验链接不交给模型生成，而是由系统按确定性
#   规则把官方入口拼成 markdown，模型只能给文字建议（第4章 RAG Agent）
def format_brief_content(brief: SchoolBrief, links: list[OfficialLink]) -> str:
    """把结构化简报拼成给用户看的站内信正文。

    核验入口放在最后的独立段落里：这是「每天返回情况 + 给链接让用户确认真实情况」
    这条验收标准的落点。链接永远来自 ``official_entry_links``，不经过模型。
    """

    blocks: list[str] = []
    if brief.summary:
        blocks.append(brief.summary)
    if brief.highlights:
        blocks.append("\n".join(f"- {line}" for line in brief.highlights))
    if brief.caveats:
        blocks.append("\n".join(f"- {line}" for line in brief.caveats))

    if links:
        blocks.append(
            "\n".join(
                [
                    "【核验入口】",
                    *[f"- [{item.label}]({item.url})" for item in links],
                    "_以上为系统给出的官方核验通道，具体情况以院校官方招生简章为准。_",
                ]
            )
        )

    return "\n\n".join(block for block in blocks if block)
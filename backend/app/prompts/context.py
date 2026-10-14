"""把领域快照渲染成提示词中的中文上下文块。"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from app.knowledge.types import RetrievedChunk
from app.schemas import (
    LearnerSnapshot,
    PlanDraft,
    PlanSnapshot,
    ReminderSnapshot,
    TrackedSchoolSnapshot,
)
from app.search.types import OfficialLink, SchoolIntel

TRACKED_STATUS_LABELS = {
    "candidate": "候选",
    "decided": "用户已选定",
    "archived": "已放弃",
}

MAX_TASK_LINES = 20
NO_DATA = "- （暂无数据）"
MAX_INTEL_SNIPPET = 240
"""单条联网线索进入提示词的最大字符数。搜索摘要可能很长，不设上限会挤占上下文预算。"""


def _bullets(lines: list[str]) -> str:
    """渲染为无序列表。"""

    return "\n".join(f"- {line}" for line in lines) if lines else NO_DATA


def render_learner(snapshot: LearnerSnapshot) -> str:
    """渲染考生画像与进度统计。"""

    exam_type = "考研" if snapshot.exam_type == "postgraduate" else "职业资格考证"
    header = [f"昵称：{snapshot.nickname}", f"备考类型：{exam_type}"]

    if snapshot.target_title:
        header.append(f"备考目标：{snapshot.target_title}")
    if snapshot.target_school or snapshot.target_major:
        target = " ".join(filter(None, [snapshot.target_school, snapshot.target_major]))
        header.append(f"目标院校专业：{target}")
    if snapshot.exam_date:
        header.append(f"考试日期：{snapshot.exam_date.isoformat()}")
    if snapshot.days_left is not None:
        header.append(f"剩余天数：{snapshot.days_left} 天")

    header.extend(
        [
            f"基础水平：{snapshot.base_level}",
            f"每日可投入：{snapshot.daily_hours:g} 小时",
            f"每周学习天数：{snapshot.weekly_days} 天（每周约 {snapshot.weekly_hours:g} 小时）",
            f"单次专注时长：{snapshot.attention_span} 分钟",
            f"自律程度：{snapshot.self_discipline}/5",
        ]
    )
    if snapshot.preferred_slots:
        header.append(f"偏好学习时段：{'、'.join(snapshot.preferred_slots)}")
    if snapshot.notes:
        header.append(f"补充说明：{snapshot.notes}")

    progress = snapshot.progress
    progress_lines = [
        f"任务总数 {progress.total_tasks}，已完成 {progress.done_tasks}，"
        f"进行中 {progress.doing_tasks}，逾期 {progress.overdue_tasks}",
        f"整体完成率 {progress.completion_rate:.0%}",
        f"近 7 天学习时长 {progress.recent_minutes} 分钟",
        f"当前连续学习 {progress.current_streak} 天（历史最长 {progress.longest_streak} 天）",
        f"连续未学习 {progress.idle_days} 天",
    ]

    return "\n".join(header) + "\n\n进度统计：\n" + _bullets(progress_lines)


def render_subjects(snapshot: LearnerSnapshot) -> str:
    """渲染科目清单与其权重、掌握程度。"""

    if not snapshot.subjects:
        return "- （用户尚未填写科目，可按通用考研科目给出建议）"

    lines = []
    for item in snapshot.subjects:
        weak = "【薄弱】" if item.is_weak else ""
        lines.append(
            f"{item.name}{weak}｜类别 {item.category}｜分值占比 {item.score_weight:.0%}"
            f"｜难度 {item.difficulty}/5｜当前掌握 {item.current_level}/5"
        )
    return _bullets(lines)


def render_plan(plan: PlanSnapshot | None, limit: int = MAX_TASK_LINES) -> str:
    """渲染当前计划的概要与任务明细。"""

    if plan is None:
        return "（当前没有进行中的学习计划）"

    lines = [
        f"计划标题：{plan.title or '未命名计划'}",
        f"计划状态：{plan.status}",
        f"计划周期：{plan.horizon_days} 天",
    ]
    if plan.start_date and plan.end_date:
        lines.append(f"起止日期：{plan.start_date.isoformat()} ~ {plan.end_date.isoformat()}")
    if plan.goal:
        lines.append(f"计划目标：{plan.goal}")
    lines.append(f"任务总数：{len(plan.tasks)}")

    if plan.tasks:
        lines.append(f"任务明细（最多列出 {limit} 条）：")
        for task in plan.tasks[:limit]:
            planned = task.planned_date.isoformat() if task.planned_date else "未排期"
            subject = f"{task.subject}｜" if task.subject else ""
            lines.append(
                f"  · [{task.status}] {planned} {subject}{task.title}"
                f"（{task.duration_minutes} 分钟，优先级 {task.priority}）"
            )

    return "\n".join(lines)


def render_plan_draft(draft: PlanDraft) -> str:
    """渲染待评审的计划草稿。"""

    lines = [
        f"计划标题：{draft.title}",
        f"计划目标：{draft.goal}",
        f"计划周期：{draft.horizon_days} 天｜每日投入 {draft.daily_hours:g} 小时",
        f"阶段数量：{len(draft.stages)}｜任务总数：{draft.total_tasks}",
    ]
    for stage in draft.stages:
        durations = [task.duration_minutes for task in stage.tasks] or [0]
        lines.append(
            f"· 阶段「{stage.name}」（第 {stage.start_offset}-{stage.end_offset} 天）："
            f"{stage.focus}；任务 {len(stage.tasks)} 个，"
            f"单任务时长 {min(durations)}-{max(durations)} 分钟"
        )
        for task in stage.tasks[:3]:
            lines.append(f"    - {task.title}（{task.duration_minutes} 分钟，{task.priority}）")
    if draft.notes:
        lines.append("计划自述的注意事项：" + "；".join(draft.notes))
    return "\n".join(lines)


def render_reminder(reminder: ReminderSnapshot) -> str:
    """渲染督促提醒所需的要素。"""

    lines = [
        f"提醒类型：{reminder.reminder_type}",
        f"整体完成率：{reminder.completion_rate:.0%}",
    ]
    if reminder.target_title:
        lines.append(f"备考目标：{reminder.target_title}")
    if reminder.days_left is not None:
        lines.append(f"距考试剩余：{reminder.days_left} 天")
    if reminder.idle_days:
        lines.append(f"连续未学习：{reminder.idle_days} 天")
    due = reminder.due_tasks
    overdue = reminder.overdue_tasks
    lines.append(f"今日待完成任务（{len(due)} 项）：{_bullets(due)}")
    lines.append(f"已逾期任务（{len(overdue)} 项）：{_bullets(overdue)}")
    # 明文给出「能顺延」这件事：否则提醒只描述了欠账，语气再客气也还是在催。
    lines.append("未完成的任务可以一键顺延到明天，计划允许动态调整，不必勉强硬撑。")
    return "\n".join(lines)


def render_retrieved(chunks: Sequence[RetrievedChunk]) -> str:
    """渲染检索到的知识片段，供提示词引用。"""

    if not chunks:
        return "- （本次未检索到参考资料，请基于通用备考规律作答，不要编造具体资料）"

    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        subject = f"{chunk.subject}｜" if chunk.subject else ""
        source = chunk.source or "知识库"
        blocks.append(f"[{index}] {subject}{source}（相似度 {chunk.score:.2f}）\n{chunk.text}")
    return "\n\n".join(blocks)


# 知识点：把「检索到的内容」与「它的来源」一起交给模型 —— 无来源的片段只能被当成
#   通用知识复述，带上 URL 才可能被引用成可核验的线索；同时空结果要显式说明是
#   「未启用」还是「没搜到」，两者对模型的约束不同（第4章 RAG Agent·引用与溯源）
def render_web_intel(intel: SchoolIntel) -> str:
    """渲染联网搜索线索，带上来源 URL。"""

    if not intel.results:
        reason = "本次未启用联网搜索" if intel.degraded else "本次联网搜索没有返回结果"
        return (
            f"- （{reason}。可以给出取舍角度与判断方法，但必须明确告知具体数据要以"
            "官方渠道为准，不得编造分数线、报录比这类具体数字）"
        )

    blocks: list[str] = []
    for index, item in enumerate(intel.results, start=1):
        snippet = item.snippet[:MAX_INTEL_SNIPPET]
        blocks.append(f"[{index}] {item.title}｜{item.url}\n{snippet}")
    return "\n\n".join(blocks)


def render_tracked_schools(schools: Sequence[TrackedSchoolSnapshot]) -> str:
    """渲染用户正在跟踪的院校，供每日简报对照。

    带上状态：用户已经拍板的那一所与仍在比较的候选，简报的关注点不同 ——
    前者要看「有没有影响报考的动向」，后者要看「还差什么信息才能决定」。
    """

    if not schools:
        return NO_DATA

    lines: list[str] = []
    for item in schools:
        label = TRACKED_STATUS_LABELS.get(item.status, item.status)
        head = " ".join(filter(None, [item.name, item.major]))
        parts = [f"{head}｜{label}"]
        if item.fit_for:
            parts.append(f"适用人群：{item.fit_for}")
        if item.pros:
            parts.append(f"已知优势：{'；'.join(item.pros[:3])}")
        if item.cons:
            parts.append(f"已知代价：{'；'.join(item.cons[:3])}")
        lines.append("；".join(parts))
    return _bullets(lines)


def render_official_links(links: Sequence[OfficialLink]) -> str:
    """渲染官方核验入口，供模型转述给考生。"""

    if not links:
        return NO_DATA
    return "\n".join(f"- {item.label}：{item.url}" for item in links)


# 知识点：上下文窗口的预算控制 —— 多轮历史不能无节制地拼进提示词，
#   要按预算从最旧的一轮开始丢，且永远保住最近一轮（第3章 Agent进阶·记忆）
def trim_history(
    history: Sequence[Mapping[str, str]], char_budget: int
) -> list[dict[str, str]]:
    """按字符预算裁剪历史，优先保留最近几轮。

    从最新往回取，取到预算用尽为止，返回仍按时间正序排列。
    最新的一轮即使单独就超预算也保留：用户追问「第二点再展开」时，
    被他指代的那条回答必须还在上下文里，否则记忆等于没有。
    """

    if char_budget <= 0:
        return []

    kept: list[dict[str, str]] = []
    used = 0
    for item in reversed(list(history)):
        text = str(item.get("content") or "")
        if not text.strip():
            continue
        if kept and used + len(text) > char_budget:
            break
        kept.append({"role": str(item.get("role") or "user"), "content": text})
        used += len(text)

    kept.reverse()
    return kept


def _strip_titles(node: Any) -> Any:
    """递归去掉 JSON Schema 中无信息量的 title 注解，压缩提示词体积。

    只删「注解式」的 title —— 即取值为字符串、由 Pydantic 自动加上的那一类。
    字段名恰好叫 title 的属性（如 PlanDraft.title）取值为子结构而不是字符串，
    必须保留：早期版本不区分两者，把该字段整个从输出契约里删掉了，
    模型因此收不到「计划标题」这个必填项。
    """

    if isinstance(node, dict):
        return {
            key: _strip_titles(value)
            for key, value in node.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def render_output_contract(model: type[BaseModel]) -> str:
    """渲染结构化输出契约，约束模型严格对齐字段名与类型。"""

    schema = _strip_titles(model.model_json_schema())
    return json.dumps(schema, ensure_ascii=False, indent=2)

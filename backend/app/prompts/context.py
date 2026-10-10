"""把领域快照渲染成提示词中的中文上下文块。"""

import json
from typing import Any

from pydantic import BaseModel

from app.schemas import LearnerSnapshot, PlanDraft, PlanSnapshot, ReminderSnapshot

MAX_TASK_LINES = 20
NO_DATA = "- （暂无数据）"


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
    return "\n".join(lines)


def _strip_titles(node: Any) -> Any:
    """递归去掉 JSON Schema 中无信息量的 title 字段，压缩提示词体积。"""

    if isinstance(node, dict):
        return {key: _strip_titles(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def render_output_contract(model: type[BaseModel]) -> str:
    """渲染结构化输出契约，约束模型严格对齐字段名与类型。"""

    schema = _strip_titles(model.model_json_schema())
    return json.dumps(schema, ensure_ascii=False, indent=2)

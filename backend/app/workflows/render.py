"""把结构化智能体结果渲染成摘要与要点，供前端展示。"""

from app.schemas import (
    ChatSummary,
    DiagnosisReport,
    NudgeMessage,
    PlanDraft,
    PlanRevision,
    PlanRevisionOp,
    ResourcePlan,
    RevisionAction,
    TaskBreakdown,
    TutoringAnswer,
    WeeklyDigest,
)

RenderResult = tuple[str, str, list[str]]

ACTION_LABELS: dict[RevisionAction, str] = {
    RevisionAction.ADD_TASK: "新增任务",
    RevisionAction.UPDATE_TASK: "调整任务",
    RevisionAction.REMOVE_TASK: "删除任务",
    RevisionAction.SHIFT_TASKS: "平移进度",
    RevisionAction.UPDATE_META: "更新计划信息",
}


def render_plan(draft: PlanDraft) -> RenderResult:
    """渲染学习计划。"""

    stage_names = "、".join(stage.name for stage in draft.stages)
    highlights = [
        f"计划周期 {draft.horizon_days} 天，共 {len(draft.stages)} 个阶段：{stage_names}",
        f"拆分出 {draft.total_tasks} 个可打卡任务，每日投入 {draft.daily_hours:g} 小时",
    ]
    highlights.extend(draft.notes[:3])
    return "分阶段备考计划", draft.strategy or draft.goal, highlights


def render_breakdown(breakdown: TaskBreakdown) -> RenderResult:
    """渲染任务拆解结果。"""

    task_names = "、".join(task.title.split("：")[-1][:12] for task in breakdown.tasks[:3])
    highlights = [
        f"拆解范围：{breakdown.scope or '当前阶段'}",
        f"共产出 {len(breakdown.tasks)} 个任务，例如：{task_names}",
    ]
    highlights.extend(breakdown.notes[:2])
    return "任务拆解清单", breakdown.summary, highlights


def render_diagnosis(report: DiagnosisReport) -> RenderResult:
    """渲染复盘诊断报告。"""

    highlights = [
        f"整体完成率 {report.completion_rate:.0%}，执行稳定性 {report.discipline_score}/5",
        *report.findings[:3],
    ]
    high_risks = report.high_risks
    if high_risks:
        titles = "；".join(item.title for item in high_risks)
        highlights.append(f"高风险项 {len(high_risks)} 个：{titles}")
    return "备考复盘诊断", report.summary, highlights


def render_resource(plan: ResourcePlan) -> RenderResult:
    """渲染资料组合建议。"""

    subjects = sorted({item.subject for item in plan.items if item.subject})
    highlights = [
        f"覆盖 {len(subjects)} 门科目，共 {len(plan.items)} 项资料建议",
        f"重点科目：{'、'.join(subjects)}" if subjects else "按通用科目给出资料组合",
        *plan.tips[:2],
    ]
    return "资料组合建议", plan.summary, highlights


def render_tutoring(answer: TutoringAnswer) -> RenderResult:
    """渲染答疑讲解结果。"""

    highlights = [
        f"学科：{answer.subject}",
        f"给出 {len(answer.steps)} 步解题路径、{len(answer.pitfalls)} 条易错提醒",
    ]
    highlights.extend(answer.key_points[:2])
    return "知识点讲解", answer.question_summary, highlights


def render_nudge(message: NudgeMessage) -> RenderResult:
    """渲染督促提醒。"""

    highlights = [f"语气：{message.tone}", *message.actions[:3]]
    if message.streak_hint:
        highlights.append(message.streak_hint)
    return message.title, message.content, highlights


def render_digest(digest: WeeklyDigest) -> RenderResult:
    """渲染周报。"""

    highlights = [*digest.highlights[:3], *digest.problems[:2]]
    return digest.title, digest.closing, highlights


def _describe_revision_op(op: PlanRevisionOp) -> str:
    """把一条修订操作描述成中文短句。"""

    label = ACTION_LABELS.get(op.action, op.action.value)
    if op.action is RevisionAction.ADD_TASK:
        return f"{label}：{op.title}（第 {op.day_offset} 天，{op.duration_minutes} 分钟）"
    if op.action is RevisionAction.UPDATE_TASK:
        return f"{label}：{op.task_title} → {op.title or '调整日期或时长'}"
    if op.action is RevisionAction.REMOVE_TASK:
        return f"{label}：{op.task_title}"
    if op.action is RevisionAction.SHIFT_TASKS:
        direction = "后移" if op.shift_days >= 0 else "前移"
        return f"{label}：未完成任务整体{direction} {abs(op.shift_days)} 天"
    return f"{label}：{op.plan_title or op.plan_goal or op.plan_strategy}"


def render_revision(revision: PlanRevision) -> RenderResult:
    """渲染计划修订提案。"""

    if revision.ops:
        highlights = [_describe_revision_op(op) for op in revision.ops[:6]]
    else:
        highlights = ["未识别出可执行的修改，计划保持不变"]
    return "计划修订提案", revision.summary or "已生成修订提案", highlights


def render_summary(summary: ChatSummary) -> RenderResult:
    """渲染聊天 Agent 的统一总结。"""

    highlights = [*summary.key_points[:4]]
    if summary.next_actions:
        highlights.append(f"建议下一步：{'；'.join(summary.next_actions[:3])}")
    return "统一总结", summary.summary, highlights

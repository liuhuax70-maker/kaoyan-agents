# 知识点：Orchestrator-Worker 编排 —— 编排者只负责「派活与收活」，
#   专业能力下沉到 worker 节点，新增 worker 不需要改动编排逻辑（第5章 LangGraph·六种编排模式）
"""工作流节点实现。

每个节点统一遵循：组装提示词 → 调用模型 → 校验结构化输出 → 渲染展示结果。

节点本身不做降级：模型不可用时直接抛错，配置缺失要在启动或首次调用时暴露出来，
而不是用一份看似正常的假结果把问题掩盖过去。
"""

from datetime import date
from typing import Any, Literal, TypeVar

from langchain_core.messages import BaseMessage
from langgraph.types import interrupt
from pydantic import BaseModel

from app.agents import compose_nudge_reply
from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge import retrieve_context
from app.llm import AgentTask, invoke_agent_task, invoke_subagent_task
from app.prompts import (
    ROLES,
    build_messages,
    render_learner,
    render_plan,
    render_plan_draft,
    render_retrieved,
    render_subjects,
)
from app.schemas import (
    DiagnosisReport,
    LearnerSnapshot,
    PlanDraft,
    PlanReviewResult,
    PlanRevision,
    PlanSnapshot,
    ReminderSnapshot,
    ResourcePlan,
    TaskBreakdown,
    TutoringAnswer,
)
from app.schemas.workflow import AgentOutput
from app.workflows.render import (
    render_breakdown,
    render_diagnosis,
    render_nudge,
    render_resource,
    render_revision,
    render_tutoring,
)
from app.workflows.render import (
    render_plan as render_plan_output,
)
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

SubagentOutcome = tuple[dict[str, Any], str]
"""子智能体的执行结果：状态片段 + 面向用户的正文。"""

GRAPH_REVIEWER = "langgraph-review-node"
"""评审结论的产出来源标识，用于区分图节点评审与其他入口。"""

CommitKind = Literal["plan_draft", "plan_revision"]
"""可落库产物的类型；枚举的权威定义在 ``PlanConfirmation.kind``，这里只借用同一组取值。"""

_CONFIRMATION_NOTES: dict[tuple[CommitKind, bool], str] = {
    ("plan_draft", True): "已确认，计划已写入你的计划表，可以在计划页继续微调。",
    ("plan_draft", False): "已取消，本次没有写入任何计划。告诉我还需要调整什么，我重新拟一版。",
    ("plan_revision", True): "已确认，改动已应用到你的计划。",
    ("plan_revision", False): "已取消，你的计划保持原样。告诉我具体想怎么改，我再出一版。",
}
"""确认结果对用户说的话，按「产物类型 + 是否通过」取值。"""


def _confirmation_note(kind: CommitKind, approved: bool, feedback: str) -> str:
    """生成确认结果说明，用户填了补充意见就附在后面。"""

    note = _CONFIRMATION_NOTES.get((kind, approved), "已处理。")
    if feedback:
        note += f"\n\n补充说明：{feedback}"
    return note


def _snapshot(state: WorkflowState) -> LearnerSnapshot:
    """从状态中还原考生画像，缺失字段使用默认值。"""

    return LearnerSnapshot.model_validate(state.get("learner") or {})


def _plan_snapshot(state: WorkflowState) -> PlanSnapshot | None:
    """从状态中还原计划快照。"""

    payload = state.get("plan")
    return PlanSnapshot.model_validate(payload) if payload else None


def _split_tasks_by_due(plan: PlanSnapshot | None) -> tuple[list[str], list[str]]:
    """把未完成任务按计划日期分成「待完成」与「已逾期」两组。

    提醒类节点需要的是具体任务名，而不是「有 3 个任务逾期」这种统计值。
    """

    due: list[str] = []
    overdue: list[str] = []
    if plan is None:
        return due, overdue

    today = date.today()
    for task in plan.tasks:
        if task.status == "done":
            continue
        if task.planned_date and task.planned_date < today:
            overdue.append(task.title)
        else:
            due.append(task.title)
    return due, overdue


async def _call(
    task: AgentTask,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    state: WorkflowState,
) -> SchemaT:
    """调用模型并解析结构化结果，失败时向上抛出。"""

    return await invoke_agent_task(
        task.value,
        messages,
        schema,
        provider=state.get("provider"),
    )


# 知识点：结构化输出的双轨信封 —— 子智能体一次调用同时给出「回灌给聊天 Agent 的正文」
#   与「驱动落库的结构化数据」，正文不再被二次摘要压扁（第2章 LangChain核心组件·结构化输出）
async def _call_subagent(
    task: AgentTask,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    state: WorkflowState,
) -> tuple[str, SchemaT]:
    """调用子智能体任务，返回 ``(面向用户的正文, 结构化产物)``。"""

    return await invoke_subagent_task(
        task,
        messages,
        schema,
        provider=state.get("provider"),
    )


def _event(node: str, detail: str, agent: str = "") -> dict[str, Any]:
    return {"node": node, "agent": agent, "status": "ok", "detail": detail, "elapsed_ms": 0}


def _output(key: str, title: str, summary: str, highlights: list[str], payload: dict) -> dict:
    return AgentOutput(
        agent=key,
        name=ROLES[key].name,
        title=title,
        summary=summary,
        highlights=highlights,
        payload=payload,
    ).model_dump(mode="json")


# --------------------------------------------------------------------------
# 图节点
# --------------------------------------------------------------------------


async def prepare_context(state: WorkflowState) -> dict[str, Any]:
    """校验并补齐输入，保证后续节点拿到完整上下文。"""

    snapshot = _snapshot(state)
    plan = _plan_snapshot(state)
    detail = f"载入画像：{len(snapshot.subjects)} 门科目，剩余 {snapshot.days_left} 天"
    if plan:
        detail += f"，当前计划 {len(plan.tasks)} 个任务"

    return {
        "learner": snapshot.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json") if plan else None,
        "events": [_event("prepare_context", detail)],
    }


async def finalize(state: WorkflowState) -> dict[str, Any]:
    """收敛节点：汇总各分支产出。"""

    outputs = state.get("outputs") or []
    errors = state.get("errors") or []
    detail = f"完成 {len(outputs)} 个智能体产出"
    if errors:
        detail += f"，{len(errors)} 个失败"
    return {"events": [_event("finalize", detail)]}


async def review_plan(state: WorkflowState) -> dict[str, Any]:
    # 知识点：条件边 vs 无条件边 —— 走哪条分支由独立的判定函数读 State 决定，
    #   节点只负责自己的产出，不把路由逻辑写进节点内部（第5章 LangGraph·六种编排模式）
    """评审节点：计划草稿产出后，由复盘诊断师做一轮独立校验。

    评审与生成刻意分成两个节点、两次模型调用：同一段提示词里既当作者又当裁判，
    模型会天然偏向自己刚写出的结果，挑不出真问题。
    """

    payload = state.get("plan_draft")
    if not payload:
        return {}

    snapshot = _snapshot(state)
    draft = PlanDraft.model_validate(payload)
    messages = build_messages(
        AgentTask.PLAN_REVIEW,
        learner_context=render_learner(snapshot),
        plan_context=render_plan_draft(draft),
    )
    review: PlanReviewResult = await _call(  # type: ignore[assignment]
        AgentTask.PLAN_REVIEW, messages, PlanReviewResult, state
    )
    review.reviewer = GRAPH_REVIEWER
    data = review.model_dump(mode="json")

    blocking = review.blocking_issues
    highlights = [
        f"计划评分 {review.score}/100，发现 {len(review.issues)} 个问题"
        f"（其中高风险 {len(blocking)} 个）",
        *(f"[{item.severity}] {item.detail}" for item in review.issues[:3]),
    ]
    if review.improvements:
        highlights.append(f"改进要点：{'；'.join(review.improvements[:3])}")

    detail = f"评审结论：{'通过' if review.approved else '需修订'}，评分 {review.score}"
    return {
        "plan_review": data,
        "outputs": [
            _output("reviewer", "计划评审结论", review.summary or detail, highlights, data)
        ],
        "events": [_event("review_plan", detail, "reviewer")],
    }


def pending_confirmation(state: WorkflowState) -> dict[str, Any] | None:
    """返回本次待人工确认的内容，没有可落库产物时返回 ``None``。

    只有真正会写库的产物才需要确认：整体重排优先于局部修订，
    与 ``persist_result`` 的落库优先级保持一致——否则用户会为一份不会被写入的东西点确认。
    """

    draft = state.get("plan_draft")
    if draft:
        title, summary, highlights = render_plan_output(PlanDraft.model_validate(draft))
        return {"kind": "plan_draft", "title": title, "summary": summary, "items": highlights}

    revision = state.get("plan_revision")
    if revision and revision.get("ops"):
        plan = _plan_snapshot(state)
        title, summary, highlights = render_revision(PlanRevision.model_validate(revision))
        return {
            "kind": "plan_revision",
            "plan_id": plan.id if plan else None,
            "title": title,
            "summary": summary,
            "items": highlights,
        }
    return None


def _read_decision(decision: Any) -> tuple[bool, str]:
    """把恢复时传入的答复规范成 ``(是否通过, 补充意见)``。"""

    if isinstance(decision, dict):
        return bool(decision.get("approve")), str(decision.get("feedback") or "").strip()
    return bool(decision), ""


# 知识点：interrupt 人工确认 —— 节点调用 interrupt() 时，状态被存进检查点、控制权交回
#   调用方；恢复时同一个 interrupt() 调用原地返回用户答复，节点从这句之后继续跑，
#   因此「生成」与「落库」之间被插进了一道人工闸门（第5章 LangGraph·人工确认）
async def confirm_plan(state: WorkflowState) -> dict[str, Any]:
    """落库前的人工确认：有可落库产物时暂停，等用户点头。

    两种答复都要改写 ``reply``：暂停那一步已经把聊天 Agent 的完整回答落成一条消息了，
    恢复时若原样再输出一次，同一段话会在会话里出现两遍。这里只留一句结果说明。

    驳回不是「什么都不做」：草稿要被清掉，否则服务层仍会把被驳回的计划写进数据库。
    """

    pending = pending_confirmation(state)
    if pending is None or not state.get("confirm_commit"):
        return {}

    approve, feedback = _read_decision(interrupt(pending))
    kind: CommitKind = pending["kind"]
    title = str(pending.get("title") or "")

    dropped = {"plan_draft": None, "plan_revision": None} if not approve else {}
    return {
        "reply": _confirmation_note(kind, approve, feedback),
        **dropped,
        "events": [
            _event(
                "confirm_plan",
                f"{'用户确认落库' if approve else '用户驳回，未落库'}：{title}",
            )
        ],
    }


# --------------------------------------------------------------------------
# 各智能体处理器
#
# 知识点：节点与处理器的分工 —— 只有 prepare_context / review_plan / confirm_plan /
#   finalize 是图节点，它们读写 State 并由图调度；下面这七个是「被工具调用的处理器」，
#   由聊天 Agent 在自己的循环里调用，因此可以自由改签名而不影响图拓扑
#   （第5章 LangGraph·基本概念）
# --------------------------------------------------------------------------


async def _run_planner(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    messages = build_messages(
        AgentTask.PLAN_DRAFT,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        request=state.get("request", ""),
    )
    narrative, draft = await _call_subagent(AgentTask.PLAN_DRAFT, messages, PlanDraft, state)
    title, summary, highlights = render_plan_output(draft)
    payload = draft.model_dump(mode="json")
    return (
        {
            "plan_draft": payload,
            "outputs": [_output("planner", title, summary, highlights, payload)],
            "events": [
                _event(
                    "planner",
                    f"生成 {draft.horizon_days} 天计划，共 {draft.total_tasks} 个任务",
                    "planner",
                )
            ],
        },
        narrative,
    )


async def _run_breakdown(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    request = state.get("request", "")
    messages = build_messages(
        AgentTask.TASK_BREAKDOWN,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        scope=request,
    )
    narrative, result = await _call_subagent(
        AgentTask.TASK_BREAKDOWN, messages, TaskBreakdown, state
    )
    title, summary, highlights = render_breakdown(result)
    payload = result.model_dump(mode="json")
    return (
        {
            "breakdown": payload,
            "outputs": [_output("breakdown", title, summary, highlights, payload)],
            "events": [_event("breakdown", f"拆解出 {len(result.tasks)} 个任务", "breakdown")],
        },
        narrative,
    )


async def _run_tutor(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    request = state.get("request", "")
    chunks = await retrieve_context(request, enabled=state.get("enable_retrieval", True))

    messages = build_messages(
        AgentTask.TUTORING,
        learner_context=render_learner(snapshot),
        request=request,
        retrieved_context=render_retrieved(chunks),
    )
    narrative, answer = await _call_subagent(AgentTask.TUTORING, messages, TutoringAnswer, state)
    title, summary, highlights = render_tutoring(answer)
    payload = answer.model_dump(mode="json")

    if chunks:
        highlights = [*highlights, f"引用知识库片段 {len(chunks)} 条"]

    return (
        {
            "tutoring": payload,
            "outputs": [
                _output(
                    "tutor",
                    title,
                    summary,
                    highlights,
                    {**payload, "references": [item.to_payload() for item in chunks]},
                )
            ],
            "events": [
                _event("tutor", f"讲解学科：{answer.subject}，检索 {len(chunks)} 条", "tutor")
            ],
        },
        narrative,
    )


async def _run_reviewer(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    plan = _plan_snapshot(state)
    messages = build_messages(
        AgentTask.DIAGNOSIS,
        learner_context=render_learner(snapshot),
        plan_context=render_plan(plan),
        request=state.get("request", "") or "请复盘我当前的备考进度",
    )
    narrative, report = await _call_subagent(
        AgentTask.DIAGNOSIS, messages, DiagnosisReport, state
    )
    title, summary, highlights = render_diagnosis(report)
    payload = report.model_dump(mode="json")
    return (
        {
            "diagnosis": payload,
            "outputs": [_output("reviewer", title, summary, highlights, payload)],
            "events": [_event("reviewer", f"完成度 {report.completion_rate:.0%}", "reviewer")],
        },
        narrative,
    )


async def _run_resource(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    request = state.get("request", "") or "请给出各科目的资料组合"
    chunks = await retrieve_context(request, enabled=state.get("enable_retrieval", True))

    messages = build_messages(
        AgentTask.RESOURCE_PLAN,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        request=request,
        retrieved_context=render_retrieved(chunks),
    )
    narrative, plan = await _call_subagent(
        AgentTask.RESOURCE_PLAN, messages, ResourcePlan, state
    )
    title, summary, highlights = render_resource(plan)
    payload = plan.model_dump(mode="json")

    if chunks:
        highlights = [*highlights, f"引用知识库片段 {len(chunks)} 条"]

    return (
        {
            "resource": payload,
            "outputs": [
                _output(
                    "resource",
                    title,
                    summary,
                    highlights,
                    {**payload, "references": [item.to_payload() for item in chunks]},
                )
            ],
            "events": [
                _event(
                    "resource",
                    f"给出 {len(plan.items)} 项资料建议，检索 {len(chunks)} 条",
                    "resource",
                )
            ],
        },
        narrative,
    )


async def _run_coach(state: WorkflowState) -> SubagentOutcome:
    snapshot = _snapshot(state)
    due_tasks, overdue_tasks = _split_tasks_by_due(_plan_snapshot(state))
    reminder = ReminderSnapshot(
        reminder_type="daily",
        target_title=snapshot.target_title,
        due_tasks=due_tasks[:5],
        overdue_tasks=overdue_tasks[:5],
        days_left=snapshot.days_left,
        idle_days=snapshot.progress.idle_days,
        completion_rate=snapshot.progress.completion_rate,
    )
    narrative, message = await compose_nudge_reply(snapshot, reminder, state.get("provider"))
    title, summary, highlights = render_nudge(message)
    payload = message.model_dump(mode="json")
    return (
        {
            "nudge": payload,
            "outputs": [_output("coach", title, summary, highlights, payload)],
            "events": [_event("coach", f"督促语气：{message.tone}", "coach")],
        },
        narrative,
    )


async def _run_plan_editor(state: WorkflowState) -> SubagentOutcome:
    """计划修订师：把修改诉求转成结构化的计划修订提案。

    这里只产出提案，不直接写库——图谱保持无副作用，
    落库统一由服务层在对话结束后执行。
    """

    snapshot = _snapshot(state)
    plan = _plan_snapshot(state)
    request = state.get("request", "") or "请根据我的要求调整计划"

    messages = build_messages(
        AgentTask.PLAN_REVISION,
        learner_context=render_learner(snapshot),
        plan_context=render_plan(plan),
        request=request,
    )
    narrative, revision = await _call_subagent(
        AgentTask.PLAN_REVISION, messages, PlanRevision, state
    )
    title, summary, highlights = render_revision(revision)
    payload = revision.model_dump(mode="json")
    return (
        {
            "plan_revision": payload,
            "outputs": [_output("plan_editor", title, summary, highlights, payload)],
            "events": [
                _event("plan_editor", f"提出 {len(revision.ops)} 项修改", "plan_editor")
            ],
        },
        narrative,
    )


AGENT_HANDLERS = {
    "planner": _run_planner,
    "breakdown": _run_breakdown,
    "tutor": _run_tutor,
    "reviewer": _run_reviewer,
    "resource": _run_resource,
    "coach": _run_coach,
    "plan_editor": _run_plan_editor,
}


def learner_of(state: WorkflowState) -> LearnerSnapshot:
    """从状态还原考生画像（供聊天 Agent 复用）。"""

    return _snapshot(state)


def plan_of(state: WorkflowState) -> PlanSnapshot | None:
    """从状态还原计划快照（供聊天 Agent 复用）。"""

    return _plan_snapshot(state)


def active_provider() -> str:
    """返回当前生效的大模型提供方，用于日志与健康检查。"""

    return get_settings().llm.default_provider
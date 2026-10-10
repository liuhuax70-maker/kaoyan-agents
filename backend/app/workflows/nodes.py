"""工作流节点实现。

每个节点统一遵循：组装提示词 → 调用模型 → 校验结构化输出 → 渲染展示结果。
模型调用失败时自动回退到离线桩，保证多智能体协作不会因为一次抖动而整体失败。
"""

from datetime import date
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.agents import compose_nudge
from app.core.config import get_settings
from app.core.logging import get_logger
from app.knowledge import retrieve_context
from app.llm import AgentTask, invoke_agent_task
from app.prompts import (
    ROLES,
    build_messages,
    render_learner,
    render_plan,
    render_retrieved,
    render_subjects,
)
from app.prompts.catalog import WORKER_ROLE_KEYS
from app.schemas import (
    DiagnosisReport,
    IntentDecision,
    LearnerSnapshot,
    PlanDraft,
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
    render_tutoring,
)
from app.workflows.render import (
    render_plan as render_plan_output,
)
from app.workflows.state import WorkflowState

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

DEFAULT_AGENTS = ("tutor",)
MAX_AGENTS = 3


def _snapshot(state: WorkflowState) -> LearnerSnapshot:
    """从状态中还原考生画像，缺失字段使用默认值。"""

    return LearnerSnapshot.model_validate(state.get("learner") or {})


def _plan_snapshot(state: WorkflowState) -> PlanSnapshot | None:
    """从状态中还原计划快照。"""

    payload = state.get("plan")
    return PlanSnapshot.model_validate(payload) if payload else None


def _stub_context(state: WorkflowState) -> dict[str, Any]:
    """把状态扁平化为离线桩所需的关键字参数。"""

    snapshot = _snapshot(state)
    progress = snapshot.progress
    plan = _plan_snapshot(state)

    today = date.today()
    due_tasks: list[str] = []
    overdue_tasks: list[str] = []
    if plan:
        for task in plan.tasks:
            if task.status == "done":
                continue
            if task.planned_date and task.planned_date < today:
                overdue_tasks.append(task.title)
            else:
                due_tasks.append(task.title)

    return {
        "request": state.get("request", ""),
        "scope": state.get("request", ""),
        "subjects": snapshot.subject_names,
        "weak_subjects": snapshot.weak_subjects,
        "days_left": snapshot.days_left,
        "daily_hours": snapshot.daily_hours,
        "attention_span": snapshot.attention_span,
        "self_discipline": snapshot.self_discipline,
        "completion_rate": progress.completion_rate,
        "total_tasks": progress.total_tasks,
        "done_tasks": progress.done_tasks,
        "overdue_count": progress.overdue_tasks or len(overdue_tasks),
        "idle_days": progress.idle_days,
        "recent_minutes": progress.recent_minutes,
        "due_tasks": due_tasks,
        "overdue_tasks": overdue_tasks,
    }


async def _call(
    task: AgentTask,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    state: WorkflowState,
) -> SchemaT:
    """调用模型并解析结构化结果，失败时回退离线桩。"""

    return await invoke_agent_task(
        task.value,
        messages,
        schema,
        provider=state.get("provider"),
        stub_context=_stub_context(state),
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


async def route_intent(state: WorkflowState) -> dict[str, Any]:
    """调度协调者：判定意图并决定参与的智能体。"""

    snapshot = _snapshot(state)
    messages = build_messages(
        AgentTask.INTENT_ROUTING,
        learner_context=render_learner(snapshot),
        request=state.get("request", ""),
    )
    decision = await _call(AgentTask.INTENT_ROUTING, messages, IntentDecision, state)

    agents = decision.normalized_agents(set(WORKER_ROLE_KEYS)) or list(DEFAULT_AGENTS)
    agents = agents[:MAX_AGENTS]

    return {
        "intent": decision.intent,
        "agents": agents,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "events": [
            _event(
                "route_intent",
                f"意图 {decision.intent}（{decision.confidence:.0%}）→ {'、'.join(agents)}",
            )
        ],
    }


async def run_agent(state: WorkflowState) -> dict[str, Any]:
    """按 agent_key 执行对应的专业智能体。"""

    key = str(state.get("agent_key", ""))
    handler = AGENT_HANDLERS.get(key)
    if handler is None:
        return {"errors": [f"未知智能体：{key}"]}
    try:
        return await handler(state)
    except Exception as exc:  # noqa: BLE001 - 单个智能体失败不应中断整体协作
        logger.exception("智能体 %s 执行失败", key)
        return {
            "errors": [f"{key} 执行失败：{exc}"],
            "events": [{"node": key, "agent": key, "status": "failed", "detail": str(exc)}],
        }


async def finalize(state: WorkflowState) -> dict[str, Any]:
    """收敛节点：汇总各分支产出。"""

    outputs = state.get("outputs") or []
    errors = state.get("errors") or []
    detail = f"完成 {len(outputs)} 个智能体产出"
    if errors:
        detail += f"，{len(errors)} 个失败"
    return {"events": [_event("finalize", detail)]}


# --------------------------------------------------------------------------
# 各智能体节点
# --------------------------------------------------------------------------


async def _run_planner(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    messages = build_messages(
        AgentTask.PLAN_DRAFT,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        request=state.get("request", ""),
    )
    draft: PlanDraft = await _call(AgentTask.PLAN_DRAFT, messages, PlanDraft, state)  # type: ignore[assignment]
    title, summary, highlights = render_plan_output(draft)
    payload = draft.model_dump(mode="json")
    return {
        "plan_draft": payload,
        "outputs": [_output("planner", title, summary, highlights, payload)],
        "events": [
            _event(
                "planner",
                f"生成 {draft.horizon_days} 天计划，共 {draft.total_tasks} 个任务",
                "planner",
            )
        ],
    }


async def _run_breakdown(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    request = state.get("request", "")
    messages = build_messages(
        AgentTask.TASK_BREAKDOWN,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        scope=request,
    )
    result: TaskBreakdown = await _call(  # type: ignore[assignment]
        AgentTask.TASK_BREAKDOWN, messages, TaskBreakdown, state
    )
    title, summary, highlights = render_breakdown(result)
    payload = result.model_dump(mode="json")
    return {
        "breakdown": payload,
        "outputs": [_output("breakdown", title, summary, highlights, payload)],
        "events": [_event("breakdown", f"拆解出 {len(result.tasks)} 个任务", "breakdown")],
    }


async def _run_tutor(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    request = state.get("request", "")
    chunks = await retrieve_context(request)

    messages = build_messages(
        AgentTask.TUTORING,
        learner_context=render_learner(snapshot),
        request=request,
        retrieved_context=render_retrieved(chunks),
    )
    answer: TutoringAnswer = await _call(  # type: ignore[assignment]
        AgentTask.TUTORING, messages, TutoringAnswer, state
    )
    title, summary, highlights = render_tutoring(answer)
    payload = answer.model_dump(mode="json")

    if chunks:
        highlights = [*highlights, f"引用知识库片段 {len(chunks)} 条"]

    return {
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
        "events": [_event("tutor", f"讲解学科：{answer.subject}，检索 {len(chunks)} 条", "tutor")],
    }


async def _run_reviewer(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    plan = _plan_snapshot(state)
    messages = build_messages(
        AgentTask.DIAGNOSIS,
        learner_context=render_learner(snapshot),
        plan_context=render_plan(plan),
        request=state.get("request", "") or "请复盘我当前的备考进度",
    )
    report: DiagnosisReport = await _call(  # type: ignore[assignment]
        AgentTask.DIAGNOSIS, messages, DiagnosisReport, state
    )
    title, summary, highlights = render_diagnosis(report)
    payload = report.model_dump(mode="json")
    return {
        "diagnosis": payload,
        "outputs": [_output("reviewer", title, summary, highlights, payload)],
        "events": [_event("reviewer", f"完成度 {report.completion_rate:.0%}", "reviewer")],
    }


async def _run_resource(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    request = state.get("request", "") or "请给出各科目的资料组合"
    chunks = await retrieve_context(request)

    messages = build_messages(
        AgentTask.RESOURCE_PLAN,
        learner_context=render_learner(snapshot),
        subject_context=render_subjects(snapshot),
        request=request,
        retrieved_context=render_retrieved(chunks),
    )
    plan: ResourcePlan = await _call(  # type: ignore[assignment]
        AgentTask.RESOURCE_PLAN, messages, ResourcePlan, state
    )
    title, summary, highlights = render_resource(plan)
    payload = plan.model_dump(mode="json")

    if chunks:
        highlights = [*highlights, f"引用知识库片段 {len(chunks)} 条"]

    return {
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
    }


async def _run_coach(state: WorkflowState) -> dict[str, Any]:
    snapshot = _snapshot(state)
    context = _stub_context(state)
    reminder = ReminderSnapshot(
        reminder_type="daily",
        target_title=snapshot.target_title,
        due_tasks=list(context["due_tasks"])[:5],
        overdue_tasks=list(context["overdue_tasks"])[:5],
        days_left=snapshot.days_left,
        idle_days=snapshot.progress.idle_days,
        completion_rate=snapshot.progress.completion_rate,
    )
    message = await compose_nudge(snapshot, reminder, state.get("provider"))
    title, summary, highlights = render_nudge(message)
    payload = message.model_dump(mode="json")
    return {
        "nudge": payload,
        "outputs": [_output("coach", title, summary, highlights, payload)],
        "events": [_event("coach", f"督促语气：{message.tone}", "coach")],
    }


AGENT_HANDLERS = {
    "planner": _run_planner,
    "breakdown": _run_breakdown,
    "tutor": _run_tutor,
    "reviewer": _run_reviewer,
    "resource": _run_resource,
    "coach": _run_coach,
}


def active_provider() -> str:
    """返回当前生效的大模型提供方，用于日志与健康检查。"""

    return get_settings().llm.default_provider

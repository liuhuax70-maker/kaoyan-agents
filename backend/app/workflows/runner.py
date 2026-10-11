"""工作流对外入口：执行与流式执行。"""

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings
from app.observability import get_observability
from app.schemas import (
    ChatSummary,
    DiagnosisReport,
    LearnerSnapshot,
    NudgeMessage,
    PlanDraft,
    PlanRevision,
    PlanSnapshot,
    ResourcePlan,
    TaskBreakdown,
    TutoringAnswer,
)
from app.schemas.workflow import AgentOutput, ToolCallRecord, WorkflowEvent, WorkflowResult
from app.workflows.graph import get_workflow

ModelT = TypeVar("ModelT", bound=BaseModel)


def _parse(payload: Any, schema: type[ModelT]) -> ModelT | None:
    """按需把状态中的字典还原为模型对象。"""

    if not payload:
        return None
    if isinstance(payload, schema):
        return payload
    return schema.model_validate(payload)


def build_initial_state(
    request: str,
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    provider: str | None = None,
    enable_retrieval: bool = True,
) -> dict[str, Any]:
    """构造工作流初始状态。"""

    return {
        "request": request,
        "learner": learner.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json") if plan else None,
        "provider": provider,
        "enable_retrieval": enable_retrieval,
        "outputs": [],
        "events": [],
        "errors": [],
    }


def build_result(state: dict[str, Any]) -> WorkflowResult:
    """把图状态转换为对外结果模型。"""

    return WorkflowResult(
        intent=str(state.get("intent") or "chat"),
        confidence=float(state.get("confidence") or 0),
        agents=list(state.get("agents") or []),
        outputs=[AgentOutput.model_validate(item) for item in state.get("outputs") or []],
        tool_calls=[
            ToolCallRecord.model_validate(item) for item in state.get("tool_calls") or []
        ],
        summary=_parse(state.get("summary"), ChatSummary),
        plan_draft=_parse(state.get("plan_draft"), PlanDraft),
        breakdown=_parse(state.get("breakdown"), TaskBreakdown),
        diagnosis=_parse(state.get("diagnosis"), DiagnosisReport),
        resource=_parse(state.get("resource"), ResourcePlan),
        tutoring=_parse(state.get("tutoring"), TutoringAnswer),
        nudge=_parse(state.get("nudge"), NudgeMessage),
        plan_revision=_parse(state.get("plan_revision"), PlanRevision),
        errors=list(state.get("errors") or []),
        events=[WorkflowEvent.model_validate(item) for item in state.get("events") or []],
    )


def _should_retrieve(enable_retrieval: bool | None) -> bool:
    """本次请求是否启用知识库检索，未显式指定时取全局配置。"""

    if enable_retrieval is not None:
        return enable_retrieval
    return get_settings().knowledge.enable_retrieval


def _should_review(enable_review: bool | None) -> bool:
    if enable_review is not None:
        return enable_review
    return get_settings().workflow.enable_plan_review


async def _attach_plan_review(
    result: WorkflowResult,
    learner: LearnerSnapshot,
    provider: str | None,
    enable_review: bool | None,
) -> None:
    """计划生成后触发一轮评审协作。

    CrewAI 的导入较重，因此按需惰性导入，避免影响服务启动速度。
    """

    if not _should_review(enable_review) or result.plan_draft is None:
        return

    from app.crews.review import review_plan

    result.plan_review = await review_plan(learner, result.plan_draft, provider)


def _trace_metadata(learner: LearnerSnapshot) -> dict[str, Any]:
    """构造追踪元信息。"""

    return {
        "subjects": learner.subject_names,
        "weak_subjects": learner.weak_subjects,
        "days_left": learner.days_left,
        "daily_hours": learner.daily_hours,
    }


async def run_workflow(
    request: str,
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    *,
    provider: str | None = None,
    enable_review: bool | None = None,
    enable_retrieval: bool | None = None,
    user_id: int | None = None,
    session_id: str | None = None,
) -> WorkflowResult:
    """执行一次完整的多智能体协作。"""

    workflow = get_workflow()
    observability = get_observability()

    with observability.trace(
        "multi-agent.workflow",
        user_id=str(user_id) if user_id is not None else None,
        session_id=session_id,
        input=request,
        tags=["workflow", "langgraph"],
        metadata=_trace_metadata(learner),
    ) as handle:
        final_state = await workflow.ainvoke(
            build_initial_state(
                request, learner, plan, provider, _should_retrieve(enable_retrieval)
            )
        )
        result = build_result(final_state)
        result.trace_id = handle.trace_id
        result.trace_url = handle.url

        await _attach_plan_review(result, learner, provider, enable_review)

        handle.update(
            output=result.reply_text(),
            metadata={
                **_trace_metadata(learner),
                "intent": result.intent,
                "agents": result.agents,
                "confidence": result.confidence,
                "errors": result.errors,
                "reviewed": result.plan_review is not None,
            },
        )

    return result


async def stream_workflow(
    request: str,
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    *,
    provider: str | None = None,
    enable_review: bool | None = None,
    enable_retrieval: bool | None = None,
    user_id: int | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式执行，按步骤推送进度与产出。

    以 values 模式订阅状态：outputs 与 events 使用累加 reducer，
    因此只需对比增量即可得到新产生的进度事件与智能体产出。
    """

    workflow = get_workflow()
    observability = get_observability()
    initial = build_initial_state(
        request, learner, plan, provider, _should_retrieve(enable_retrieval)
    )

    seen_events = 0
    seen_outputs = 0
    final_state: dict[str, Any] = initial

    with observability.trace(
        "multi-agent.workflow.stream",
        user_id=str(user_id) if user_id is not None else None,
        session_id=session_id,
        input=request,
        tags=["workflow", "langgraph", "stream"],
        metadata=_trace_metadata(learner),
    ) as handle:
        async for state in workflow.astream(initial, stream_mode="values"):
            final_state = state

            outputs = state.get("outputs") or []
            for item in outputs[seen_outputs:]:
                yield {"type": "output", "output": item}
            seen_outputs = len(outputs)

            events = state.get("events") or []
            for event in events[seen_events:]:
                yield {"type": "progress", **event}
            seen_events = len(events)

        result = build_result(final_state)
        result.trace_id = handle.trace_id
        result.trace_url = handle.url

        await _attach_plan_review(result, learner, provider, enable_review)

        handle.update(
            output=result.reply_text(),
            metadata={
                **_trace_metadata(learner),
                "intent": result.intent,
                "agents": result.agents,
                "reviewed": result.plan_review is not None,
            },
        )

    yield {"type": "result", "result": result.model_dump(mode="json")}

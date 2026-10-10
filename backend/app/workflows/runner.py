"""工作流对外入口：执行与流式执行。"""

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings
from app.schemas import (
    DiagnosisReport,
    LearnerSnapshot,
    NudgeMessage,
    PlanDraft,
    PlanSnapshot,
    ResourcePlan,
    TaskBreakdown,
    TutoringAnswer,
)
from app.schemas.workflow import AgentOutput, WorkflowEvent, WorkflowResult
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
) -> dict[str, Any]:
    """构造工作流初始状态。"""

    return {
        "request": request,
        "learner": learner.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json") if plan else None,
        "provider": provider,
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
        plan_draft=_parse(state.get("plan_draft"), PlanDraft),
        breakdown=_parse(state.get("breakdown"), TaskBreakdown),
        diagnosis=_parse(state.get("diagnosis"), DiagnosisReport),
        resource=_parse(state.get("resource"), ResourcePlan),
        tutoring=_parse(state.get("tutoring"), TutoringAnswer),
        nudge=_parse(state.get("nudge"), NudgeMessage),
        errors=list(state.get("errors") or []),
        events=[WorkflowEvent.model_validate(item) for item in state.get("events") or []],
    )


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


async def run_workflow(
    request: str,
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    *,
    provider: str | None = None,
    enable_review: bool | None = None,
) -> WorkflowResult:
    """执行一次完整的多智能体协作。"""

    workflow = get_workflow()
    final_state = await workflow.ainvoke(build_initial_state(request, learner, plan, provider))
    result = build_result(final_state)
    await _attach_plan_review(result, learner, provider, enable_review)
    return result


async def stream_workflow(
    request: str,
    learner: LearnerSnapshot,
    plan: PlanSnapshot | None = None,
    *,
    provider: str | None = None,
    enable_review: bool | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """流式执行，按步骤推送进度与产出。

    以 values 模式订阅状态：outputs 与 events 使用累加 reducer，
    因此只需对比增量即可得到新产生的进度事件与智能体产出。
    """

    workflow = get_workflow()
    initial = build_initial_state(request, learner, plan, provider)

    seen_events = 0
    seen_outputs = 0
    final_state: dict[str, Any] = initial

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
    await _attach_plan_review(result, learner, provider, enable_review)
    yield {"type": "result", "result": result.model_dump(mode="json")}

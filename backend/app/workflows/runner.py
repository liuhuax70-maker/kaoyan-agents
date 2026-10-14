"""工作流对外入口：执行与流式执行。"""

from collections.abc import AsyncIterator
from typing import Any, TypeVar

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel

from app.core.config import get_settings
from app.observability import get_observability
from app.schemas import (
    DiagnosisReport,
    LearnerSnapshot,
    NudgeMessage,
    PlanDraft,
    PlanReviewResult,
    PlanRevision,
    PlanSnapshot,
    ResourcePlan,
    TaskBreakdown,
    TutoringAnswer,
)
from app.schemas.workflow import (
    AgentOutput,
    PlanConfirmation,
    ToolCallRecord,
    WorkflowEvent,
    WorkflowResult,
)
from app.workflows.graph import get_checkpointed_workflow, get_workflow

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
    enable_review: bool = True,
    history: list[dict[str, str]] | None = None,
    confirm_commit: bool = False,
) -> dict[str, Any]:
    """构造工作流初始状态。

    ``enable_review`` 与 ``confirm_commit`` 都是写进状态的显式开关：条件边与确认节点
    只读状态，不再回头查配置，这样同一份状态回放出来的路径永远一致。

    ``history`` 由调用方（服务层）从会话记录里取，图本身不读数据库，
    因此多轮记忆的有无都可以脱离数据库单测。
    """

    return {
        "request": request,
        "learner": learner.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json") if plan else None,
        "provider": provider,
        "enable_retrieval": enable_retrieval,
        "enable_review": enable_review,
        "confirm_commit": confirm_commit,
        "history": list(history or []),
        "outputs": [],
        "events": [],
        "errors": [],
    }


def build_result(state: dict[str, Any]) -> WorkflowResult:
    """把图状态转换为对外结果模型。"""

    return WorkflowResult(
        agents=list(state.get("agents") or []),
        outputs=[AgentOutput.model_validate(item) for item in state.get("outputs") or []],
        tool_calls=[
            ToolCallRecord.model_validate(item) for item in state.get("tool_calls") or []
        ],
        reply=str(state.get("reply") or ""),
        plan_draft=_parse(state.get("plan_draft"), PlanDraft),
        breakdown=_parse(state.get("breakdown"), TaskBreakdown),
        diagnosis=_parse(state.get("diagnosis"), DiagnosisReport),
        resource=_parse(state.get("resource"), ResourcePlan),
        tutoring=_parse(state.get("tutoring"), TutoringAnswer),
        nudge=_parse(state.get("nudge"), NudgeMessage),
        plan_revision=_parse(state.get("plan_revision"), PlanRevision),
        plan_review=_parse(state.get("plan_review"), PlanReviewResult),
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


def _should_confirm(confirm_commit: bool | None, thread_id: str | None) -> bool:
    """本次请求是否需要在落库前暂停等人工确认。

    确认能力与检查点同开关：没有 ``thread_id`` 就没有检查点，图暂停后无从恢复，
    因此这种组合下直接不暂停，而不是把一个无法结束的会话留给用户。
    """

    if thread_id is None:
        return False
    if confirm_commit is not None:
        return confirm_commit
    return get_settings().workflow.require_plan_confirmation


def _config_for(thread_id: str | None) -> dict[str, Any] | None:
    """把 thread_id 折成 LangGraph 的运行配置。"""

    return {"configurable": {"thread_id": thread_id}} if thread_id else None


async def _resolve_workflow(
    thread_id: str | None,
) -> tuple[CompiledStateGraph, dict[str, Any] | None]:
    """按是否给了 thread_id 选出「带检查点」或「直跑」两种图。"""

    if thread_id is None:
        return get_workflow(), None
    return await get_checkpointed_workflow(), _config_for(thread_id)


def _attach_confirmation(
    result: WorkflowResult, state: dict[str, Any], thread_id: str | None
) -> None:
    """图停在确认闸门上时，把待确认内容挂到结果上。

    ``__interrupt__`` 是 LangGraph 放暂停载荷的保留键，形状是 ``Interrupt`` 元组；
    这里只认 ``confirm_plan`` 那种带 ``kind`` 的载荷，别的暂停原因不在这里冒充确认请求。
    """

    for item in state.get("__interrupt__") or ():
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value.get("kind"):
            result.confirmation = PlanConfirmation(thread_id=thread_id or "", **value)
            return


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
    history: list[dict[str, str]] | None = None,
    thread_id: str | None = None,
    confirm_commit: bool | None = None,
) -> WorkflowResult:
    """执行一次完整的多智能体协作。

    给了 ``thread_id`` 就走带检查点的图：出现计划草稿时图会停在确认闸门上，
    返回的结果带 ``confirmation`` 而**不写库**；调用方随后用同一个 ``thread_id``
    调 ``resume_workflow`` 才继续。
    """

    workflow, config = await _resolve_workflow(thread_id)
    observability = get_observability()

    with observability.trace(
        "multi-agent.workflow",
        user_id=str(user_id) if user_id is not None else None,
        session_id=session_id,
        input=request,
        tags=["workflow", "langgraph"],
        metadata={**_trace_metadata(learner), "history_turns": len(history or [])},
    ) as handle:
        final_state = await workflow.ainvoke(
            build_initial_state(
                request,
                learner,
                plan,
                provider,
                _should_retrieve(enable_retrieval),
                _should_review(enable_review),
                history,
                confirm_commit=_should_confirm(confirm_commit, thread_id),
            ),
            config,
        )
        result = build_result(final_state)
        _attach_confirmation(result, final_state, thread_id)
        result.trace_id = handle.trace_id
        result.trace_url = handle.url

        handle.update(
            output=result.reply_text(),
            metadata={
                **_trace_metadata(learner),
                "agents": result.agents,
                "errors": result.errors,
                "reviewed": result.plan_review is not None,
                "awaiting_confirmation": result.awaiting_confirmation,
            },
        )

    return result


async def resume_workflow(thread_id: str, decision: dict[str, Any]) -> WorkflowResult:
    """从人工确认的暂停点恢复执行。

    恢复请求带回的是**用户答复**而不是新的用户输入：图从 ``confirm_plan`` 里那句
    ``interrupt`` 之后继续，已经跑过的聊天 Agent 不会重跑，也不会再花一次模型调用。
    """

    workflow = await get_checkpointed_workflow()
    observability = get_observability()

    with observability.trace(
        "multi-agent.workflow.resume",
        session_id=thread_id,
        tags=["workflow", "langgraph", "resume"],
        metadata={"thread_id": thread_id, "approve": bool(decision.get("approve"))},
    ) as handle:
        final_state = await workflow.ainvoke(Command(resume=decision), _config_for(thread_id))
        result = build_result(final_state)
        result.trace_id = handle.trace_id
        result.trace_url = handle.url
        handle.update(
            output=result.reply_text(),
            metadata={
                "agents": result.agents,
                "committed": result.has_plan or result.has_plan_revision,
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
    history: list[dict[str, str]] | None = None,
    thread_id: str | None = None,
    confirm_commit: bool | None = None,
) -> AsyncIterator[dict[str, Any]]:
    # 知识点：多模式流式 —— 同一个图可以同时订阅多种流：values 给「状态整块更新」，
    #   custom 给「节点内部想推就推的增量」；传模式列表时每条产出都带模式标签
    #   （第5章 LangGraph·流式）
    """流式执行，按步骤推送进度、产出与最终回答的逐字增量。

    两条通道各管一段：

    - ``values``：每次状态更新后推一份完整 State，配合累加 reducer 用
      「本次长度 − 上次长度」切出新增的 outputs 与 events；
    - ``custom``：聊天 Agent 在自己的节点内部通过 ``get_stream_writer``
      推出的 token 增量，不经过 State，因此不必等节点跑完就能到达用户。

    图停在人工确认闸门上时，收尾帧换成 ``awaiting_confirmation`` 而不是 ``result``：
    调用方据此知道「这次没有落库，等用户答复」。
    """

    workflow, config = await _resolve_workflow(thread_id)
    observability = get_observability()
    initial = build_initial_state(
        request,
        learner,
        plan,
        provider,
        _should_retrieve(enable_retrieval),
        _should_review(enable_review),
        history,
        confirm_commit=_should_confirm(confirm_commit, thread_id),
    )

    seen_events = 0
    seen_outputs = 0
    final_state: dict[str, Any] = initial
    interrupted = False

    with observability.trace(
        "multi-agent.workflow.stream",
        user_id=str(user_id) if user_id is not None else None,
        session_id=session_id,
        input=request,
        tags=["workflow", "langgraph", "stream"],
        metadata={**_trace_metadata(learner), "history_turns": len(history or [])},
    ) as handle:
        async for mode, chunk in workflow.astream(
            initial, config, stream_mode=["custom", "values"]
        ):
            if mode == "custom":
                # 节点自己推的增量原样透传，例如 {"type": "token", "text": ...}
                yield chunk
                continue

            final_state = chunk

            outputs = chunk.get("outputs") or []
            for item in outputs[seen_outputs:]:
                yield {"type": "output", "output": item}
            seen_outputs = len(outputs)

            events = chunk.get("events") or []
            for event in events[seen_events:]:
                yield {"type": "progress", **event}
            seen_events = len(events)

            # 暂停载荷也走 values 通道；它是本次流出的最后一个状态快照
            if chunk.get("__interrupt__"):
                interrupted = True
                break

        result = build_result(final_state)
        _attach_confirmation(result, final_state, thread_id)
        result.trace_id = handle.trace_id
        result.trace_url = handle.url

        handle.update(
            output=result.reply_text(),
            metadata={
                **_trace_metadata(learner),
                "agents": result.agents,
                "reviewed": result.plan_review is not None,
                "awaiting_confirmation": result.awaiting_confirmation,
            },
        )

    kind = "awaiting_confirmation" if interrupted else "result"
    yield {"type": kind, "result": result.model_dump(mode="json")}

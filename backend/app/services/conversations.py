"""多智能体对话服务：上下文准备、工作流执行与结果落库。

流式场景下的会话管理是关键：工作流执行可能持续数十秒，
因此上下文准备与结果落库各用一次短会话，避免长时间占用数据库连接。
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import AgentConversation, AgentMessage, MessageRole, StudyPlan
from app.db.session import db
from app.schemas import LearnerSnapshot, PlanSnapshot
from app.schemas.api import ChatRequest, ChatResponse
from app.schemas.workflow import PlanConfirmation, WorkflowResult
from app.services.plan_edit import apply_plan_revision
from app.services.plans import persist_plan_draft
from app.services.snapshots import (
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_primary_target,
)
from app.workflows import resume_workflow, run_workflow, stream_workflow

logger = get_logger(__name__)

TITLE_LENGTH = 30
WORKFLOW_NAME = "multi_agent_chat"

STATUS_ACTIVE = "active"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
"""会话停在人工确认上时的状态，用于把「有待确认的计划」与「已完成」区分开。"""

PENDING_SCAN_LIMIT = 20
"""回溯多少条助手消息来找待确认标记。"""


@dataclass(slots=True)
class CommitContext:
    """落库所需的最小上下文：会话、用户、目标与当前计划。

    与 ``ChatContext`` 分开是为了让「恢复一次确认」也能落库——
    那条链路没有本次提问、没有画像，只有一次答复。
    """

    user_id: int
    conversation_id: int
    target_id: int | None
    plan: PlanSnapshot | None
    thread_id: str = ""


@dataclass(slots=True)
class ChatContext:
    """一次对话的执行上下文。"""

    user_id: int
    conversation_id: int
    target_id: int | None
    learner: LearnerSnapshot
    plan: PlanSnapshot | None
    message: str
    provider: str | None
    enable_review: bool | None
    enable_retrieval: bool | None
    history: list[dict[str, str]]
    """当前提问之前的对话轮次，按时间正序，供聊天 Agent 指代上文。"""

    thread_id: str
    """本次提问的检查点线程。

    一轮对话一条线程，而不是一个会话一条：线程状态是**累加**的
    （``outputs`` / ``events`` 都带 add reducer），复用线程会让上一轮的产出
    泄进这一轮的结果里，上一轮的待确认计划也会跟着续到这一轮。
    """

    confirm_commit: bool | None

    def commit(self) -> CommitContext:
        """取出落库所需的字段。"""

        return CommitContext(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            target_id=self.target_id,
            plan=self.plan,
            thread_id=self.thread_id,
        )


def sse(payload: dict) -> str:
    """把事件序列化为 SSE 数据帧。"""

    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _resolve_conversation(
    session: AsyncSession, request: ChatRequest
) -> AgentConversation:
    """复用已有会话或新建。"""

    if request.conversation_id is not None:
        existing = await session.get(AgentConversation, request.conversation_id)
        if existing is not None and existing.user_id == request.user_id:
            return existing

    conversation = AgentConversation(
        user_id=request.user_id,
        title=request.message.strip()[:TITLE_LENGTH],
        workflow=WORKFLOW_NAME,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def _append_message(
    session: AsyncSession,
    conversation_id: int,
    role: MessageRole,
    content: str,
    *,
    agent_name: str = "",
    payload: dict | None = None,
    meta: dict | None = None,
) -> AgentMessage:
    """写入一条会话消息并同步消息计数。"""

    message = AgentMessage(
        conversation_id=conversation_id,
        role=role,
        agent_name=agent_name,
        content=content,
        payload=payload or {},
        meta=meta or {},
    )
    session.add(message)
    await session.flush()

    conversation = await session.get(AgentConversation, conversation_id)
    if conversation is not None:
        total = await session.scalar(
            select(func.count())
            .select_from(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
        )
        conversation.message_count = int(total or 0)
        await session.flush()

    return message


# 知识点：对话记忆的存储形态 —— 会话记录本身就是记忆，不需要另建记忆表：
#   一行消息既是回放给前端的记录，也是下一轮拼进提示词的上文（第3章 Agent进阶·记忆）
async def load_history(
    session: AsyncSession,
    conversation_id: int,
    limit: int,
    *,
    before_id: int | None = None,
) -> list[dict[str, str]]:
    """读取会话中当前提问之前的历史轮次，按时间正序返回。

    只取用户与助手的正文：工具调用轨迹与结构化产出留在 ``meta`` / ``payload`` 里
    供前端回放，不该占用模型的上下文预算。

    ``before_id`` 传本次用户消息的 id，把它自己排除在外——历史是「上文」，
    不包括本次提问。
    """

    conditions = [
        AgentMessage.conversation_id == conversation_id,
        AgentMessage.role.in_((MessageRole.USER, MessageRole.ASSISTANT)),
    ]
    if before_id is not None:
        conditions.append(AgentMessage.id < before_id)

    rows = list(
        await session.scalars(
            select(AgentMessage)
            .where(*conditions)
            .order_by(AgentMessage.id.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return [{"role": str(row.role), "content": row.content or ""} for row in rows]


async def start_conversation(
    session: AsyncSession, request: ChatRequest
) -> ChatContext | None:
    """准备执行上下文：加载画像与计划，创建会话，记录提问并取出上文。"""

    learner = await load_learner_snapshot(session, request.user_id)
    if learner is None:
        return None

    target = await load_primary_target(session, request.user_id)
    plan = await load_latest_plan_snapshot(session, request.user_id)
    conversation = await _resolve_conversation(session, request)

    message = await _append_message(
        session, conversation.id, MessageRole.USER, request.message
    )
    history = await load_history(
        session,
        conversation.id,
        get_settings().workflow.history_limit,
        before_id=message.id,
    )

    return ChatContext(
        user_id=request.user_id,
        conversation_id=conversation.id,
        target_id=target.id if target else None,
        learner=learner,
        plan=plan,
        message=request.message,
        provider=request.provider,
        enable_review=request.enable_review,
        enable_retrieval=request.enable_retrieval,
        history=history,
        thread_id=f"{conversation.id}:{message.id}",
        confirm_commit=request.confirm_commit,
    )


def _result_meta(result: WorkflowResult, **extra: object) -> dict:
    """构造消息元信息，供前端回放调用链。"""

    return {
        "agents": result.agents,
        "tool_calls": [item.model_dump(mode="json") for item in result.tool_calls],
        "trace_id": result.trace_id,
        "events": [item.model_dump(mode="json") for item in result.events],
        **extra,
    }


async def _set_conversation_status(
    session: AsyncSession, conversation_id: int, status: str
) -> None:
    """更新会话状态，用于标记「有待确认的计划」。"""

    conversation = await session.get(AgentConversation, conversation_id)
    if conversation is not None:
        conversation.status = status
        await session.flush()


# 知识点：Checkpointer 与 thread_id —— 落库前的人工确认把「一次运行」劈成两段请求：
#   前半段只落消息、不写计划并记下 thread_id，后半段带回用户答复恢复图再写库
#   （第5章 LangGraph·人工确认）
async def _persist_awaiting_confirmation(
    session: AsyncSession, commit: CommitContext, result: WorkflowResult
) -> ChatResponse:
    """停在确认闸门上的那一次：只记助手消息，**不写任何计划**。"""

    confirmation = result.confirmation
    reply = result.reply_text()
    message = await _append_message(
        session,
        commit.conversation_id,
        MessageRole.ASSISTANT,
        reply,
        agent_name=",".join(result.agents),
        payload={"outputs": [item.model_dump(mode="json") for item in result.outputs]},
        meta=_result_meta(
            result,
            plan_id=None,
            pending_confirmation=(
                confirmation.model_dump(mode="json") if confirmation else None
            ),
        ),
    )
    await _set_conversation_status(session, commit.conversation_id, STATUS_AWAITING_CONFIRMATION)

    return ChatResponse(
        conversation_id=commit.conversation_id,
        message_id=message.id,
        agents=result.agents,
        tool_calls=result.tool_calls,
        outputs=result.outputs,
        reply=reply,
        confirmation=confirmation,
        errors=result.errors,
        trace_id=result.trace_id,
        trace_url=result.trace_url,
    )


async def persist_result(
    session: AsyncSession, commit: CommitContext, result: WorkflowResult
) -> ChatResponse:
    """把工作流结果落库：计划、助手消息与元信息。

    停在人工确认上时改走另一条路：消息照记，计划一个字都不写——
    「确认」的意义就在于用户点头之前数据库是干净的。
    """

    if result.awaiting_confirmation:
        return await _persist_awaiting_confirmation(session, commit, result)

    plan_id: int | None = None
    if result.plan_draft is not None and commit.target_id is not None:
        # 整份重排优先于局部修订：同一轮里两者同时出现时，以重排结果为准
        plan = await persist_plan_draft(
            session,
            user_id=commit.user_id,
            target_id=commit.target_id,
            draft=result.plan_draft,
            generated_by=",".join(result.agents) or "plan_generation",
        )
        plan_id = plan.id
    elif result.plan_draft is not None:
        logger.warning("用户 %s 尚无备考目标，跳过计划落库", commit.user_id)
    elif result.plan_revision is not None and commit.plan is not None:
        # 聊天 Agent 通过 revise_plan 工具提出的改动在这里落库，
        # 图谱本身不碰数据库，保持可脱离数据库单测。
        outcome = await apply_plan_revision(
            session, plan_id=commit.plan.id, revision=result.plan_revision
        )
        plan_id = commit.plan.id
        logger.info("计划修订：%s", "；".join(outcome.details) or "无改动")

    reply = result.reply_text()
    message = await _append_message(
        session,
        commit.conversation_id,
        MessageRole.ASSISTANT,
        reply,
        agent_name=",".join(result.agents),
        payload={
            "outputs": [item.model_dump(mode="json") for item in result.outputs],
            "plan_review": (
                result.plan_review.model_dump(mode="json") if result.plan_review else None
            ),
        },
        meta=_result_meta(result, plan_id=plan_id),
    )

    return ChatResponse(
        conversation_id=commit.conversation_id,
        message_id=message.id,
        agents=result.agents,
        tool_calls=result.tool_calls,
        outputs=result.outputs,
        reply=reply,
        plan_id=plan_id,
        plan_review=result.plan_review,
        errors=result.errors,
        trace_id=result.trace_id,
        trace_url=result.trace_url,
    )


async def load_pending_confirmation(
    session: AsyncSession, conversation_id: int
) -> PlanConfirmation | None:
    """取出该会话待人工确认的内容，没有则返回 ``None``。

    以会话状态为闸门：确认一次之后状态就回到 active，
    同一个 thread 不会被重复恢复，也避免用户点两次「确认」写出两份计划。
    """

    conversation = await session.get(AgentConversation, conversation_id)
    if conversation is None or conversation.status != STATUS_AWAITING_CONFIRMATION:
        return None

    # 取最近若干条助手消息再挑带标记的那条，而不是只看最后一条：
    # 用户可能先追问了别的再回头点确认，此时待确认内容并不在最后一条上。
    rows = await session.scalars(
        select(AgentMessage.meta)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == MessageRole.ASSISTANT,
        )
        .order_by(AgentMessage.id.desc())
        .limit(PENDING_SCAN_LIMIT)
    )
    for meta in rows:
        payload = (meta or {}).get("pending_confirmation")
        if payload:
            return PlanConfirmation.model_validate(payload)
    return None


async def confirm_pending_plan(
    session: AsyncSession, conversation_id: int, approve: bool, feedback: str = ""
) -> ChatResponse | None:
    """恢复被人工确认暂停的那一轮：用户点确认才写库，点驳回则什么都不写。"""

    pending = await load_pending_confirmation(session, conversation_id)
    if pending is None:
        return None

    conversation = await session.get(AgentConversation, conversation_id)
    if conversation is None:  # pragma: no cover - 与上面的查询同事务，不可能只差这一步
        return None

    result = await resume_workflow(
        pending.thread_id, {"approve": approve, "feedback": feedback}
    )
    target = await load_primary_target(session, conversation.user_id)
    commit = CommitContext(
        user_id=conversation.user_id,
        conversation_id=conversation_id,
        target_id=target.id if target else None,
        plan=await load_latest_plan_snapshot(session, conversation.user_id),
        thread_id=pending.thread_id,
    )

    # 先开闸再落库：状态一旦回到 active，重复提交就会被挡在上面那道检查之外
    await _set_conversation_status(session, conversation_id, STATUS_ACTIVE)
    return await persist_result(session, commit, result)


async def handle_chat(session: AsyncSession, request: ChatRequest) -> ChatResponse | None:
    """处理一次非流式对话。"""

    context = await start_conversation(session, request)
    if context is None:
        return None

    result = await run_workflow(
        context.message,
        context.learner,
        context.plan,
        provider=context.provider,
        enable_review=context.enable_review,
        enable_retrieval=context.enable_retrieval,
        user_id=context.user_id,
        session_id=str(context.conversation_id),
        history=context.history,
        thread_id=context.thread_id,
        confirm_commit=context.confirm_commit,
    )
    return await persist_result(session, context.commit(), result)


async def stream_chat(request: ChatRequest) -> AsyncIterator[str]:
    """处理流式对话，按 SSE 推送进度、产出与最终结果。"""

    async with db.session() as session:
        context = await start_conversation(session, request)

    if context is None:
        yield sse({"type": "error", "message": "用户不存在"})
        return

    yield sse({"type": "start", "conversation_id": context.conversation_id})

    final: ChatResponse | None = None
    try:
        async for chunk in stream_workflow(
            context.message,
            context.learner,
            context.plan,
            provider=context.provider,
            enable_review=context.enable_review,
            enable_retrieval=context.enable_retrieval,
            user_id=context.user_id,
            session_id=str(context.conversation_id),
            history=context.history,
            thread_id=context.thread_id,
            confirm_commit=context.confirm_commit,
        ):
            if chunk["type"] in ("result", "awaiting_confirmation"):
                result = WorkflowResult.model_validate(chunk["result"])
                async with db.session() as session:
                    final = await persist_result(session, context.commit(), result)
                if chunk["type"] == "awaiting_confirmation":
                    # 收尾帧自己带齐会话与待确认内容，不再发 done：这一轮并没有完成
                    yield sse(
                        {
                            "type": "awaiting_confirmation",
                            "conversation_id": final.conversation_id,
                            "message_id": final.message_id,
                            "reply": final.reply,
                            "agents": final.agents,
                            "tool_calls": [
                                item.model_dump(mode="json") for item in final.tool_calls
                            ],
                            "confirmation": (
                                final.confirmation.model_dump(mode="json")
                                if final.confirmation
                                else None
                            ),
                            "trace_id": final.trace_id,
                            "trace_url": final.trace_url,
                        }
                    )
                    return
                continue
            yield sse(chunk)
    except Exception as exc:  # noqa: BLE001 - 流式接口必须给出明确收尾
        logger.exception("流式对话失败 conversation=%s", context.conversation_id)
        yield sse({"type": "error", "message": f"生成失败：{exc}"})
        return

    if final is None:  # pragma: no cover - 工作流总会返回结果
        yield sse({"type": "error", "message": "工作流未返回结果"})
        return

    yield sse(
        {
            "type": "done",
            "conversation_id": final.conversation_id,
            "message_id": final.message_id,
            "agents": final.agents,
            "tool_calls": [item.model_dump(mode="json") for item in final.tool_calls],
            "reply": final.reply,
            "plan_id": final.plan_id,
            "errors": final.errors,
            "trace_id": final.trace_id,
            "trace_url": final.trace_url,
        }
    )


async def load_conversation(
    session: AsyncSession, conversation_id: int, user_id: int | None = None
) -> AgentConversation | None:
    """读取会话详情。"""

    conversation = await session.get(AgentConversation, conversation_id)
    if conversation is None:
        return None
    if user_id is not None and conversation.user_id != user_id:
        return None
    return conversation


async def list_conversations(
    session: AsyncSession, user_id: int, limit: int = 20
) -> list[AgentConversation]:
    """列出用户的会话。"""

    return list(
        await session.scalars(
            select(AgentConversation)
            .where(AgentConversation.user_id == user_id)
            .order_by(AgentConversation.id.desc())
            .limit(limit)
        )
    )


async def latest_plan_id(session: AsyncSession, user_id: int) -> int | None:
    """返回用户最新计划 ID。"""

    return await session.scalar(
        select(StudyPlan.id)
        .where(StudyPlan.user_id == user_id)
        .order_by(StudyPlan.id.desc())
        .limit(1)
    )

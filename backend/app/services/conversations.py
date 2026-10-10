"""多智能体对话服务：上下文准备、工作流执行与结果落库。

流式场景下的会话管理是关键：工作流执行可能持续数十秒，
因此上下文准备与结果落库各用一次短会话，避免长时间占用数据库连接。
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AgentConversation, AgentMessage, MessageRole, StudyPlan
from app.db.session import db
from app.schemas import LearnerSnapshot, PlanSnapshot
from app.schemas.api import ChatRequest, ChatResponse
from app.schemas.workflow import WorkflowResult
from app.services.plans import persist_plan_draft
from app.services.snapshots import (
    load_latest_plan_snapshot,
    load_learner_snapshot,
    load_primary_target,
)
from app.workflows import run_workflow, stream_workflow

logger = get_logger(__name__)

TITLE_LENGTH = 30
WORKFLOW_NAME = "multi_agent_chat"


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


async def start_conversation(
    session: AsyncSession, request: ChatRequest
) -> ChatContext | None:
    """准备执行上下文：加载画像、计划，创建会话并记录用户消息。"""

    learner = await load_learner_snapshot(session, request.user_id)
    if learner is None:
        return None

    target = await load_primary_target(session, request.user_id)
    plan = await load_latest_plan_snapshot(session, request.user_id)
    conversation = await _resolve_conversation(session, request)

    await _append_message(session, conversation.id, MessageRole.USER, request.message)

    return ChatContext(
        user_id=request.user_id,
        conversation_id=conversation.id,
        target_id=target.id if target else None,
        learner=learner,
        plan=plan,
        message=request.message,
        provider=request.provider,
        enable_review=request.enable_review,
    )


async def persist_result(
    session: AsyncSession, context: ChatContext, result: WorkflowResult
) -> ChatResponse:
    """把工作流结果落库：计划、助手消息与元信息。"""

    plan_id: int | None = None
    if result.plan_draft is not None and context.target_id is not None:
        plan = await persist_plan_draft(
            session,
            user_id=context.user_id,
            target_id=context.target_id,
            draft=result.plan_draft,
            generated_by=",".join(result.agents) or "plan_generation",
        )
        plan_id = plan.id
    elif result.plan_draft is not None:
        logger.warning("用户 %s 尚无备考目标，跳过计划落库", context.user_id)

    reply = result.reply_text()
    outputs = [item.model_dump(mode="json") for item in result.outputs]

    message = await _append_message(
        session,
        context.conversation_id,
        MessageRole.ASSISTANT,
        reply,
        agent_name=",".join(result.agents),
        payload={
            "outputs": outputs,
            "plan_review": (
                result.plan_review.model_dump(mode="json") if result.plan_review else None
            ),
        },
        meta={
            "intent": result.intent,
            "agents": result.agents,
            "confidence": result.confidence,
            "plan_id": plan_id,
            "trace_id": result.trace_id,
            "events": [item.model_dump(mode="json") for item in result.events],
        },
    )

    return ChatResponse(
        conversation_id=context.conversation_id,
        message_id=message.id,
        intent=result.intent,
        agents=result.agents,
        outputs=result.outputs,
        reply=reply,
        plan_id=plan_id,
        plan_review=result.plan_review,
        errors=result.errors,
        trace_id=result.trace_id,
        trace_url=result.trace_url,
    )


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
        user_id=context.user_id,
        session_id=str(context.conversation_id),
    )
    return await persist_result(session, context, result)


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
            user_id=context.user_id,
            session_id=str(context.conversation_id),
        ):
            if chunk["type"] == "result":
                result = WorkflowResult.model_validate(chunk["result"])
                async with db.session() as session:
                    final = await persist_result(session, context, result)
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
            "intent": final.intent,
            "agents": final.agents,
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

"""多智能体对话接口。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import SessionDep
from app.schemas.api import ChatMessageRead, ChatRequest, ChatResponse, ConversationRead
from app.services.conversations import (
    handle_chat,
    list_conversations,
    load_conversation,
    stream_chat,
)

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("", response_model=ChatResponse, summary="多智能体对话")
async def chat(payload: ChatRequest, session: SessionDep) -> ChatResponse:
    """执行一次多智能体协作对话，并落库会话与计划。"""

    response = await handle_chat(session, payload)
    if response is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return response


@router.post("/stream", summary="多智能体对话（SSE 流式）")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """以 SSE 推送协作进度、智能体产出与最终结果。"""

    return StreamingResponse(
        stream_chat(payload), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    summary="查询会话列表",
)
async def conversations(user_id: int, session: SessionDep, limit: int = 20) -> list[object]:
    """列出用户的会话。"""

    return await list_conversations(session, user_id, limit=limit)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    summary="查询会话详情",
)
async def conversation_detail(
    conversation_id: int,
    session: SessionDep,
    user_id: int | None = None,
) -> object:
    """读取会话及其消息。"""

    conversation = await load_conversation(session, conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessageRead],
    summary="查询会话消息",
)
async def conversation_messages(conversation_id: int, session: SessionDep) -> list[object]:
    """返回会话的消息列表（按时间正序）。"""

    conversation = await load_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return list(conversation.messages)

"""知识库接口。"""

from typing import Any

from fastapi import APIRouter, HTTPException

from app.knowledge import builtin_documents, get_knowledge_base
from app.schemas.api import (
    KnowledgeIngestRequest,
    KnowledgeSearchRequest,
    KnowledgeStatsRead,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/stats", response_model=KnowledgeStatsRead, summary="知识库状态")
async def stats() -> KnowledgeStatsRead:
    """返回向量库与向量化实现信息。"""

    try:
        payload = await get_knowledge_base().stats()
    except Exception as exc:  # noqa: BLE001 - 配置不完整时需要给出可读错误
        raise HTTPException(status_code=503, detail=f"知识库不可用：{exc}") from exc
    return KnowledgeStatsRead.model_validate(payload)


@router.post("/ingest", response_model=KnowledgeStatsRead, summary="写入知识库")
async def ingest(payload: KnowledgeIngestRequest) -> KnowledgeStatsRead:
    """写入内置语料，可选先清空集合。"""

    try:
        base = get_knowledge_base()
        if payload.reset:
            await base.reset()
        if payload.use_builtin:
            await base.ingest(builtin_documents())
        return KnowledgeStatsRead.model_validate(await base.stats())
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"知识库写入失败：{exc}") from exc


@router.post("/search", summary="检索知识库")
async def search(payload: KnowledgeSearchRequest) -> list[dict[str, Any]]:
    """按语义检索知识片段。"""

    try:
        chunks = await get_knowledge_base().search(payload.query, top_k=payload.top_k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"知识库检索失败：{exc}") from exc
    return [chunk.to_payload() for chunk in chunks]

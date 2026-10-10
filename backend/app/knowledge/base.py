"""知识库服务：切片、向量化、入库与检索。"""

from collections.abc import Iterable
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.knowledge.corpus import builtin_documents
from app.knowledge.embeddings import BaseEmbedder, build_embedder
from app.knowledge.stores import BaseVectorStore, build_vector_store
from app.knowledge.text import chunk_text
from app.knowledge.types import Document, RetrievedChunk, VectorRecord

logger = get_logger(__name__)


class KnowledgeBase:
    """知识库门面，屏蔽向量库与向量化实现的差异。"""

    def __init__(
        self,
        store: BaseVectorStore,
        embedder: BaseEmbedder,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._settings = settings or get_settings()

    @property
    def backend(self) -> str:
        """向量库实现名称。"""

        return self._store.backend

    @property
    def collection(self) -> str:
        """集合名称。"""

        return self._store.collection

    @property
    def embedding_name(self) -> str:
        """向量化实现名称。"""

        return self._embedder.name

    @property
    def dimension(self) -> int:
        """向量维度。"""

        return self._embedder.dimension

    def _prepare(self, documents: Iterable[Document]) -> list[tuple[str, str, dict[str, Any]]]:
        """把文档切片为待入库片段。"""

        section = self._settings.knowledge
        prepared: list[tuple[str, str, dict[str, Any]]] = []

        for document in documents:
            fragments = chunk_text(document.text, section.chunk_size, section.chunk_overlap)
            for index, fragment in enumerate(fragments):
                metadata: dict[str, Any] = {
                    **document.metadata,
                    "doc_id": document.id,
                    "source": document.title or document.id,
                    "chunk_index": index,
                    "chunk_total": len(fragments),
                }
                prepared.append((f"{document.id}::{index}", fragment, metadata))

        return prepared

    async def ingest(self, documents: Iterable[Document], *, reset: bool = False) -> int:
        """写入文档，返回写入的片段数。"""

        if reset:
            await self._store.drop()

        prepared = self._prepare(documents)
        if not prepared:
            return 0

        vectors = await self._embedder.embed([item[1] for item in prepared])
        await self._store.ensure_collection(self.dimension)

        records = [
            VectorRecord(id=identifier, vector=vector, text=text, metadata=metadata)
            for (identifier, text, metadata), vector in zip(prepared, vectors, strict=True)
        ]
        written = await self._store.upsert(records)
        logger.info("知识库写入 %d 个片段（backend=%s）", written, self.backend)
        return written

    async def ensure_builtin_corpus(self) -> int:
        """集合为空时写入内置语料，保证开箱即可检索。"""

        if await self._store.count() > 0:
            return 0
        return await self.ingest(builtin_documents())

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        subject: str | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        """检索与查询最相关的知识片段。"""

        if not query.strip():
            return []

        section = self._settings.knowledge
        vector = await self._embedder.embed_one(query)
        return await self._store.search(
            vector,
            top_k or section.top_k,
            section.min_score if min_score is None else min_score,
            subject,
        )

    async def count(self) -> int:
        """已入库片段数。"""

        return await self._store.count()

    async def reset(self) -> None:
        """清空集合。"""

        await self._store.drop()
        logger.info("知识库集合已清空：%s", self.collection)

    async def stats(self) -> dict[str, Any]:
        """返回知识库运行状态。"""

        return {
            "backend": self.backend,
            "collection": self.collection,
            "embedding": self.embedding_name,
            "dimension": self.dimension,
            "chunks": await self.count(),
        }


def build_knowledge_base(settings: Settings | None = None) -> KnowledgeBase:
    """按配置构建知识库。"""

    resolved = settings or get_settings()
    return KnowledgeBase(
        store=build_vector_store(resolved),
        embedder=build_embedder(resolved),
        settings=resolved,
    )


_knowledge_base: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """返回进程内复用的知识库实例。"""

    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = build_knowledge_base()
    return _knowledge_base


def reset_knowledge_base() -> None:
    """清空单例，切换配置后调用。"""

    global _knowledge_base
    _knowledge_base = None


async def retrieve_context(
    query: str, top_k: int | None = None, *, enabled: bool = True
) -> list[RetrievedChunk]:
    """面向工作流的检索入口。

    检索属于增强能力而非核心链路：任何异常都降级为空结果，
    不能因为向量库不可用导致整个问答失败。
    ``enabled=False`` 用于响应用户在本次对话中主动关闭检索的意图。
    """

    settings = get_settings()
    section = settings.knowledge
    if not enabled or not section.enabled or not section.enable_retrieval:
        return []

    try:
        base = get_knowledge_base()
        if section.auto_ingest:
            await base.ensure_builtin_corpus()
        return await base.search(query, top_k)
    except Exception as exc:  # noqa: BLE001 - 兜底降级，避免中断主流程
        logger.warning("知识库检索失败，已跳过检索增强：%s", exc)
        return []

"""向量库实现：Milvus 与本地兜底。

生产环境使用 Milvus；由于 milvus-lite 不支持 Windows，
本地开发使用纯 Python 的 JSON 持久化 + 暴力余弦检索兜底。
两者实现同一接口，业务代码无需感知差异。
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.knowledge.text import cosine_similarity
from app.knowledge.types import RetrievedChunk, VectorRecord

logger = get_logger(__name__)


class BaseVectorStore(ABC):
    """向量库抽象接口。"""

    collection: str

    @property
    def backend(self) -> str:
        """返回实现名称，用于健康检查与日志。"""

        return type(self).__name__

    @abstractmethod
    async def ensure_collection(self, dimension: int) -> None:
        """确保集合存在且维度正确。"""

    @abstractmethod
    async def upsert(self, records: list[VectorRecord]) -> int:
        """写入或覆盖向量记录，返回写入条数。"""

    @abstractmethod
    async def search(
        self,
        vector: list[float],
        top_k: int,
        min_score: float = 0.0,
        subject: str | None = None,
    ) -> list[RetrievedChunk]:
        """按向量检索相似片段。"""

    @abstractmethod
    async def count(self) -> int:
        """返回集合内记录数。"""

    @abstractmethod
    async def drop(self) -> None:
        """删除集合。"""


class LocalVectorStore(BaseVectorStore):
    """本地兜底实现：JSON 持久化 + 暴力余弦检索。

    仅用于开发与测试，数据量在数千片段内表现尚可。
    """

    def __init__(self, collection: str, path: Path) -> None:
        self.collection = collection
        self._path = path / f"{collection}.json"
        self._dimension = 0
        self._records: dict[str, VectorRecord] | None = None

    def _load(self) -> dict[str, VectorRecord]:
        if self._records is not None:
            return self._records

        records: dict[str, VectorRecord] = {}
        if self._path.exists():
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning("向量库文件损坏，将重新开始：%s", exc)
                payload = {}

            self._dimension = int(payload.get("dimension") or 0)
            for item in payload.get("records", []):
                record = VectorRecord(
                    id=str(item.get("id", "")),
                    vector=[float(value) for value in item.get("vector", [])],
                    text=str(item.get("text", "")),
                    metadata=dict(item.get("metadata") or {}),
                )
                records[record.id] = record

        self._records = records
        return records

    def _flush(self) -> None:
        records = self._load()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "collection": self.collection,
            "dimension": self._dimension,
            "records": [
                {
                    "id": record.id,
                    "vector": record.vector,
                    "text": record.text,
                    "metadata": record.metadata,
                }
                for record in records.values()
            ],
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    async def ensure_collection(self, dimension: int) -> None:
        self._load()
        if self._dimension and self._dimension != dimension:
            logger.warning(
                "本地向量库维度由 %d 变更为 %d，将清空历史数据", self._dimension, dimension
            )
            self._records = {}
        self._dimension = dimension

    async def upsert(self, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        stored = self._load()
        for record in records:
            stored[record.id] = record
        self._flush()
        return len(records)

    async def search(
        self,
        vector: list[float],
        top_k: int,
        min_score: float = 0.0,
        subject: str | None = None,
    ) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for record in self._load().values():
            if subject and str(record.metadata.get("subject", "")) != subject:
                continue
            score = cosine_similarity(vector, record.vector)
            if score < min_score:
                continue
            scored.append(
                RetrievedChunk(
                    id=record.id, text=record.text, score=score, metadata=record.metadata
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    async def count(self) -> int:
        return len(self._load())

    async def drop(self) -> None:
        self._records = {}
        self._dimension = 0
        if self._path.exists():
            self._path.unlink()


class MilvusVectorStore(BaseVectorStore):
    """Milvus 向量库实现（MilvusClient 轻量接口）。"""

    ID_MAX_LENGTH = 128

    def __init__(self, collection: str, uri: str, token: str = "") -> None:
        self.collection = collection
        self._uri = uri
        self._token = token
        self._client: Any = None

    @property
    def client(self) -> Any:
        """惰性创建 Milvus 客户端，避免导入期就建立连接。"""

        if self._client is None:
            from pymilvus import MilvusClient

            self._client = MilvusClient(uri=self._uri, token=self._token)
        return self._client

    async def ensure_collection(self, dimension: int) -> None:
        if not self.client.has_collection(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                dimension=dimension,
                primary_field_name="id",
                id_type="string",
                max_length=self.ID_MAX_LENGTH,
                vector_field_name="vector",
                metric_type="COSINE",
                auto_id=False,
                enable_dynamic_field=True,
            )
            logger.info("已创建 Milvus 集合 %s（dim=%d）", self.collection, dimension)

        # 检索要求集合处于加载状态，加载操作幂等，重复调用不会有副作用。
        self.client.load_collection(self.collection)

    async def upsert(self, records: list[VectorRecord]) -> int:
        if not records:
            return 0
        await self.ensure_collection(len(records[0].vector))
        data = [
            {
                "id": record.id,
                "vector": record.vector,
                "text": record.text,
                "metadata": record.metadata,
            }
            for record in records
        ]
        self.client.upsert(collection_name=self.collection, data=data)
        # Milvus 的写入先进入增长段，而 get_collection_stats 的 row_count
        # 在 flush 之前恒为 0。若不显式 flush，count() 会误报空集合，
        # 导致 ensure_builtin_corpus() 每次请求都重复写入。
        self.client.flush(collection_name=self.collection)
        return len(data)

    async def search(
        self,
        vector: list[float],
        top_k: int,
        min_score: float = 0.0,
        subject: str | None = None,
    ) -> list[RetrievedChunk]:
        if not self.client.has_collection(self.collection):
            return []

        self.client.load_collection(self.collection)
        results = self.client.search(
            collection_name=self.collection,
            data=[vector],
            limit=top_k,
            output_fields=["text", "metadata"],
        )

        chunks: list[RetrievedChunk] = []
        for hit in (results[0] if results else []):
            entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
            score = float(hit.get("distance", 0.0)) if isinstance(hit, dict) else 0.0
            if score < min_score:
                continue
            metadata = dict(entity.get("metadata") or {})
            if subject and str(metadata.get("subject", "")) != subject:
                continue
            chunks.append(
                RetrievedChunk(
                    id=str(hit.get("id", "")),
                    text=str(entity.get("text", "")),
                    score=score,
                    metadata=metadata,
                )
            )
        return chunks

    async def count(self) -> int:
        if not self.client.has_collection(self.collection):
            return 0
        stats = self.client.get_collection_stats(self.collection)
        return int(stats.get("row_count", 0))

    async def drop(self) -> None:
        if self.client.has_collection(self.collection):
            self.client.drop_collection(self.collection)


def build_vector_store(settings: Settings | None = None) -> BaseVectorStore:
    """按配置构建向量库实现。"""

    resolved = settings or get_settings()
    section = resolved.vector

    if section.backend == "milvus":
        return MilvusVectorStore(section.collection, section.milvus_uri, section.milvus_token)

    path = Path(section.local_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return LocalVectorStore(section.collection, path)

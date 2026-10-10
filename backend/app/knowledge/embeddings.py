"""向量化适配层。

DeepSeek 没有 embedding 接口，因此向量化单独配置：
- stub：确定性哈希向量，离线可用，保证无网络也能跑通全流程与测试；
- ollama / openai / dashscope：走 OpenAI 兼容的 /embeddings 协议。
"""

from abc import ABC, abstractmethod

import httpx

from app.core.config import EmbeddingSection, Settings, get_settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.knowledge.text import normalize_vector, token_hash, tokenize

logger = get_logger(__name__)

STUB_MODEL = "stub-hash"


class BaseEmbedder(ABC):
    """向量化接口。"""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    @property
    def name(self) -> str:
        """返回可读的实现标识。"""

        return f"{type(self).__name__}({self.dimension})"

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回顺序与输入一致。"""

    async def embed_one(self, text: str) -> list[float]:
        """单条向量化。"""

        vectors = await self.embed([text])
        return vectors[0] if vectors else [0.0] * self.dimension


class StubEmbedder(BaseEmbedder):
    """确定性哈希向量。

    采用 hashing trick：同一 token 恒映射到同一维度并带符号，
    因此两段文本重叠越多、余弦相似度越高——离线状态下的检索依然有意义，
    而不是随机噪声。
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = token_hash(token)
            index = digest % self.dimension
            sign = 1.0 if (digest >> 63) & 1 == 0 else -1.0
            vector[index] += sign
        return normalize_vector(vector)


class OpenAICompatEmbedder(BaseEmbedder):
    """兼容 OpenAI Embeddings 协议的向量化客户端。"""

    def __init__(
        self,
        dimension: int,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float,
        batch_size: int,
    ) -> None:
        super().__init__(dimension)
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._batch_size = max(1, batch_size)

    @property
    def name(self) -> str:
        return f"{self._model}({self.dimension})"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                vectors.extend(await self._call(client, batch))
        return vectors

    async def _call(self, client: httpx.AsyncClient, batch: list[str]) -> list[list[float]]:
        response = await client.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._model, "input": batch},
        )
        response.raise_for_status()
        payload = response.json()

        items = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        if len(items) != len(batch):
            raise ValueError(f"向量化返回数量不匹配：期望 {len(batch)}，实际 {len(items)}")
        return [normalize_vector([float(value) for value in item["embedding"]]) for item in items]


def build_embedder(settings: Settings | None = None) -> BaseEmbedder:
    """按配置构建向量化实现。"""

    resolved = settings or get_settings()
    section: EmbeddingSection = resolved.embedding
    config = section.resolved()

    if config["provider"] == "stub":
        return StubEmbedder(section.dimension)

    if not section.is_ready:
        raise ConfigurationError(
            f"向量化提供方 {config['provider']} 缺少密钥配置，请检查 .env 或改用 stub"
        )

    return OpenAICompatEmbedder(
        section.dimension,
        model=config["model"],
        base_url=config["base_url"],
        api_key=config["api_key"],
        timeout=section.timeout_seconds,
        batch_size=section.batch_size,
    )

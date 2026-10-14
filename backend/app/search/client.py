"""联网搜索适配层。

Tavily 与博查（Bocha）协议不同但职责相同：给一个查询词，回一批带 URL 的摘要。
差异集中在两个 ``_parse``，因此适配成本在配置而不是在调用方。

只用已装的 ``httpx``，不引入额外的搜索 SDK —— 少一个依赖就少一处需要跟着协议变更维护的地方。
"""

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import SearchSection, Settings, get_settings
from app.core.errors import ConfigurationError
from app.search.types import SearchResult


class BaseSearchClient(ABC):
    """搜索接口。"""

    provider: str = ""

    def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @abstractmethod
    async def search(self, query: str, *, top_k: int) -> list[SearchResult]:
        """执行一次搜索，返回按相关性排序的结果。"""


class TavilySearchClient(BaseSearchClient):
    """Tavily 搜索客户端（``POST /search``，Bearer 鉴权）。"""

    provider = "tavily"

    async def search(self, query: str, *, top_k: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/search",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "max_results": top_k, "search_depth": "basic"},
            )
            response.raise_for_status()
            payload = response.json()

        return [self._parse(item) for item in payload.get("results") or []]

    @staticmethod
    def _parse(item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=str(item.get("title") or "").strip(),
            url=str(item.get("url") or "").strip(),
            snippet=str(item.get("content") or "").strip(),
            score=_as_float(item.get("score")),
            provider="tavily",
        )


class BochaSearchClient(BaseSearchClient):
    """博查搜索客户端（``POST /v1/web-search``，Bearer 鉴权）。"""

    provider = "bocha"

    async def search(self, query: str, *, top_k: int) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/web-search",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "count": top_k, "summary": True},
            )
            response.raise_for_status()
            payload = response.json()

        pages = (payload.get("data") or {}).get("webPages") or {}
        return [self._parse(item) for item in pages.get("value") or []]

    @staticmethod
    def _parse(item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=str(item.get("name") or "").strip(),
            url=str(item.get("url") or "").strip(),
            # 开了 summary 时摘要更长，优先用它；没有则退回 snippet
            snippet=str(item.get("summary") or item.get("snippet") or "").strip(),
            provider="bocha",
        )


# Tavily 的 results 与博查的 data.webPages.value 形状不同，但都归一到同一个
# SearchResult；调用方拿到的结果与用的是哪一家无关。
PROVIDER_CLIENTS: dict[str, type[BaseSearchClient]] = {
    "tavily": TavilySearchClient,
    "bocha": BochaSearchClient,
}


def build_search_client(settings: Settings | None = None) -> BaseSearchClient:
    """按配置构建搜索客户端。"""

    resolved = settings or get_settings()
    section: SearchSection = resolved.search

    if not section.is_ready:
        raise ConfigurationError(f"搜索提供方 {section.provider} 缺少密钥配置，请检查 .env")

    return PROVIDER_CLIENTS[section.provider](
        api_key=section.api_key,
        base_url=section.base_url,
        timeout=section.timeout_seconds,
    )


def _as_float(value: Any) -> float:
    """把提供方给出的相关性字段安全地转成浮点数。

    第三方响应里这个字段可能是字符串、null 或者压根没有，
    直接 ``float()`` 会让整次搜索因为一个不重要的字段而失败。
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
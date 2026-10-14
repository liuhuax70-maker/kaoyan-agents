"""联网搜索的数据结构。"""

from dataclasses import dataclass, field

from app.knowledge.types import RetrievedChunk


@dataclass(slots=True)
class SearchResult:
    """一条联网搜索结果。"""

    title: str
    url: str
    snippet: str
    score: float = 0.0
    provider: str = ""

    # 知识点：多数据源的统一片段形状 —— 外部数据源只要产出同一种「带来源的片段」，
    #   下游的引用渲染与溯源链路就不必为每加一个数据源重写一遍（第4章 RAG Agent·构建知识库）
    def to_chunk(self, *, subject: str = "择校") -> RetrievedChunk:
        """适配成知识库片段，复用既有的引用与溯源链路。

        ``source`` 取页面标题而不是 URL：引用列表里要显示人能读懂的名字，
        URL 另放在 ``metadata["url"]``，由前端渲染成可点击链接。
        """

        return RetrievedChunk(
            id=self.url or self.title,
            text=self.snippet,
            score=self.score,
            metadata={
                "source": self.title or self.url,
                "title": self.title,
                "url": self.url,
                "subject": subject,
                "provider": self.provider,
            },
        )


@dataclass(slots=True)
class OfficialLink:
    """一条官方核验入口。"""

    label: str
    url: str


@dataclass(slots=True)
class SchoolIntel:
    """一次择校情报采集的结果。"""

    results: list[SearchResult] = field(default_factory=list)
    links: list[OfficialLink] = field(default_factory=list)
    degraded: bool = False
    """为 True 表示走了兜底路径（未启用、无密钥或搜索失败），此时 ``results`` 必为空。"""
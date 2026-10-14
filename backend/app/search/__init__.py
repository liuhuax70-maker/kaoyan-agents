"""联网搜索与官方入口兜底（择校情报的数据来源）。"""

from app.search.base import gather_school_intel
from app.search.client import (
    BaseSearchClient,
    BochaSearchClient,
    TavilySearchClient,
    build_search_client,
)
from app.search.official_links import official_entry_links
from app.search.types import OfficialLink, SchoolIntel, SearchResult

__all__ = [
    "BaseSearchClient",
    "BochaSearchClient",
    "OfficialLink",
    "SchoolIntel",
    "SearchResult",
    "TavilySearchClient",
    "build_search_client",
    "gather_school_intel",
    "official_entry_links",
]
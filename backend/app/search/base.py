"""择校情报采集门面。"""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.search.client import build_search_client
from app.search.official_links import official_entry_links
from app.search.types import SchoolIntel

logger = get_logger(__name__)


# 知识点：增强能力的降级契约 —— 联网检索是增强而非核心链路，任何异常都必须降级为
#   「空结果 + 兜底入口」而不是抛出；同时兜底内容本身要有用，否则降级等于功能消失
#   （第4章 RAG Agent·构建知识库）
async def gather_school_intel(
    query: str,
    *,
    school: str = "",
    major: str = "",
    top_k: int | None = None,
    enabled: bool = True,
) -> SchoolIntel:
    """采集择校情报：联网搜索结果 + 官方核验入口。

    与 ``retrieve_context`` 同一条契约：未启用、无密钥、超时或报错都降级为
    「无搜索结果 + 官方入口」，``degraded`` 置 True。官方入口不依赖任何外部服务，
    因此即使完全没有搜索能力，「去哪里核验」这件事依然有答案。
    """

    links = official_entry_links(school, major=major)
    section = get_settings().search

    if not enabled or not section.enabled:
        return SchoolIntel(links=links, degraded=True)

    try:
        client = build_search_client()
        results = await client.search(query, top_k=top_k or section.top_k)
    except Exception as exc:  # noqa: BLE001 - 兜底降级，避免中断主流程
        logger.warning("联网搜索失败，已降级为官方入口兜底：%s", exc)
        return SchoolIntel(links=links, degraded=True)

    return SchoolIntel(results=results, links=links)
"""官方核验入口的确定性生成。"""

from urllib.parse import quote_plus

from app.search.types import OfficialLink

YZ_CHSI_CATALOG = "https://yz.chsi.com.cn/zsml/"
"""研招网硕士专业目录查询入口。与院校无关，因此永远有效。"""

SEARCH_JUMP = "https://www.baidu.com/s?wd={query}"
"""搜索跳转 URL 模板，用来构造「去哪查」而不是「查到什么」。"""


# 知识点：幻觉抑制的工程手段 —— 「去哪核验」不交给模型生成：让它写院校域名等于
#   请它编造链接，而链接一旦编错就是「把假事实当事实交付」（第4章 RAG Agent）
def official_entry_links(school: str, *, major: str = "") -> list[OfficialLink]:
    """返回目标院校的官方核验入口。

    只给确定性入口与搜索跳转 URL，**绝不猜院校域名**：``yz.example.edu.cn``
    这类猜测是在编造事实，猜错还可能落到抢注域名；跳转 URL 永远可解析。
    ``school`` 为空时只返回与院校无关的研招网入口，仍保证「有地方可查」。
    """

    links = [OfficialLink("研招网 · 硕士专业目录", YZ_CHSI_CATALOG)]

    name = school.strip()
    if not name:
        return links

    topic = " ".join(filter(None, [name, major.strip()]))
    links.append(OfficialLink(f"{name} 研究生院 · 招生简章", _jump(f"{name} 研究生院 招生简章")))
    if major.strip():
        links.append(OfficialLink(f"{topic} · 招生专业目录", _jump(f"{topic} 招生专业目录")))
    links.append(OfficialLink(f"{name} 官网", _jump(f"{name} 官网")))
    return links


def _jump(query: str) -> str:
    """把查询词包成搜索跳转 URL。"""

    return SEARCH_JUMP.format(query=quote_plus(query))
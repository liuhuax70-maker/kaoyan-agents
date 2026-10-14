"""联网搜索与官方入口兜底的用例。

分层验证：客户端只断言「请求构造 + 响应解析」，门面断言「降级契约」，
官方入口断言「绝不编造院校域名」。
"""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import SearchSection
from app.core.errors import ConfigurationError
from app.prompts.context import render_official_links, render_web_intel
from app.search import base as base_module
from app.search import client as client_module
from app.search import gather_school_intel
from app.search.official_links import official_entry_links
from app.search.types import SchoolIntel, SearchResult

# 本模块要验证的正是客户端自己构造请求与解析响应这两件事，
# 而 conftest 的 autouse 夹具会把 search 换成假实现（它服务的是上层用例）。
# 因此在导入期先留一份真实现的引用，再由下面的夹具还原回去。
REAL_SEARCH_METHODS = {
    client_module.TavilySearchClient: client_module.TavilySearchClient.search,
    client_module.BochaSearchClient: client_module.BochaSearchClient.search,
}


@pytest.fixture(autouse=True)
def real_search_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    """还原真实的 search 实现，覆盖 conftest 的假件。

    在导入期抓取原方法再还原，而不是重新实现一遍 —— 测的必须是真正要上线的代码。
    """

    for client_class, method in REAL_SEARCH_METHODS.items():
        monkeypatch.setattr(client_class, "search", method)


TAVILY_PAYLOAD: dict[str, Any] = {
    "query": "计算机考研 择校",
    "results": [
        {
            "title": "某校招生简章",
            "url": "https://example.edu.cn/zs",
            "content": "招收计算机技术专业硕士。",
            "score": "0.87",
        },
        {
            "title": "无分数条目",
            "url": "https://example.edu.cn/b",
            "content": "内容",
            "score": None,
        },
    ],
}

BOCHA_PAYLOAD: dict[str, Any] = {
    "code": 200,
    "data": {
        "webPages": {
            "value": [
                {
                    "name": "某校分数线公告",
                    "url": "https://example.edu.cn/line",
                    "snippet": "短摘要",
                    "summary": "更完整的摘要内容。",
                }
            ]
        }
    },
}


class RecordingClient:
    """``httpx.AsyncClient`` 的替身：记录请求并返回预置响应。

    比 MockTransport 更适合这里的场景 —— 客户端内部自行构造 ``AsyncClient``，
    没有注入 transport 的口子，而这里真正要断言的正是「构造出了什么请求」。
    """

    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> "RecordingClient":
        return self

    async def __aenter__(self) -> "RecordingClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(
        self, url: str, headers: dict[str, str] | None = None, json: Any = None
    ) -> httpx.Response:
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return httpx.Response(
            self.status, json=self.payload, request=httpx.Request("POST", url)
        )


def _section(**overrides: Any) -> SearchSection:
    """构造一份可直接注入的搜索配置。"""

    defaults: dict[str, Any] = {
        "enabled": True,
        "tavily_api_key": "test-key",
        "tavily_base_url": "https://api.tavily.test",
        "bocha_api_key": "test-key",
        "bocha_base_url": "https://api.bocha.test",
    }
    return SearchSection(**{**defaults, **overrides})


def _install_config(monkeypatch: pytest.MonkeyPatch, section: SearchSection) -> None:
    """把配置注入到门面与工厂两个命名空间。"""

    stub = SimpleNamespace(search=section)
    monkeypatch.setattr(base_module, "get_settings", lambda: stub)
    monkeypatch.setattr(client_module, "get_settings", lambda: stub)


# --------------------------------------------------------------------------
# 客户端：请求构造与响应解析
# --------------------------------------------------------------------------


async def test_tavily_client_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RecordingClient(TAVILY_PAYLOAD)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", recorder)

    client = client_module.TavilySearchClient(
        api_key="test-key", base_url="https://api.tavily.test", timeout=5.0
    )
    results = await client.search("计算机考研 择校", top_k=5)

    call = recorder.calls[0]
    assert call["url"] == "https://api.tavily.test/search"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["max_results"] == 5

    assert len(results) == 2
    assert results[0].title == "某校招生简章"
    assert results[0].url == "https://example.edu.cn/zs"
    assert results[0].provider == "tavily"
    # 相关性字段可能是字符串或 null，直接 float() 会让整次搜索因一个次要字段失败
    assert results[0].score == pytest.approx(0.87)
    assert results[1].score == 0.0


async def test_bocha_client_parses_nested_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RecordingClient(BOCHA_PAYLOAD)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", recorder)

    client = client_module.BochaSearchClient(
        api_key="test-key", base_url="https://api.bocha.test", timeout=5.0
    )
    results = await client.search("计算机考研 择校", top_k=3)

    call = recorder.calls[0]
    assert call["url"] == "https://api.bocha.test/v1/web-search"
    assert call["json"]["count"] == 3

    assert results[0].title == "某校分数线公告"
    assert results[0].provider == "bocha"
    # 开了 summary 时优先用更完整的字段
    assert results[0].snippet == "更完整的摘要内容。"


async def test_search_client_propagates_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """客户端本身不吞异常，降级由门面负责 —— 职责分开才好分别测。"""

    recorder = RecordingClient({}, status=500)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", recorder)

    client = client_module.TavilySearchClient(
        api_key="test-key", base_url="https://api.tavily.test", timeout=5.0
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.search("任意查询", top_k=3)


def test_build_search_client_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section(tavily_api_key=""))
    with pytest.raises(ConfigurationError):
        client_module.build_search_client()


def test_build_search_client_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section(provider="bocha"))
    assert client_module.build_search_client().provider == "bocha"

    _install_config(monkeypatch, _section(provider="tavily"))
    assert client_module.build_search_client().provider == "tavily"


# --------------------------------------------------------------------------
# 官方入口：绝不编造院校域名
# --------------------------------------------------------------------------


def test_official_entry_links_without_school() -> None:
    links = official_entry_links("")
    assert len(links) == 1
    assert links[0].url == "https://yz.chsi.com.cn/zsml/"


def test_official_entry_links_never_fabricate_school_host() -> None:
    """入口只能是「确定性站点 + 搜索跳转」。

    猜 ``yz.example.edu.cn`` 这类域名是在编造事实，猜错还可能落到抢注域名；
    因此这里断言主机名白名单，而不是断言某条具体链接长什么样。
    """

    links = official_entry_links("某某大学", major="计算机技术")

    assert len(links) >= 3
    allowed = {"yz.chsi.com.cn", "www.baidu.com"}
    for item in links:
        assert httpx.URL(item.url).host in allowed
        assert item.label

    labels = " ".join(item.label for item in links)
    assert "某某大学" in labels
    assert "研招网" in labels


# --------------------------------------------------------------------------
# 门面：降级契约
# --------------------------------------------------------------------------


async def test_gather_degrades_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section(enabled=False))
    intel = await gather_school_intel("择校", school="某某大学", major="计算机技术")

    assert intel.degraded is True
    assert intel.results == []
    # 降级不等于功能消失：核验入口依然要在
    assert len(intel.links) >= 3


async def test_gather_degrades_when_per_call_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section())
    intel = await gather_school_intel("择校", enabled=False)

    assert intel.degraded is True
    assert intel.results == []


async def test_gather_degrades_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section(tavily_api_key=""))
    intel = await gather_school_intel("择校", school="某某大学")

    assert intel.degraded is True
    assert intel.results == []
    assert intel.links


async def test_gather_degrades_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section())
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient", RecordingClient({}, status=503)
    )

    intel = await gather_school_intel("择校", school="某某大学")
    assert intel.degraded is True
    assert intel.results == []


async def test_gather_returns_results_and_links(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_config(monkeypatch, _section())
    monkeypatch.setattr(
        client_module.httpx, "AsyncClient", RecordingClient(TAVILY_PAYLOAD)
    )

    intel = await gather_school_intel("计算机考研 择校", school="某某大学", major="计算机技术")

    assert intel.degraded is False
    assert len(intel.results) == 2
    assert len(intel.links) >= 3


# --------------------------------------------------------------------------
# 接入既有引用链路
# --------------------------------------------------------------------------


def test_search_result_adapts_to_retrieved_chunk() -> None:
    """引用列表要显示人能读懂的名字，URL 另放 metadata 供前端做链接。"""

    result = SearchResult(
        title="某校招生简章", url="https://example.edu.cn/zs", snippet="正文", score=0.9
    )
    chunk = result.to_chunk()

    assert chunk.source == "某校招生简章"
    assert chunk.subject == "择校"
    payload = chunk.to_payload()
    assert payload["metadata"]["url"] == "https://example.edu.cn/zs"


def test_render_web_intel_includes_urls() -> None:
    intel = SchoolIntel(
        results=[SearchResult(title="某校", url="https://example.edu.cn/zs", snippet="正文")]
    )
    rendered = render_web_intel(intel)
    assert "https://example.edu.cn/zs" in rendered
    assert "某校" in rendered


def test_render_web_intel_distinguishes_disabled_from_empty() -> None:
    """「未启用」与「搜了但没结果」对模型的约束不同，不能都渲染成同一句话。"""

    disabled = render_web_intel(SchoolIntel(degraded=True))
    empty = render_web_intel(SchoolIntel(degraded=False))

    assert "未启用" in disabled
    assert "没有返回结果" in empty
    # 两条路径都要明确禁止编造具体数字
    assert "不得编造" in disabled
    assert "不得编造" in empty


def test_render_official_links_lists_entries() -> None:
    rendered = render_official_links(official_entry_links("某某大学"))
    assert "研招网" in rendered
    assert "https://yz.chsi.com.cn/zsml/" in rendered
"""测试夹具。

环境变量必须在导入应用模块之前设置：配置对象带缓存，
一旦提前读取就会固化默认值。
"""

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

TMP_DIR = Path(tempfile.gettempdir()) / "kaoyan_agents_test"
TMP_DIR.mkdir(parents=True, exist_ok=True)

os.environ["APP__ENV"] = "testing"
os.environ["APP__LOG_LEVEL"] = "WARNING"
os.environ["DATABASE__URL"] = f"sqlite+aiosqlite:///{(TMP_DIR / 'test.db').as_posix()}"
os.environ["VECTOR__BACKEND"] = "local"
os.environ["LLM__DEFAULT_PROVIDER"] = "stub"
os.environ["CELERY__TASK_ALWAYS_EAGER"] = "true"
# 测试环境没有 Redis，缩短超时避免连接等待拖慢用例
os.environ["REDIS__SOCKET_TIMEOUT"] = "0.5"
# 默认关闭计划评审协作，需要覆盖的用例显式开启
os.environ["WORKFLOW__ENABLE_PLAN_REVIEW"] = "false"

import fakeredis.aioredis  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.cache.redis import cache  # noqa: E402
from app.main import app  # noqa: E402

FakeRedisClient = fakeredis.aioredis.FakeRedis


@pytest.fixture
async def fake_cache(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeRedisClient]:
    """用内存 Redis 替换真实连接，避免测试依赖 Docker。"""

    client = FakeRedisClient(decode_responses=True)
    monkeypatch.setattr(cache, "_client", client)
    yield client
    await client.aclose()
    monkeypatch.setattr(cache, "_client", None)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """返回直连 ASGI 应用的异步客户端。"""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client

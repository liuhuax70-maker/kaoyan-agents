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
# 默认提供方必须是一个「配置齐全即视为就绪」的真实提供方：
# 测试用假模型接管调用，但健康检查读的是配置本身，因此不能是空密钥的 deepseek。
os.environ["LLM__DEFAULT_PROVIDER"] = "ollama"
os.environ["CELERY__TASK_ALWAYS_EAGER"] = "true"
# 测试环境没有 Redis，缩短超时避免连接等待拖慢用例
os.environ["REDIS__SOCKET_TIMEOUT"] = "0.5"
# 默认关闭计划评审协作，需要覆盖的用例显式开启
os.environ["WORKFLOW__ENABLE_PLAN_REVIEW"] = "false"
# 默认不在落库前暂停：绝大多数用例验证的是编排与落库本身，
# 人工确认那条链路由 test_api.py 的确认用例显式打开
os.environ["WORKFLOW__REQUIRE_PLAN_CONFIRMATION"] = "false"
# 向量库落到临时目录，避免污染仓库
os.environ["VECTOR__LOCAL_PATH"] = str(TMP_DIR / "vectorstore")

import fakeredis.aioredis  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.cache.redis import cache  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import db  # noqa: E402
from app.main import app  # noqa: E402
from tests.fakes import (  # noqa: E402
    install_fake_checkpointer,
    install_fake_embedder,
    install_fake_model,
    install_fake_search,
)

FakeRedisClient = fakeredis.aioredis.FakeRedis


@pytest.fixture(autouse=True)
def fake_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    """把模型与向量化工厂替换成测试假件。

    自动启用：绝大多数用例验证的是编排、落库与接口契约，
    不应因为缺密钥或缺网络而失败。需要真实工厂行为的用例自行覆盖本夹具。
    """

    install_fake_model(monkeypatch)
    install_fake_embedder(monkeypatch)
    install_fake_search(monkeypatch)


@pytest.fixture(autouse=True)
def fake_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """把工作流检查点换成内存实现。

    与假模型同理：用例验证的是「暂停—恢复」这条链路本身，
    而不是 SQLite 或 PostgreSQL 的存取细节，换掉后端即可在无外部依赖的前提下跑通。
    真实后端的装配由 ``test_checkpoint.py`` 直接验证。
    """

    install_fake_checkpointer(monkeypatch)


@pytest.fixture
async def app_db() -> AsyncIterator[AsyncSession]:
    """面向应用数据库单例的会话。

    每个用例重建表结构以保证隔离；任务与 API 共用同一套配置，
    因此这里必须用 ``db`` 单例而不是另建引擎。
    """

    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with db.session_factory() as session:
        yield session
        await session.rollback()


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
    """返回直连 ASGI 应用的异步客户端。

    每个用例重建表结构，保证接口测试之间互不干扰。
    """

    async with db.engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client

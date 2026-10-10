"""骨架可用性测试：配置、健康检查与依赖降级。"""

from httpx import AsyncClient

from app.core.config import DatabaseSection, Settings, get_settings
from app.main import app, lifespan


async def test_root_returns_service_info(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "kaoyan-agents"
    assert body["health"] == "/api/health"


async def test_health_reports_all_components(
    client: AsyncClient, fake_cache: object
) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "testing"
    assert body["components"]["database"]["ok"] is True
    assert body["components"]["redis"]["ok"] is True
    assert body["components"]["llm"]["ready"] is True
    assert body["components"]["vector"]["backend"] == "local"


async def test_lifespan_boots_and_serves_health(
    client: AsyncClient, fake_cache: object
) -> None:
    """启动钩子需完成数据库探测与缓存连接，且不阻塞接口。"""

    async with lifespan(app):
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_degrades_without_redis(client: AsyncClient) -> None:
    """Redis 不可用时不应中断服务，只降级为 degraded。"""

    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["components"]["redis"]["ok"] is False


def test_settings_read_from_environment() -> None:
    settings = get_settings()
    assert settings.app.env == "testing"
    assert settings.database.is_sqlite is True
    assert settings.vector.backend == "local"
    assert settings.celery.task_always_eager is True


def test_database_url_masks_password() -> None:
    section = DatabaseSection(url="postgresql+asyncpg://kaoyan:secret@db:5432/kaoyan")
    assert "secret" not in section.safe_url
    assert section.is_sqlite is False


def test_llm_provider_config_and_readiness() -> None:
    settings = Settings(
        llm={
            "default_provider": "deepseek",
            "deepseek_api_key": "sk-test",
            "ollama_base_url": "http://localhost:11434/v1",
        }
    )
    deepseek = settings.llm.provider_config()
    assert deepseek["model"] == "deepseek-chat"
    assert deepseek["base_url"] == "https://api.deepseek.com/v1"
    assert settings.llm.is_ready() is True

    assert settings.llm.is_ready("ollama") is True
    assert settings.llm.provider_config("ollama")["model"] == "qwen2.5:7b"
    assert settings.llm.is_ready("openai") is False

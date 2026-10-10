"""应用配置。

所有配置集中在此处声明，通过环境变量或 .env 文件覆盖；
嵌套配置使用双下划线分隔，例如 ``DATABASE__URL`` 对应 ``database.url``。
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "testing", "production"]
LLMProviderName = Literal["stub", "deepseek", "ollama", "openai"]
VectorBackend = Literal["milvus", "local"]

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "stub": {"api_key": "", "base_url": "", "model": "stub"},
    "deepseek": {
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "ollama": {
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
    },
    "openai": {"api_key": "", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
}


class AppSection(BaseModel):
    """应用级配置。"""

    name: str = "kaoyan-agents"
    env: AppEnv = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"
    log_json: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        """返回允许跨域的来源列表。"""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        """是否运行在生产环境。"""

        return self.env == "production"


class DatabaseSection(BaseModel):
    """数据库配置，支持 PostgreSQL 与 SQLite 兜底。"""

    url: str = "sqlite+aiosqlite:///./data/kaoyan.db"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_pre_ping: bool = True

    @property
    def is_sqlite(self) -> bool:
        """是否为 SQLite 连接串。"""

        return self.url.startswith("sqlite")

    @property
    def safe_url(self) -> str:
        """隐藏密码后的连接串，用于日志与健康检查。"""

        if "://" not in self.url or "@" not in self.url:
            return self.url
        scheme, rest = self.url.split("://", 1)
        _, host = rest.split("@", 1)
        return f"{scheme}://***@{host}"


class RedisSection(BaseModel):
    """Redis 配置。"""

    url: str = "redis://localhost:6379/0"
    socket_timeout: float = 5.0
    max_connections: int = 50


class CelerySection(BaseModel):
    """Celery 异步任务配置。"""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"
    task_always_eager: bool = True
    timezone: str = "Asia/Shanghai"


class VectorSection(BaseModel):
    """向量库配置。"""

    backend: VectorBackend = "local"
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""
    collection: str = "kaoyan_knowledge"
    embedding_dim: int = 1024
    top_k: int = 6
    local_path: str = "./data/vectorstore"


class LLMSection(BaseModel):
    """大模型配置，统一走 OpenAI 兼容适配层。"""

    default_provider: LLMProviderName = "stub"
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout_seconds: float = 60.0
    max_retries: int = 2

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:7b"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    def provider_config(self, name: str | None = None) -> dict[str, Any]:
        """返回指定提供方的连接参数。"""

        provider = str(name or self.default_provider).lower()
        if provider == "deepseek":
            overrides = {
                "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url,
                "model": self.deepseek_model,
            }
        elif provider == "ollama":
            overrides = {"base_url": self.ollama_base_url, "model": self.ollama_model}
        elif provider == "openai":
            overrides = {
                "api_key": self.openai_api_key,
                "base_url": self.openai_base_url,
                "model": self.openai_model,
            }
        elif provider == "stub":
            overrides = {}
        else:
            raise ValueError(f"不支持的大模型提供方：{provider}")

        config = {**PROVIDER_DEFAULTS[provider], **overrides}
        config["provider"] = provider
        return config

    def is_ready(self, name: str | None = None) -> bool:
        """判断指定提供方是否具备可用凭据。"""

        config = self.provider_config(name)
        if config["provider"] == "stub":
            return True
        if config["provider"] == "ollama":
            return bool(config["base_url"])
        return bool(config["api_key"])


class WorkflowSection(BaseModel):
    """多智能体协作配置。"""

    enable_plan_review: bool = True
    """生成计划后是否自动触发评审协作。"""

    plan_review_process: Literal["crew", "local"] = "crew"
    """评审执行方式：crew 走 CrewAI 多角色协作，local 走单智能体离线评审。"""


class ObservabilitySection(BaseModel):
    """可观测性配置（LangFuse）。"""

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def langfuse_active(self) -> bool:
        """LangFuse 是否具备完整凭据。"""

        return (
            self.langfuse_enabled
            and bool(self.langfuse_public_key)
            and bool(self.langfuse_secret_key)
        )


class Settings(BaseSettings):
    """全局配置聚合。"""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSection = Field(default_factory=AppSection)
    database: DatabaseSection = Field(default_factory=DatabaseSection)
    redis: RedisSection = Field(default_factory=RedisSection)
    celery: CelerySection = Field(default_factory=CelerySection)
    vector: VectorSection = Field(default_factory=VectorSection)
    llm: LLMSection = Field(default_factory=LLMSection)
    workflow: WorkflowSection = Field(default_factory=WorkflowSection)
    observability: ObservabilitySection = Field(default_factory=ObservabilitySection)


@lru_cache
def get_settings() -> Settings:
    """返回带缓存的配置单例。"""

    return Settings()

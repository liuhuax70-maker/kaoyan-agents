"""按配置构建聊天模型。

所有提供方（DeepSeek / Ollama / OpenAI）都走 OpenAI 兼容协议，
因此只需要一个 ChatOpenAI 实现 + 不同的 base_url；离线桩作为独立分支。
"""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError
from app.llm.stub import StubChatModel


def build_chat_model(
    task: str,
    provider: str | None = None,
    *,
    settings: Settings | None = None,
    stub_context: dict[str, Any] | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    """构建指定任务的聊天模型。

    Args:
        task: 任务标识，离线桩依据它生成对应结构的内容，真实模型忽略该参数。
        provider: 提供方名称，缺省使用配置中的 default_provider。
        settings: 配置对象，便于测试注入。
        stub_context: 离线桩的内容生成上下文。
        temperature: 覆盖默认温度。
    """

    resolved = settings or get_settings()
    config = resolved.llm.provider_config(provider)

    if config["provider"] == "stub":
        return StubChatModel(task=task, stub_context=stub_context or {})

    if not resolved.llm.is_ready(config["provider"]):
        raise ConfigurationError(
            f"大模型提供方 {config['provider']} 缺少必要配置（密钥或地址），请检查 .env"
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"] or None,
        temperature=resolved.llm.temperature if temperature is None else temperature,
        max_tokens=resolved.llm.max_tokens,
        timeout=resolved.llm.timeout_seconds,
        max_retries=resolved.llm.max_retries,
    )

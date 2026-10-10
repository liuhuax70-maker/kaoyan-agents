"""按配置构建聊天模型，并提供带离线兜底的结构化调用。

所有提供方（DeepSeek / Ollama / OpenAI）都走 OpenAI 兼容协议，
因此只需要一个 ChatOpenAI 实现 + 不同的 base_url；离线桩作为独立分支。
"""

from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.llm.structured import invoke_structured
from app.llm.stub import StubChatModel

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


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


async def invoke_agent_task(
    task: str,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    *,
    provider: str | None = None,
    stub_context: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> SchemaT:
    """调用模型并解析结构化结果，失败时自动回退离线桩。

    这是工作流节点与定时任务共用的调用入口：远程模型任何异常都不应让整条链路失败，
    而离线桩返回的是与真实模型同构的 JSON，因此上层无需区分两种情况。
    """

    context = stub_context or {}

    try:
        model = build_chat_model(task, provider, settings=settings, stub_context=context)
        return await invoke_structured(model, messages, schema)
    except Exception as exc:  # noqa: BLE001 - 远程模型任何异常都应触发兜底
        logger.warning("任务 %s 模型调用失败，回退离线桩：%s", task, exc)

    fallback = StubChatModel(task=task, stub_context=context)
    return await invoke_structured(fallback, messages, schema)

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
from app.llm.structured import CallStats, invoke_structured
from app.llm.stub import StubChatModel
from app.observability import get_observability

logger = get_logger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

PROMPT_PREVIEW_LIMIT = 600


def _prompt_preview(messages: list[BaseMessage]) -> str:
    """取最后一条消息作为输入预览，避免把整份提示词推给追踪服务。"""

    if not messages:
        return ""
    content = messages[-1].content
    text = content if isinstance(content, str) else str(content)
    return text[:PROMPT_PREVIEW_LIMIT]


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

    这是工作流节点、CrewAI 适配器与定时任务共用的调用入口：
    远程模型任何异常都不应让整条链路失败，而离线桩返回的是与真实模型同构的 JSON，
    因此上层无需区分两种情况。这里同时也是模型调用埋点的唯一位置。
    """

    context = stub_context or {}
    resolved = settings or get_settings()
    config = resolved.llm.provider_config(provider)
    observability = get_observability()
    stats = CallStats()

    with observability.generation(
        task,
        model=str(config["model"]),
        input=_prompt_preview(messages),
        metadata={"provider": config["provider"], "stub": config["provider"] == "stub"},
    ) as generation:
        try:
            model = build_chat_model(task, provider, settings=resolved, stub_context=context)
            result = await invoke_structured(model, messages, schema, stats=stats)
        except Exception as exc:  # noqa: BLE001 - 远程模型任何异常都应触发兜底
            logger.warning("任务 %s 模型调用失败，回退离线桩：%s", task, exc)
            generation.record(level="WARNING")
            fallback = StubChatModel(task=task, stub_context=context)
            result = await invoke_structured(fallback, messages, schema, stats=stats)

        generation.record(output=result.model_dump(mode="json"), usage=stats.usage)
        return result

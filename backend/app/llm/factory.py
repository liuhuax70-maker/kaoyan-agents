"""按配置构建聊天模型，并提供带埋点的结构化调用。

所有提供方（DeepSeek / Ollama / OpenAI）都走 OpenAI 兼容协议，
因此只需要一个 ``ChatOpenAI`` 实现 + 不同的 ``base_url``。

这里刻意不设任何降级分支：模型调用失败即向上抛出。
静默回退会让「模型没配好」表现为「回答质量差」，问题被掩盖在业务层之下。
"""

from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.llm.structured import CallStats, invoke_structured
from app.llm.tasks import AgentTask, output_model_for
from app.observability import get_observability
from app.schemas import SubagentReply

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


# 知识点：模型适配层 —— 三个提供方共用一套 OpenAI 兼容协议，差异只在 base_url 与
#   model 名，因此适配成本集中在配置而非代码（第2章 LangChain核心组件·模型）
def build_chat_model(
    task: str,
    provider: str | None = None,
    *,
    settings: Settings | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    """构建指定任务的聊天模型。

    Args:
        task: 任务标识，仅用于日志与埋点定位，不影响模型行为。
        provider: 提供方名称，缺省使用配置中的 ``default_provider``。
        settings: 配置对象，便于测试注入。
        temperature: 覆盖默认温度。
    """

    resolved = settings or get_settings()
    config = resolved.llm.provider_config(provider)

    if not resolved.llm.is_ready(config["provider"]):
        raise ConfigurationError(
            f"任务 {task} 使用的大模型提供方 {config['provider']} 缺少必要配置"
            "（密钥或地址），请检查 .env"
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


# 知识点：结构化输出 —— 用 Pydantic schema 约束模型输出，解析失败时把错误回灌给
#   模型重出，而不是让一次格式抖动打断整条链路（第2章 LangChain核心组件·结构化输出）
async def invoke_agent_task(
    task: str,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    *,
    provider: str | None = None,
    settings: Settings | None = None,
) -> SchemaT:
    """调用模型并把输出解析为结构化对象。

    这是工作流节点与定时任务共用的调用入口，也是模型调用埋点的唯一位置。
    调用或解析失败一律抛出，由调用方决定如何呈现错误——不做静默降级，
    否则「模型没配好」会表现为「回答质量差」，问题被掩盖在业务层之下。
    """

    resolved = settings or get_settings()
    config = resolved.llm.provider_config(provider)
    observability = get_observability()
    stats = CallStats()

    with observability.generation(
        task,
        model=str(config["model"]),
        input=_prompt_preview(messages),
        metadata={"provider": config["provider"]},
    ) as generation:
        model = build_chat_model(task, provider, settings=resolved)
        result = await invoke_structured(model, messages, schema, stats=stats)
        generation.record(output=result.model_dump(mode="json"), usage=stats.usage)
        return result


# 知识点：双轨产出 —— 同一次结构化调用里同时要回「面向用户的正文」与
#   「驱动落库的数据」，两者一次成型，取代「先结构化、再发一次请求总结」的两段式
#   （第2章 LangChain核心组件·结构化输出）
async def invoke_subagent_task(
    task: AgentTask,
    messages: list[BaseMessage],
    schema: type[SchemaT],
    *,
    provider: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, SchemaT]:
    """调用子智能体任务，返回 ``(面向用户的正文, 结构化产物)``。

    调用方只声明业务 Schema，信封由 :func:`output_model_for` 按任务自动套上，
    因此子智能体实现里看不到任何信封相关的代码。
    """

    envelope = await invoke_agent_task(
        task.value,
        messages,
        output_model_for(task),
        provider=provider,
        settings=settings,
    )
    reply: SubagentReply[SchemaT] = envelope  # type: ignore[assignment]
    return reply.narrative.strip(), reply.data
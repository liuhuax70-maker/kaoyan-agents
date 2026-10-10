"""把项目内的聊天模型适配成 CrewAI 可用的 LLM。"""

from typing import Any

from crewai.llms.base_llm import BaseLLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from app.llm import build_chat_model, extract_usage
from app.observability import get_observability

MESSAGE_TYPES: dict[str, type[BaseMessage]] = {
    "system": SystemMessage,
    "user": HumanMessage,
    "assistant": AIMessage,
}

CONTEXT_WINDOW_SIZE = 8192


def as_text(value: Any) -> str:
    """把多模态内容压平为纯文本。"""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                parts.append("" if text is None else str(text))
            else:
                parts.append(str(item))
        return "".join(parts)
    return "" if value is None else str(value)


def to_langchain_messages(payload: str | list[Any]) -> list[BaseMessage]:
    """把 CrewAI 的消息结构转换为 LangChain 消息。"""

    if isinstance(payload, str):
        return [HumanMessage(content=payload)]

    messages: list[BaseMessage] = []
    for item in payload:
        if not isinstance(item, dict):
            messages.append(HumanMessage(content=as_text(item)))
            continue
        role = str(item.get("role", "user"))
        factory = MESSAGE_TYPES.get(role, HumanMessage)
        messages.append(factory(content=as_text(item.get("content", ""))))
    return messages


class KaoyanCrewLLM(BaseLLM):
    """CrewAI 自定义 LLM。

    CrewAI 只要求 LLM 实现 ``call()``，因此这里直接复用项目统一的模型工厂：
    真实模型与离线桩走同一条路径，CrewAI 协作流程也就能够在无密钥环境下被真实执行。
    ``model`` 字段被复用为任务标识，离线桩据此生成对应结构的内容。
    """

    llm_type: str = "kaoyan-crew"

    provider_name: str | None = None
    stub_context: dict[str, Any] = Field(default_factory=dict)

    def call(
        self,
        messages: str | list[Any],
        tools: list[Any] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
        **kwargs: Any,
    ) -> str:
        """CrewAI 同步调用入口。"""

        model = build_chat_model(
            self.model, self.provider_name, stub_context=self.stub_context
        )
        observability = get_observability()

        with observability.generation(
            f"crew.{self.model}",
            model=self.model,
            input=as_text(messages),
            metadata={"provider": self.provider_name or "default", "framework": "crewai"},
        ) as generation:
            response = model.invoke(to_langchain_messages(messages))
            text = as_text(response.content)
            generation.record(output=text, usage=extract_usage(response))
            return text

    @property
    def stop_sequences(self) -> list[str]:
        """不支持停止词，交由上层按结构解析。"""

        return []

    def supports_stop_words(self) -> bool:
        """声明不支持停止词。"""

        return False

    def get_context_window_size(self) -> int:
        """返回上下文窗口大小，供 CrewAI 裁剪提示词。"""

        return CONTEXT_WINDOW_SIZE

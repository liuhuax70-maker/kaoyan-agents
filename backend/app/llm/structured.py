"""结构化输出解析与指标提取。"""

import json
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from app.core.errors import StructuredOutputError
from app.core.logging import get_logger

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(slots=True)
class CallStats:
    """一次结构化调用的用量统计，用于可观测性上报。"""

    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def usage(self) -> tuple[int, int]:
        """返回 (输入 token, 输出 token)。"""

        return self.input_tokens, self.output_tokens

FENCED_JSON = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象。

    依次尝试三种形态：纯 JSON、Markdown 代码块内的 JSON、首尾大括号之间的片段。
    真实模型经常会在 JSON 前后附加解释文字，这里做容错处理。
    """

    if not text or not text.strip():
        raise StructuredOutputError("模型返回内容为空")

    candidates: list[str] = []
    fenced = FENCED_JSON.search(text)
    if fenced:
        candidates.append(fenced.group("body").strip())

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    candidates.append(text.strip())

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload

    raise StructuredOutputError(f"模型输出中未找到合法 JSON 对象：{text[:160]}")


def extract_usage(message: BaseMessage) -> tuple[int, int]:
    """从模型响应中提取 token 用量，返回 (输入, 输出)。"""

    usage = getattr(message, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


def message_text(message: BaseMessage) -> str:
    """把模型消息的内容压平成纯文本。

    不同提供方返回的 ``content`` 可能是字符串、也可能是分块列表，
    因此读取模型正文一律走这里，避免各处各写一遍。
    """

    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


async def invoke_structured(
    model: BaseChatModel,
    messages: list[BaseMessage],
    schema: type[ModelT],
    *,
    retries: int = 1,
    stats: CallStats | None = None,
) -> ModelT:
    """调用模型并解析为结构化对象。

    解析失败时会把错误信息回灌给模型要求重出，避免一次格式抖动导致整条链路失败。
    传入 ``stats`` 时会累计尝试次数与 token 用量。
    """

    conversation = list(messages)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        response = await model.ainvoke(conversation)

        if stats is not None:
            input_tokens, output_tokens = extract_usage(response)
            stats.attempts += 1
            stats.input_tokens += input_tokens
            stats.output_tokens += output_tokens

        try:
            payload = extract_json_object(message_text(response))
            return schema.model_validate(payload)
        except (StructuredOutputError, ValidationError) as exc:
            last_error = exc
            logger.warning("结构化输出解析失败（第 %d 次尝试）：%s", attempt + 1, exc)
            if attempt == retries:
                break
            conversation = [
                *conversation,
                HumanMessage(
                    content=(
                        "上一次输出无法解析为目标结构，错误如下：\n"
                        f"{exc}\n"
                        "请直接重新输出一个合法 JSON 对象，不要包含解释文字或 Markdown 标记。"
                    )
                ),
            ]

    raise StructuredOutputError(f"结构化输出解析失败：{last_error}")

"""离线桩模型：把确定性内容包装成 LangChain 聊天模型。"""

import json
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.llm.offline import build_offline_payload


class StubChatModel(BaseChatModel):
    """确定性离线模型。

    输出与真实模型完全同构的 JSON 文本，因此上层的解析、校验与落库逻辑一致，
    切换 provider 时业务代码无需改动。这样在没有密钥的环境下也能跑通全流程与测试。
    """

    task: str = "generic"
    stub_context: dict[str, Any] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "kaoyan-stub"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = build_offline_payload(self.task, self.stub_context)
        message = AIMessage(
            content=json.dumps(payload, ensure_ascii=False),
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

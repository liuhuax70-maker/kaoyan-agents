"""模型适配层测试：JSON 容错解析、离线桩、供应商选择与重试。"""

from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.core.config import Settings
from app.core.errors import ConfigurationError, StructuredOutputError
from app.llm import (
    AgentTask,
    StubChatModel,
    build_chat_model,
    extract_json_object,
    invoke_structured,
    schema_for,
)
from app.schemas import PlanDraft


class SequencedChatModel(BaseChatModel):
    """测试用模型：按顺序返回预设内容。"""

    replies: list[str] = []
    received: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "sequenced-test"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        index = min(len(self.received), len(self.replies) - 1)
        content = self.replies[index]
        self.received.append(content)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def test_extract_json_accepts_plain_object() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_accepts_fenced_block() -> None:
    text = '好的，结果如下：\n```json\n{"a": {"b": 2}}\n```\n以上。'
    assert extract_json_object(text) == {"a": {"b": 2}}


def test_extract_json_accepts_surrounding_text() -> None:
    assert extract_json_object('结果：{"a": [1, 2]} 完毕') == {"a": [1, 2]}


def test_extract_json_rejects_non_json() -> None:
    with pytest.raises(StructuredOutputError):
        extract_json_object("这里没有任何 JSON 内容")


@pytest.mark.parametrize("task", list(AgentTask))
async def test_stub_model_outputs_schema_valid_payload(task: AgentTask) -> None:
    """离线桩必须为每个任务产出能通过校验的结构化内容。"""

    model = StubChatModel(task=task.value)
    result = await invoke_structured(model, [HumanMessage(content="测试")], schema_for(task))
    assert isinstance(result, schema_for(task))


async def test_stub_plan_draft_reflects_stub_context() -> None:
    """离线桩应依据上下文生成内容，而不是返回固定死数据。"""

    model = StubChatModel(
        task=AgentTask.PLAN_DRAFT.value,
        stub_context={
            "subjects": ["数学", "专业课"],
            "weak_subjects": ["数学"],
            "days_left": 45,
            "daily_hours": 5,
            "attention_span": 60,
        },
    )
    draft = await invoke_structured(model, [HumanMessage(content="制定计划")], PlanDraft)

    assert draft.horizon_days == 45
    assert len(draft.stages) == 3
    subjects = {task.subject for stage in draft.stages for task in stage.tasks}
    assert subjects == {"数学", "专业课", "综合"}
    weak_tasks = [task for stage in draft.stages for task in stage.tasks if task.subject == "数学"]
    assert all(task.priority == "high" for task in weak_tasks)


async def test_invoke_structured_retries_after_invalid_output() -> None:
    """首次输出不合法时应重试，并把错误回灌给模型。"""

    model = SequencedChatModel(
        replies=[
            "这不是 JSON",
            '{"title": "冲刺计划", "goal": "提升数学成绩", "horizon_days": 30}',
        ]
    )

    result = await invoke_structured(
        model, [HumanMessage(content="制定计划")], PlanDraft, retries=1
    )

    assert result.title == "冲刺计划"
    assert len(model.received) == 2


async def test_invoke_structured_raises_after_retries_exhausted() -> None:
    model = SequencedChatModel(replies=["仍然不是 JSON"])

    with pytest.raises(StructuredOutputError):
        await invoke_structured(model, [HumanMessage(content="制定计划")], PlanDraft, retries=1)


def test_factory_returns_stub_model() -> None:
    settings = Settings(llm={"default_provider": "stub"})
    model = build_chat_model(AgentTask.PLAN_DRAFT.value, settings=settings)
    assert isinstance(model, StubChatModel)
    assert model.task == AgentTask.PLAN_DRAFT.value


def test_factory_builds_openai_compatible_model() -> None:
    settings = Settings(
        llm={"default_provider": "deepseek", "deepseek_api_key": "sk-test-value"}
    )
    model = build_chat_model(AgentTask.PLAN_DRAFT.value, settings=settings)
    assert getattr(model, "model_name", "") == "deepseek-chat"


def test_factory_requires_credentials_for_remote_provider() -> None:
    settings = Settings(llm={"default_provider": "deepseek", "deepseek_api_key": ""})
    with pytest.raises(ConfigurationError):
        build_chat_model(AgentTask.PLAN_DRAFT.value, settings=settings)

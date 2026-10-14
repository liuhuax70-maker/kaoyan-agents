"""模型适配层测试：JSON 容错解析、提供方选择、配置校验与结构化重试。"""

from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ConfigurationError, StructuredOutputError
from app.llm import (
    AgentTask,
    build_chat_model,
    extract_json_object,
    invoke_structured,
    output_model_for,
)
from app.prompts import (
    build_messages,
    render_learner,
    render_official_links,
    render_plan_draft,
    render_reminder,
    render_retrieved,
    render_subjects,
)
from app.schemas import (
    LearnerSnapshot,
    PlanDraft,
    ReminderSnapshot,
    SubjectSnapshot,
)
from app.search.official_links import official_entry_links
from tests.fakes import FakeChatModel, build_plan_draft, parse_prompt_context


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


def _learner() -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        days_left=120,
        daily_hours=5,
        attention_span=60,
        subjects=[SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True)],
    )


def _variables() -> dict[str, str]:
    """覆盖全部模板所需的变量，供不同任务的提示词组装复用。"""

    learner = _learner()
    draft = PlanDraft.model_validate(
        build_plan_draft(parse_prompt_context([HumanMessage(content="制定复习计划")]))
    )
    reminder = ReminderSnapshot(
        reminder_type="daily",
        due_tasks=["高数第一章精读"],
        overdue_tasks=["英语真题阅读两篇"],
        completion_rate=0.3,
    )
    return {
        "learner_context": render_learner(learner),
        "subject_context": render_subjects(learner),
        "plan_context": render_plan_draft(draft),
        "reminder_context": render_reminder(reminder),
        "retrieved_context": render_retrieved([]),
        "official_links": render_official_links(
            official_entry_links("某某大学", major="计算机技术")
        ),
        "tracked_context": "\n".join(f"- {name}｜候选" for name in ("某某大学", "某某理工大学")),
        "request": "帮我制定从现在到考试的复习计划",
        "scope": "把数学基础阶段拆成两周的任务",
    }


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
async def test_every_task_output_validates_against_its_schema(task: AgentTask) -> None:
    """每个任务的提示词、假产出与 Schema 必须三者对齐。

    这是替代原「离线桩」用例的契约测试：桩没了，
    但「任务 → 模板 → Schema」这条链路的自洽性仍必须被守住。

    提示词与解析统一取 ``output_model_for``：子智能体任务拿到的是一层双轨信封，
    图节点任务拿到的是业务 Schema 本身——两者永远同步，正是这个用例在守的契约。
    """

    messages = build_messages(task, **_variables())
    model = output_model_for(task)
    result = await invoke_structured(FakeChatModel(task=task.value), messages, model)

    assert isinstance(result, model)


async def test_fake_plan_draft_reflects_prompt_context() -> None:
    """假模型应依据提示词里的上下文生成内容，而不是返回固定死数据。"""

    messages = build_messages(AgentTask.PLAN_DRAFT, **_variables())
    envelope = await invoke_structured(
        FakeChatModel(task=AgentTask.PLAN_DRAFT.value),
        messages,
        output_model_for(AgentTask.PLAN_DRAFT),
    )
    draft = envelope.data

    assert draft.horizon_days == 120
    weak_tasks = [task for stage in draft.stages for task in stage.tasks if task.subject == "数学"]
    assert weak_tasks
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


def test_offline_provider_is_no_longer_accepted() -> None:
    """离线提供方已从配置中移除：配置非法就该启动失败，而不是静默降级。"""

    with pytest.raises(ValidationError):
        Settings(llm={"default_provider": "stub"})


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
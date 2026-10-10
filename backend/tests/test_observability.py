"""LangFuse 可观测性测试。

用自建客户端覆盖「已启用」分支：断言真正调用了追踪接口，
而不只是验证「没配密钥时是空操作」。
"""

from typing import Any

from app.core.config import Settings
from app.observability import Observability
from app.schemas import LearnerSnapshot, SubjectSnapshot
from app.workflows import run_workflow

TRACE_ID = "trace-abc123"
TRACE_URL = f"https://langfuse.local/trace/{TRACE_ID}"


class FakeSpan:
    """记录进入与退出状态的假 span。"""

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name = name
        self.kwargs = kwargs
        self.entered = False

    def __enter__(self) -> "FakeSpan":
        self.entered = True
        return self

    def __exit__(self, *args: object) -> bool:
        self.entered = False
        return False


class FakeLangfuse:
    """记录调用参数的假 LangFuse 客户端。"""

    def __init__(self, *, trace_id: str = TRACE_ID, url: str = TRACE_URL) -> None:
        self.spans: list[FakeSpan] = []
        self.generations: list[FakeSpan] = []
        self.trace_updates: list[dict[str, Any]] = []
        self.generation_updates: list[dict[str, Any]] = []
        self.flushed = 0
        self._trace_id = trace_id
        self._url = url

    def start_as_current_span(self, **kwargs: Any) -> FakeSpan:
        span = FakeSpan(kwargs.pop("name"), **kwargs)
        self.spans.append(span)
        return span

    def start_as_current_generation(self, **kwargs: Any) -> FakeSpan:
        span = FakeSpan(kwargs.pop("name"), **kwargs)
        self.generations.append(span)
        return span

    def update_current_trace(self, **kwargs: Any) -> None:
        self.trace_updates.append(kwargs)

    def update_current_generation(self, **kwargs: Any) -> None:
        self.generation_updates.append(kwargs)

    def get_current_trace_id(self) -> str:
        return self._trace_id

    def get_trace_url(self, *, trace_id: str | None = None) -> str:
        return self._url

    def flush(self) -> None:
        self.flushed += 1


class BrokenLangfuse(FakeLangfuse):
    """所有接口都抛异常的客户端，用于验证埋点不会影响业务。"""

    def start_as_current_span(self, **kwargs: Any) -> FakeSpan:
        raise RuntimeError("span 创建失败")

    def update_current_trace(self, **kwargs: Any) -> None:
        raise RuntimeError("trace 更新失败")

    def start_as_current_generation(self, **kwargs: Any) -> FakeSpan:
        raise RuntimeError("generation 创建失败")

    def update_current_generation(self, **kwargs: Any) -> None:
        raise RuntimeError("generation 更新失败")


def _learner() -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        target_title="复旦计算机",
        days_left=120,
        daily_hours=5,
        attention_span=60,
        subjects=[SubjectSnapshot(name="数学", is_weak=True)],
    )


def _settings(**observability: Any) -> Settings:
    return Settings(observability=observability)


def test_disabled_when_credentials_missing() -> None:
    observability = Observability(_settings(langfuse_enabled=False))

    assert observability.enabled is False
    status = observability.status()
    assert status["configured"] is False
    assert status["enabled"] is False

    # 空操作路径不应抛错
    with observability.trace("noop") as handle:
        assert handle.active is False
        handle.update(output="ignored")
    with observability.generation("noop") as generation:
        generation.record(output="ignored", usage=(1, 2))
    observability.flush()


def test_partial_credentials_are_not_enough() -> None:
    """只填了 enabled 但没有密钥时不应启用。"""

    observability = Observability(_settings(langfuse_enabled=True, langfuse_public_key="pk"))
    assert observability.enabled is False


def test_trace_records_ids_and_updates() -> None:
    client = FakeLangfuse()
    observability = Observability(_settings(), client=client)
    assert observability.enabled is True

    with observability.trace(
        "multi-agent.workflow",
        user_id="7",
        session_id="42",
        input="帮我制定复习计划",
        tags=["workflow"],
        metadata={"days_left": 120},
    ) as handle:
        handle.update(output="已生成计划", metadata={"intent": "plan"})

    assert handle.trace_id == TRACE_ID
    assert handle.url == TRACE_URL
    assert client.spans[0].name == "multi-agent.workflow"
    assert client.spans[0].kwargs["input"] == "帮我制定复习计划"

    first_update = client.trace_updates[0]
    assert first_update["user_id"] == "7"
    assert first_update["session_id"] == "42"
    assert first_update["tags"] == ["workflow"]

    last_update = client.trace_updates[-1]
    assert last_update["output"] == "已生成计划"
    assert last_update["metadata"] == {"intent": "plan"}


def test_generation_records_output_usage_and_latency() -> None:
    client = FakeLangfuse()
    observability = Observability(_settings(), client=client)

    with observability.generation(
        "plan_draft", model="deepseek-chat", input="提示词片段", metadata={"provider": "deepseek"}
    ) as generation:
        generation.record(output={"title": "备考计划"}, usage=(128, 512))

    assert generation.latency_ms >= 0
    assert client.generations[0].name == "plan_draft"
    assert client.generations[0].kwargs["model"] == "deepseek-chat"

    update = client.generation_updates[0]
    assert update["output"] == {"title": "备考计划"}
    assert update["usage_details"] == {"input": 128, "output": 512}
    assert "latency_ms" in update["metadata"]


def test_flush_delegates_to_client() -> None:
    client = FakeLangfuse()
    Observability(_settings(), client=client).flush()
    assert client.flushed == 1


def test_client_failures_never_break_business_logic() -> None:
    observability = Observability(_settings(), client=BrokenLangfuse())

    with observability.trace("broken") as handle:
        assert handle.active is False
        handle.update(output="仍然可以继续")

    with observability.generation("broken") as generation:
        generation.record(output="ok", usage=(1, 1))

    observability.flush()


def test_long_payload_is_truncated() -> None:
    client = FakeLangfuse()
    observability = Observability(_settings(), client=client)

    with observability.trace("long", input="x" * 5000) as handle:
        handle.update(output="y" * 5000)

    assert len(client.spans[0].kwargs["input"]) < 2100
    assert len(client.trace_updates[-1]["output"]) < 2100


async def test_workflow_returns_no_trace_when_disabled() -> None:
    """默认（未配置 LangFuse）时工作流照常返回，只是没有 trace。"""

    result = await run_workflow("帮我制定复习计划", _learner(), enable_review=False)

    assert result.plan_draft is not None
    assert result.trace_id is None
    assert result.trace_url is None


async def test_workflow_and_model_calls_are_traced(monkeypatch) -> None:
    """启用后：一次工作流产生一条 trace，每次模型调用产生一个 generation。"""

    client = FakeLangfuse()
    observability = Observability(_settings(), client=client)
    monkeypatch.setattr("app.workflows.runner.get_observability", lambda: observability)
    monkeypatch.setattr("app.llm.factory.get_observability", lambda: observability)

    result = await run_workflow(
        "帮我制定复习计划",
        _learner(),
        enable_review=False,
        user_id=7,
        session_id="42",
    )

    assert result.trace_id == TRACE_ID
    assert result.trace_url == TRACE_URL

    assert len(client.spans) == 1
    assert client.spans[0].name == "multi-agent.workflow"

    # 意图识别 + 规划 + 拆解，至少三次模型调用被记录
    assert len(client.generations) >= 3
    traced_tasks = {span.name for span in client.generations}
    assert "intent_routing" in traced_tasks
    assert "plan_draft" in traced_tasks

    assert client.trace_updates[0]["session_id"] == "42"
    assert client.trace_updates[-1]["metadata"]["intent"] == "plan"
    assert all(span.entered is False for span in client.spans)


async def test_stream_workflow_is_traced(monkeypatch) -> None:
    from app.workflows import stream_workflow

    client = FakeLangfuse()
    observability = Observability(_settings(), client=client)
    monkeypatch.setattr("app.workflows.runner.get_observability", lambda: observability)
    monkeypatch.setattr("app.llm.factory.get_observability", lambda: observability)

    chunks = [
        chunk
        async for chunk in stream_workflow(
            "帮我制定复习计划", _learner(), enable_review=False, user_id=1
        )
    ]

    assert chunks[-1]["type"] == "result"
    assert chunks[-1]["result"]["trace_id"] == TRACE_ID
    assert client.spans[0].name == "multi-agent.workflow.stream"

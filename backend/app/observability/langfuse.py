"""LangFuse 可观测性门面。

设计要点：
1. 未配置密钥时全部方法都是空操作，因此调用点可以无条件埋点，
   不需要在每个使用处判断开关；
2. 任何埋点异常都只记 debug 日志，绝不影响主流程；
3. 同时支持传入自建客户端，便于测试覆盖「已启用」分支。
"""

import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any

from app.core.config import ObservabilitySection, Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PAYLOAD_LIMIT = 2000


def _truncate(value: Any, limit: int = PAYLOAD_LIMIT) -> Any:
    """裁剪过长的载荷，避免把整份提示词推给追踪服务。"""

    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


@dataclass(slots=True)
class TraceHandle:
    """一次追踪的句柄。"""

    trace_id: str | None = None
    url: str | None = None
    _client: Any = None

    @property
    def active(self) -> bool:
        """是否处于真实追踪中。"""

        return self._client is not None

    def update(self, **kwargs: Any) -> None:
        """更新 trace 级信息（用户、会话、输入输出、标签等）。"""

        if self._client is None:
            return
        payload = {key: _truncate(value) for key, value in kwargs.items()}
        try:
            self._client.update_current_trace(**payload)
        except Exception as exc:  # noqa: BLE001 - 埋点失败不能影响业务
            logger.debug("更新 trace 失败：%s", exc)


@dataclass(slots=True)
class GenerationHandle:
    """一次模型调用的句柄。"""

    _client: Any = None
    latency_ms: int = 0
    _output: Any = None
    _usage: tuple[int, int] | None = None
    _level: str | None = None

    def record(
        self,
        *,
        output: Any = None,
        usage: tuple[int, int] | None = None,
        level: str | None = None,
    ) -> None:
        """记录输出与 token 用量，需在 with 块内调用。"""

        if output is not None:
            self._output = output
        if usage is not None:
            self._usage = usage
        if level is not None:
            self._level = level

    def finalize(self) -> None:
        """在 span 关闭前写入采集到的信息。"""

        if self._client is None:
            return

        payload: dict[str, Any] = {
            "metadata": {"latency_ms": self.latency_ms},
            "level": self._level or "DEFAULT",
        }
        if self._output is not None:
            payload["output"] = _truncate(self._output)
        if self._usage is not None:
            payload["usage_details"] = {
                "input": int(self._usage[0]),
                "output": int(self._usage[1]),
            }

        try:
            self._client.update_current_generation(**payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("记录 generation 失败：%s", exc)


class Observability:
    """可观测性门面。"""

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any = None,
    ) -> None:
        self._section: ObservabilitySection = (settings or get_settings()).observability
        self._client = client if client is not None else self._build_client()

    def _build_client(self) -> Any:
        section = self._section
        if not section.langfuse_active:
            return None

        try:
            from langfuse import Langfuse

            client = Langfuse(
                public_key=section.langfuse_public_key,
                secret_key=section.langfuse_secret_key,
                host=section.langfuse_host,
            )
        except Exception as exc:  # noqa: BLE001 - 追踪不可用不应阻断启动
            logger.warning("LangFuse 初始化失败，追踪将不可用：%s", exc)
            return None

        logger.info("LangFuse 追踪已启用：%s", section.langfuse_host)
        return client

    @property
    def enabled(self) -> bool:
        """追踪是否真实可用。"""

        return self._client is not None

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        input: Any = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceHandle]:
        """开启一次追踪（工作流、定时任务等）。"""

        if self._client is None:
            yield TraceHandle()
            return

        with ExitStack() as stack:
            handle = TraceHandle()
            try:
                stack.enter_context(
                    self._client.start_as_current_span(
                        name=name,
                        input=_truncate(input),
                        metadata=metadata or {},
                    )
                )
                self._client.update_current_trace(
                    user_id=user_id,
                    session_id=session_id,
                    tags=tags or [],
                )
                handle = TraceHandle(
                    trace_id=self._client.get_current_trace_id(),
                    url=self._client.get_trace_url(),
                    _client=self._client,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("开启追踪失败，本次不追踪：%s", exc)
                handle = TraceHandle()

            yield handle

    @contextmanager
    def generation(
        self,
        name: str,
        *,
        model: str | None = None,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[GenerationHandle]:
        """包裹一次模型调用，记录模型、耗时与 token 用量。"""

        if self._client is None:
            yield GenerationHandle()
            return

        started = time.perf_counter()
        with ExitStack() as stack:
            handle = GenerationHandle()
            try:
                stack.enter_context(
                    self._client.start_as_current_generation(
                        name=name,
                        model=model,
                        input=_truncate(input),
                        metadata=metadata or {},
                    )
                )
                handle = GenerationHandle(_client=self._client)
            except Exception as exc:  # noqa: BLE001
                logger.debug("创建 generation 失败：%s", exc)

            yield handle

            handle.latency_ms = int((time.perf_counter() - started) * 1000)
            handle.finalize()

    def flush(self) -> None:
        """等待追踪数据上报完成。"""

        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.debug("刷新追踪数据失败：%s", exc)

    def status(self) -> dict[str, Any]:
        """返回追踪可用状态，供健康检查与总览接口使用。"""

        return {
            "configured": self._section.langfuse_active,
            "enabled": self.enabled,
            "host": self._section.langfuse_host,
        }


_observability: Observability | None = None


def get_observability() -> Observability:
    """返回进程内复用的可观测性门面。"""

    global _observability
    if _observability is None:
        _observability = Observability()
    return _observability


def reset_observability() -> None:
    """清空单例，切换配置或退出前调用。"""

    global _observability
    if _observability is not None:
        _observability.flush()
    _observability = None

# 知识点：Checkpointer —— 图的状态本可以只活在内存里，挂上检查点后每次状态更新都会按
#   thread_id 归档；正是这份归档让「暂停等人工确认、再从原处恢复」成为可能
#   （第5章 LangGraph·人工确认）
"""工作流检查点存储。

``interrupt`` 要求图能把暂停点的状态存下来、事后从原处继续，因此必须挂 checkpointer：

- 开发与测试用 SQLite（``langgraph-checkpoint-sqlite``）；
- 生产用 PostgreSQL（``langgraph-checkpoint-postgres``）。

两种后端在这里收敛成一个进程级异步单例。构建失败直接抛出：检查点是「计划落库前
人工确认」的前置条件，静默退化成「无检查点直跑」等于悄悄关掉这项能力。

建表由 ``setup()`` 完成（两种实现都提供），因此**不需要 alembic 迁移**：
检查点表由库自己拥有并随库版本演进，手写一份迁移只会与 ``setup()`` 的 DDL 漂移。
"""

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_saver: BaseCheckpointSaver | None = None
"""进程级检查点单例，由 ``get_checkpointer()`` 惰性构建。"""

_lifecycle: AsyncExitStack | None = None
"""持有长生命周期资源（SQLite 连接 / PostgreSQL 连接池）。"""

_lock = asyncio.Lock()


def _psycopg_url(url: str) -> str:
    """把 SQLAlchemy 连接串转成 psycopg 能直接消费的形式。

    应用的连接串带驱动后缀（``postgresql+asyncpg://``），psycopg 不认这个写法。
    只改 postgres 系的前缀：把别的连接串也改写成 postgresql 只会把配置错误
    伪装成一个连不上的数据库。
    """

    scheme, separator, rest = url.partition("://")
    if not separator or not scheme.startswith("postgres"):
        return url
    return f"postgresql://{rest}"


async def _build() -> BaseCheckpointSaver:
    """按数据库类型构建检查点实现并建表。"""

    settings = get_settings()
    global _lifecycle
    _lifecycle = _lifecycle or AsyncExitStack()

    saver: BaseCheckpointSaver
    if settings.database.is_sqlite:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = Path(settings.workflow.checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await _lifecycle.enter_async_context(aiosqlite.connect(path))
        saver = AsyncSqliteSaver(connection)
    else:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = await _lifecycle.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_psycopg_url(settings.database.url))
        )

    await saver.setup()
    logger.info("工作流检查点已就绪：%s", type(saver).__name__)
    return saver


async def get_checkpointer() -> BaseCheckpointSaver:
    """返回进程级检查点单例，首次调用时构建。"""

    global _saver
    if _saver is None:
        async with _lock:
            if _saver is None:
                _saver = await _build()
    return _saver


def set_checkpointer(saver: BaseCheckpointSaver | None, lifecycle: Any = None) -> None:
    """替换当前检查点实现。

    测试注入内存实现时用得到：内存实现随用例结束即失效，
    不需要临时文件，也不会让上一个用例的中断被下一个用例的恢复读到
    （会话 ID 会重复）。
    """

    global _saver, _lifecycle
    _saver = saver
    _lifecycle = lifecycle


async def reset_checkpointer() -> None:
    """关闭并清理已构建的检查点，释放其持有的连接。"""

    global _saver, _lifecycle
    stack, _lifecycle, _saver = _lifecycle, None, None
    if stack is not None:
        await stack.aclose()
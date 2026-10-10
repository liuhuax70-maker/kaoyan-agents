"""数据库引擎与会话管理。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import DatabaseSection, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def ensure_sqlite_directory(url: str) -> None:
    """为 SQLite 文件连接串预先创建父目录。

    迁移脚本与应用启动都会用到，因此抽成模块级函数复用。
    """

    if "///" not in url:
        return
    raw_path = url.split("///", 1)[-1]
    if not raw_path or raw_path.startswith(":memory:"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


class Database:
    """异步数据库连接管理，按需惰性创建引擎。"""

    def __init__(self, section: DatabaseSection | None = None) -> None:
        self.section = section or get_settings().database
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        """返回异步引擎，首次访问时创建。"""

        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """返回会话工厂。"""

        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._session_factory

    def _build_engine(self) -> AsyncEngine:
        """依据连接串构造引擎，SQLite 与 PostgreSQL 参数不同。"""

        url = self.section.url
        options: dict[str, Any] = {
            "echo": self.section.echo,
            "pool_pre_ping": self.section.pool_pre_ping,
        }
        if self.section.is_sqlite:
            ensure_sqlite_directory(url)
            options["connect_args"] = {"check_same_thread": False}
        else:
            options["pool_size"] = self.section.pool_size
            options["max_overflow"] = self.section.max_overflow

        logger.info("初始化数据库引擎：%s", self.section.safe_url)
        return create_async_engine(url, **options)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """提供事务性会话，异常时自动回滚。"""

        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        """探测数据库连通性。"""

        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉具体异常类型
            logger.warning("数据库连接不可用：%s", exc)
            return False
        return True

    async def dispose(self) -> None:
        """释放连接池。"""

        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None


db = Database()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供数据库会话。"""

    async with db.session() as session:
        yield session

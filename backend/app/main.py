"""FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.cache.redis import cache
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.session import db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """应用启动与关闭钩子。"""

    settings = get_settings()
    setup_logging(settings.app.log_level, settings.app.log_json)
    logger.info("启动 %s（env=%s）", settings.app.name, settings.app.env)

    if not await db.ping():
        logger.warning("数据库当前不可用，业务接口将返回错误")

    await cache.connect()
    try:
        yield
    finally:
        await cache.close()
        await db.dispose()
        logger.info("服务已关闭")


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""

    settings = get_settings()
    application = FastAPI(
        title="考研考证学习规划与督促系统",
        description="基于 LangGraph + CrewAI 的多智能体学习规划与督促服务",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.app.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.app.api_prefix)

    @application.get("/", tags=["system"], summary="服务信息")
    async def root() -> dict[str, str]:
        return {
            "name": settings.app.name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{settings.app.api_prefix}/health",
        }

    return application


app = create_app()

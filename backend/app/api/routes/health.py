"""健康检查与运行状态接口。"""

from typing import Any

from fastapi import APIRouter

from app.cache.redis import cache
from app.core.config import get_settings
from app.db.session import db

router = APIRouter(tags=["system"])


@router.get("/health", summary="健康检查")
async def health() -> dict[str, Any]:
    """返回各依赖组件的可用状态。"""

    settings = get_settings()
    database_ok = await db.ping()
    redis_ok = await cache.ping()

    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app.name,
        "env": settings.app.env,
        "components": {
            "database": {"ok": database_ok, "url": settings.database.safe_url},
            "redis": {"ok": redis_ok, "url": settings.redis.url},
            "vector": {
                "backend": settings.vector.backend,
                "collection": settings.vector.collection,
            },
            "llm": {
                "provider": settings.llm.default_provider,
                "ready": settings.llm.is_ready(),
            },
            "observability": {"langfuse": settings.observability.langfuse_active},
        },
    }

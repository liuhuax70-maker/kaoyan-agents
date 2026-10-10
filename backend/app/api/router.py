"""接口总路由，统一挂载各业务子路由。"""

from fastapi import APIRouter

from app.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router)

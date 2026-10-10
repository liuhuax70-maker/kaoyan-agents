"""接口总路由，统一挂载各业务子路由。"""

from fastapi import APIRouter

from app.api.routes import (
    chat,
    health,
    knowledge,
    plans,
    reminders,
    system,
    targets,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(users.router)
api_router.include_router(targets.router)
api_router.include_router(plans.router)
api_router.include_router(tasks.router)
api_router.include_router(chat.router)
api_router.include_router(reminders.router)
api_router.include_router(knowledge.router)

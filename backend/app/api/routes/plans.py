"""学习计划接口。"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import StudyPlan
from app.schemas.api import ChatRequest, ChatResponse, PlanGenerateRequest, PlanRead
from app.services.conversations import handle_chat

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("/generate", response_model=ChatResponse, summary="生成个性化学习计划")
async def generate_plan(payload: PlanGenerateRequest, session: SessionDep) -> ChatResponse:
    """触发多智能体工作流生成计划并落库。

    本质是一次面向规划意图的对话，因此复用同一套服务。
    若用户尚未创建备考目标，计划无法入库，``plan_id`` 会返回 null。
    """

    goal = payload.goal.strip() or "从现在到考试的完整复习计划"
    request = ChatRequest(
        user_id=payload.user_id,
        message=f"帮我制定学习计划：{goal}",
        provider=payload.provider,
        enable_review=payload.enable_review,
    )

    response = await handle_chat(session, request)
    if response is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return response


@router.get("", response_model=list[PlanRead], summary="按用户查询学习计划")
async def list_plans(user_id: int, session: SessionDep, limit: int = 20) -> list[StudyPlan]:
    """列出用户的学习计划，含阶段与任务。"""

    return list(
        await session.scalars(
            select(StudyPlan)
            .where(StudyPlan.user_id == user_id)
            .order_by(StudyPlan.id.desc())
            .limit(limit)
        )
    )


@router.get("/{plan_id}", response_model=PlanRead, summary="查询学习计划")
async def get_plan(plan_id: int, session: SessionDep) -> StudyPlan:
    """读取计划详情。"""

    plan = await session.scalar(select(StudyPlan).where(StudyPlan.id == plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail="学习计划不存在")
    return plan

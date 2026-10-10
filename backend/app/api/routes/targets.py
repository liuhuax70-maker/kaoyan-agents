"""备考目标与科目接口。"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.api.deps import SessionDep
from app.db.models import ExamTarget, Subject, User
from app.schemas.api import TargetCreate, TargetRead

router = APIRouter(prefix="/targets", tags=["targets"])


@router.post(
    "",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建备考目标",
)
async def create_target(payload: TargetCreate, session: SessionDep) -> ExamTarget:
    """创建备考目标并一并写入科目。"""

    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    if payload.make_primary:
        await session.execute(
            update(ExamTarget)
            .where(ExamTarget.user_id == payload.user_id)
            .values(is_primary=False)
        )

    target = ExamTarget(
        user_id=payload.user_id,
        exam_type=payload.exam_type,
        title=payload.title,
        target_school=payload.target_school,
        target_major=payload.target_major,
        exam_date=payload.exam_date,
        target_score=payload.target_score,
        description=payload.description,
        is_primary=payload.make_primary,
    )
    for index, item in enumerate(payload.subjects):
        target.subjects.append(Subject(**item.model_dump(), order_index=index))

    session.add(target)
    await session.flush()

    created = await session.scalar(select(ExamTarget).where(ExamTarget.id == target.id))
    if created is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="目标创建失败")
    return created


@router.get("", response_model=list[TargetRead], summary="按用户查询备考目标")
async def list_targets(user_id: int, session: SessionDep, limit: int = 20) -> list[ExamTarget]:
    """列出用户的备考目标。"""

    return list(
        await session.scalars(
            select(ExamTarget)
            .where(ExamTarget.user_id == user_id)
            .order_by(ExamTarget.is_primary.desc(), ExamTarget.id.desc())
            .limit(limit)
        )
    )


@router.get("/{target_id}", response_model=TargetRead, summary="查询备考目标")
async def get_target(target_id: int, session: SessionDep) -> ExamTarget:
    """读取目标详情与科目清单。"""

    target = await session.scalar(select(ExamTarget).where(ExamTarget.id == target_id))
    if target is None:
        raise HTTPException(status_code=404, detail="备考目标不存在")
    return target

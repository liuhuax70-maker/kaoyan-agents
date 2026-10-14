"""备考目标与科目接口。"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select, update

from app.api.deps import SessionDep
from app.db.models import ExamTarget, Subject, TrackedSchoolStatus, User
from app.schemas.api import TargetCreate, TargetRead, TrackedSchoolRead
from app.services.targets import (
    archive_school,
    decide_school,
    list_tracked_schools,
)

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


@router.get(
    "/{target_id}/schools",
    response_model=list[TrackedSchoolRead],
    summary="查询候选院校",
)
async def list_schools(
    target_id: int,
    session: SessionDep,
    status_filter: TrackedSchoolStatus | None = None,
) -> list:
    """列出该目标下正在跟踪的院校，默认包含已归档的。"""

    target = await session.get(ExamTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="备考目标不存在")
    return await list_tracked_schools(session, target_id=target_id, status=status_filter)


@router.post(
    "/{target_id}/schools/{school_id}/decide",
    response_model=TrackedSchoolRead,
    summary="选定某所院校",
)
async def decide(target_id: int, school_id: int, session: SessionDep) -> object:
    """用户拍板：把它标为已选定，并写回备考目标。

    这是**唯一**会改动 ``ExamTarget.target_school`` 的入口，
    因此「决定是用户做的」在数据链路上一目了然。
    """

    school = await decide_school(session, target_id=target_id, school_id=school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="候选院校不存在")
    return school


@router.post(
    "/{target_id}/schools/{school_id}/archive",
    response_model=TrackedSchoolRead,
    summary="放弃某所院校",
)
async def archive(target_id: int, school_id: int, session: SessionDep) -> object:
    """把一所院校移出考虑范围。"""

    school = await archive_school(session, target_id=target_id, school_id=school_id)
    if school is None:
        raise HTTPException(status_code=404, detail="候选院校不存在")
    return school

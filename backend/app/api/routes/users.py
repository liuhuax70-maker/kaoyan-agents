"""用户与学习档案接口。"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep
from app.db.models import LearnerProfile, User
from app.schemas.api import ProfileInput, UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def _load_user(session: SessionDep, user_id: int) -> User:
    """读取用户，不存在时抛出 404。"""

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="创建用户")
async def create_user(payload: UserCreate, session: SessionDep) -> User:
    """创建用户，可同时初始化学习档案。"""

    existing = await session.scalar(select(User).where(User.username == payload.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"用户名 {payload.username} 已存在")

    user = User(
        username=payload.username,
        nickname=payload.nickname,
        email=payload.email,
        timezone=payload.timezone,
    )
    if payload.profile is not None:
        user.profile = LearnerProfile(**payload.profile.model_dump())

    session.add(user)
    await session.flush()

    # 重新查询以获取数据库生成的 created_at 并加载档案
    created = await session.scalar(select(User).where(User.id == user.id))
    if created is None:  # pragma: no cover - 仅在并发删除时触发
        raise HTTPException(status_code=500, detail="用户创建失败")
    return created


@router.get("/{user_id}", response_model=UserRead, summary="查询用户")
async def get_user(user_id: int, session: SessionDep) -> User:
    """读取用户及其学习档案。"""

    return await _load_user(session, user_id)


@router.patch("/{user_id}", response_model=UserRead, summary="更新用户与档案")
async def update_user(user_id: int, payload: UserUpdate, session: SessionDep) -> User:
    """更新用户基本信息与学习档案。"""

    user = await _load_user(session, user_id)

    for field, value in payload.model_dump(exclude_unset=True, exclude={"profile"}).items():
        setattr(user, field, value)

    if payload.profile is not None:
        await _apply_profile(session, user, payload.profile)

    await session.flush()
    updated = await session.scalar(select(User).where(User.id == user.id))
    if updated is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="用户更新失败")
    return updated


async def _apply_profile(session: SessionDep, user: User, payload: ProfileInput) -> None:
    """写入或更新学习档案。"""

    values = payload.model_dump()
    profile = await session.scalar(
        select(LearnerProfile).where(LearnerProfile.user_id == user.id)
    )
    if profile is None:
        session.add(LearnerProfile(user_id=user.id, **values))
    else:
        for field, value in values.items():
            setattr(profile, field, value)
    await session.flush()

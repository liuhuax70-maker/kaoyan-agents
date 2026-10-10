"""SQLAlchemy 声明式基类与公共列类型。"""

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, BigInteger, DateTime, Integer, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一约束命名，保证 Alembic 迁移可重复生成
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 统一使用通用 JSON 类型。
# 之所以不使用 JSONB 变体：Alembic 自动生成迁移时会把变体渲染为 PostgreSQL 专用类型，
# 导致同一份迁移无法在 SQLite 兜底环境执行。需要 JSONB 时可另行手写迁移。
JSONType = JSON()


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IntegerIdMixin:
    """自增整型主键，兼容 SQLite 与 PostgreSQL。"""

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        comment="主键",
    )


class TimestampMixin:
    """创建时间与更新时间字段。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


def enum_column(enum_class: type[Enum], name: str) -> SAEnum:
    """构造跨数据库兼容的枚举列。

    底层使用 VARCHAR + CHECK 约束而非原生 ENUM 类型，
    避免 Alembic 在 PostgreSQL 上升级枚举值时受限，
    同时保证 SQLite 兜底环境行为一致。
    """

    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        length=32,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda cls: [member.value for member in cls],
    )

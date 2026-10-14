"""add school_brief reminder type

Revision ID: c41d7e5a8b90
Revises: 3f8c1a9d2b47
Create Date: 2026-10-14 16:00:00.000000

给既有枚举加成员 —— 本次三处迁移里唯一带破坏性的一处。

``enum_column`` 渲染成 ``VARCHAR(32) + 具名 CHECK``（``native_enum=False`` +
``create_constraint=True``），而 SQLite 不支持修改列上的约束，只能整表重建。
``batch_alter_table(recreate="always")`` 就是干这个的：建新表、拷数据、换名。
PostgreSQL 上非原生枚举同样是 CHECK，所以这一份写法两边都成立。

重建期间旧的 CHECK 会随旧表一起消失，新的由 ``type_`` 参数带出来 —— 这正是不写
``recreate="auto"`` 而写 ``always`` 的原因：SQLite 下必须走重建这条路径。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'c41d7e5a8b90'
down_revision: str | None = '3f8c1a9d2b47'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = ('daily', 'weekly', 'overdue', 'countdown', 'idle')
AFTER = (*BEFORE, 'school_brief')


def _reminder_type(members: tuple[str, ...]) -> sa.Enum:
    """构造与模型定义同形的枚举列类型。"""

    return sa.Enum(
        *members,
        name="reminder_type",
        native_enum=False,
        create_constraint=True,
        length=32,
    )


def upgrade() -> None:
    with op.batch_alter_table("reminders", recreate="always") as batch_op:
        batch_op.alter_column(
            "reminder_type",
            existing_type=_reminder_type(BEFORE),
            type_=_reminder_type(AFTER),
            existing_nullable=False,
            existing_comment="提醒类型",
        )


def downgrade() -> None:
    # 先删掉新成员的存量行：枚举收窄后它们过不了新表的 CHECK，
    # 拷贝数据那一步会整条失败，而不是「少几行」。
    op.execute("DELETE FROM reminders WHERE reminder_type = 'school_brief'")

    with op.batch_alter_table("reminders", recreate="always") as batch_op:
        batch_op.alter_column(
            "reminder_type",
            existing_type=_reminder_type(AFTER),
            type_=_reminder_type(BEFORE),
            existing_nullable=False,
            existing_comment="提醒类型",
        )
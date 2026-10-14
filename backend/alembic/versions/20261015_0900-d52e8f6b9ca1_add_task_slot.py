"""add task slot

Revision ID: d52e8f6b9ca1
Revises: c41d7e5a8b90
Create Date: 2026-10-15 09:00:00.000000

给既有表 ``study_tasks`` 加一个可空的 ``slot``（课表行维度：上午/下午/晚上）。

这是本次三处迁移里最轻的一处：单条 ``add_column`` + 一个索引，
不需要 ``batch_alter_table`` 整表重建 —— 因为加的是**普通可空字符串**而不是
枚举。``enum_column`` 会带出具名 CHECK（``native_enum=False`` +
``create_constraint=True``），SQLite 改不了列约束；可空字符串没有这个包袱，
downgrade 一条 ``drop_column`` 就回去了。

取值约束不放在数据库里：词表的权威定义在 ``app/services/scheduling.py`` 的
``SLOTS``，契约由 Pydantic 的 ``Slot`` 承担。时段只用于展示与排序，
从不做筛选键，因此 DB 层校验买不到任何东西。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'd52e8f6b9ca1'
down_revision: str | None = 'c41d7e5a8b90'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "study_tasks",
        sa.Column(
            "slot",
            sa.String(length=8),
            nullable=True,
            comment="学习时段：上午/下午/晚上",
        ),
    )
    op.create_index(op.f("ix_study_tasks_slot"), "study_tasks", ["slot"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_study_tasks_slot"), table_name="study_tasks")
    op.drop_column("study_tasks", "slot")

"""add tracked schools

Revision ID: 3f8c1a9d2b47
Revises: 20de4bd4d1b4
Create Date: 2026-10-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '3f8c1a9d2b47'
down_revision: str | None = '20de4bd4d1b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 全新实体，不碰任何既有表：这里可以直接建自己的 CHECK 约束，
    # 完全绕开 SQLite 修改既有枚举列时要做表重建的麻烦（对比给 reminder_type 加成员那次）。
    op.create_table('tracked_schools',
    sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False, comment='所属用户'),
    sa.Column('target_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False, comment='所属备考目标'),
    sa.Column('name', sa.String(length=128), nullable=False, comment='院校名称'),
    sa.Column('major', sa.String(length=128), nullable=False, comment='目标专业/方向'),
    sa.Column('status', sa.Enum('candidate', 'decided', 'archived', name='tracked_school_status', native_enum=False, create_constraint=True, length=32), nullable=False, comment='候选 / 已由用户拍板 / 已放弃'),
    sa.Column('snapshot', sa.JSON(), nullable=False, comment='生成时冻结的优劣势与核验入口，用于简报与回放'),
    sa.Column('last_briefed_at', sa.DateTime(timezone=True), nullable=True, comment='上次纳入每日简报的时间，用于避免同一院校反复简报'),
    sa.Column('order_index', sa.Integer(), nullable=False, comment='展示顺序'),
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False, comment='主键'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='更新时间'),
    sa.ForeignKeyConstraint(['target_id'], ['exam_targets.id'], name=op.f('fk_tracked_schools_target_id_exam_targets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_tracked_schools_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tracked_schools'))
    )
    op.create_index(op.f('ix_tracked_schools_target_id'), 'tracked_schools', ['target_id'], unique=False)
    op.create_index(op.f('ix_tracked_schools_user_id'), 'tracked_schools', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tracked_schools_user_id'), table_name='tracked_schools')
    op.drop_index(op.f('ix_tracked_schools_target_id'), table_name='tracked_schools')
    op.drop_table('tracked_schools')
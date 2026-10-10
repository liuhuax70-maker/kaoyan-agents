"""智能体会话与消息模型。"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, JSONType, TimestampMixin, enum_column
from app.db.models.enums import MessageRole

if TYPE_CHECKING:
    from app.db.models.user import User


class AgentConversation(Base, IntegerIdMixin, TimestampMixin):
    """一次多智能体协作会话。"""

    __tablename__ = "agent_conversations"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属用户",
    )
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_targets.id", ondelete="SET NULL"), index=True, comment="关联备考目标"
    )
    title: Mapped[str] = mapped_column(String(128), default="", comment="会话标题")
    workflow: Mapped[str] = mapped_column(
        String(64), default="", comment="触发的工作流名称，如 plan_generation"
    )
    status: Mapped[str] = mapped_column(String(32), default="active", comment="会话状态")
    message_count: Mapped[int] = mapped_column(Integer, default=0, comment="消息条数")

    user: Mapped["User"] = relationship(back_populates="conversations", lazy="raise")
    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentMessage.id",
    )

    def __repr__(self) -> str:
        return f"<AgentConversation id={self.id} title={self.title!r} workflow={self.workflow}>"


class AgentMessage(Base, IntegerIdMixin, TimestampMixin):
    """会话中的单条消息，包含智能体输出与执行指标。"""

    __tablename__ = "agent_messages"

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属会话",
    )
    role: Mapped[MessageRole] = mapped_column(
        enum_column(MessageRole, "message_role"),
        default=MessageRole.USER,
        nullable=False,
        comment="消息角色",
    )
    agent_name: Mapped[str] = mapped_column(
        String(64), default="", comment="产生该消息的智能体标识"
    )
    content: Mapped[str] = mapped_column(Text, default="", comment="消息正文")
    content_type: Mapped[str] = mapped_column(
        String(32), default="markdown", comment="正文格式：markdown / json / text"
    )
    payload: Mapped[dict] = mapped_column(
        JSONType, default=dict, comment="结构化输出，便于前端渲染与回溯"
    )
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, comment="路由、引用等附加信息")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, comment="输入 token 数")
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, comment="输出 token 数")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, comment="耗时（毫秒）")

    conversation: Mapped["AgentConversation"] = relationship(
        back_populates="messages", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<AgentMessage id={self.id} role={self.role} agent={self.agent_name!r}>"

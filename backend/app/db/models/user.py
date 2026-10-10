"""用户与学习档案模型。"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, JSONType, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.conversation import AgentConversation
    from app.db.models.reminder import Reminder
    from app.db.models.target import ExamTarget


class User(Base, IntegerIdMixin, TimestampMixin):
    """备考学生。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="登录名"
    )
    email: Mapped[str | None] = mapped_column(String(128), unique=True, comment="邮箱")
    nickname: Mapped[str] = mapped_column(String(64), default="考生", comment="昵称")
    hashed_password: Mapped[str | None] = mapped_column(String(255), comment="密码哈希")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    timezone: Mapped[str] = mapped_column(
        String(32), default="Asia/Shanghai", comment="时区，用于提醒调度"
    )

    profile: Mapped["LearnerProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    targets: Mapped[list["ExamTarget"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    conversations: Mapped[list["AgentConversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


class LearnerProfile(Base, IntegerIdMixin, TimestampMixin):
    """用户学习档案：基础水平、可投入时间与学习习惯。"""

    __tablename__ = "learner_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        comment="所属用户",
    )
    education: Mapped[str] = mapped_column(String(64), default="", comment="学历背景")
    major: Mapped[str] = mapped_column(String(64), default="", comment="所学专业")
    base_level: Mapped[str] = mapped_column(
        String(32), default="一般", comment="基础水平：薄弱 / 一般 / 扎实"
    )
    daily_hours: Mapped[float] = mapped_column(
        Float, default=4.0, comment="每日可投入学习小时数"
    )
    weekly_days: Mapped[int] = mapped_column(Integer, default=6, comment="每周学习天数")
    attention_span: Mapped[int] = mapped_column(
        Integer, default=50, comment="单次专注时长（分钟）"
    )
    self_discipline: Mapped[int] = mapped_column(
        Integer, default=3, comment="自律程度评分 1-5，用于督促强度"
    )
    preferred_slots: Mapped[list[str]] = mapped_column(
        JSONType, default=list, comment="偏好学习时段，如 ['上午', '晚上']"
    )
    notes: Mapped[str] = mapped_column(Text, default="", comment="补充说明")

    # 反向引用一律 lazy="raise"：避免与父级集合的双向 eager 加载形成循环查询，
    # 需要时在查询处显式 selectinload。
    user: Mapped["User"] = relationship(back_populates="profile", lazy="raise")

    def __repr__(self) -> str:
        return f"<LearnerProfile user_id={self.user_id} daily_hours={self.daily_hours}>"

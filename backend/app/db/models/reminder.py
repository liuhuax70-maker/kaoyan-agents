"""提醒督促模型。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, TimestampMixin, enum_column
from app.db.models.enums import ReminderChannel, ReminderStatus, ReminderType

if TYPE_CHECKING:
    from app.db.models.user import User


class Reminder(Base, IntegerIdMixin, TimestampMixin):
    """定时提醒记录，由 Celery 调度生成并发送。"""

    __tablename__ = "reminders"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="提醒对象",
    )
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_plans.id", ondelete="SET NULL"), index=True, comment="关联计划"
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_tasks.id", ondelete="SET NULL"), index=True, comment="关联任务"
    )
    reminder_type: Mapped[ReminderType] = mapped_column(
        enum_column(ReminderType, "reminder_type"),
        default=ReminderType.DAILY,
        nullable=False,
        comment="提醒类型",
    )
    channel: Mapped[ReminderChannel] = mapped_column(
        enum_column(ReminderChannel, "reminder_channel"),
        default=ReminderChannel.IN_APP,
        nullable=False,
        comment="发送渠道",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="提醒标题")
    content: Mapped[str] = mapped_column(Text, default="", comment="提醒正文")
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False, comment="计划发送时间"
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="实际发送时间"
    )
    status: Mapped[ReminderStatus] = mapped_column(
        enum_column(ReminderStatus, "reminder_status"),
        default=ReminderStatus.PENDING,
        nullable=False,
        index=True,
        comment="发送状态",
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    error_message: Mapped[str] = mapped_column(String(255), default="", comment="失败原因")

    user: Mapped["User"] = relationship(back_populates="reminders", lazy="raise")

    @property
    def is_pending(self) -> bool:
        """是否为待发送状态。"""

        return self.status == ReminderStatus.PENDING

    def __repr__(self) -> str:
        return (
            f"<Reminder id={self.id} type={self.reminder_type} "
            f"status={self.status} scheduled_at={self.scheduled_at}>"
        )


class StudyStreak(Base, IntegerIdMixin, TimestampMixin):
    """连续学习统计，用于督促与激励。"""

    __tablename__ = "study_streaks"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
        comment="所属用户",
    )
    current_streak: Mapped[int] = mapped_column(Integer, default=0, comment="当前连续天数")
    longest_streak: Mapped[int] = mapped_column(Integer, default=0, comment="历史最长连续天数")
    total_days: Mapped[int] = mapped_column(Integer, default=0, comment="累计学习天数")
    total_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="累计学习时长（分钟）")
    last_study_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="最近一次学习时间"
    )
    last_check_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近一次统计时间"
    )

    def __repr__(self) -> str:
        return f"<StudyStreak user_id={self.user_id} current={self.current_streak}>"

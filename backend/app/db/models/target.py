"""备考目标与考试科目模型。"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, TimestampMixin, enum_column
from app.db.models.enums import ExamType, TargetStatus

if TYPE_CHECKING:
    from app.db.models.plan import StudyPlan
    from app.db.models.user import User


class ExamTarget(Base, IntegerIdMixin, TimestampMixin):
    """备考目标，例如「考研 · 复旦计算机」或「软考中级」。"""

    __tablename__ = "exam_targets"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属用户",
    )
    exam_type: Mapped[ExamType] = mapped_column(
        enum_column(ExamType, "exam_type"),
        default=ExamType.POSTGRADUATE,
        nullable=False,
        comment="备考类型",
    )
    title: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="目标名称，如 复旦计算机 / 软考中级"
    )
    target_school: Mapped[str] = mapped_column(String(128), default="", comment="目标院校")
    target_major: Mapped[str] = mapped_column(String(128), default="", comment="目标专业/方向")
    exam_date: Mapped[date] = mapped_column(Date, nullable=False, comment="考试日期")
    target_score: Mapped[float | None] = mapped_column(Float, comment="目标分数")
    status: Mapped[TargetStatus] = mapped_column(
        enum_column(TargetStatus, "target_status"),
        default=TargetStatus.PREPARING,
        nullable=False,
        comment="目标状态",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否主目标，督促优先级更高"
    )
    description: Mapped[str] = mapped_column(Text, default="", comment="补充说明")

    user: Mapped["User"] = relationship(back_populates="targets", lazy="raise")
    subjects: Mapped[list["Subject"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Subject.order_index",
    )
    plans: Mapped[list["StudyPlan"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ExamTarget id={self.id} title={self.title!r} exam_date={self.exam_date}>"


class Subject(Base, IntegerIdMixin, TimestampMixin):
    """考试科目及其权重与掌握程度。"""

    __tablename__ = "subjects"

    target_id: Mapped[int] = mapped_column(
        ForeignKey("exam_targets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属目标",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="科目名称")
    category: Mapped[str] = mapped_column(
        String(32), default="公共课", comment="科目类别：公共课 / 专业课"
    )
    score_weight: Mapped[float] = mapped_column(
        Float, default=0.0, comment="分值占比 0-1，用于时间分配"
    )
    difficulty: Mapped[int] = mapped_column(
        Integer, default=3, comment="科目难度 1-5，由用户或智能体评估"
    )
    current_level: Mapped[int] = mapped_column(
        Integer, default=2, comment="当前掌握程度 1-5"
    )
    is_weak: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否薄弱科目，影响任务优先级"
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, comment="展示顺序")

    target: Mapped["ExamTarget"] = relationship(back_populates="subjects", lazy="raise")

    def __repr__(self) -> str:
        return f"<Subject id={self.id} name={self.name!r} weak={self.is_weak}>"

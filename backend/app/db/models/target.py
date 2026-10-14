"""备考目标与考试科目模型。"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, JSONType, TimestampMixin, enum_column
from app.db.models.enums import ExamType, TargetStatus, TrackedSchoolStatus

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
    tracked_schools: Mapped[list["TrackedSchool"]] = relationship(
        back_populates="target",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TrackedSchool.order_index",
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


class TrackedSchool(Base, IntegerIdMixin, TimestampMixin):
    """用户正在跟踪的候选院校。

    存在的理由不是「存个列表」：每日简报必须知道**简报什么**，而最有价值的那几周
    恰恰发生在用户还没拍板之前 —— 此时 `ExamTarget.target_school` 还是空的。
    这张表就是那份 watch-list。

    它同时把「不替用户做决定」变成一次可审计的状态迁移：择校参谋只会写
    ``CANDIDATE`` 行，只有用户的显式动作才把某行提升为 ``DECIDED`` 并写回
    ``ExamTarget.target_school``。没有这张表，产品无从证明自己没替用户选。
    """

    __tablename__ = "tracked_schools"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属用户",
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("exam_targets.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属备考目标",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="院校名称")
    major: Mapped[str] = mapped_column(String(128), default="", comment="目标专业/方向")
    status: Mapped[TrackedSchoolStatus] = mapped_column(
        enum_column(TrackedSchoolStatus, "tracked_school_status"),
        default=TrackedSchoolStatus.CANDIDATE,
        nullable=False,
        comment="候选 / 已由用户拍板 / 已放弃",
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONType,
        default=dict,
        comment="生成时冻结的优劣势与核验入口，用于简报与回放",
    )
    last_briefed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="上次纳入每日简报的时间，用于避免同一院校反复简报"
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, comment="展示顺序")

    target: Mapped["ExamTarget"] = relationship(
        back_populates="tracked_schools", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<TrackedSchool id={self.id} name={self.name!r} status={self.status}>"

"""学习计划、阶段、任务与打卡记录模型。"""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntegerIdMixin, JSONType, TimestampMixin, enum_column
from app.db.models.enums import PlanStatus, Priority, StageType, TaskStatus, TaskType

if TYPE_CHECKING:
    from app.db.models.target import ExamTarget, Subject
    from app.db.models.user import User


class StudyPlan(Base, IntegerIdMixin, TimestampMixin):
    """个性化学习计划，由规划工作流生成。"""

    __tablename__ = "study_plans"

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
        comment="关联备考目标",
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="计划标题")
    goal: Mapped[str] = mapped_column(Text, default="", comment="目标描述")
    strategy: Mapped[str] = mapped_column(Text, default="", comment="备考策略说明")
    horizon_days: Mapped[int] = mapped_column(Integer, default=0, comment="计划总天数")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="开始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="结束日期")
    total_hours: Mapped[float] = mapped_column(Float, default=0.0, comment="计划总学时")
    status: Mapped[PlanStatus] = mapped_column(
        enum_column(PlanStatus, "plan_status"),
        default=PlanStatus.DRAFT,
        nullable=False,
        comment="计划状态",
    )
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号，重规划时递增")
    generated_by: Mapped[str] = mapped_column(
        String(64), default="", comment="生成该计划的工作流与智能体标识"
    )
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, comment="扩展信息")

    user: Mapped["User"] = relationship(lazy="raise")
    target: Mapped["ExamTarget"] = relationship(back_populates="plans", lazy="raise")
    stages: Mapped[list["PlanStage"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PlanStage.order_index",
    )
    tasks: Mapped[list["StudyTask"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StudyTask.planned_date",
    )

    def __repr__(self) -> str:
        return f"<StudyPlan id={self.id} title={self.title!r} status={self.status}>"


class PlanStage(Base, IntegerIdMixin, TimestampMixin):
    """计划阶段，如基础夯实、强化提升、真题冲刺、模考复盘。"""

    __tablename__ = "plan_stages"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属计划",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="阶段名称")
    stage_type: Mapped[StageType] = mapped_column(
        enum_column(StageType, "stage_type"),
        default=StageType.FOUNDATION,
        nullable=False,
        comment="阶段类型",
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, comment="阶段顺序")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="阶段开始日期")
    end_date: Mapped[date] = mapped_column(Date, nullable=False, comment="阶段结束日期")
    focus: Mapped[str] = mapped_column(Text, default="", comment="阶段重点")
    target_hours: Mapped[float] = mapped_column(Float, default=0.0, comment="阶段目标学时")
    completion_rate: Mapped[float] = mapped_column(
        Float, default=0.0, comment="阶段完成度 0-1"
    )

    plan: Mapped["StudyPlan"] = relationship(back_populates="stages", lazy="raise")
    tasks: Mapped[list["StudyTask"]] = relationship(
        back_populates="stage",
        lazy="selectin",
        order_by="StudyTask.order_index",
    )

    def __repr__(self) -> str:
        return f"<PlanStage id={self.id} name={self.name!r}>"


class StudyTask(Base, IntegerIdMixin, TimestampMixin):
    """最小可打卡学习单元。"""

    __tablename__ = "study_tasks"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属计划",
    )
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_stages.id", ondelete="SET NULL"), index=True, comment="所属阶段"
    )
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), index=True, comment="关联科目"
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属用户",
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="任务标题")
    description: Mapped[str] = mapped_column(Text, default="", comment="任务说明")
    task_type: Mapped[TaskType] = mapped_column(
        enum_column(TaskType, "task_type"),
        default=TaskType.LEARN,
        nullable=False,
        comment="任务类型",
    )
    planned_date: Mapped[date] = mapped_column(Date, nullable=False, comment="计划完成日期")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="预计耗时（分钟）")
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority, "task_priority"),
        default=Priority.MEDIUM,
        nullable=False,
        comment="优先级",
    )
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"),
        default=TaskStatus.TODO,
        nullable=False,
        comment="任务状态",
    )
    difficulty: Mapped[int] = mapped_column(Integer, default=3, comment="任务难度 1-5")
    resource_hint: Mapped[str] = mapped_column(
        String(255), default="", comment="资料提示，由资料智能体给出"
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, comment="同日内排序")
    depends_on_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("study_tasks.id", ondelete="SET NULL"), comment="前置任务，支持任务拆解依赖"
    )

    plan: Mapped["StudyPlan"] = relationship(back_populates="tasks", lazy="raise")
    stage: Mapped["PlanStage | None"] = relationship(back_populates="tasks", lazy="raise")
    subject: Mapped["Subject | None"] = relationship(lazy="raise")
    progress_records: Mapped[list["TaskProgress"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="TaskProgress.id",
    )

    def __repr__(self) -> str:
        return f"<StudyTask id={self.id} title={self.title!r} status={self.status}>"


class TaskProgress(Base, IntegerIdMixin, TimestampMixin):
    """任务打卡与进度记录，保留多次打点的历史。"""

    __tablename__ = "task_progress"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("study_tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="关联任务",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="打卡用户",
    )
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "progress_status"),
        default=TaskStatus.DONE,
        nullable=False,
        comment="本次打卡后的状态",
    )
    actual_minutes: Mapped[int] = mapped_column(Integer, default=0, comment="实际耗时（分钟）")
    completion_rate: Mapped[float] = mapped_column(
        Float, default=1.0, comment="本次完成度 0-1"
    )
    score: Mapped[float | None] = mapped_column(Float, comment="自测得分，可用于复盘分析")
    note: Mapped[str] = mapped_column(Text, default="", comment="学习备注 / 卡点记录")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="开始时间"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="完成时间"
    )

    task: Mapped["StudyTask"] = relationship(back_populates="progress_records", lazy="raise")

    def __repr__(self) -> str:
        return f"<TaskProgress task_id={self.task_id} status={self.status}>"

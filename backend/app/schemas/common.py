"""智能体上下文快照。

把数据库实体转换成与存储解耦的快照对象：提示词渲染与智能体逻辑只依赖这些快照，
既不绑定 ORM，也便于在测试中直接构造。
"""

from datetime import date

from pydantic import BaseModel, Field


class SubjectSnapshot(BaseModel):
    """单个科目的备考现状。"""

    name: str
    category: str = "公共课"
    score_weight: float = Field(default=0.0, ge=0, le=1, description="分值占比 0-1")
    difficulty: int = Field(default=3, ge=1, le=5, description="科目难度")
    current_level: int = Field(default=2, ge=1, le=5, description="当前掌握程度")
    is_weak: bool = False


class ProgressSnapshot(BaseModel):
    """学习进度统计。"""

    total_tasks: int = 0
    done_tasks: int = 0
    doing_tasks: int = 0
    overdue_tasks: int = 0
    completion_rate: float = Field(default=0.0, ge=0, le=1)
    recent_minutes: int = Field(default=0, description="近 7 天学习时长（分钟）")
    current_streak: int = Field(default=0, description="当前连续学习天数")
    longest_streak: int = Field(default=0, description="历史最长连续天数")
    idle_days: int = Field(default=0, description="连续未学习天数")


class TaskSnapshot(BaseModel):
    """任务快照，供复盘与督促智能体使用。"""

    id: int | None = None
    title: str
    subject: str = ""
    stage: str = ""
    task_type: str = ""
    planned_date: date | None = None
    duration_minutes: int = 0
    priority: str = "medium"
    status: str = "todo"

    @property
    def is_done(self) -> bool:
        """是否已完成。"""

        return self.status == "done"


class PlanSnapshot(BaseModel):
    """计划快照。"""

    id: int | None = None
    title: str = ""
    goal: str = ""
    status: str = "active"
    start_date: date | None = None
    end_date: date | None = None
    horizon_days: int = 0
    tasks: list[TaskSnapshot] = Field(default_factory=list)


class LearnerSnapshot(BaseModel):
    """考生完整画像，是所有智能体的统一输入。"""

    nickname: str = "考生"
    exam_type: str = "postgraduate"
    target_title: str = ""
    target_school: str = ""
    target_major: str = ""
    exam_date: date | None = None
    days_left: int | None = Field(default=None, description="距考试剩余天数")
    base_level: str = "一般"
    daily_hours: float = Field(default=4.0, gt=0, le=24)
    weekly_days: int = Field(default=6, ge=1, le=7)
    attention_span: int = Field(default=50, description="单次专注时长（分钟）")
    self_discipline: int = Field(default=3, ge=1, le=5, description="自律程度，用于督促强度")
    preferred_slots: list[str] = Field(default_factory=list)
    notes: str = ""
    subjects: list[SubjectSnapshot] = Field(default_factory=list)
    progress: ProgressSnapshot = Field(default_factory=ProgressSnapshot)

    @property
    def weak_subjects(self) -> list[str]:
        """薄弱科目名称列表。"""

        return [item.name for item in self.subjects if item.is_weak]

    @property
    def subject_names(self) -> list[str]:
        """全部科目名称。"""

        return [item.name for item in self.subjects]

    @property
    def weekly_hours(self) -> float:
        """每周可投入学时。"""

        return round(self.daily_hours * self.weekly_days, 1)


class ReminderSnapshot(BaseModel):
    """待发送提醒的内容要素。"""

    reminder_type: str = "daily"
    target_title: str = ""
    due_tasks: list[str] = Field(default_factory=list)
    overdue_tasks: list[str] = Field(default_factory=list)
    days_left: int | None = None
    idle_days: int = 0
    completion_rate: float = Field(default=0.0, ge=0, le=1)

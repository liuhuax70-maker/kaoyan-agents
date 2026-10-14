"""规划智能体的结构化输出。

使用「相对天数偏移」而非绝对日期：模型不需要知道今天是几号，
由工作流在落库时换算成真实日期，避免模型算错日期。
"""

from pydantic import BaseModel, Field

from app.db.models.enums import Priority, StageType, TaskType
from app.schemas.common import Slot


class TaskDraft(BaseModel):
    """拆解后的最小可执行任务。"""

    title: str = Field(min_length=2, max_length=120, description="任务标题，动宾结构且可打卡")
    description: str = Field(default="", max_length=500, description="任务说明与验收标准")
    task_type: TaskType = TaskType.LEARN
    subject: str = Field(default="", max_length=32, description="所属科目，需与科目清单一致")
    day_offset: int = Field(default=0, ge=0, le=2000, description="相对计划开始日的第几天")
    duration_minutes: int = Field(default=60, ge=10, le=480, description="预计耗时（分钟）")
    priority: Priority = Priority.MEDIUM
    difficulty: int = Field(default=3, ge=1, le=5)
    resource_hint: str = Field(default="", max_length=200, description="资料或章节提示")
    slot: Slot | None = Field(
        default=None,
        description="学习时段：上午/下午/晚上。留空则由系统按用户偏好时段分配",
    )
    depends_on_index: int | None = Field(
        default=None, description="前置任务在本阶段任务列表中的下标"
    )


class StageDraft(BaseModel):
    """备考阶段。"""

    name: str = Field(min_length=2, max_length=40)
    stage_type: StageType = StageType.FOUNDATION
    focus: str = Field(default="", max_length=300, description="阶段重点与达成标准")
    start_offset: int = Field(default=0, ge=0, le=2000)
    end_offset: int = Field(default=0, ge=0, le=2000)
    target_hours: float = Field(default=0.0, ge=0, le=5000)
    tasks: list[TaskDraft] = Field(default_factory=list)


class PlanDraft(BaseModel):
    """完整学习计划草稿。"""

    title: str = Field(min_length=2, max_length=80)
    goal: str = Field(min_length=2, max_length=300, description="可衡量的目标描述")
    strategy: str = Field(default="", max_length=600, description="整体备考策略说明")
    horizon_days: int = Field(ge=7, le=2000, description="计划总天数")
    daily_hours: float = Field(default=4.0, gt=0, le=16)
    stages: list[StageDraft] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="风险提示或执行建议")

    @property
    def total_tasks(self) -> int:
        """任务总数。"""

        return sum(len(stage.tasks) for stage in self.stages)


class TaskBreakdown(BaseModel):
    """针对某个阶段或科目的细化拆解结果。"""

    scope: str = Field(default="", max_length=80, description="拆解范围说明")
    summary: str = Field(default="", max_length=300)
    tasks: list[TaskDraft] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

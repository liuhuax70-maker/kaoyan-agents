"""计划修订的结构化输出。

聊天 Agent 通过工具修改计划表时，子智能体产出的是「修订指令」而不是直接写库：
图谱保持无副作用，落库统一由服务层完成。
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.db.models.enums import Priority, TaskStatus, TaskType


class RevisionAction(StrEnum):
    """单条修订操作的类型。"""

    ADD_TASK = "add_task"
    """在指定阶段新增一个任务。"""

    UPDATE_TASK = "update_task"
    """调整已有任务的字段。"""

    REMOVE_TASK = "remove_task"
    """删除已有任务。"""

    SHIFT_TASKS = "shift_tasks"
    """把未完成任务的日期整体平移。"""

    UPDATE_META = "update_meta"
    """修改计划标题、目标或策略。"""


class PlanRevisionOp(BaseModel):
    """一条计划修订操作；按 action 取用相应字段。

    定位已有任务统一使用 ``task_title``（模糊匹配），
    而不是主键：模型更容易稳定地产出标题，主键对模型不可见。
    """

    action: RevisionAction

    # ---- 定位 ----
    task_title: str = Field(default="", max_length=120, description="要定位的已有任务标题片段")

    # ---- 新增 / 改名 ----
    title: str = Field(default="", max_length=120, description="新增任务的标题，或改名后的新标题")
    description: str = Field(default="", max_length=500, description="任务说明与验收标准")
    stage_name: str = Field(
        default="", max_length=40, description="所属阶段名称，缺省归入第一个阶段"
    )
    subject: str = Field(default="", max_length=32, description="所属科目，需与科目清单一致")
    task_type: TaskType = TaskType.LEARN

    # ---- 新增任务的时间与权重 ----
    day_offset: int = Field(default=0, ge=0, le=2000, description="相对计划开始日的第几天")
    duration_minutes: int = Field(default=60, ge=10, le=480, description="预计耗时（分钟）")
    priority: Priority = Priority.MEDIUM

    # ---- 调整已有任务：一律用 new_* 前缀 ----
    # 之所以不复用上面的字段：它们都有非空默认值，
    # 无法区分「模型没打算改」和「模型就是想设成默认值」。
    new_title: str = Field(default="", max_length=120, description="仅 update_task 生效")
    new_day_offset: int | None = Field(
        default=None, ge=0, le=2000, description="仅 update_task 生效"
    )
    new_duration_minutes: int | None = Field(
        default=None, ge=10, le=480, description="仅 update_task 生效"
    )
    new_priority: Priority | None = Field(default=None, description="仅 update_task 生效")
    new_status: TaskStatus | None = Field(default=None, description="仅 update_task 生效")

    # ---- 整体平移 ----
    shift_days: int = Field(default=0, ge=-365, le=365, description="仅 shift_tasks 生效")

    # ---- 计划级 ----
    plan_title: str = Field(default="", max_length=80)
    plan_goal: str = Field(default="", max_length=300)
    plan_strategy: str = Field(default="", max_length=600)


class PlanRevision(BaseModel):
    """一次完整的计划修订提案。"""

    summary: str = Field(default="", max_length=300, description="改了什么、为什么改")
    ops: list[PlanRevisionOp] = Field(default_factory=list, description="按顺序执行的操作")

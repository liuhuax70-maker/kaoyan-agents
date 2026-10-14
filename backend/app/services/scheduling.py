# 知识点：排序口径的单一来源 —— 展示用的中文时段不能直接参与 ORDER BY，
#   因为中文字典序不等于时间顺序；把「谁在前」抽成一处映射供全部加载器复用，
#   排序口径就不会在各处悄悄漂移（第3章 Agent进阶·工具可靠性）
"""学习时段的排序与分配。

时段是课表的行维度：同一个「上午」里要能看见当天所有任务，跨天比较时又要按
上午 → 下午 → 晚上 排。中文字符串的字典序**不等于**时间顺序
（``"上午" < "下午" < "晚上"`` 并不成立），所以裸的 ``order_by(StudyTask.slot)``
是一个**静默错误**的排序 —— 它不报错，只是把任务按 Unicode 码位排乱。

这个模块提供两件事，各自只有一份实现：

- ``order_tasks`` —— 全库统一的任务排序口径，三个加载器共用；
- ``assign_slots`` —— 确定性的时段分配，不经过模型即可单测。
"""

from collections.abc import Iterable, Sequence
from itertools import groupby

from sqlalchemy import Case, case
from sqlalchemy.sql import Select

from app.db.models import StudyTask
from app.schemas.plan import TaskDraft

SLOTS: tuple[str, ...] = ("上午", "下午", "晚上")
"""时段的唯一权威词表。

数据库里存的是自由字符串，取值范围的权威定义只在这里；``app/schemas/common.py``
的 ``Slot`` 只是它的类型投影，供契约与校验使用。
"""

SLOT_ORDER: dict[str, int] = {name: index for index, name in enumerate(SLOTS)}

DEFAULT_ATTENTION_SPAN = 60
"""画像缺失时的单次专注时长兜底，与 ``LearnerProfile.attention_span`` 的默认值同量级。"""


def slot_rank() -> Case:
    """把中文时段折成可排序的整数。

    ``else_`` 给未定时段的任务一个排在最后的序位：它们不该插进任何具体时段中间，
    但也不能因为 ``NULL`` 在部分数据库里排最前而跑到「上午」之前。
    """

    return case(SLOT_ORDER, value=StudyTask.slot, else_=len(SLOTS))


def order_tasks(statement: Select) -> Select:
    """为查询加上全库统一的任务排序：(日期, 时段, 日内序, 主键)。

    末位的 ``id`` 让顺序在任何情况下都稳定：同一格里的两个任务若 ``order_index``
    撞号（手工新增与顺延都可能），没有主键兜底时返回顺序由数据库自行决定，
    同一个页面前后刷新两次就可能不一样。
    """

    return statement.order_by(
        StudyTask.planned_date,
        slot_rank(),
        StudyTask.order_index,
        StudyTask.id,
    )


def preferred_slots(preferred: Sequence[str] | None) -> list[str]:
    """清洗用户偏好：只留词表内的时段、去重并保持原顺序；为空时退回全部时段。"""

    picked: list[str] = []
    for name in preferred or ():
        if name in SLOT_ORDER and name not in picked:
            picked.append(name)
    return picked or list(SLOTS)


def assign_slots(
    tasks: Iterable[TaskDraft],
    preferred: Sequence[str] | None = None,
    *,
    attention_span: int = DEFAULT_ATTENTION_SPAN,
) -> int:
    """为任务补齐缺失的时段，返回被赋值的任务数。

    **水线填充**：同一天内按顺序把任务放进当前时段，累计时长达到单次专注时长就换
    下一个时段；时段用尽后回绕 —— 一天的任务多于时段数时，同一时段也可以有多个任务。
    ``attention_span`` 就是「水线」的高度：忽略它会把一整天的任务全塞进「上午」，
    课表反而看不出安排。

    已经带 ``slot`` 的任务不覆盖：模型比规则更清楚哪一科适合放在哪个时段。
    """

    span = max(attention_span, 1)
    slots = preferred_slots(preferred)
    filled = 0

    for _, day_tasks in groupby(_ordered_by_day(tasks), key=lambda item: item.day_offset):
        cursor = 0
        used = 0
        for task in day_tasks:
            if task.slot is not None:
                continue
            if used >= span and cursor + 1 < len(slots):
                cursor += 1
                used = 0
            task.slot = slots[cursor]
            used += task.duration_minutes
            filled += 1

    return filled


def _ordered_by_day(tasks: Iterable[TaskDraft]) -> list[TaskDraft]:
    """按 (相对天数, 标题) 排序，``groupby`` 要求同一日的任务相邻。"""

    return sorted(tasks, key=lambda item: (item.day_offset, item.title))

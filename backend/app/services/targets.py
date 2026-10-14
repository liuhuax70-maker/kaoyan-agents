"""候选院校的落库与状态迁移。

这一层承担的是产品那条硬约束的**可审计性**：
择校参谋只被允许写 ``CANDIDATE`` 行；把某一行提升为 ``DECIDED`` 的只有用户的显式动作，
并且只有那一步才会写回 ``ExamTarget.target_school``。没有这层分离，
「产品没有替用户做决定」就只是一句无法验证的声明。

仓库此前没有 Target/Subject 服务层（``routes/targets.py`` 内联构造 ORM），
从候选院校开始建：这里的写入逻辑里有不变式（每用户至多一个 DECIDED），
放在路由里既测不动也会被下一条路由复制一遍。
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.timeutil import utc_now
from app.db.models import ExamTarget, TrackedSchool, TrackedSchoolStatus
from app.schemas import (
    SchoolAdvisorAnswer,
    SchoolCandidate,
    TrackedSchoolSnapshot,
)

logger = get_logger(__name__)


def _snapshot_of(candidate: SchoolCandidate, verification_links: list[str]) -> dict:
    """把候选按生成时的样子冻结下来。

    简报与刷新回放都读这份快照，而不是重新问一次模型：
    同一所院校在不同时间被问到会给出不同措辞，用户回看时会以为信息变了。
    """

    return {
        "fit_for": candidate.fit_for,
        "pros": list(candidate.pros),
        "cons": list(candidate.cons),
        "evidence": list(candidate.evidence),
        "verification_links": list(verification_links),
    }


async def list_tracked_schools(
    session: AsyncSession,
    *,
    target_id: int,
    status: TrackedSchoolStatus | None = None,
) -> list[TrackedSchool]:
    """列出某个备考目标下正在跟踪的院校，按展示顺序返回。"""

    statement = select(TrackedSchool).where(TrackedSchool.target_id == target_id)
    if status is not None:
        statement = statement.where(TrackedSchool.status == status)
    statement = statement.order_by(TrackedSchool.order_index, TrackedSchool.id)
    return list(await session.scalars(statement))


async def get_tracked_school(
    session: AsyncSession, *, target_id: int, school_id: int
) -> TrackedSchool | None:
    """按主键读取候选院校，并确认它确实属于该目标。"""

    school = await session.get(TrackedSchool, school_id)
    if school is None or school.target_id != target_id:
        return None
    return school


async def upsert_candidates(
    session: AsyncSession,
    *,
    user_id: int,
    target_id: int,
    answer: SchoolAdvisorAnswer,
) -> list[TrackedSchool]:
    """把参谋给出的候选写入 watch-list，按院校名去重。

    已存在的行只更新快照、**保留原状态**：用户已经拍板的院校不能被一次新的咨询
    悄悄降回候选。重复咨询同一批学校是常态，因此这里必须幂等。
    """

    existing = {
        item.name.strip(): item
        for item in await list_tracked_schools(session, target_id=target_id)
    }
    offset = len(existing)
    rows: list[TrackedSchool] = []

    for index, candidate in enumerate(answer.candidates):
        snapshot = _snapshot_of(candidate, answer.verification_links)
        current = existing.get(candidate.name.strip())
        if current is not None:
            current.snapshot = snapshot
            if candidate.major:
                current.major = candidate.major
            rows.append(current)
            continue

        row = TrackedSchool(
            user_id=user_id,
            target_id=target_id,
            name=candidate.name,
            major=candidate.major,
            status=TrackedSchoolStatus.CANDIDATE,
            snapshot=snapshot,
            order_index=offset + index,
        )
        session.add(row)
        rows.append(row)

    await session.flush()
    logger.info(
        "院校候选已入库 target_id=%s，本次 %d 所，累计 %d 所",
        target_id,
        len(answer.candidates),
        len(rows),
    )
    return rows


def tracked_schools_as_snapshots(
    rows: Sequence[TrackedSchool],
) -> list[TrackedSchoolSnapshot]:
    """把候选院校 ORM 转成提示词用的快照。

    ``app/agents/*`` 只依赖快照而非 ORM（见 ``app/services/snapshots.py``），
    简报的提示词组装因此能脱离数据库单测。快照读 ``snapshot`` 里的冻结字段，
    而不是重新调用模型：同一所院校的优劣势在生成时是什么样，简报里就是什么样。
    """

    return [
        TrackedSchoolSnapshot(
            name=row.name,
            major=row.major,
            status=row.status.value,
            fit_for=str((row.snapshot or {}).get("fit_for", "")),
            pros=list((row.snapshot or {}).get("pros", [])),
            cons=list((row.snapshot or {}).get("cons", [])),
        )
        for row in rows
    ]


async def mark_briefed(session: AsyncSession, *, school_ids: Sequence[int]) -> None:
    """把纳入本次简报的候选院校盖上时间戳。

    这个时间戳将来用于「同一所院校避免反复简报」的调权；现在只记录，
    不参与筛选——院校每天的动向都可能不同，不因昨天简报过今天就跳过。
    """

    if not school_ids:
        return
    statement = (
        select(TrackedSchool).where(TrackedSchool.id.in_(school_ids))
    )
    for row in await session.scalars(statement):
        row.last_briefed_at = utc_now()
    await session.flush()


async def decide_school(
    session: AsyncSession, *, target_id: int, school_id: int
) -> TrackedSchool | None:
    """记录「用户自己选定了这一所」，并把目标院校写回备考目标。

    只在这里改 ``ExamTarget.target_school``：参谋的产出永远走不到这一行，
    因此「谁做的决定」在数据上是可以区分的。
    """

    school = await get_tracked_school(session, target_id=target_id, school_id=school_id)
    if school is None:
        return None

    # 每用户至多一个 DECIDED：换校是常态，旧的那所降回候选而不是删掉，
    # 用户后悔时还能找回原来的分析
    previous = list(
        await session.scalars(
            select(TrackedSchool).where(
                TrackedSchool.user_id == school.user_id,
                TrackedSchool.status == TrackedSchoolStatus.DECIDED,
                TrackedSchool.id != school.id,
            )
        )
    )
    for item in previous:
        item.status = TrackedSchoolStatus.CANDIDATE

    school.status = TrackedSchoolStatus.DECIDED

    target = await session.get(ExamTarget, target_id)
    if target is not None:
        target.target_school = school.name
        if school.major:
            target.target_major = school.major

    await session.flush()
    logger.info(
        "用户选定院校 school_id=%s（%s），已写回目标 target_id=%s",
        school.id,
        school.name,
        target_id,
    )
    return school


async def archive_school(
    session: AsyncSession, *, target_id: int, school_id: int
) -> TrackedSchool | None:
    """把一所院校移出考虑范围。

    归档而不是删除：删除会让历史会话里提到的院校在追踪列表里凭空消失，
    用户会以为是自己记错了。
    """

    school = await get_tracked_school(session, target_id=target_id, school_id=school_id)
    if school is None:
        return None

    school.status = TrackedSchoolStatus.ARCHIVED
    await session.flush()
    return school
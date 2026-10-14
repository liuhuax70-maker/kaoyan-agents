"""检查点测试：真实 SQLite 后端的装配，以及「暂停—确认—恢复」这条链路。

其余用例都跑在内存检查点上（``install_fake_checkpointer``），它们验证的是编排逻辑；
本文件专门验证**真实实现**能不能装配起来、能不能把状态存取下来——
这正是「内存假件」替代不了的那部分。
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.core.config import WorkflowSection, get_settings
from app.schemas import LearnerSnapshot, SubjectSnapshot
from app.workflows import checkpoint as checkpoint_module
from app.workflows import resume_workflow, run_workflow
from app.workflows.nodes import pending_confirmation


def test_confirmation_defaults_to_on() -> None:
    """产品默认「必须确认」，测试环境只是显式把默认关掉了。

    断言的是配置类的默认值本身，而不是测试环境里那份被覆盖过的配置：
    否则「默认到底开不开」这件事在用例里永远看不到。
    """

    assert WorkflowSection().require_plan_confirmation is True


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://u:p@h:5432/db", "postgresql://u:p@h:5432/db"),
        ("postgresql://h/db", "postgresql://h/db"),
        ("sqlite+aiosqlite:///./data/kaoyan.db", "sqlite+aiosqlite:///./data/kaoyan.db"),
    ],
)
def test_psycopg_url_only_rewrites_postgres_urls(url: str, expected: str) -> None:
    """只改写 postgres 系前缀。

    把别的连接串一并改写成 ``postgresql://``，会把「配置写错了」
    伪装成「数据库连不上」，排障方向直接跑偏。
    """

    assert checkpoint_module._psycopg_url(url) == expected


def test_pending_confirmation_ignores_empty_revisions() -> None:
    """没有可落库产物时不该弹确认，空修订也算没有。"""

    assert pending_confirmation({}) is None
    assert pending_confirmation({"plan_revision": {"ops": []}}) is None
    assert pending_confirmation({"plan_revision": None}) is None


def _learner() -> LearnerSnapshot:
    return LearnerSnapshot(
        nickname="小研",
        target_title="复旦计算机",
        days_left=120,
        daily_hours=5,
        attention_span=60,
        self_discipline=4,
        subjects=[SubjectSnapshot(name="数学", score_weight=0.3, is_weak=True)],
    )


@pytest.fixture
async def sqlite_checkpointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Path]:
    """把检查点换成真实 SQLite 实现，落盘到临时目录。

    默认夹具已经把 ``_saver`` 换成了内存实现，这里显式清空，
    让 ``get_checkpointer()`` 真正走一遍「构建后端 → setup 建表」。
    """

    path = tmp_path / "checkpoints.db"
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "workflow",
        settings.workflow.model_copy(update={"checkpoint_path": str(path)}),
    )
    monkeypatch.setattr(checkpoint_module, "_saver", None)
    monkeypatch.setattr(checkpoint_module, "_lifecycle", None)

    yield path

    await checkpoint_module.reset_checkpointer()


async def test_sqlite_checkpointer_is_built_and_set_up(sqlite_checkpointer: Path) -> None:
    """配置指向 SQLite 时，装配出的是 SQLite 后端，并且真的建了表。"""

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    saver = await checkpoint_module.get_checkpointer()

    assert isinstance(saver, AsyncSqliteSaver)
    assert sqlite_checkpointer.exists(), "setup() 应当把检查点表落到配置的路径上"

    # 单例：再取一次不应重新构建
    assert await checkpoint_module.get_checkpointer() is saver


async def test_workflow_pauses_and_resumes_on_the_real_checkpointer(
    sqlite_checkpointer: Path,
) -> None:
    """阶段 4 验收：真实检查点能把图停在确认闸门，并从原处恢复。"""

    paused = await run_workflow(
        "帮我制定学习计划：数学冲刺 110 分",
        _learner(),
        thread_id="thread-1",
        confirm_commit=True,
    )

    assert paused.awaiting_confirmation
    assert paused.confirmation is not None
    assert paused.confirmation.kind == "plan_draft"
    assert paused.confirmation.thread_id == "thread-1"
    # 草稿还在结果里（用户要看到它才能决定），但这一步没有任何写库动作
    assert paused.plan_draft is not None

    resumed = await resume_workflow("thread-1", {"approve": True, "feedback": ""})

    assert not resumed.awaiting_confirmation
    assert resumed.plan_draft is not None, "恢复后草稿必须还在，否则落库会丢掉计划"
    assert "已确认" in resumed.reply


async def test_resume_without_a_checkpoint_writes_nothing(sqlite_checkpointer: Path) -> None:
    """恢复一个不存在的 thread 不会凭空写出一份计划。

    LangGraph 对这种 thread 不会报错，而是从入口节点重跑一遍；因此「没有可落库产物」
    这条底线由状态本身守住，而不是靠库抛异常——这也是服务层要用会话状态做闸门的原因。
    """

    result = await resume_workflow("thread-that-never-started", {"approve": True})

    assert result.plan_draft is None
    assert result.plan_revision is None
    assert not result.awaiting_confirmation


async def test_confirmation_carries_the_draft_highlights(sqlite_checkpointer: Path) -> None:
    """确认请求要带上可供用户逐条核对的要点，否则「确认」只是一句空话。"""

    paused = await run_workflow(
        "帮我制定学习计划：数学冲刺",
        _learner(),
        thread_id="thread-2",
        confirm_commit=True,
    )

    confirmation = paused.confirmation
    assert confirmation is not None
    assert confirmation.title
    assert confirmation.items, "应当给出计划要点供用户核对"


async def test_workflow_without_a_thread_never_pauses(sqlite_checkpointer: Path) -> None:
    """没有 thread_id 就没有检查点，确认能力随之关闭。"""

    result = await run_workflow(
        "帮我制定学习计划：数学冲刺", _learner(), confirm_commit=True
    )

    assert not result.awaiting_confirmation
    assert result.plan_draft is not None


async def test_rejected_confirmation_clears_the_draft(sqlite_checkpointer: Path) -> None:
    """驳回也必须走完图：草稿被清掉，服务层才不会把它写进数据库。"""

    await run_workflow(
        "帮我制定学习计划：数学冲刺",
        _learner(),
        thread_id="thread-3",
        confirm_commit=True,
    )
    resumed: Any = await resume_workflow(
        "thread-3", {"approve": False, "feedback": "每天时间太长"}
    )

    assert resumed.plan_draft is None
    assert resumed.plan_revision is None
    assert "每天时间太长" in resumed.reply
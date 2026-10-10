"""迁移脚本测试：保证 upgrade / downgrade 在全新数据库上可完整执行。

SQLite 兜底环境能跑通，说明迁移没有依赖 PostgreSQL 专用类型，
部署到 Docker 中的 PostgreSQL 时才不会出现「本地能建表、线上报错」的问题。
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "users",
    "learner_profiles",
    "exam_targets",
    "subjects",
    "study_plans",
    "plan_stages",
    "study_tasks",
    "task_progress",
    "reminders",
    "study_streaks",
    "agent_conversations",
    "agent_messages",
}


def _alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def _table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            return set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_and_downgrade_on_fresh_database(tmp_path, monkeypatch) -> None:
    """全新数据库应能建出全部业务表，并能完整回滚。"""

    db_file = tmp_path / "migration.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE__URL", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    get_settings.cache_clear()

    config = _alembic_config()
    command.upgrade(config, "head")

    tables = _table_names(db_url)
    assert tables >= EXPECTED_TABLES
    assert "alembic_version" in tables

    command.downgrade(config, "base")

    remaining = _table_names(db_url)
    assert not (EXPECTED_TABLES & remaining)

    get_settings.cache_clear()

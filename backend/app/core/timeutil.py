"""时间工具。

数据库的 server_default 使用 CURRENT_TIMESTAMP（UTC 且不含时区），
因此这里统一产出 naive UTC 时间，避免 SQLite 读写时出现时区不一致。
"""

from datetime import UTC, date, datetime, time, timedelta


def utc_now() -> datetime:
    """返回当前 UTC 时间（不含时区信息）。"""

    return datetime.now(UTC).replace(tzinfo=None)


def utc_today() -> date:
    """返回当前 UTC 日期。"""

    return utc_now().date()


def day_start(value: date) -> datetime:
    """返回某天的起始时间。"""

    return datetime.combine(value, time.min)


def days_ago(days: int, *, reference: datetime | None = None) -> datetime:
    """返回 N 天前的时间点。"""

    base = reference or utc_now()
    return base - timedelta(days=days)

"""部署后基础设施自检。

依次探测 PostgreSQL、Redis 与向量库，并对向量库做一次真实的
「写入 + 检索」往返。脚本不会清空既有集合，可随时重复执行。

用法（在 backend 目录下执行）：

    python -m scripts.verify_infrastructure
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

from app.cache.redis import cache
from app.core.config import get_settings
from app.db.session import db
from app.knowledge import build_knowledge_base
from app.knowledge.types import Document

# 仅用于打印真实检索的相似度，不作为断言：
# 相似度高低取决于 embedding 实现，stub 向量化不具备语义能力。
PROBE_QUERIES = ("英语真题怎么刷", "数学极限总出错怎么办")
ROUNDTRIP_ID = "verify::roundtrip"


async def check_database() -> bool:
    """探测 PostgreSQL 连通性。"""

    if await db.ping():
        print("[OK]   PostgreSQL 连接正常")
        return True
    print("[FAIL] PostgreSQL 无法连接")
    return False


async def check_redis() -> bool:
    """探测 Redis 连通性。"""

    if await cache.ping():
        print("[OK]   Redis 连接正常")
        return True
    print("[FAIL] Redis 无法连接")
    return False


async def _check_roundtrip(base: object) -> bool:
    """用探针文本自身作为查询，验证写入与检索往返。

    相同文本经确定性的向量化后得到相同向量，余弦相似度为 1.0，
    因此该断言与 embedding 的语义能力强弱无关，只反映向量库是否真的存住了数据。
    """

    probe = f"基础设施自检探针，写入时间 {datetime.now(UTC).isoformat(timespec='seconds')}"
    await base.ingest([Document(id=ROUNDTRIP_ID, text=probe)])  # type: ignore[attr-defined]
    hits = await base.search(probe, top_k=1, min_score=0.0)  # type: ignore[attr-defined]

    if not hits or not hits[0].id.startswith(ROUNDTRIP_ID):
        print("[FAIL] 写入与检索往返失败，写入的数据未被检索到")
        return False

    print(f"[OK]   往返验证通过：探针命中自身（相似度 {hits[0].score:.4f}）")
    return True


async def check_vector() -> bool:
    """探测向量库连通性，并验证写入与检索往返。"""

    settings = get_settings()
    try:
        base = build_knowledge_base(settings)
        written = await base.ensure_builtin_corpus()
        total = await base.count()
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要给出完整原因
        print(f"[FAIL] 向量库不可用：{exc!r}")
        return False

    print(f"[OK]   向量库连接正常（backend={base.backend} collection={base.collection}）")
    print(f"       内置语料写入 {written} 个片段，集合现有 {total} 个片段")

    if total == 0:
        print("[FAIL] 集合为空，无法验证检索")
        return False

    if not await _check_roundtrip(base):
        return False

    for query in PROBE_QUERIES:
        hits = await base.search(query, top_k=3, min_score=0.0)
        if not hits:
            print(f"[FAIL] 检索无结果：{query}")
            return False
        top = hits[0]
        print(
            f"[INFO] 检索「{query}」命中 {len(hits)} 条"
            f"，最高相似度 {top.score:.4f}（{top.source or top.id}）"
        )
    return True


async def main() -> int:
    """执行全部检查并返回进程退出码。"""

    settings = get_settings()
    print("=" * 64)
    print("考研智能体系统 · 基础设施自检")
    print("=" * 64)
    print(f"database = {settings.database.safe_url}")
    print(f"redis    = {settings.redis.url}")
    print(f"vector   = {settings.vector.backend}")
    print(f"embedding= {settings.embedding.provider}（dim={settings.embedding.dimension}）")
    print("-" * 64)

    results = [await check_database(), await check_redis(), await check_vector()]

    await db.dispose()
    await cache.close()

    print("-" * 64)
    if all(results):
        print("全部组件正常。")
        return 0

    print(f"存在 {results.count(False)} 项异常，请检查上方输出。")
    return 1


if __name__ == "__main__":
    # 统一按 UTF-8 输出，避免中文 Windows 下日志文件被 GBK 编码而出现乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))

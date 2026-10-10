"""Redis 客户端封装。

Redis 不可用时降级而非中断服务：连接失败会记录告警并保持应用可启动，
便于在无 Docker 的本地环境中继续开发。
"""

from typing import Any

from redis.asyncio import Redis, from_url

from app.core.config import RedisSection, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisCache:
    """异步 Redis 客户端管理器。"""

    def __init__(self, section: RedisSection | None = None) -> None:
        self.section = section or get_settings().redis
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        """返回 Redis 客户端，首次访问时创建。"""

        if self._client is None:
            self._client = from_url(
                self.section.url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=self.section.socket_timeout,
                max_connections=self.section.max_connections,
            )
        return self._client

    @property
    def connected(self) -> bool:
        """客户端是否已建立。"""

        return self._client is not None

    async def connect(self) -> bool:
        """建立连接并探测，失败时释放客户端。"""

        try:
            await self.client.ping()
        except Exception as exc:  # noqa: BLE001 - 连接失败需要降级而非抛出
            logger.warning("Redis 连接不可用，相关功能将降级：%s", exc)
            await self.close()
            return False
        logger.info("Redis 连接成功：%s", self.section.url)
        return True

    async def ping(self) -> bool:
        """探测连通性。"""

        try:
            return bool(await self.client.ping())
        except Exception:  # noqa: BLE001 - 健康检查返回布尔结果即可
            return False

    async def get_json(self, key: str) -> Any | None:
        """读取并反序列化 JSON 缓存。"""

        import json

        raw = await self.client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """序列化写入 JSON 缓存。"""

        import json

        payload = json.dumps(value, ensure_ascii=False, default=str)
        try:
            if ttl:
                await self.client.setex(key, ttl, payload)
            else:
                await self.client.set(key, payload)
        except Exception as exc:  # noqa: BLE001 - 缓存写入失败不应影响主流程
            logger.warning("写入缓存失败 key=%s：%s", key, exc)
            return False
        return True

    async def delete(self, *keys: str) -> int:
        """删除缓存键。"""

        if not keys:
            return 0
        try:
            return int(await self.client.delete(*keys))
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除缓存失败 keys=%s：%s", keys, exc)
            return 0

    async def close(self) -> None:
        """关闭连接。"""

        if self._client is not None:
            await self._client.aclose()
            self._client = None


cache = RedisCache()

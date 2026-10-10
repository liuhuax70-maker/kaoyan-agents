"""缓存层：Redis 客户端封装。"""

from app.cache.redis import RedisCache, cache

__all__ = ["RedisCache", "cache"]

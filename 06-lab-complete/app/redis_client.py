"""Lazy Redis connection shared by each worker's request handlers."""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url, decode_responses=True,
    socket_connect_timeout=0.5, socket_timeout=0.5,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False
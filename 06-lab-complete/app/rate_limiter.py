"""Atomic Redis sliding window shared across workers and restarts."""
import hashlib
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Redis supplies the clock; Lua makes pruning/counting/adding atomic.
SLIDING_WINDOW = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(1, math.ceil(tonumber(oldest[2]) + 60 - now))}
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('EXPIRE', KEYS[1], 60)
return {1, 0}
"""


def check_rate_limit(key: str) -> None:
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    allowed, retry_after = r.eval(
        SLIDING_WINDOW, 1, f"rate:{fingerprint}",
        settings.rate_limit_per_minute, uuid.uuid4().hex,
    )
    if not allowed:
        raise HTTPException(
            status_code=429, detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )
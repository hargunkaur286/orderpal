"""Per-user rate limiting in Redis (fixed window).

Why: every /chat or /ask call costs LLM money and quota. Without a limit, one script hitting a
public demo link can burn the monthly budget in minutes. Redis because the counter must be shared
by every server instance, and INCR is atomic, so two simultaneous requests can't both read "9".

Fixed window = count requests per calendar minute. Simple and cheap; the known flaw is a burst at
a window boundary (10 at 12:00:59 + 10 at 12:01:00). A sliding window or token bucket fixes that.
"""
import time

from redis.asyncio import Redis


async def allow(redis: Redis, key: str, limit: int, window_s: int = 60) -> tuple[bool, int]:
    """Returns (allowed, seconds_until_the_window_resets)."""
    now = time.time()
    bucket = f"rl:{key}:{int(now // window_s)}"
    async with redis.pipeline(transaction=True) as pipe:      # MULTI/EXEC: both commands or neither
        pipe.incr(bucket)
        pipe.expire(bucket, window_s, nx=True)                 # set TTL once; Redis cleans up old keys
        count, _ = await pipe.execute()
    return count <= limit, window_s - int(now % window_s)

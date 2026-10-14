"""In-memory sliding-window rate limiter, applied per client IP and per bucket.

Good enough for a single instance. For horizontal scaling the counters would move to a shared
store (Redis, or a MongoDB collection with a TTL index).
"""

import asyncio
import math
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self, window_seconds: float = 60.0, max_keys: int = 50_000) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def hit(self, key: str, limit: int) -> float | None:
        """Record a hit. Returns None if allowed, else seconds until a slot frees up."""
        now = time.monotonic()
        async with self._lock:
            if len(self._hits) > self._max_keys:
                self._evict(now)
            q = self._hits[key]
            while q and now - q[0] >= self._window:
                q.popleft()
            if len(q) >= limit:
                return max(0.0, self._window - (now - q[0]))
            q.append(now)
            return None

    def _evict(self, now: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] >= self._window]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if request.app.state.settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit_attr: str):
    """FastAPI dependency factory, e.g. ``Depends(rate_limit("analysis", "analysis_rate_limit_per_minute"))``."""

    async def dependency(request: Request) -> None:
        limit = getattr(request.app.state.settings, limit_attr)
        retry_after = await limiter.hit(f"{bucket}:{client_ip(request)}", limit)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(math.ceil(retry_after))},
            )

    return dependency

"""Per-key sliding-window rate limiter (in memory, single process)."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit must be >= 1 and window_seconds > 0")
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> tuple[bool, float]:
        """Record a hit. Returns (allowed, seconds_until_a_slot_frees_up)."""
        now = self.clock()
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False, max(0.0, self.window - (now - q[0]))
        q.append(now)
        if len(self._hits) > self.max_keys:
            self._purge(now)
        return True, 0.0

    def _purge(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self.window]:
            del self._hits[k]
        while len(self._hits) > self.max_keys:  # still too many: drop the oldest
            del self._hits[next(iter(self._hits))]

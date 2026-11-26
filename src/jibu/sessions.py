"""Short-lived conversation memory: the last matched entry id per session. No message text."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from .engine import ConversationState


class SessionStore:
    def __init__(
        self,
        ttl_seconds: float = 600,
        max_sessions: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = ttl_seconds
        self.max = max_sessions
        self.clock = clock
        self._data: OrderedDict[str, tuple[float, ConversationState]] = OrderedDict()

    def get(self, key: str) -> ConversationState:
        item = self._data.get(key)
        if item is None:
            return ConversationState()
        ts, state = item
        if self.clock() - ts > self.ttl:
            del self._data[key]
            return ConversationState()
        return state

    def put(self, key: str, state: ConversationState) -> None:
        self._data[key] = (self.clock(), state)
        self._data.move_to_end(key)
        while len(self._data) > self.max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
